"""Automaticke mereni vinetace z rady snimku umele hvezdy."""

from __future__ import annotations

from dataclasses import dataclass
import math
from pathlib import Path
from typing import Callable, Sequence

import numpy as np
from PIL import Image, ImageDraw

from .vignetting import VignettingCalibration


@dataclass(frozen=True)
class SourceMeasurement:
    source: str
    x: float
    y: float
    radius_px: float
    normalized_radius: float
    azimuth_deg: float
    flux_r: float
    flux_g: float
    flux_b: float
    saturated: bool

    def report(self) -> dict[str, object]:
        return {
            "source": self.source,
            "x": self.x,
            "y": self.y,
            "radius_px": self.radius_px,
            "normalized_radius": self.normalized_radius,
            "azimuth_deg": self.azimuth_deg,
            "flux_r": self.flux_r,
            "flux_g": self.flux_g,
            "flux_b": self.flux_b,
            "saturated": self.saturated,
        }


def _box_mean(values: np.ndarray, radius: int = 3) -> np.ndarray:
    padded = np.pad(values, radius, mode="edge")
    integral = np.pad(padded, ((1, 0), (1, 0)), mode="constant").cumsum(0).cumsum(1)
    size = 2 * radius + 1
    total = (
        integral[size:, size:]
        - integral[:-size, size:]
        - integral[size:, :-size]
        + integral[:-size, :-size]
    )
    return total / float(size * size)


def _component(mask: np.ndarray, seed_y: int, seed_x: int) -> np.ndarray:
    selected = np.zeros_like(mask, dtype=bool)
    if not mask[seed_y, seed_x]:
        return selected
    stack = [(seed_y, seed_x)]
    selected[seed_y, seed_x] = True
    while stack:
        y, x = stack.pop()
        for dy in (-1, 0, 1):
            for dx in (-1, 0, 1):
                if dx == 0 and dy == 0:
                    continue
                yy, xx = y + dy, x + dx
                if (
                    0 <= yy < mask.shape[0]
                    and 0 <= xx < mask.shape[1]
                    and mask[yy, xx]
                    and not selected[yy, xx]
                ):
                    selected[yy, xx] = True
                    stack.append((yy, xx))
    return selected


def _dilate(mask: np.ndarray, iterations: int) -> np.ndarray:
    result = mask.copy()
    for _ in range(iterations):
        padded = np.pad(result, 1, mode="constant")
        expanded = np.zeros_like(result)
        for dy in range(3):
            for dx in range(3):
                expanded |= padded[dy : dy + result.shape[0], dx : dx + result.shape[1]]
        result = expanded
    return result


def measure_artificial_source(
    red: np.ndarray,
    green: np.ndarray,
    blue: np.ndarray,
    saturation: np.ndarray,
    max_radius_px: float,
) -> tuple[float, float, dict[str, float], bool]:
    """Najde jediny jasny zdroj a zmeri integralni tok ve trech kanalech."""

    combined = np.maximum(red, 0) + 2.0 * np.maximum(green, 0) + np.maximum(blue, 0)
    height, width = combined.shape
    yy, xx = np.indices(combined.shape)
    valid_circle = np.hypot(xx - width / 2.0, yy - height / 2.0) <= max_radius_px * 1.03
    background_values = combined[valid_circle & np.isfinite(combined)]
    if background_values.size < 100:
        raise ValueError("V obrazu neni dostatek platnych pixelu.")
    background = float(np.median(background_values))
    noise = 1.4826 * float(np.median(np.abs(background_values - background)))
    smoothed = _box_mean(np.where(valid_circle, combined, background), 3)
    smoothed[~valid_circle] = -np.inf
    peak_index = int(np.nanargmax(smoothed))
    peak_y, peak_x = np.unravel_index(peak_index, smoothed.shape)
    peak = float(smoothed[peak_y, peak_x])
    if not math.isfinite(peak) or peak <= background + max(10.0 * noise, 1e-6):
        raise ValueError("Nebyl nalezen dostatecne vyrazny svetelny zdroj.")

    search_radius = max(18, round(min(height, width) * 0.055))
    y0, y1 = max(0, peak_y - search_radius), min(height, peak_y + search_radius + 1)
    x0, x1 = max(0, peak_x - search_radius), min(width, peak_x + search_radius + 1)
    local = combined[y0:y1, x0:x1]
    threshold = background + max(6.0 * noise, 0.06 * (peak - background))
    component = _component(local > threshold, peak_y - y0, peak_x - x0)
    if np.count_nonzero(component) < 2:
        raise ValueError("Svetelny zdroj je prilis maly nebo slaby.")
    aperture = _dilate(component, 4)
    outer = _dilate(aperture, 10)
    annulus = outer & ~_dilate(aperture, 3)
    if np.count_nonzero(annulus) < 30:
        raise ValueError("Zdroj je prilis blizko okraji obrazu.")

    weights = np.maximum(local - background, 0.0) * component
    weight_sum = float(np.sum(weights))
    local_y, local_x = np.indices(local.shape)
    center_x = x0 + float(np.sum(local_x * weights) / weight_sum)
    center_y = y0 + float(np.sum(local_y * weights) / weight_sum)
    fluxes: dict[str, float] = {}
    for label, channel in (("R", red), ("G", green), ("B", blue)):
        cut = channel[y0:y1, x0:x1]
        sky = float(np.median(cut[annulus]))
        flux = float(np.sum(cut[aperture] - sky))
        if not math.isfinite(flux) or flux <= 0:
            raise ValueError(f"Kanal {label} nema kladny tok zdroje.")
        fluxes[label] = flux
    saturated = bool(np.any(saturation[y0:y1, x0:x1][aperture]))
    return center_x, center_y, fluxes, saturated


