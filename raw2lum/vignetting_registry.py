"""Persistent collection and automatic selection of custom vignetting profiles."""

from __future__ import annotations

import math
import os
from pathlib import Path
import re
import shutil

from .vignetting import (
    VignettingCalibration,
    load_vignetting_calibration,
    save_vignetting_calibration,
)


def default_registry_directory() -> Path:
    base = Path(os.environ.get("APPDATA", Path.home()))
    return base / "PyRaw2Lum" / "vignetting_profiles"


def _safe_name(text: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_.-]+", "_", text).strip("_.")
    return cleaned or "vignetting_profile"


class VignettingProfileRegistry:
    """Managed profile directory used by the GUI across application launches."""

    def __init__(self, directory: str | Path | None = None) -> None:
        self.directory = Path(directory) if directory is not None else default_registry_directory()

    def entries(self) -> list[tuple[Path, VignettingCalibration]]:
        if not self.directory.is_dir():
            return []
        result: list[tuple[Path, VignettingCalibration]] = []
        for path in sorted(self.directory.glob("*.json")):
            try:
                result.append((path, load_vignetting_calibration(path)))
            except (OSError, ValueError, KeyError, TypeError):
                continue
        return result

    def store(self, calibration: VignettingCalibration) -> Path:
        self.directory.mkdir(parents=True, exist_ok=True)
        aperture = f"{calibration.aperture:g}".replace(".", "_")
        lens = _safe_name(calibration.lens_model_exif or calibration.lens_name)[:60]
        target = self.directory / (
            f"{_safe_name(calibration.profile_key)}__{lens}__f{aperture}.json"
        )
        return save_vignetting_calibration(calibration, target)

    def import_file(self, source: str | Path) -> Path:
        source_path = Path(source)
        calibration = load_vignetting_calibration(source_path)
        target = self.store(calibration)
        if source_path.resolve() != target.resolve():
            # store() serialises a validated, normalised copy. Preserve mtime only
            # when the source and managed path are not identical.
            try:
                shutil.copystat(source_path, target)
            except OSError:
                pass
        return target

    def remove(self, path: str | Path) -> None:
        target = Path(path).resolve()
        root = self.directory.resolve()
        if target.parent != root or target.suffix.lower() != ".json":
            raise ValueError("Profil neni ulozen ve spravovane slozce PyRaw2Lum.")
        target.unlink(missing_ok=True)

    def match(self, exif, instrument_profile) -> Path | None:
        candidates: list[tuple[float, Path]] = []
        for path, calibration in self.entries():
            if calibration.profile_key != instrument_profile.key:
                continue
            if calibration.camera_model != exif.camera_model:
                continue
            if not math.isclose(calibration.aperture, exif.aperture, abs_tol=0.06):
                continue
            expected_lens = (calibration.lens_model_exif or "").strip().casefold()
            actual_lens = (exif.lens_model or "").strip().casefold()
            if expected_lens and actual_lens and expected_lens != actual_lens:
                continue
            candidates.append((path.stat().st_mtime, path))
        if not candidates:
            return None
        return max(candidates, key=lambda item: item[0])[1]


def profile_label(calibration: VignettingCalibration) -> str:
    lens = calibration.lens_model_exif or calibration.lens_name
    return f"{calibration.camera_model} | {lens} | f/{calibration.aperture:g}"
