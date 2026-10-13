"""Optional ASTAP integration for rectilinear, longer-focal-length images."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import json
import math
from pathlib import Path
import shutil
import subprocess
import tempfile
from typing import Callable

import numpy as np
from astropy.io import fits
from astropy.wcs import WCS
from astropy.wcs.utils import proj_plane_pixel_scales
from PIL import Image
import rawpy


@dataclass(frozen=True)
class AstapSolution:
    source: str
    center_ra_deg: float
    center_dec_deg: float
    pixel_scale_x_arcsec: float
    pixel_scale_y_arcsec: float
    width_px: int
    height_px: int
    field_width_deg: float
    field_height_deg: float
    wcs_header: dict[str, object]

    def report(self) -> dict[str, object]:
        return asdict(self)


def find_astap_executable() -> Path | None:
    candidates = []
    for name in ("astap_cli.exe", "astap.exe", "astap_cli", "astap"):
        found = shutil.which(name)
        if found:
            candidates.append(Path(found))
    candidates.extend(
        [
            Path(r"C:\Program Files\astap\astap_cli.exe"),
            Path(r"C:\Program Files\astap\astap.exe"),
            Path(r"C:\Program Files (x86)\astap\astap.exe"),
        ]
    )
    return next((path for path in candidates if path.is_file()), None)


def installed_database_families(executable: str | Path) -> tuple[str, ...]:
    folder = Path(executable).resolve().parent
    families = []
    for family in ("w08", "g05", "d05", "d20", "d50", "d80"):
        if next(folder.glob(f"{family}_*"), None) is not None:
            families.append(family.upper())
    return tuple(families)


def recommended_database(field_height_deg: float) -> str:
    if field_height_deg > 20.0:
        return "W08"
    if field_height_deg > 6.0:
        return "G05"
    if field_height_deg > 0.6:
        return "D05"
    if field_height_deg > 0.3:
        return "D20"
    if field_height_deg > 0.2:
        return "D50"
    return "D80"


def acceptable_databases(field_height_deg: float) -> tuple[str, ...]:
    """Return ASTAP database families that cover the requested field/depth.

    The denser D-series databases can replace a shallower one for the same
    field size.  G05 and W08 are separate wide-field databases.
    """

    if field_height_deg > 20.0:
        return ("W08", "G05", "D05", "D20", "D50", "D80")
    if field_height_deg > 6.0:
        return ("G05", "D05", "D20", "D50", "D80")
    if field_height_deg > 0.6:
        return ("D05", "D20", "D50", "D80")
    if field_height_deg > 0.3:
        return ("D20", "D50", "D80")
    if field_height_deg > 0.2:
        return ("D50", "D80")
    return ("D80",)


def _raw_to_tiff(source: Path, target: Path) -> tuple[int, int]:
    with rawpy.imread(str(source)) as raw:
        rgb = raw.postprocess(
            output_bps=8,
            use_camera_wb=True,
            no_auto_bright=False,
            gamma=(2.222, 4.5),
        )
    image = Image.fromarray(np.asarray(rgb, dtype=np.uint8), mode="RGB")
    image.save(target, format="TIFF", compression="tiff_lzw")
    return image.size


def _read_wcs(path: Path, source: Path, width: int, height: int) -> AstapSolution:
    header = fits.Header.fromfile(path, endcard=False, padding=False)
    wcs = WCS(header).celestial
    center = wcs.pixel_to_world(width / 2.0, height / 2.0)
    left = wcs.pixel_to_world(0.0, height / 2.0)
    right = wcs.pixel_to_world(float(width - 1), height / 2.0)
    top = wcs.pixel_to_world(width / 2.0, 0.0)
    bottom = wcs.pixel_to_world(width / 2.0, float(height - 1))
    scales = np.abs(proj_plane_pixel_scales(wcs)) * 3600.0
    if len(scales) != 2 or not np.all(np.isfinite(scales)):
        raise ValueError("ASTAP vratil WCS bez platneho meritka pixelu.")
    safe_header: dict[str, object] = {}
    for key in header:
        value = header[key]
        if isinstance(value, (str, int, float, bool)):
            safe_header[key] = value
    return AstapSolution(
        source=str(source),
        center_ra_deg=float(center.ra.deg),
        center_dec_deg=float(center.dec.deg),
        pixel_scale_x_arcsec=float(scales[0]),
        pixel_scale_y_arcsec=float(scales[1]),
        width_px=width,
        height_px=height,
        field_width_deg=float(left.separation(right).deg),
        field_height_deg=float(top.separation(bottom).deg),
        wcs_header=safe_header,
    )


def solve_raw_with_astap(
    source: str | Path,
    executable: str | Path,
    field_height_deg: float,
    progress: Callable[[str], None] | None = None,
) -> AstapSolution:
    """Convert a RAW temporarily, run ASTAP, and return its WCS solution."""

    notify = progress or (lambda _message: None)
    source_path = Path(source)
    executable_path = Path(executable)
    if not source_path.is_file():
        raise ValueError("Vybrany RAW soubor neexistuje.")
    if not executable_path.is_file():
        raise ValueError("Spustitelny soubor ASTAP nebyl nalezen.")
    if not math.isfinite(field_height_deg) or not 0.1 <= field_height_deg <= 120.0:
        raise ValueError("Vyska zorneho pole ASTAP musi byt 0,1 az 120 stupnu.")
    needed = recommended_database(field_height_deg)
    acceptable = acceptable_databases(field_height_deg)
    installed = installed_database_families(executable_path)
    if not set(acceptable).intersection(installed):
        available = ", ".join(installed) if installed else "zadna"
        raise ValueError(
            f"Pro pole vysoke {field_height_deg:g}° je doporucena databaze ASTAP {needed}; "
            f"nebyla ale nalezena zadna pouzitelna databaze (nalezeno: {available})."
        )
    with tempfile.TemporaryDirectory(prefix="pyraw2lum_astap_") as directory:
        temporary = Path(directory)
        image_path = temporary / "solve.tiff"
        notify("Převádím RAW do dočasného TIFF pro ASTAP…")
        width, height = _raw_to_tiff(source_path, image_path)
        notify("Spouštím automatickou astrometrii ASTAP…")
        command = [
            str(executable_path),
            "-f",
            str(image_path),
            "-fov",
            f"{field_height_deg:.8g}",
            "-r",
            "180",
            "-z",
            "0",
            "-wcs",
        ]
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=300,
            check=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        wcs_path = image_path.with_suffix(".wcs")
        if completed.returncode != 0 or not wcs_path.is_file():
            details = (completed.stdout + "\n" + completed.stderr).strip()
            raise ValueError(
                f"ASTAP obraz nevyresil (kod {completed.returncode}). "
                + (details[-800:] if details else "Zkontrolujte hvezdy, FOV a databazi.")
            )
        return _read_wcs(wcs_path, source_path, width, height)


def save_astap_solution(solution: AstapSolution, path: str | Path) -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(solution.report(), ensure_ascii=False, indent=2, allow_nan=False),
        encoding="utf-8",
    )
    return target
