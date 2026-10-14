from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

import numpy as np

from raw2lum.profiles import CANON_600D_SIGMA_45
from raw2lum.core import _vignetting_transmissions
from raw2lum.vignetting import (
    VignettingCalibration,
    load_vignetting_calibration,
    save_vignetting_calibration,
)
from raw2lum.vignetting_calibration import _robust_radial_fit, measure_artificial_source
from raw2lum.vignetting_registry import VignettingProfileRegistry, profile_label


class VignettingTests(unittest.TestCase):
    def test_registry_stores_matches_and_removes_profile(self) -> None:
        calibration = VignettingCalibration(
            profile_key=CANON_600D_SIGMA_45.key,
            camera_model=CANON_600D_SIGMA_45.camera_model,
            lens_name=CANON_600D_SIGMA_45.lens_name,
            aperture=3.5,
            max_radius_px=CANON_600D_SIGMA_45.max_calibrated_radius,
            coefficients={"R": (-0.2,), "G": (-0.25,), "B": (-0.3,)},
            fit_rms_percent={"R": 1.0, "G": 1.0, "B": 1.0},
            lens_model_exif="Sigma 4.5mm F2.8 EX DC HSM Circular Fisheye",
        )
        exif = SimpleNamespace(
            camera_model=CANON_600D_SIGMA_45.camera_model,
            lens_model="Sigma 4.5mm F2.8 EX DC HSM Circular Fisheye",
            aperture=3.5,
        )
        with tempfile.TemporaryDirectory() as directory:
            registry = VignettingProfileRegistry(directory)
            path = registry.store(calibration)
            self.assertEqual(registry.match(exif, CANON_600D_SIGMA_45), path)
            registry.remove(path)
            self.assertIsNone(registry.match(exif, CANON_600D_SIGMA_45))

    def test_profile_description_round_trip_and_registry_edit(self) -> None:
        calibration = VignettingCalibration(
            profile_key=CANON_600D_SIGMA_45.key,
            camera_model=CANON_600D_SIGMA_45.camera_model,
            lens_name=CANON_600D_SIGMA_45.lens_name,
            aperture=3.5,
            max_radius_px=CANON_600D_SIGMA_45.max_calibrated_radius,
            coefficients={"R": (-0.2,), "G": (-0.25,), "B": (-0.3,)},
            fit_rms_percent={"R": 1.0, "G": 1.0, "B": 1.0},
            description="Canon 600D + Sigma 4,5 mm",
        )
        with tempfile.TemporaryDirectory() as directory:
            registry = VignettingProfileRegistry(directory)
            path = registry.store(calibration)
            loaded = load_vignetting_calibration(path)
            self.assertEqual(loaded.description, calibration.description)
            self.assertTrue(profile_label(loaded).startswith(calibration.description))
            registry.update_description(path, "Sestava na Jizerce")
            edited = load_vignetting_calibration(path)
            self.assertEqual(edited.description, "Sestava na Jizerce")

    def test_artificial_source_is_found_and_measured_in_rgb(self) -> None:
        rng = np.random.default_rng(123)
        shape = (200, 200)
        red = rng.normal(100.0, 1.0, shape)
        green = rng.normal(120.0, 1.0, shape)
        blue = rng.normal(80.0, 1.0, shape)
        red[94:107, 144:157] += 500.0
        green[94:107, 144:157] += 1000.0
        blue[94:107, 144:157] += 250.0
        x, y, fluxes, saturated = measure_artificial_source(
            red, green, blue, np.zeros(shape, dtype=bool), max_radius_px=95.0
        )
        self.assertAlmostEqual(x, 150.0, delta=1.0)
        self.assertAlmostEqual(y, 100.0, delta=1.0)
        self.assertFalse(saturated)
        self.assertAlmostEqual(fluxes["G"] / fluxes["R"], 2.0, delta=0.03)
        self.assertAlmostEqual(fluxes["B"] / fluxes["R"], 0.5, delta=0.03)

    def test_robust_radial_fit_recovers_profile_with_outlier(self) -> None:
        radius = np.linspace(0.0, 0.95, 24)
        expected = np.asarray([-0.45, -0.22, -0.08])
        flux = 10000.0 * np.exp(
            expected[0] * radius**2
            + expected[1] * radius**4
            + expected[2] * radius**6
        )
        flux *= 1.0 + 0.003 * np.sin(np.arange(len(radius)))
        flux[11] *= 0.72
        coefficients, used, rms = _robust_radial_fit(radius, flux)
        self.assertLess(len(used), len(radius))
        np.testing.assert_allclose(coefficients, expected, atol=0.035)
        self.assertLess(rms, 0.5)

    def test_profile_round_trip_and_center_normalization(self) -> None:
        calibration = VignettingCalibration(
            profile_key=CANON_600D_SIGMA_45.key,
            camera_model=CANON_600D_SIGMA_45.camera_model,
            lens_name=CANON_600D_SIGMA_45.lens_name,
            aperture=3.5,
            max_radius_px=50.0,
            coefficients={
                "R": (-0.5, -0.1, 0.0),
                "G": (-0.4, -0.1, 0.0),
                "B": (-0.6, -0.1, 0.0),
            },
            fit_rms_percent={"R": 1.0, "G": 1.0, "B": 1.0},
        )
        with tempfile.TemporaryDirectory() as directory:
            path = save_vignetting_calibration(calibration, Path(directory) / "profile.json")
            loaded = load_vignetting_calibration(path)
        loaded.validate_for(CANON_600D_SIGMA_45, 3.5)
        transmission = loaded.transmission("G", (100, 100))
        self.assertAlmostEqual(transmission[50, 50], 1.0, places=8)
        self.assertLess(transmission[50, 99], 1.0)

    def test_custom_flat_replaces_instead_of_multiplying_builtin_profile(self) -> None:
        calibration = VignettingCalibration(
            profile_key=CANON_600D_SIGMA_45.key,
            camera_model=CANON_600D_SIGMA_45.camera_model,
            lens_name=CANON_600D_SIGMA_45.lens_name,
            aperture=3.5,
            max_radius_px=50.0,
            coefficients={"R": (-0.4,), "G": (-0.5,), "B": (-0.6,)},
            fit_rms_percent={"R": 1.0, "G": 1.0, "B": 1.0},
        )
        shape = (100, 100)
        red, green, blue = _vignetting_transmissions(
            CANON_600D_SIGMA_45, calibration, shape
        )
        np.testing.assert_allclose(red, calibration.transmission("R", shape))
        np.testing.assert_allclose(green, calibration.transmission("G", shape))
        np.testing.assert_allclose(blue, calibration.transmission("B", shape))
        built_in = CANON_600D_SIGMA_45.vignetting(shape)
        self.assertNotAlmostEqual(green[0, 0], green[0, 0] * built_in[0, 0], places=6)


if __name__ == "__main__":
    unittest.main()
