from types import SimpleNamespace

import numpy as np
from PIL import Image, ImageDraw

from raw2lum.rendering import (
    _draw_altitude_circles,
    _draw_true_horizon_circle,
    _smooth_calibrated_circle,
)


def _result(orientation=True, horizon=True, altitudes=False):
    return SimpleNamespace(
        profile=SimpleNamespace(max_calibrated_radius=8.0),
        orientation_matrix=np.eye(3) if orientation else None,
        orientation_info={"projection_radius_scale": 10.0},
        show_horizon_circle=horizon,
        show_altitude_circles=altitudes,
    )


def test_calibrated_circle_gets_smooth_edge_without_cropping_inside() -> None:
    source = Image.new("RGB", (20, 20), (255, 0, 0))
    masked = _smooth_calibrated_circle(source, _result(), 1)

    assert masked.getpixel((10, 10)) == (255, 0, 0)
    assert masked.getpixel((0, 0)) == (0, 0, 0)
    edge_red = masked.getpixel((10, 2))[0]
    assert 0 < edge_red < 255


def test_horizon_is_line_not_mask_and_requires_full_orientation() -> None:
    image = Image.new("RGB", (20, 20), (120, 40, 20))
    draw = ImageDraw.Draw(image)
    _draw_true_horizon_circle(draw, _result(), 0, 0, 20, 20, 1)

    # r_horizon = sin(45°) * 10 ~= 7.07; data outside it remain untouched.
    assert image.getpixel((10, 1)) == (120, 40, 20)
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


def test_altitude_grid_is_optional_and_requires_full_orientation() -> None:
    base = (120, 40, 20)
    enabled = Image.new("RGB", (20, 20), base)
    _draw_altitude_circles(
        ImageDraw.Draw(enabled), _result(altitudes=True), 0, 0, 20, 20, 1
    )
    assert any(pixel != base for pixel in enabled.getdata())

    for result in (_result(altitudes=False), _result(False, altitudes=True)):
        disabled = Image.new("RGB", (20, 20), base)
        _draw_altitude_circles(
            ImageDraw.Draw(disabled), result, 0, 0, 20, 20, 1
        )
        assert all(pixel == base for pixel in disabled.getdata())
