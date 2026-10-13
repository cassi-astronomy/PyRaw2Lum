"""Tvorba prezentacniho PNG s dvojitou fotometrickou legendou."""

from __future__ import annotations

import math
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from .core import AnalysisResult, msa_to_luminance
from .i18n import tr
from .palette import (
    HOLLAN_LOG_BASE_LUMINANCE,
    HOLLAN_LOG_HALF_STEP,
    HOLLAN_LOG_PALETTE,
    HOLLAN_LOG_STEPS_PER_DECADE,
    colorize,
    colorize_hollan_luminance,
)


def _projection_radius_scale(result: AnalysisResult) -> float:
    """Vrati projekcni meritko z hvezdne kalibrace, jinak z profilu."""

    orientation_info = getattr(result, "orientation_info", None)
    if orientation_info is not None:
        fitted = orientation_info.get("projection_radius_scale")
        if fitted is not None:
            value = float(fitted)
            if math.isfinite(value) and value > 0:
                return value
    return (
        result.profile.crop_size
        * result.profile.focal_length_mm
        / result.profile.sensor_width_mm
    )


def _font(size: int, bold: bool = False) -> ImageFont.ImageFont:
    names = (
        [r"C:\Windows\Fonts\segoeuib.ttf", r"C:\Windows\Fonts\arialbd.ttf"]
        if bold
        else [r"C:\Windows\Fonts\segoeui.ttf", r"C:\Windows\Fonts\arial.ttf"]
    )
    names += ["DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf"]
    for name in names:
        try:
            return ImageFont.truetype(name, size=size)
        except OSError:
            continue
    return ImageFont.load_default()


def _centered(draw: ImageDraw.ImageDraw, xy: tuple[float, float], text: str, font, fill) -> None:
    box = draw.textbbox((0, 0), text, font=font)
    width = box[2] - box[0]
    draw.text((xy[0] - width / 2, xy[1]), text, font=font, fill=fill)


def orient_image_north_up(
    image: Image.Image,
    north_angle_deg: float | None,
) -> Image.Image:
    """Otoci mapu bez mezibarev tak, aby sever smeroval svisle nahoru."""

    if north_angle_deg is None:
        return image
    return image.rotate(
        north_angle_deg + 90.0,
        resample=Image.Resampling.NEAREST,
        expand=False,
        fillcolor=(0, 0, 0),
    )


def _smooth_calibrated_circle(
    image: Image.Image,
    result: AnalysisResult,
    display_scale: int,
) -> Image.Image:
    """Apply an anti-aliased edge only at the calibrated image-circle limit."""

    radius = result.profile.max_calibrated_radius * display_scale
    supersampling = 2
    mask = Image.new(
        "L", (image.width * supersampling, image.height * supersampling), 0
    )
    draw = ImageDraw.Draw(mask)
    cx = image.width * supersampling / 2.0
    cy = image.height * supersampling / 2.0
    rr = radius * supersampling
    draw.ellipse((cx - rr, cy - rr, cx + rr, cy + rr), fill=255)
    mask = mask.resize(image.size, Image.Resampling.LANCZOS)
    return Image.composite(image, Image.new("RGB", image.size, "black"), mask)


def _draw_true_horizon_circle(
    draw: ImageDraw.ImageDraw,
    result: AnalysisResult,
    map_left: int,
    map_top: int,
    map_width: int,
    map_height: int,
    display_scale: int,
) -> None:
    """Mark altitude 0° without masking the calibrated below-horizon band."""

    # A precise horizontal system is known only after the full multi-star
    # solution. A one-direction rotation cannot determine camera tilt.
    if result.orientation_matrix is None or not getattr(
        result, "show_horizon_circle", True
    ):
        return
    radius = math.sin(math.pi / 4.0) * _projection_radius_scale(result) * display_scale
    calibrated = result.profile.max_calibrated_radius * display_scale
    if not math.isfinite(radius) or radius <= 0 or radius >= calibrated:
        return
    cx = map_left + map_width / 2.0
    cy = map_top + map_height / 2.0
    bounds = (cx - radius, cy - radius, cx + radius, cy + radius)
    # Dark halo keeps the neutral line readable over every palette colour.
    draw.ellipse(bounds, outline=(20, 20, 20), width=max(2, display_scale * 2))
    draw.ellipse(bounds, outline=(225, 225, 225), width=max(1, display_scale))


