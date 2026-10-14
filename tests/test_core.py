from __future__ import annotations

import os
import unittest
from pathlib import Path
from types import SimpleNamespace

import numpy as np
from PIL import Image

from raw2lum.core import (
    ExifData,
    analyze_raw,
    dark_matches_light,
    exif_time_to_utc,
    exposure_normalization_factor,
    luminance_to_msa,
    msa_to_luminance,
    _rectilinear_solid_angle_correction,
)
from raw2lum.color_analysis import compute_color_indices, summarize_color
from raw2lum.palette import HOLLAN_LOG_PALETTE, NPS_PALETTE
from raw2lum.profiles import (
    CANON_600D_SIGMA_45,
    CANON_R6M2_SIGMA_45,
    profile_for_camera,
    rectilinear_profile,
)
from raw2lum.rendering import (
    fisheye_to_panorama,
    orient_image_north_up,
    reproject_fisheye_north_up,
)
from raw2lum.astrometry import (
    STAR_BY_LABEL,
    StarMatch,
    solve_orientation,
    star_enu_vector,
)


class ConversionTests(unittest.TestCase):
    def test_relative_rgb_color_indices(self) -> None:
        red = np.array([[2.0, -1.0], [4.0, 1.0]])
        green = np.array([[4.0, 2.0], [4.0, 1.0]])
        blue = np.array([[4.0, 3.0], [2.0, 1.0]])
        mask = np.array([[True, True], [True, False]])
        blue_fraction, blue_green, red_green = compute_color_indices(
            red, green, blue, mask
        )
        self.assertAlmostEqual(float(blue_fraction[0, 0]), 0.4)
        self.assertAlmostEqual(float(blue_green[0, 0]), 1.0)
        self.assertAlmostEqual(float(red_green[0, 0]), 0.5)
        self.assertTrue(np.isnan(blue_fraction[0, 1]))  # zaporny R po darku
        self.assertTrue(np.isnan(blue_fraction[1, 1]))  # explicitni maska

    def test_zenith_color_uses_channel_medians(self) -> None:
        red = np.array([[2.0, 2.0], [100.0, 2.0]])
        green = np.full((2, 2), 4.0)
        blue = np.full((2, 2), 4.0)
        summary = summarize_color(red, green, blue, np.ones((2, 2), dtype=bool))
        self.assertAlmostEqual(summary.red_fraction, 0.2)
        self.assertAlmostEqual(summary.green_fraction, 0.4)
        self.assertAlmostEqual(summary.blue_fraction, 0.4)
        self.assertAlmostEqual(summary.blue_green_ratio, 1.0)
        self.assertEqual(summary.valid_pixels, 4)

    def test_r6m2_uses_its_own_smaller_image_circle(self) -> None:
        profile = profile_for_camera("Canon EOS R6m2")
        self.assertIs(profile, CANON_R6M2_SIGMA_45)
        self.assertEqual(profile.crop_size, 2072)
        self.assertLess(profile.crop_size, CANON_600D_SIGMA_45.crop_size)
        self.assertEqual(profile.output_size, 1036)

    def test_rectilinear_profile_preserves_full_rectangular_sensor(self) -> None:
        profile = rectilinear_profile(
            "Canon EOS 600D", "20 mm lens", 20.0, 2.8, 5184, 3456
        )
        self.assertEqual(profile.projection, "rectilinear")
        self.assertEqual((profile.input_width, profile.input_height), (5184, 3456))
        self.assertEqual((profile.output_width, profile.output_height), (2592, 1728))

    def test_rectilinear_pixel_solid_angle_is_corrected_towards_corners(self) -> None:
        profile = rectilinear_profile(
            "Canon EOS 600D", "20 mm lens", 20.0, 2.8, 5184, 3456
        )
        correction = _rectilinear_solid_angle_correction(profile, (120, 180))
        self.assertAlmostEqual(float(correction[59, 89]), 1.0, places=3)
        self.assertGreater(float(correction[0, 0]), 1.2)

    def test_msa_round_trip(self) -> None:
        expected = np.array([17.5, 20.0, 22.0])
        actual = luminance_to_msa(msa_to_luminance(expected))
        np.testing.assert_allclose(actual, expected, atol=1e-12)

    def test_pascal_palette_endpoints(self) -> None:
        self.assertEqual(tuple(NPS_PALETTE[0]), (30, 0, 0))
        self.assertEqual(tuple(NPS_PALETTE[-1]), (255, 255, 255))
        self.assertEqual(len(NPS_PALETTE), 46)

    def test_hollan_log_palette(self) -> None:
        self.assertEqual(len(HOLLAN_LOG_PALETTE), 45)
        self.assertEqual(tuple(HOLLAN_LOG_PALETTE[0]), (66, 33, 0))
        self.assertEqual(tuple(HOLLAN_LOG_PALETTE[-1]), (255, 255, 255))

    def test_prague_time_is_converted_to_utc(self) -> None:
        self.assertEqual(
            exif_time_to_utc("2026:01:15 22:00:00", "Europe/Prague"),
            "2026-01-15 21:00:00 UTC",
        )
        self.assertEqual(
            exif_time_to_utc("2026:09:15 22:35:36", "Europe/Prague"),
            "2026-09-15 20:35:36 UTC",
        )

    def test_fixed_camera_time_offset(self) -> None:
        self.assertEqual(
            exif_time_to_utc("2026:09:15 22:35:36", "UTC+01:00"),
            "2026-09-15 21:35:36 UTC",
        )

    def test_exposure_and_iso_normalization(self) -> None:
        factor_30 = exposure_normalization_factor(400, 30, 3.5, 97)
        factor_300 = exposure_normalization_factor(400, 300, 3.5, 97)
        factor_iso_800 = exposure_normalization_factor(800, 30, 3.5, 97)
        self.assertAlmostEqual(factor_300 / factor_30, 10.0)
        self.assertAlmostEqual(factor_iso_800 / factor_30, 2.0)
        # Je-li RAW signal u desetkrat delsi expozice desetkrat vyssi,
        # vysledna absolutni luminance zustane stejna.
        self.assertAlmostEqual(1000 / factor_30, 10000 / factor_300)

    def test_dark_matching_uses_inclusive_one_second_tolerance(self) -> None:
        def metadata(exposure: float, iso: float = 400, camera: str = "Canon EOS 600D"):
            return ExifData(camera, exposure, iso, 3.5, 4.5, None, None)

        light = metadata(30.0)
        self.assertTrue(dark_matches_light(light, metadata(29.0)))
        self.assertTrue(dark_matches_light(light, metadata(31.0)))
        self.assertFalse(dark_matches_light(light, metadata(31.01)))
        self.assertFalse(dark_matches_light(light, metadata(30.0, iso=800)))
        self.assertFalse(dark_matches_light(light, metadata(30.0, camera="Canon EOS 6D")))

    def test_panorama_uses_calibrated_projection_and_north_in_center(self) -> None:
        size = CANON_600D_SIGMA_45.output_size
        yy, xx = np.indices((size, size), dtype=np.float32)
        values = yy * 2000.0 + xx
        result = SimpleNamespace(
            profile=CANON_600D_SIGMA_45,
            north_angle_deg=0.0,
            orientation_matrix=None,
        )
        panorama = fisheye_to_panorama(values, result, (3, 8))
        center = size // 2
        np.testing.assert_array_equal(panorama[0], np.full(8, values[center, center]))
        radius = round(
            min(
                CANON_600D_SIGMA_45.max_calibrated_radius,
                CANON_600D_SIGMA_45.output_size / 2 - 1,
            )
        )
        self.assertEqual(panorama[-1, 4], values[center, center + radius])
        # Posledni radek obsahuje i uzky kalibrovany pas pod horizontem.
        self.assertEqual(panorama[-1, 2], values[center + radius, center])
        self.assertEqual(panorama[-1, 6], values[center - radius, center])

    def test_panorama_horizon_uses_star_fitted_projection_scale(self) -> None:
        size = CANON_600D_SIGMA_45.output_size
        yy, xx = np.indices((size, size), dtype=np.float32)
        center = size / 2.0
        radial_values = np.hypot(xx - center, yy - center).astype(np.float32)
        nominal = (
            CANON_600D_SIGMA_45.crop_size
            * CANON_600D_SIGMA_45.focal_length_mm
            / CANON_600D_SIGMA_45.sensor_width_mm
        )
        fitted = nominal * 0.94
        result = SimpleNamespace(
            profile=CANON_600D_SIGMA_45,
            north_angle_deg=None,
            orientation_matrix=np.eye(3),
            orientation_info={"projection_radius_scale": fitted},
        )
        out_h, out_w = 401, 720
        panorama = fisheye_to_panorama(radial_values, result, (out_h, out_w))
        max_radius = min(
            CANON_600D_SIGMA_45.max_calibrated_radius,
            size / 2.0 - 1.0,
        )
        max_distance = 2.0 * np.arcsin(max_radius / fitted)
        horizon_row = round((np.pi / 2.0) / max_distance * (out_h - 1))
        self.assertAlmostEqual(
            float(panorama[horizon_row, out_w // 2]),
            fitted / np.sqrt(2.0),
            delta=2.0,
        )

    def test_round_map_rotation_places_north_at_top(self) -> None:
        pixels = np.zeros((5, 5, 3), dtype=np.uint8)
        pixels[2, 4] = (255, 0, 0)  # sever je puvodne vpravo
        rotated = np.asarray(orient_image_north_up(Image.fromarray(pixels), 0.0))
        self.assertEqual(tuple(rotated[0, 2]), (255, 0, 0))

    def test_star_reprojected_round_map_is_not_mirrored_east_west(self) -> None:
        size = 32
        yy, xx = np.indices((size, size), dtype=np.float32)
        values = yy * 100.0 + xx
        profile = SimpleNamespace(
            crop_size=size,
            focal_length_mm=1.0,
            sensor_width_mm=2.0,
            # Deliberately smaller than the tested radius: presentation must
            # retain real RAW pixels outside the vignetting calibration.
            max_calibrated_radius=3.0,
        )
        result = SimpleNamespace(
            profile=profile,
            orientation_matrix=np.eye(3),
            orientation_info={"projection_radius_scale": 16.0},
        )
        output = reproject_fisheye_north_up(values, result)
        center, radius = size // 2, 4

        # For a camera looking upward, a north-up round map is an overhead
        # view: raw north (bottom here) moves to the top, while raw east
        # (right here) moves to the left. This is a rotation, not a mirror.
        self.assertEqual(
            output[center - radius, center], values[center + radius, center]
        )
        self.assertEqual(
            output[center, center - radius], values[center, center + radius]
        )
        self.assertEqual(
            output[center, center + radius], values[center, center - radius]
        )

    def test_three_stars_recover_full_camera_orientation(self) -> None:
        labels = [label for label in STAR_BY_LABEL if label.startswith(("Vega ", "Deneb ", "Altair "))]
        stars = [STAR_BY_LABEL[label] for label in labels]
        captured = "2026-09-15 20:35:36 UTC"
        latitude, longitude = 50.82, 15.35
        ax, ay, az = np.radians((2.0, -3.0, 27.0))
        rx = np.array(((1, 0, 0), (0, np.cos(ax), -np.sin(ax)), (0, np.sin(ax), np.cos(ax))))
        ry = np.array(((np.cos(ay), 0, np.sin(ay)), (0, 1, 0), (-np.sin(ay), 0, np.cos(ay))))
        rz = np.array(((np.cos(az), -np.sin(az), 0), (np.sin(az), np.cos(az), 0), (0, 0, 1)))
        expected = rz @ ry @ rx
        scale = (
            CANON_600D_SIGMA_45.crop_size
            * CANON_600D_SIGMA_45.focal_length_mm
            / CANON_600D_SIGMA_45.sensor_width_mm
        )
        center = CANON_600D_SIGMA_45.output_size / 2
        matches = []
        for star in stars:
            world = star_enu_vector(star, captured, latitude, longitude)
            camera = expected.T @ world
            z = np.arccos(np.clip(camera[2], -1, 1))
            radius = np.sin(z / 2) * scale
            angle = np.arctan2(camera[1], camera[0])
            matches.append(
                StarMatch(star, center + radius * np.cos(angle), center + radius * np.sin(angle))
            )
        solution = solve_orientation(
            matches,
            CANON_600D_SIGMA_45,
            captured,
            latitude,
            longitude,
        )
        np.testing.assert_allclose(solution.camera_to_enu, expected, atol=1e-7)
        self.assertAlmostEqual(solution.radius_scale, scale, places=4)
        self.assertLess(solution.rms_deg, 1e-6)

    def test_stars_recover_projection_scale_as_well_as_rotation(self) -> None:
        stars = [
            next(star for star in STAR_BY_LABEL.values() if star.name == name)
            for name in ("Vega", "Deneb", "Altair")
        ]
        captured = "2026-09-15 20:35:36 UTC"
        latitude, longitude = 50.82, 15.35
        nominal = (
            CANON_600D_SIGMA_45.crop_size
            * CANON_600D_SIGMA_45.focal_length_mm
            / CANON_600D_SIGMA_45.sensor_width_mm
        )
        actual_scale = nominal * 1.045
        center = CANON_600D_SIGMA_45.output_size / 2
        matches = []
        for star in stars:
            camera = star_enu_vector(star, captured, latitude, longitude)
            distance = np.arccos(np.clip(camera[2], -1, 1))
            radius = np.sin(distance / 2) * actual_scale
            angle = np.arctan2(camera[1], camera[0])
            matches.append(
                StarMatch(star, center + radius * np.cos(angle), center + radius * np.sin(angle))
            )
        solution = solve_orientation(
            matches,
            CANON_600D_SIGMA_45,
            captured,
            latitude,
            longitude,
        )
        self.assertAlmostEqual(solution.radius_scale, actual_scale, places=4)
        np.testing.assert_allclose(solution.camera_to_enu, np.eye(3), atol=1e-7)
        self.assertLess(solution.rms_deg, 1e-6)


@unittest.skipUnless(os.environ.get("RAW2LUM_REFERENCE_DIR"), "referencni data nejsou nastavena")
class PascalReferenceTests(unittest.TestCase):
    def test_matches_three_pascal_maps(self) -> None:
        base = Path(os.environ["RAW2LUM_REFERENCE_DIR"])
        dark = base / "dark.CR2"
        for stem in ("jizerka", "kralovka", "rozdroze"):
            with self.subTest(stem=stem):
                result = analyze_raw(base / f"{stem}_2026.CR2", dark)
                reference = np.asarray(Image.open(base / f"{stem}.ppm"))[:, :1444]
                equality = np.all(result.color_map == reference, axis=2)
                # Rozdily jsou omezeny na puvodni volitelne vyhlazovani a okraj.
                self.assertGreater(float(np.mean(equality)), 0.985)


if __name__ == "__main__":
    unittest.main()
