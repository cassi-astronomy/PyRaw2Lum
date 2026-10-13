"""Ukladani a aplikace uzivatelsky zmerene barevne vinetace."""

from __future__ import annotations

from dataclasses import dataclass
import json
import math
from pathlib import Path

import numpy as np


@dataclass(frozen=True)
class VignettingCalibration:
    profile_key: str
    camera_model: str
    lens_name: str
    aperture: float
    max_radius_px: float
    coefficients: dict[str, tuple[float, ...]]
    fit_rms_percent: dict[str, float]
    lens_model_exif: str | None = None
    source_files: tuple[str, ...] = ()
    measurements: tuple[dict[str, object], ...] = ()
    schema_version: int = 1
    model: str = "radial_log_even"

    def validate_for(self, profile, aperture: float) -> None:
        if self.profile_key != profile.key or self.camera_model != profile.camera_model:
            raise ValueError(
                "Profil vinetace patri jine sestave: "
                f"{self.camera_model} / {self.profile_key}."
            )
        if not math.isclose(self.aperture, aperture, abs_tol=0.06):
            raise ValueError(
                f"Profil vinetace je pro f/{self.aperture:g}, snimek ma f/{aperture:g}."
            )
        if self.model != "radial_log_even":
            raise ValueError(f"Nepodporovany model vinetace {self.model!r}.")
        if self.max_radius_px <= 0:
            raise ValueError("Profil vinetace ma neplatny polomer.")
        for channel in ("R", "G", "B"):
            values = self.coefficients.get(channel)
            if values is None or not 1 <= len(values) <= 4 or not np.all(np.isfinite(values)):
                raise ValueError(f"Profil nema platne koeficienty kanalu {channel}.")

    def transmission(self, channel: str, shape: tuple[int, int]) -> np.ndarray:
        """Relativni propustnost, normalizovana na hodnotu 1 v opticke ose."""

        coefficients = self.coefficients[channel]
        height, width = shape
        yy, xx = np.indices(shape, dtype=np.float64)
        radius = np.hypot(xx - width / 2.0, yy - height / 2.0)
        normalized = radius / self.max_radius_px
        log_value = np.zeros_like(normalized)
        power = normalized * normalized
        for coefficient in coefficients:
            log_value += coefficient * power
            power *= normalized * normalized
        transmission = np.exp(np.clip(log_value, -4.0, 1.0))
        transmission[normalized > 1.03] = 1.0
        return transmission

    def report(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "model": self.model,
            "profile_key": self.profile_key,
            "camera_model": self.camera_model,
            "lens_name": self.lens_name,
            "lens_model_exif": self.lens_model_exif,
            "aperture": self.aperture,
            "max_radius_px": self.max_radius_px,
            "coefficients": {
                channel: list(values) for channel, values in self.coefficients.items()
            },
            "fit_rms_percent": self.fit_rms_percent,
            "source_files": list(self.source_files),
            "measurements": list(self.measurements),
        }


def save_vignetting_calibration(
    calibration: VignettingCalibration, path: str | Path
) -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("w", encoding="utf-8") as handle:
        json.dump(calibration.report(), handle, ensure_ascii=False, indent=2, allow_nan=False)
    return target


def load_vignetting_calibration(path: str | Path) -> VignettingCalibration:
    source = Path(path)
    try:
        data = json.loads(source.read_text(encoding="utf-8"))
        calibration = VignettingCalibration(
            schema_version=int(data.get("schema_version", 1)),
            model=str(data["model"]),
            profile_key=str(data["profile_key"]),
            camera_model=str(data["camera_model"]),
            lens_name=str(data["lens_name"]),
            lens_model_exif=(
                str(data["lens_model_exif"])
                if data.get("lens_model_exif") not in (None, "")
                else None
            ),
            aperture=float(data["aperture"]),
            max_radius_px=float(data["max_radius_px"]),
            coefficients={
                channel: tuple(float(value) for value in values)
                for channel, values in data["coefficients"].items()
            },
            fit_rms_percent={
                channel: float(value)
                for channel, value in data.get("fit_rms_percent", {}).items()
            },
            source_files=tuple(str(value) for value in data.get("source_files", ())),
            measurements=tuple(dict(value) for value in data.get("measurements", ())),
        )
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise ValueError(f"Soubor {source.name} neni platny profil vinetace.") from exc
    if calibration.schema_version != 1:
        raise ValueError(
            f"Nepodporovana verze profilu vinetace {calibration.schema_version}."
        )
    return calibration