def _draw_altitude_circles(
    draw: ImageDraw.ImageDraw,
    result: AnalysisResult,
    map_left: int,
    map_top: int,
    map_width: int,
    map_height: int,
    display_scale: int,
) -> None:
    """Draw optional 10-degree altitude rings after a full star solution."""

    if result.orientation_matrix is None or not getattr(
        result, "show_altitude_circles", False
    ):
        return
    scale = _projection_radius_scale(result) * display_scale
    calibrated = result.profile.max_calibrated_radius * display_scale
    cx = map_left + map_width / 2.0
    cy = map_top + map_height / 2.0
    line_width = max(1, display_scale)
    font = _font(max(9, 8 * display_scale))
    for altitude_deg in range(10, 90, 10):
        zenith_distance = math.radians(90.0 - altitude_deg)
        radius = math.sin(zenith_distance / 2.0) * scale
        if not math.isfinite(radius) or radius <= 0 or radius >= calibrated:
            continue
        bounds = (cx - radius, cy - radius, cx + radius, cy + radius)
        draw.ellipse(bounds, outline=(175, 175, 175), width=line_width)
        label = f"{altitude_deg}°"
        box = draw.textbbox((0, 0), label, font=font)
        diagonal = radius / math.sqrt(2.0)
        label_x = cx + diagonal - (box[2] - box[0]) - 2 * display_scale
        label_y = cy - diagonal - (box[3] - box[1]) / 2.0
        draw.text(
            (label_x + display_scale, label_y + display_scale),
            label,
            font=font,
            fill=(20, 20, 20),
        )
        draw.text((label_x, label_y), label, font=font, fill=(225, 225, 225))

    # Altitude 90° is a point, not a circle.
    arm = max(3, 3 * display_scale)
    draw.line((cx - arm, cy, cx + arm, cy), fill=(225, 225, 225), width=line_width)
    draw.line((cx, cy - arm, cx, cy + arm), fill=(225, 225, 225), width=line_width)


def _draw_compass_on_round_map(
    draw: ImageDraw.ImageDraw,
    map_left: int,
    map_top: int,
    map_width: int,
    map_height: int,
    border: int,
    language: str = "cs",
) -> None:
    """Popisky v samostatnem cernem ramu kolem kruhove mapy."""

    font_size = max(28, int(map_width * 0.015))
    font = _font(font_size, bold=True)
    center_x = map_left + map_width / 2.0
    center_y = map_top + map_height / 2
    vertical_offset = max(2, (border - font_size) / 2.0 - 2)
    north, south, west, east = (
        ("N", "S", "W", "E") if language == "en" else ("S", "J", "Z", "V")
    )
    _centered(draw, (center_x, map_top - border + vertical_offset), north, font, "white")
    _centered(draw, (center_x, map_top + map_height + vertical_offset), south, font, "white")
    _centered(
        draw,
        (map_left - border / 2.0, center_y - font_size / 2.0),
        west,
        font,
        "white",
    )
    _centered(
        draw,
        (map_left + map_width + border / 2.0, center_y - font_size / 2.0),
        east,
        font,
        "white",
    )


