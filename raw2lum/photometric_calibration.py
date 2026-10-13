"""Experimental absolute calibration of an instrument from catalogue stars."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import json
import math
import os
from pathlib import Path
import re


# Approximate visual illuminance above the atmosphere of a Johnson V = 0 star.
V_ZERO_ILLUMINANCE_LUX = 2.54e-6


@dataclass(frozen=True)
class StarPhotometricCalibration:
    profile_key: str
    camera_model: str
    lens_name: str
    aperture: float
    calibration_divisor: float
    source: str
    zero_point: float
    extinction_mag_per_airmass: float
    fit_rms_mag: float
    used_stars: int
    sample_solid_angle_sr: float
    lens_model_exif: str | None = None
    color_coefficient: float | None = None
    schema_version: int = 1
    method: str = "stellar_bouguer_v_jkc"

    def validate_for(self, profile, exif) -> None:
        if self.profile_key != profile.key or self.camera_model != exif.camera_model:
            raise ValueError("Fotometricky profil patri jine sestave.")
        if not math.isclose(self.aperture, exif.aperture, abs_tol=0.06):
            raise ValueError(
                f"Fotometricky profil je pro f/{self.aperture:g}, snimek ma f/{exif.aperture:g}."
            )
        expected = (self.lens_model_exif or "").strip().casefold()
        actual = (exif.lens_model or "").strip().casefold()
        if expected and actual and expected != actual:
            raise ValueError("Fotometricky profil patri jinemu objektivu.")
        if not math.isfinite(self.calibration_divisor) or self.calibration_divisor <= 0:
            raise ValueError("Fotometricky profil ma neplatny prevodni koeficient.")

    def report(self) -> dict[str, object]:
        return asdict(self)


def derive_star_calibration(extinction_result, profile, exif) -> StarPhotometricCalibration:
    """Derive the radiance divisor from the above-atmosphere Bouguer intercept."""

    pixel_pitch_mm = profile.sensor_width_mm * 2.0 / profile.crop_size
    solid_angle = (pixel_pitch_mm / profile.focal_length_mm) ** 2
    measured_zero_star_sum = 10.0 ** (-0.4 * extinction_result.zero_point)
    divisor_used = float(extinction_result.calibration_divisor_used)
    new_divisor = (
        divisor_used
        * measured_zero_star_sum
        * solid_angle
        / V_ZERO_ILLUMINANCE_LUX
    )
    calibration = StarPhotometricCalibration(
        profile_key=profile.key,
        camera_model=exif.camera_model,
        lens_name=profile.lens_name,
        lens_model_exif=exif.lens_model,
        aperture=exif.aperture,
        calibration_divisor=float(new_divisor),
        source=extinction_result.source,
        zero_point=extinction_result.zero_point,
        extinction_mag_per_airmass=extinction_result.extinction_mag_per_airmass,
        color_coefficient=extinction_result.color_coefficient,
        fit_rms_mag=extinction_result.fit_rms_mag,
        used_stars=extinction_result.used_stars,
        sample_solid_angle_sr=float(solid_angle),
    )
    calibration.validate_for(profile, exif)
    return calibration


def save_star_calibration(
    calibration: StarPhotometricCalibration, path: str | Path
) -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(calibration.report(), ensure_ascii=False, indent=2, allow_nan=False),
        encoding="utf-8",
    )
    return target


def load_star_calibration(path: str | Path) -> StarPhotometricCalibration:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    calibration = StarPhotometricCalibration(
        profile_key=str(data["profile_key"]),
        camera_model=str(data["camera_model"]),
        lens_name=str(data["lens_name"]),
        lens_model_exif=data.get("lens_model_exif"),
        aperture=float(data["aperture"]),
        calibration_divisor=float(data["calibration_divisor"]),
        source=str(data["source"]),
        zero_point=float(data["zero_point"]),
        extinction_mag_per_airmass=float(data["extinction_mag_per_airmass"]),
        color_coefficient=(
            float(data["color_coefficient"])
            if data.get("color_coefficient") is not None
            else None
        ),
        fit_rms_mag=float(data["fit_rms_mag"]),
        used_stars=int(data["used_stars"]),
        sample_solid_angle_sr=float(data["sample_solid_angle_sr"]),
        schema_version=int(data.get("schema_version", 1)),
        method=str(data.get("method", "stellar_bouguer_v_jkc")),
    )
    if calibration.schema_version != 1 or calibration.method != "stellar_bouguer_v_jkc":
        raise ValueError("Nepodporovany format hvezdne fotometricke kalibrace.")
    return calibration


def _safe_name(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", text).strip("_.") or "stellar_profile"


class StarCalibrationRegistry:
    def __init__(self, directory: str | Path | None = None) -> None:
        if directory is None:
            base = Path(os.environ.get("APPDATA", Path.home()))
            directory = base / "PyRaw2Lum" / "photometric_profiles"
        self.directory = Path(directory)

    def entries(self) -> list[tuple[Path, StarPhotometricCalibration]]:
        if not self.directory.is_dir():
            return []
        entries: list[tuple[Path, StarPhotometricCalibration]] = []
        for path in sorted(self.directory.glob("*.json")):
            try:
                entries.append((path, load_star_calibration(path)))
            except (OSError, ValueError, KeyError, TypeError):
                continue
        return entries

    def store(self, calibration: StarPhotometricCalibration) -> Path:
        aperture = f"{calibration.aperture:g}".replace(".", "_")
        lens = _safe_name(calibration.lens_model_exif or calibration.lens_name)[:60]
        path = self.directory / f"{_safe_name(calibration.profile_key)}__{lens}__f{aperture}.json"
        return save_star_calibration(calibration, path)

    def import_file(self, path: str | Path) -> Path:
        return self.store(load_star_calibration(path))

    def remove(self, path: str | Path) -> None:
        target = Path(path).resolve()
        if target.parent != self.directory.resolve() or target.suffix.lower() != ".json":
            raise ValueError("Profil neni ulozen ve spravovane slozce PyRaw2Lum.")
        target.unlink(missing_ok=True)

    def match(self, exif, profile) -> Path | None:
        matches: list[tuple[float, Path]] = []
        for path, calibration in self.entries():
            try:
                calibration.validate_for(profile, exif)
            except ValueError:
                continue
            matches.append((path.stat().st_mtime, path))
        return max(matches, key=lambda item: item[0])[1] if matches else None


def calibration_label(calibration: StarPhotometricCalibration) -> str:
    lens = calibration.lens_model_exif or calibration.lens_name
    return (
        f"{calibration.camera_model} | {lens} | f/{calibration.aperture:g} | "
        f"T={calibration.calibration_divisor:.5g}"
    )