def _robust_radial_fit(radius: np.ndarray, flux: np.ndarray) -> tuple[np.ndarray, np.ndarray, float]:
    if np.any(flux <= 0):
        raise ValueError("Tok zdroje musi byt kladny.")
    design = np.column_stack((np.ones(len(radius)), radius**2, radius**4, radius**6))
    target = np.log(flux)
    indices = np.arange(len(radius))
    for _ in range(6):
        coefficients, *_ = np.linalg.lstsq(design[indices], target[indices], rcond=None)
        residual = target - design @ coefficients
        local = residual[indices]
        mad = 1.4826 * np.median(np.abs(local - np.median(local)))
        if mad <= 1e-8:
            break
        keep = np.abs(residual - np.median(local)) <= max(3.0 * mad, 0.025)
        new_indices = np.flatnonzero(keep)
        if len(new_indices) == len(indices) or len(new_indices) < 8:
            break
        indices = new_indices
    coefficients, *_ = np.linalg.lstsq(design[indices], target[indices], rcond=None)
    normalized_coefficients = coefficients[1:]
    predicted = np.exp(design @ coefficients)
    fractional = flux / predicted - 1.0
    rms_percent = 100.0 * float(np.sqrt(np.mean(np.square(fractional[indices]))))
    return normalized_coefficients, indices, rms_percent


def calibrate_vignetting(
    image_paths: Sequence[str | Path],
    dark_paths: Sequence[str | Path],
    progress: Callable[[str], None] | None = None,
) -> tuple[VignettingCalibration, tuple[SourceMeasurement, ...]]:
    """Zmeri radialni RGB profil vinetace ze serie RAW snimku jednoho zdroje."""

    from .core import _load_visible_crop, dark_matches_light, read_exif
    from .profiles import profile_for_camera

    notify = progress or (lambda _message: None)
    images = [Path(path) for path in image_paths]
    darks = [Path(path) for path in dark_paths]
    if len(images) < 10:
        raise ValueError("Pro kalibraci vinetace je potreba alespon 10 snimku.")
    if not darks:
        raise ValueError("Pro kalibraci pridejte alespon jeden odpovidajici dark.")
    first_exif = read_exif(images[0])
    profile = profile_for_camera(first_exif.camera_model)
    if not math.isclose(first_exif.aperture, profile.reference_aperture, abs_tol=0.06):
        raise ValueError(
            f"Sestava PyRaw2Lum je kalibrovana pro f/{profile.reference_aperture:g}; "
            f"kalibracni snimky maji f/{first_exif.aperture:g}."
        )
    measurements: list[SourceMeasurement] = []
    for number, image_path in enumerate(images, start=1):
        exif = read_exif(image_path)
        if exif.camera_model != first_exif.camera_model:
            raise ValueError("Kalibracni rada obsahuje vice modelu fotoaparatu.")
        if not math.isclose(exif.aperture, first_exif.aperture, abs_tol=0.06):
            raise ValueError("Kalibracni rada obsahuje vice clonovych cisel.")
        if not math.isclose(exif.iso, first_exif.iso, rel_tol=0.0, abs_tol=0.5):
            raise ValueError("Kalibracni rada obsahuje vice hodnot ISO.")
        matches = [path for path in darks if dark_matches_light(exif, read_exif(path))]
        if not matches:
            raise ValueError(f"Pro {image_path.name} nebyl nalezen odpovidajici dark.")
        light, white_level, labels = _load_visible_crop(image_path, profile)
        dark_sum = np.zeros_like(light)
        for dark_path in matches:
            dark, _, dark_labels = _load_visible_crop(dark_path, profile)
            if dark_labels != labels or dark.shape != light.shape:
                raise ValueError(f"Dark {dark_path.name} neni kompatibilni.")
            dark_sum += dark
        signal = light - dark_sum / len(matches)
        cells = [
            signal[0::2, 0::2], signal[0::2, 1::2],
            signal[1::2, 0::2], signal[1::2, 1::2],
        ]
        channels = {
            label: [cell for cell, cell_label in zip(cells, labels) if cell_label == label]
            for label in ("R", "G", "B")
        }
        red = channels["R"][0]
        green = (channels["G"][0] + channels["G"][1]) / 2.0
        blue = channels["B"][0]
        saturation = np.logical_or.reduce(
            [
                light[0::2, 0::2] >= white_level * 0.98,
                light[0::2, 1::2] >= white_level * 0.98,
                light[1::2, 0::2] >= white_level * 0.98,
                light[1::2, 1::2] >= white_level * 0.98,
            ]
        )
        x, y, fluxes, saturated = measure_artificial_source(
            red, green, blue, saturation, profile.max_calibrated_radius
        )
        if saturated:
            raise ValueError(f"Zdroj je na snimku {image_path.name} saturovany.")
        exposure_scale = exif.iso * exif.exposure_s / (exif.aperture**2)
        center_x, center_y = red.shape[1] / 2.0, red.shape[0] / 2.0
        radius = math.hypot(x - center_x, y - center_y)
        measurements.append(
            SourceMeasurement(
                source=str(image_path), x=x, y=y, radius_px=radius,
                normalized_radius=radius / profile.max_calibrated_radius,
                azimuth_deg=math.degrees(math.atan2(y - center_y, x - center_x)) % 360.0,
                flux_r=fluxes["R"] / exposure_scale,
                flux_g=fluxes["G"] / exposure_scale,
                flux_b=fluxes["B"] / exposure_scale,
                saturated=False,
            )
        )
        notify(f"{number}/{len(images)}: {image_path.name}, r={radius/profile.max_calibrated_radius:.3f}")

    radius = np.asarray([item.normalized_radius for item in measurements])
    if float(np.min(radius)) > 0.18:
        raise ValueError("Chybi snimek zdroje blizko stredu (r < 0,18 polomeru).")
    if float(np.max(radius)) < 0.72:
        raise ValueError("Chybi snimek zdroje u okraje (r > 0,72 polomeru).")
    coefficients: dict[str, tuple[float, ...]] = {}
    rms: dict[str, float] = {}
    for channel, attribute in (("R", "flux_r"), ("G", "flux_g"), ("B", "flux_b")):
        flux = np.asarray([getattr(item, attribute) for item in measurements])
        fitted, _used, error = _robust_radial_fit(radius, flux)
        coefficients[channel] = tuple(float(value) for value in fitted)
        rms[channel] = error
    calibration = VignettingCalibration(
        profile_key=profile.key,
        camera_model=profile.camera_model,
        lens_name=profile.lens_name,
        aperture=first_exif.aperture,
        max_radius_px=profile.max_calibrated_radius,
        coefficients=coefficients,
        fit_rms_percent=rms,
        source_files=tuple(str(path) for path in images),
        measurements=tuple(item.report() for item in measurements),
    )
    calibration.validate_for(profile, first_exif.aperture)
    return calibration, tuple(measurements)