def render_map(result: AnalysisResult, output_path: str | Path, display_scale: int = 2) -> None:
    """Ulozi bezeztratove PNG; barvy vzdy zustavaji diskretni a presne."""

    if display_scale not in (1, 2, 3):
        raise ValueError("Prezentační meritko musi byt 1, 2 nebo 3.")
    output_path = Path(output_path)
    if result.orientation_matrix is not None:
        values = reproject_fisheye_north_up(result.luminance_cd_m2, result)
        map_image = Image.fromarray(colorize(values), mode="RGB")
    else:
        map_image = Image.fromarray(result.color_map, mode="RGB")
        map_image = orient_image_north_up(map_image, result.north_angle_deg)
    if display_scale != 1:
        map_image = map_image.resize(
            (map_image.width * display_scale, map_image.height * display_scale),
            resample=Image.Resampling.NEAREST,
        )
    map_image = _smooth_calibrated_circle(map_image, result, display_scale)

    border = max(42, int(map_image.width * 0.028))
    width = map_image.width + 2 * border
    top = max(118, int(width * 0.045))
    footer = max(370, int(width * 0.15))
    map_left, map_top = border, top + border
    framed_height = map_image.height + 2 * border
    canvas = Image.new("RGB", (width, top + framed_height + footer), "black")
    canvas.paste(map_image, (map_left, map_top))
    draw = ImageDraw.Draw(canvas)
    if result.north_angle_deg is not None or result.orientation_matrix is not None:
        _draw_compass_on_round_map(
            draw, map_left, map_top, map_image.width, map_image.height, border, result.language
        )
    _draw_altitude_circles(
        draw,
        result,
        map_left,
        map_top,
        map_image.width,
        map_image.height,
        display_scale,
    )
    _draw_true_horizon_circle(
        draw,
        result,
        map_left,
        map_top,
        map_image.width,
        map_image.height,
        display_scale,
    )

    title_font = _font(max(30, int(width * 0.015)), bold=True)
    normal_font = _font(max(20, int(width * 0.009)))
    tick_font = _font(max(17, int(width * 0.0075)))
    small_font = _font(max(16, int(width * 0.007)))
    title = tr("Mapa jasu oblohy", result.language)
    if result.location:
        title += f" – {result.location}"
    _centered(draw, (width / 2, top * 0.19), title, title_font, "white")
    subtitle = f"{tr('Zenit', result.language)}: {result.zenith_msa:.2f} mag/arcsec²"
    _centered(draw, (width / 2, top * 0.62), subtitle, normal_font, (220, 220, 220))

    legend_top = top + framed_height + max(35, int(width * 0.014))
    legend_left = int(width * 0.08)
    # Vpravo nechavame samostatne misto pro nazvy jednotek, aby se
    # neprekryvaly s posledni ciselne oznacenou hodnotou.
    legend_right = int(width * 0.84)
    legend_width = legend_right - legend_left
    bar_height = max(45, int(width * 0.022))
    # Rozsah obsahuje celou puvodni NPS paletu vcetne tmaveho podteku.
    msa_left, msa_right = 17.5, 22.2
    sample_msa = np.linspace(msa_left, msa_right, legend_width, dtype=np.float64)
    bar = colorize(msa_to_luminance(sample_msa))[None, :, :]
    bar = np.repeat(bar, bar_height, axis=0)
    canvas.paste(Image.fromarray(bar, mode="RGB"), (legend_left, legend_top))
    draw.rectangle(
        (legend_left, legend_top, legend_right - 1, legend_top + bar_height - 1),
        outline=(210, 210, 210),
        width=1,
    )

    msa_ticks = np.arange(17.5, 22.01, 0.5)
    label_y = legend_top + bar_height + 10
    for tick in msa_ticks:
        xpos = legend_left + (tick - msa_left) / (msa_right - msa_left) * legend_width
        draw.line((xpos, legend_top + bar_height, xpos, legend_top + bar_height + 8), fill="white", width=1)
        _centered(draw, (xpos, label_y), f"{tick:.1f}", tick_font, "white")

    unit_x = legend_right + max(14, int(width * 0.006))
    draw.text((unit_x, label_y), "mag/arcsec²", font=small_font, fill="white", anchor="la")
    exif = result.exif
    captured = result.captured_at_utc or ("time unavailable" if result.language == "en" else "čas neuveden")
    info = (
        f"{captured}  |  {exif.camera_model}  |  {result.profile.lens_name}  |  "
        f"{exif.exposure_s:g} s  ·  ISO {exif.iso:g}  ·  f/{exif.aperture:g}"
    )
    _centered(draw, (width / 2, label_y + max(50, int(width * 0.023))), info, small_font, (180, 180, 180))
    canvas.save(output_path, format="PNG", optimize=True)


