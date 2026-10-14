from __future__ import annotations

import math
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from raw2lum.photometric_calibration import (
    StarCalibrationRegistry,
    V_ZERO_ILLUMINANCE_LUX,
    derive_star_calibration,
    load_star_calibration,
    save_star_calibration,
)
from raw2lum.profiles import CANON_600D_SIGMA_45


class StarCalibrationTests(unittest.TestCase):
    def test_bouguer_zero_point_recovers_known_divisor(self) -> None:
        profile = CANON_600D_SIGMA_45
        used_divisor = 97.0
        expected_divisor = 123.4
        pitch_mm = profile.sensor_width_mm * 2.0 / profile.input_width
        solid_angle = (pitch_mm / profile.focal_length_mm) ** 2
        measured_sum = (
            expected_divisor
            / used_divisor
            * V_ZERO_ILLUMINANCE_LUX
            / solid_angle
        )
        extinction = SimpleNamespace(
            source="light.CR2",
            zero_point=-2.5 * math.log10(measured_sum),
            extinction_mag_per_airmass=0.23,
            color_coefficient=0.04,
            fit_rms_mag=0.05,
            used_stars=42,
            calibration_divisor_used=used_divisor,
        )
        exif = SimpleNamespace(
            camera_model=profile.camera_model,
            lens_model="Sigma 4.5 mm",
            aperture=3.5,
        )
        result = derive_star_calibration(extinction, profile, exif)
        self.assertAlmostEqual(result.calibration_divisor, expected_divisor, places=10)

    def test_profile_round_trip_and_registry_match(self) -> None:
        profile = CANON_600D_SIGMA_45
        exif = SimpleNamespace(
            camera_model=profile.camera_model,
            lens_model="Sigma 4.5 mm",
            aperture=3.5,
        )
        extinction = SimpleNamespace(
            source="light.CR2",
            zero_point=5.0,
            extinction_mag_per_airmass=0.2,
            color_coefficient=None,
            fit_rms_mag=0.08,
            used_stars=30,
            calibration_divisor_used=97.0,
        )
        calibration = derive_star_calibration(extinction, profile, exif)
        with tempfile.TemporaryDirectory() as directory:
            saved = save_star_calibration(calibration, Path(directory) / "profile.json")
            loaded = load_star_calibration(saved)
            self.assertEqual(loaded, calibration)
            registry = StarCalibrationRegistry(Path(directory) / "managed")
            managed = registry.store(loaded)
            self.assertEqual(registry.match(exif, profile), managed)
            registry.remove(managed)
            self.assertIsNone(registry.match(exif, profile))


if __name__ == "__main__":
    unittest.main()
