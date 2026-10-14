from types import SimpleNamespace

import numpy as np
from PIL import Image, ImageDraw

import raw2lum.rendering as rendering
from raw2lum.rendering import (
    _draw_altitude_circles,
    _draw_true_horizon_circle,
    _project_altitude_segments,
)


def _result(orientation=True, horizon=True, altitudes=False):
    return SimpleNamespace(
        profile=SimpleNamespace(max_calibrated_radius=8.0),
        orientation_matrix=np.eye(3) if orientation else None,
        orientation_info={"projection_radius_scale": 10.0},
        show_horizon_circle=horizon,
        show_altitude_circles=altitudes,
    )


def test_horizon_is_line_not_mask_and_requires_full_orientation() -> None:
    image = Image.new("RGB", (20, 20), (120, 40, 20))
    draw = ImageDraw.Draw(image)
    _draw_true_horizon_circle(draw, _result(), 0, 0, 20, 20, 1)

    # r_horizon = sin(45°) * 10 ~= 7.07; data outside it remain untouched.
    assert image.getpixel((10, 0)) == (120, 40, 20)
    assert image.getpixel((10, 3)) != (120, 40, 20)

    without_solution = Image.new("RGB", (20, 20), (120, 40, 20))
    _draw_true_horizon_circle(
        ImageDraw.Draw(without_solution), _result(False), 0, 0, 20, 20, 1
    )
    assert without_solution.getpixel((10, 3)) == (120, 40, 20)

    disabled = Image.new("RGB", (20, 20), (120, 40, 20))
    _draw_true_horizon_circle(
        ImageDraw.Draw(disabled), _result(horizon=False), 0, 0, 20, 20, 1
    )
    assert disabled.getpixel((10, 3)) == (120, 40, 20)


def test_horizon_is_drawn_outside_vignetting_calibration_radius() -> None:
    result = _result()
    result.profile.max_calibrated_radius = 6.0
    image = Image.new("RGB", (20, 20), (120, 40, 20))
    _draw_true_horizon_circle(ImageDraw.Draw(image), result, 0, 0, 20, 20, 1)
    assert any(pixel != (120, 40, 20) for pixel in image.getdata())


def test_altitude_grid_is_optional_and_requires_full_orientation() -> None:
    base = (120, 40, 20)
    enabled = Image.new("RGB", (20, 20), base)
    _draw_altitude_circles(
        ImageDraw.Draw(enabled), _result(altitudes=True), 0, 0, 20, 20, 1
    )
    colors = set(enabled.getdata())
    assert (0, 0, 0) in colors
    assert (255, 255, 255) in colors

    for result in (_result(altitudes=False), _result(False, altitudes=True)):
        disabled = Image.new("RGB", (20, 20), base)
        _draw_altitude_circles(
            ImageDraw.Draw(disabled), result, 0, 0, 20, 20, 1
        )
        assert all(pixel == base for pixel in disabled.getdata())


def test_tilted_round_map_projects_off_center_curves_without_warping_pixels() -> None:
    angle = np.deg2rad(18.0)
    tilted = _result()
    tilted.orientation_matrix = np.asarray(
        (
            (np.cos(angle), 0.0, np.sin(angle)),
            (0.0, 1.0, 0.0),
            (-np.sin(angle), 0.0, np.cos(angle)),
        )
    )
    segments = _project_altitude_segments(tilted, 0.0, 40, 40, 2)
    points = np.asarray([point for segment in segments for point in segment])
    radii = np.hypot(points[:, 0] - 20.0, points[:, 1] - 20.0)
    assert np.ptp(radii) > 2.0


def test_round_map_compass_places_east_left_and_west_right(monkeypatch) -> None:
    labels = []
    monkeypatch.setattr(
        rendering,
        "_centered",
        lambda _draw, xy, label, _font, _fill: labels.append((xy, label)),
    )
    image = Image.new("RGB", (140, 140), "black")
    rendering._draw_compass_on_round_map(
        ImageDraw.Draw(image), 20, 20, 100, 100, 20, language="en"
    )
    positions = {label: xy for xy, label in labels}
    assert positions["E"][0] < positions["N"][0]
    assert positions["W"][0] > positions["N"][0]