def render_luminance_map(
    result: AnalysisResult,
    output_path: str | Path,
    display_scale: int = 2,
) -> None:
    """PNG v presne Hollanove logaritmicke stupnici luminance."""

    if display_scale not in (1, 2, 3):
        raise ValueError("Prezentační meritko musi byt 1, 2 nebo 3.")
    output_path = Path(output_path)
    values = (
        reproject_fisheye_north_up(result.luminance_cd_m2, result)
        if result.orientation_matrix is not None
        else result.luminance_cd_m2
    )
    rgb = colorize_hollan_luminance(values)
    map_image = Image.fromarray(rgb, mode="RGB")
    map_image = orient_image_north_up(map_image, result.north_angle_deg)
    if display_scale != 1:
        map_image = map_image.resize(
            (map_image.width * display_scale, map_image.height * display_scale),
            resample=Image.Resampling.NEAREST,
        )
    map_image = _smooth_calibrated_circle(map_image, result, display_scale)

    border = max(42, int(map_image.width * 0.028))
    width = map_image.width + 2 * border
    top = max(118, int(width * 0.045))
    footer = max(370, int(width * 0.15))
    map_left, map_top = border, top + border
    framed_height = map_image.height + 2 * border
    canvas = Image.new("RGB", (width, top + framed_height + footer), "black")
    canvas.paste(map_image, (map_left, map_top))
    draw = ImageDraw.Draw(canvas)
    if result.north_angle_deg is not None or result.orientation_matrix is not None:
        _draw_compass_on_round_map(
            draw, map_left, map_top, map_image.width, map_image.height, border, result.language
        )
    _draw_altitude_circles(
        draw,
        result,
        map_left,
        map_top,
        map_image.width,
        map_image.height,
        display_scale,
    )
    _draw_true_horizon_circle(
        draw,
        result,
        map_left,
        map_top,
        map_image.width,
        map_image.height,
        display_scale,
    )
    title_font = _font(max(30, int(width * 0.015)), bold=True)
    normal_font = _font(max(20, int(width * 0.009)))
    tick_font = _font(max(17, int(width * 0.0075)))
    upper_tick_font = _font(max(20, int(width * 0.009)), bold=True)
    small_font = _font(max(16, int(width * 0.007)))
    title = tr("Mapa luminance oblohy", result.language)
    if result.location:
        title += f" – {result.location}"
    _centered(draw, (width / 2, top * 0.19), title, title_font, "white")
    subtitle = f"{tr('Zenit', result.language)}: {result.zenith_cd_m2:.7f} cd/m²"
    _centered(draw, (width / 2, top * 0.62), subtitle, normal_font, (220, 220, 220))

    legend_top = top + framed_height + max(82, int(width * 0.032))
    legend_left = int(width * 0.08)
    legend_right = int(width * 0.84)
    legend_width = legend_right - legend_left
    bar_height = max(45, int(width * 0.022))
    lower = HOLLAN_LOG_BASE_LUMINANCE * math.exp(-HOLLAN_LOG_HALF_STEP)
    upper = HOLLAN_LOG_BASE_LUMINANCE * math.pow(
        10.0,
        (len(HOLLAN_LOG_PALETTE) - 0.5) / HOLLAN_LOG_STEPS_PER_DECADE,
    )
    samples = np.geomspace(lower, upper, legend_width, dtype=np.float64)
    bar = colorize_hollan_luminance(samples)[None, :, :]
    bar = np.repeat(bar, bar_height, axis=0)
    canvas.paste(Image.fromarray(bar, mode="RGB"), (legend_left, legend_top))
    draw.rectangle(
        (legend_left, legend_top, legend_right - 1, legend_top + bar_height - 1),
        outline=(210, 210, 210),
        width=1,
    )

    label_y = legend_top + bar_height + 10
    # Skutecne dolni hranice deviti barevnych dekad. BaseLum=0.00004 je
    # stred prvniho odstinu; kvuli Round zacina pasmo o pul kroku drive.
    ticks = [lower * (10.0**decade) for decade in range(9)]
    tick_labels = (
        "0,0000318",
        "0,000318",
        "0,00318",
        "0,0318",
        "0,318",
        "3,18",
        "31,8",
        "318",
        "3 180",
    )
    log_lower, log_upper = math.log10(lower), math.log10(upper)
    for tick, label in zip(ticks, tick_labels):
        xpos = legend_left + (math.log10(tick) - log_lower) / (log_upper - log_lower) * legend_width
        draw.line((xpos, legend_top + bar_height, xpos, legend_top + bar_height + 8), fill="white", width=1)
        _centered(draw, (xpos, label_y), label, tick_font, "white")

    # Vsechny bezne mocniny deseti jsou ve vetsi samostatne horni rade.
    middle_y = legend_top - max(38, int(width * 0.017))
    upper_ticks = [10.0**power for power in range(-4, 5)]
    upper_labels = ("0,0001", "0,001", "0,01", "0,1", "1", "10", "100", "1 000", "10 000")
    for tick, label in zip(upper_ticks, upper_labels):
        xpos = legend_left + (math.log10(tick) - log_lower) / (log_upper - log_lower) * legend_width
        draw.line((xpos, legend_top - 8, xpos, legend_top), fill=(230, 230, 230), width=2)
        _centered(draw, (xpos, middle_y), label, upper_tick_font, (245, 245, 245))

    unit_x = legend_right + max(14, int(width * 0.006))
    draw.text((unit_x, label_y), "cd/m²", font=small_font, fill="white", anchor="la")
    exif = result.exif
    captured = result.captured_at_utc or (
        "time unavailable" if result.language == "en" else "čas neuveden"
    )
    info = (
        f"{captured}  |  {exif.camera_model}  |  {result.profile.lens_name}  |  "
        f"{exif.exposure_s:g} s  ·  ISO {exif.iso:g}  ·  f/{exif.aperture:g}"
    )
    _centered(draw, (width / 2, label_y + max(58, int(width * 0.026))), info, small_font, (180, 180, 180))
    canvas.save(output_path, format="PNG", optimize=True)


def _nan_box_mean(values: np.ndarray, radius: int = 5) -> np.ndarray:
    """Rychly lokalni prumer, ktery ignoruje NaN za obrazovym kruhem."""

    source = np.asarray(values, dtype=np.float64)
    valid = np.isfinite(source)
    data = np.where(valid, source, 0.0)

    def window_sum(array: np.ndarray) -> np.ndarray:
        padded = np.pad(array, radius, mode="constant")
        integral = np.pad(padded, ((1, 0), (1, 0)), mode="constant").cumsum(0).cumsum(1)
        size = 2 * radius + 1
        return (
            integral[size:, size:]
            - integral[:-size, size:]
            - integral[size:, :-size]
            + integral[:-size, :-size]
        )

    total = window_sum(data)
    count = window_sum(valid.astype(np.float64))
    result = np.full(source.shape, np.nan, dtype=np.float32)
    usable = count > 0
    result[usable] = (total[usable] / count[usable]).astype(np.float32)
    return result