def make_vignetting_plot(
    calibration: VignettingCalibration,
    measurements: Sequence[SourceMeasurement],
) -> Image.Image:
    width, height = 1100, 700
    left, top, right, bottom = 95, 65, 1040, 610
    image = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(image)
    draw.rectangle((left, top, right, bottom), outline="#333333", width=2)

    def px(value: float) -> float:
        return left + value * (right - left)

    def py(value: float) -> float:
        return bottom - value * (bottom - top)

    for tick in np.linspace(0.0, 1.0, 6):
        draw.line((px(tick), bottom, px(tick), bottom + 7), fill="#333333")
        draw.text((px(tick) - 12, bottom + 12), f"{tick:.1f}", fill="#222222")
        draw.line((left - 7, py(tick), left, py(tick)), fill="#333333")
        draw.text((40, py(tick) - 7), f"{tick:.1f}", fill="#222222")
    colors = {"R": "#d82d2d", "G": "#178a32", "B": "#245bd6"}
    samples = np.linspace(0.0, 1.0, 300)
    for channel, attribute in (("R", "flux_r"), ("G", "flux_g"), ("B", "flux_b")):
        coefficients = calibration.coefficients[channel]
        log_transmission = sum(
            coefficient * samples ** (2 * (index + 1))
            for index, coefficient in enumerate(coefficients)
        )
        curve = np.exp(log_transmission)
        points = [(px(float(x)), py(float(y))) for x, y in zip(samples, curve)]
        draw.line(points, fill=colors[channel], width=4)
        flux = np.asarray([getattr(item, attribute) for item in measurements])
        center_level = math.exp(
            float(np.mean(np.log(flux[np.asarray([m.normalized_radius for m in measurements]) < 0.2])))
        )
        for item, value in zip(measurements, flux / center_level):
            x, y = px(item.normalized_radius), py(float(value))
            draw.ellipse((x - 4, y - 4, x + 4, y + 4), fill=colors[channel])
    draw.text((left, 22), "Kalibrace vinetace umele hvezdy", fill="#111111")
    draw.text((left + 420, 22), "R / G / B: relativni propustnost", fill="#111111")
    draw.text((left + 380, 650), "Normalizovany polomer obrazoveho kruhu", fill="#111111")
    draw.text((15, 42), "Propustnost", fill="#111111")
    return image
