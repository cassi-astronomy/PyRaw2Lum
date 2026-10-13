from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import numpy as np

from raw2lum.extinction import (
    CatalogStar,
    ExtinctionResult,
    StarPhotometry,
    _isolated_candidates,
    _robust_fit,
    bundled_gaia_catalog_path,
    load_gaia_gspc_csv,
    mid_exposure_utc,
    save_extinction_result,
)


class ExtinctionTests(unittest.TestCase):
    def test_bundled_catalog_is_available_offline(self) -> None:
        path = bundled_gaia_catalog_path()
        self.assertTrue(path.is_file())
        self.assertGreater(len(load_gaia_gspc_csv(path, max_v_mag=6.0)), 3000)

    def test_mid_exposure_uses_half_of_exposure(self) -> None:
        self.assertEqual(
            mid_exposure_utc("2026-09-15 20:35:36 UTC", 179.0),
            "2026-09-15 20:37:05.500 UTC",
        )

    def test_gaia_csv_loader_accepts_archive_columns_and_flags(self) -> None:
        content = (
            "source_id,ra,dec,b_jkc_mag,v_jkc_mag,v_jkc_flag\n"
            "1,10.0,20.0,6.1,5.5,1\n"
            "2,11.0,21.0,6.4,5.8,0\n"
            "3,12.0,22.0,9.0,8.5,1\n"
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "gaia.csv"
            path.write_text(content, encoding="utf-8")
            stars = load_gaia_gspc_csv(path, max_v_mag=7.5)
        self.assertEqual(len(stars), 1)
        self.assertEqual(stars[0].source_id, "1")
        self.assertAlmostEqual(stars[0].b_minus_v, 0.6)

    def test_robust_bouguer_fit_recovers_extinction_and_rejects_outlier(self) -> None:
        measurements = []
        expected_k, expected_zero, expected_color = 0.23, -4.8, 0.08
        for index in range(30):
            airmass = 1.0 + 1.3 * index / 29
            color = -0.1 + 1.4 * ((index * 7) % 29) / 28
            v_mag = 4.0 + (index % 9) * 0.25
            noise = 0.008 * np.sin(index)
            instrumental = (
                v_mag + expected_zero + expected_k * airmass + expected_color * color + noise
            )
            if index == 17:
                instrumental += 1.2
            measurements.append(
                StarPhotometry(
                    source_id=str(index),
                    ra_deg=0.0,
                    dec_deg=0.0,
                    altitude_deg=45.0,
                    azimuth_deg=0.0,
                    airmass=airmass,
                    v_mag=v_mag,
                    b_minus_v=color,
                    x=0.0,
                    y=0.0,
                    trail_length_px=0.0,
                    flux=1.0,
                    snr=100.0,
                    instrumental_mag=instrumental,
                    used=True,
                    reason="",
                )
            )
        _valid, indices, coefficients, _residuals, uncertainty = _robust_fit(measurements)
        self.assertLess(len(indices), len(measurements))
        self.assertAlmostEqual(coefficients[1], expected_k, delta=0.01)
        self.assertAlmostEqual(coefficients[2], expected_color, delta=0.01)
        self.assertLess(uncertainty, 0.01)

    def test_isolation_filter_removes_close_catalog_pair(self) -> None:
        stars = [
            CatalogStar(str(index), 0.0, 0.0, 4.0 + index, None)
            for index in range(4)
        ]
        x = np.asarray([10.0, 12.0, 50.0, 90.0])
        y = np.asarray([10.0, 10.0, 50.0, 90.0])
        selected = _isolated_candidates(
            np.arange(4), x, y, stars, exclusion_radius=5.0
        )
        self.assertNotIn(0, selected)
        self.assertNotIn(1, selected)
        self.assertIn(2, selected)
        self.assertIn(3, selected)

    def test_extinction_exports_json_csv_and_plot(self) -> None:
        item = StarPhotometry(
            source_id="1", ra_deg=1.0, dec_deg=2.0, altitude_deg=45.0,
            azimuth_deg=90.0, airmass=1.4, v_mag=5.0, b_minus_v=0.5,
            x=10.0, y=20.0, trail_length_px=0.0, flux=100.0, snr=30.0,
            instrumental_mag=-5.0, used=True, reason="", residual_mag=0.01,
        )
        second = StarPhotometry(
            **{**item.__dict__, "source_id": "2", "airmass": 2.0,
               "instrumental_mag": -4.85}
        )
        result = ExtinctionResult(
            source="test.CR2", mode="tracker", extinction_mag_per_airmass=0.25,
            extinction_std_error=0.02, zero_point=-10.4, color_coefficient=None,
            fit_rms_mag=0.03, used_stars=2, measured_stars=2,
            catalog_candidates=2, airmass_min=1.4, airmass_max=2.0,
            mid_exposure_utc="2026-01-01 00:00:15.000 UTC",
            measurements=(item, second),
        )
        with tempfile.TemporaryDirectory() as directory:
            paths = save_extinction_result(result, directory)
            self.assertEqual(len(paths), 3)
            self.assertTrue(all(path.is_file() and path.stat().st_size > 0 for path in paths))


if __name__ == "__main__":
    unittest.main()