def _colorize_blue_fraction(values: np.ndarray) -> np.ndarray:
    """Pevna nepravobarevna skala pro B/(R+G+B), vhodna pro porovnani noci."""

    source = np.asarray(values, dtype=np.float64)
    knots = np.asarray((0.10, 0.18, 0.26, 0.34, 0.42, 0.50), dtype=np.float64)
    colors = np.asarray(
        (
            (180, 35, 0),
            (245, 120, 0),
            (245, 220, 80),
            (90, 215, 205),
            (25, 105, 235),
            (80, 20, 145),
        ),
        dtype=np.float64,
    )
    output = np.zeros(source.shape + (3,), dtype=np.uint8)
    valid = np.isfinite(source)
    clipped = np.clip(source[valid], knots[0], knots[-1])
    for channel in range(3):
        output[..., channel][valid] = np.rint(
            np.interp(clipped, knots, colors[:, channel])
        ).astype(np.uint8)
    return output


def render_blue_fraction_map(
    result: AnalysisResult,
    output_path: str | Path,
    display_scale: int = 2,
) -> None:
    """Ulozi experimentální mapu relativniho podilu modreho RAW kanalu."""

    if display_scale not in (1, 2, 3):
        raise ValueError("Prezentační meritko musi byt 1, 2 nebo 3.")
    channels = (result.relative_red, result.relative_green, result.relative_blue)
    if result.orientation_matrix is not None:
        channels = tuple(reproject_fisheye_north_up(channel, result) for channel in channels)
    valid = np.isfinite(
        reproject_fisheye_north_up(result.blue_fraction, result)
        if result.orientation_matrix is not None
        else result.blue_fraction
    )
    smoothed = []
    for channel in channels:
        masked = np.where(valid, channel, np.nan)
        smoothed.append(_nan_box_mean(masked, radius=5))
    red, green, blue = smoothed
    total = red + green + blue
    values = np.full(red.shape, np.nan, dtype=np.float32)
    good = valid & np.isfinite(total) & (red > 0) & (green > 0) & (blue > 0)
    values[good] = blue[good] / total[good]
    map_image = Image.fromarray(_colorize_blue_fraction(values), mode="RGB")
    if result.orientation_matrix is None:
        map_image = orient_image_north_up(map_image, result.north_angle_deg)
    if display_scale != 1:
        map_image = map_image.resize(
            (map_image.width * display_scale, map_image.height * display_scale),
            resample=Image.Resampling.BILINEAR,
        )
    map_image = _smooth_calibrated_circle(map_image, result, display_scale)

    border = max(42, int(map_image.width * 0.028))
    width = map_image.width + 2 * border
    top = max(135, int(width * 0.052))
    footer = max(330, int(width * 0.14))
    map_left, map_top = border, top + border
    framed_height = map_image.height + 2 * border
    canvas = Image.new("RGB", (width, top + framed_height + footer), "black")
    canvas.paste(map_image, (map_left, map_top))
    draw = ImageDraw.Draw(canvas)
    if result.north_angle_deg is not None or result.orientation_matrix is not None:
        _draw_compass_on_round_map(
            draw, map_left, map_top, map_image.width, map_image.height, border, result.language
        )
    _draw_altitude_circles(
        draw,
        result,
        map_left,
        map_top,
        map_image.width,
        map_image.height,
        display_scale,
    )
    _draw_true_horizon_circle(
        draw,
        result,
        map_left,
        map_top,
        map_image.width,
        map_image.height,
        display_scale,
    )

    title_font = _font(max(30, int(width * 0.015)), bold=True)
    normal_font = _font(max(20, int(width * 0.009)))
    tick_font = _font(max(17, int(width * 0.0075)))
    small_font = _font(max(16, int(width * 0.007)))
    title = tr("Barevný index oblohy – podíl modrého RAW kanálu", result.language)
    if result.location:
        title += f" – {result.location}"
    _centered(draw, (width / 2, top * 0.13), title, title_font, "white")
    summary = result.zenith_color
    subtitle = (
        f"{tr('Zenit', result.language)}: B {100.0 * summary.blue_fraction:.1f} %  ·  "
        f"B/G {summary.blue_green_ratio:.3f}  ·  R/G {summary.red_green_ratio:.3f}"
    )
    _centered(draw, (width / 2, top * 0.57), subtitle, normal_font, (220, 220, 220))

    legend_top = top + framed_height + max(38, int(width * 0.015))
    legend_left, legend_right = int(width * 0.09), int(width * 0.80)
    legend_width = legend_right - legend_left
    bar_height = max(45, int(width * 0.022))
    samples = np.linspace(0.10, 0.50, legend_width, dtype=np.float64)
    bar = np.repeat(_colorize_blue_fraction(samples)[None, :, :], bar_height, axis=0)
    canvas.paste(Image.fromarray(bar, mode="RGB"), (legend_left, legend_top))
    draw.rectangle(
        (legend_left, legend_top, legend_right - 1, legend_top + bar_height - 1),
        outline=(210, 210, 210), width=1,
    )
    label_y = legend_top + bar_height + 10
    for tick in np.arange(0.10, 0.501, 0.05):
        xpos = legend_left + (tick - 0.10) / 0.40 * legend_width
        draw.line((xpos, legend_top + bar_height, xpos, legend_top + bar_height + 8), fill="white")
        _centered(draw, (xpos, label_y), f"{100*tick:.0f} %", tick_font, "white")
    draw.text((legend_right + 35, label_y), "B/(R+G+B)", font=small_font, fill="white")
    warning = tr((
        "Experimentální relativní RGB index; nejde o spektrum ani o fotopickou, "
        "skotopickou či melanopickou luminanci."
    ), result.language)
    _centered(draw, (width / 2, label_y + max(52, int(width * 0.024))), warning, small_font, (190, 190, 190))
    captured = result.captured_at_utc or ("time unavailable" if result.language == "en" else "čas neuveden")
    info = f"{captured}  |  {result.exif.camera_model}  |  {result.profile.lens_name}"
    _centered(draw, (width / 2, label_y + max(100, int(width * 0.045))), info, small_font, (160, 160, 160))
    canvas.save(Path(output_path), format="PNG", optimize=True)

def fisheye_to_panorama(
    values: np.ndarray,
    result: AnalysisResult,
    out_shape: tuple[int, int],
) -> np.ndarray:
    """Rozvine kalibrovane rybi oko na azimut × vysku nad obzorem.

    Sever je uprostred, panorama jde zleva J–Z–S–V–J a obzor je dole.
    Pouziva inverzi projekce ulozene v pristrojovem profilu, nikoli linearni
    aproximaci polomeru.
    """

    if result.north_angle_deg is None and result.orientation_matrix is None:
        raise ValueError("Pro orientovane panorama chybi urceni svetovych stran.")
    out_h, out_w = out_shape
    src_h, src_w = values.shape
    azimuth = np.linspace(-math.pi, math.pi, out_w, endpoint=False, dtype=np.float64)
    panorama = np.full((out_h, out_w), np.nan, dtype=np.float32)
    radius_scale = _projection_radius_scale(result)
    max_radius = min(
        result.profile.max_calibrated_radius,
        radius_scale,
        src_w / 2.0 - 1.0,
        src_h / 2.0 - 1.0,
    )
    max_zenith_distance = 2.0 * math.asin(max_radius / radius_scale)
    for row in range(out_h):
        zenith_distance = (row / max(out_h - 1, 1)) * max_zenith_distance
        if result.orientation_matrix is not None:
            altitude = math.pi / 2.0 - zenith_distance
            world = np.vstack(
                (
                    math.cos(altitude) * np.sin(azimuth),
                    math.cos(altitude) * np.cos(azimuth),
                    np.full(out_w, math.sin(altitude)),
                )
            )
            camera = np.asarray(result.orientation_matrix).T @ world
            panorama[row] = _sample_camera_vectors(values, result, camera)
        else:
            north = math.radians(float(result.north_angle_deg))
            image_angle = north - azimuth
            radius = math.sin(zenith_distance / 2.0) * radius_scale
            src_x = np.rint(src_w / 2.0 + radius * np.cos(image_angle)).astype(np.int32)
            src_y = np.rint(src_h / 2.0 + radius * np.sin(image_angle)).astype(np.int32)
            valid = (src_x >= 0) & (src_x < src_w) & (src_y >= 0) & (src_y < src_h)
            panorama[row, valid] = values[src_y[valid], src_x[valid]]
    return panorama


def _sample_camera_vectors(
    values: np.ndarray,
    result: AnalysisResult,
    camera: np.ndarray,
) -> np.ndarray:
    """Vzorkuje fisheye pole pro jednotkove vektory v souradnicich kamery."""

    src_h, src_w = values.shape
    camera = np.asarray(camera, dtype=np.float64)
    zenith_distance = np.arccos(np.clip(camera[2], -1.0, 1.0))
    radius_scale = _projection_radius_scale(result)
    radius = np.sin(zenith_distance / 2.0) * radius_scale
    angle = np.arctan2(camera[1], camera[0])
    src_x = np.rint(src_w / 2.0 + radius * np.cos(angle)).astype(np.int32)
    src_y = np.rint(src_h / 2.0 + radius * np.sin(angle)).astype(np.int32)
    valid = (
        (radius <= result.profile.max_calibrated_radius)
        & (src_x >= 0)
        & (src_x < src_w)
        & (src_y >= 0)
        & (src_y < src_h)
    )
    sampled = np.full(camera.shape[1], np.nan, dtype=np.float32)
    sampled[valid] = values[src_y[valid], src_x[valid]]
    return sampled


def reproject_fisheye_north_up(
    values: np.ndarray,
    result: AnalysisResult,
) -> np.ndarray:
    """Srovna naklonene rybi oko do zenitove mapy se severem nahore."""

    if result.orientation_matrix is None:
        raise ValueError("Pro korekci naklonu chybi astrometricka orientace.")
    height, width = values.shape
    center_x, center_y = width / 2.0, height / 2.0
    radius_scale = _projection_radius_scale(result)
    output = np.full((height, width), np.nan, dtype=np.float32)
    x = np.arange(width, dtype=np.float64)
    for row in range(height):
        dx = x - center_x
        dy = row - center_y
        radius = np.hypot(dx, dy)
        valid = radius <= result.profile.max_calibrated_radius
        zenith_distance = 2.0 * np.arcsin(np.clip(radius / radius_scale, 0.0, 1.0))
        image_angle = np.arctan2(dy, dx)
        azimuth = image_angle + math.pi / 2.0
        world = np.vstack(
            (
                np.sin(zenith_distance) * np.sin(azimuth),
                np.sin(zenith_distance) * np.cos(azimuth),
                np.cos(zenith_distance),
            )
        )
        camera = np.asarray(result.orientation_matrix).T @ world
        sampled = _sample_camera_vectors(values, result, camera)
        output[row, valid] = sampled[valid]
    return output


def _panorama_base(
    result: AnalysisResult,
    rgb: np.ndarray,
    title: str,
    subtitle: str,
) -> tuple[Image.Image, ImageDraw.ImageDraw, int, int, int]:
    map_image = Image.fromarray(rgb, mode="RGB")
    width, map_height = map_image.size
    top = max(88, int(width * 0.055))
    compass_height = max(55, int(width * 0.032))
    footer = max(245, int(width * 0.16))
    canvas = Image.new("RGB", (width, top + map_height + compass_height + footer), "black")
    canvas.paste(map_image, (0, top))
    draw = ImageDraw.Draw(canvas)
    title_font = _font(max(24, int(width * 0.017)), bold=True)
    normal_font = _font(max(17, int(width * 0.010)))
    compass_font = _font(max(19, int(width * 0.012)), bold=True)
    _centered(draw, (width / 2, max(8, int(top * 0.12))), title, title_font, "white")
    _centered(draw, (width / 2, max(45, int(top * 0.58))), subtitle, normal_font, (220, 220, 220))

    radius_scale = _projection_radius_scale(result)
    max_radius = min(
        result.profile.max_calibrated_radius,
        radius_scale,
        result.profile.output_size / 2.0 - 1.0,
    )
    max_zenith_distance = 2.0 * math.asin(max_radius / radius_scale)
    horizon_fraction = (math.pi / 2.0) / max_zenith_distance
    horizon_y = top + int(round((map_height - 1) * horizon_fraction))
    map_bottom = top + map_height
    compass = (
        ("S", "W", "N", "E", "S")
        if result.language == "en"
        else ("J", "Z", "S", "V", "J")
    )
    for fraction, label in zip((0.0, 0.25, 0.5, 0.75, 1.0), compass):
        x = min(width - 1, int(fraction * width))
        draw.line((x, top, x, map_bottom), fill=(150, 150, 150), width=1)
        anchor_x = max(12, min(width - 12, x))
        _centered(draw, (anchor_x, map_bottom + 10), label, compass_font, "white")
    draw.line((0, horizon_y, width, horizon_y), fill="white", width=2)
    draw.text(
        (10, top + 5),
        tr("Zenit", result.language),
        font=normal_font,
        fill=(225, 225, 225),
    )
    draw.text(
        (10, horizon_y - 30),
        tr("obzor", result.language),
        font=normal_font,
        fill=(225, 225, 225),
    )
    legend_top = map_bottom + compass_height + max(18, int(width * 0.012))
    return canvas, draw, legend_top, top, map_height


def _panorama_info(result: AnalysisResult) -> str:
    exif = result.exif
    captured = result.captured_at_utc or ("time unavailable" if result.language == "en" else "čas neuveden")
    return (
        f"{captured}  |  {exif.camera_model}  |  "
        f"{exif.exposure_s:g} s  ·  ISO {exif.iso:g}  ·  f/{exif.aperture:g}"
    )


def render_msa_panorama(
    result: AnalysisResult,
    output_path: str | Path,
    display_scale: int = 2,
) -> None:
    """Orientovane panorama v puvodni diskretni NPS stupnici."""

    if display_scale not in (1, 2, 3):
        raise ValueError("Prezentační meritko musi byt 1, 2 nebo 3.")
    shape = (360 * display_scale, 1440 * display_scale)
    panorama = fisheye_to_panorama(result.msa, result, shape)
    rgb = colorize(msa_to_luminance(panorama))
    title = tr("Panorama jasu oblohy", result.language)
    if result.location:
        title += f" – {result.location}"
    canvas, draw, legend_top, _top, _height = _panorama_base(
        result, rgb, title, f"{tr('Zenit', result.language)}: {result.zenith_msa:.2f} mag/arcsec²"
    )
    width = canvas.width
    left, right = int(width * 0.08), int(width * 0.88)
    bar_height = max(30, int(width * 0.018))
    samples = np.linspace(17.5, 22.2, right - left, dtype=np.float64)
    bar = np.repeat(colorize(msa_to_luminance(samples))[None, :, :], bar_height, axis=0)
    canvas.paste(Image.fromarray(bar, mode="RGB"), (left, legend_top))
    tick_font = _font(max(14, int(width * 0.008)))
    for tick in np.arange(17.5, 22.01, 0.5):
        x = left + (tick - 17.5) / (22.2 - 17.5) * (right - left)
        draw.line((x, legend_top + bar_height, x, legend_top + bar_height + 7), fill="white")
        _centered(draw, (x, legend_top + bar_height + 8), f"{tick:.1f}", tick_font, "white")
    draw.text((right + 12, legend_top + bar_height + 8), "mag/arcsec²", font=tick_font, fill="white")
    _centered(
        draw,
        (width / 2, legend_top + bar_height + max(48, int(width * 0.029))),
        _panorama_info(result),
        tick_font,
        (180, 180, 180),
    )
    canvas.save(Path(output_path), format="PNG", optimize=True)

def render_luminance_panorama(
    result: AnalysisResult,
    output_path: str | Path,
    display_scale: int = 2,
) -> None:
    """Orientovane panorama v Hollanove logaritmicke stupnici cd/m²."""

    if display_scale not in (1, 2, 3):
        raise ValueError("Prezentační meritko musi byt 1, 2 nebo 3.")
    shape = (360 * display_scale, 1440 * display_scale)
    panorama = fisheye_to_panorama(result.luminance_cd_m2, result, shape)
    rgb = colorize_hollan_luminance(panorama)
    title = tr("Panorama luminance oblohy", result.language)
    if result.location:
        title += f" – {result.location}"
    canvas, draw, legend_top, _top, _height = _panorama_base(
        result, rgb, title, f"{tr('Zenit', result.language)}: {result.zenith_cd_m2:.7f} cd/m²"
    )
    width = canvas.width
    left, right = int(width * 0.08), int(width * 0.88)
    bar_height = max(30, int(width * 0.018))
    lower = HOLLAN_LOG_BASE_LUMINANCE * math.exp(-HOLLAN_LOG_HALF_STEP)
    upper = HOLLAN_LOG_BASE_LUMINANCE * math.pow(
        10.0, (len(HOLLAN_LOG_PALETTE) - 0.5) / HOLLAN_LOG_STEPS_PER_DECADE
    )
    samples = np.geomspace(lower, upper, right - left, dtype=np.float64)
    bar = np.repeat(colorize_hollan_luminance(samples)[None, :, :], bar_height, axis=0)
    canvas.paste(Image.fromarray(bar, mode="RGB"), (left, legend_top))
    tick_font = _font(max(14, int(width * 0.008)))
    log_lower, log_upper = math.log10(lower), math.log10(upper)
    for power in range(-4, 5):
        tick = 10.0**power
        x = left + (math.log10(tick) - log_lower) / (log_upper - log_lower) * (right - left)
        draw.line((x, legend_top + bar_height, x, legend_top + bar_height + 7), fill="white")
        label = f"{tick:g}" if tick < 1000 else f"{int(tick):,}".replace(",", " ")
        _centered(draw, (x, legend_top + bar_height + 8), label, tick_font, "white")
    draw.text((right + 12, legend_top + bar_height + 8), "cd/m²", font=tick_font, fill="white")
    _centered(
        draw,
        (width / 2, legend_top + bar_height + max(48, int(width * 0.029))),
        _panorama_info(result),
        tick_font,
        (180, 180, 180),
    )
    canvas.save(Path(output_path), format="PNG", optimize=True)

