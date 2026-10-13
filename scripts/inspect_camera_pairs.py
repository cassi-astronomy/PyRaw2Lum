"""Diagnostika geometrie a citlivosti párových RAWů dvou fotoaparátů."""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import rawpy


def load_signal(light_path: Path, dark_path: Path):
    with rawpy.imread(str(light_path)) as raw:
        light = raw.raw_image_visible.astype(np.float32).copy()
        colors = raw.raw_colors_visible.copy()
        labels = raw.color_desc.decode("ascii")
    with rawpy.imread(str(dark_path)) as raw:
        dark = raw.raw_image_visible.astype(np.float32).copy()
    return light - dark, colors, labels


def channel_medians(signal, colors, labels, cx, cy, radius):
    yy, xx = np.indices(signal.shape)
    mask = (xx - cx) ** 2 + (yy - cy) ** 2 <= radius**2
    result = {}
    for label in "RGB":
        ids = [index for index, value in enumerate(labels) if value == label]
        values = signal[mask & np.isin(colors, ids)]
        result[label] = float(np.median(values))
    return result


def radial_profile(signal, cx, cy, radii):
    yy, xx = np.indices(signal.shape)
    distance = np.hypot(xx - cx, yy - cy)
    result = []
    for radius in radii:
        annulus = (distance >= radius - 5) & (distance < radius + 5)
        result.append((radius, float(np.median(signal[annulus]))))
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("directory", type=Path)
    args = parser.parse_args()
    root = args.directory

    configurations = {
        "600D": {
            "dark": root / "600D_dark.CR2",
            "center": (2612.0, 1709.0),
            "sample_radius": 250.0,
            "edge_radii": range(1250, 1601, 25),
            "suffix": ".CR2",
        },
        "R6": {
            "dark": root / "R6_dark.CR3",
            "center": (6022 / 2, 4024 / 2),
            "sample_radius": 180.0,
            "edge_radii": range(850, 1201, 25),
            "suffix": ".CR3",
        },
    }
    for camera, config in configurations.items():
        print(f"\n{camera}")
        brightest = None
        brightest_level = -np.inf
        for number in range(1, 6):
            path = root / f"{camera}_{number}{config['suffix']}"
            signal, colors, labels = load_signal(path, config["dark"])
            medians = channel_medians(
                signal,
                colors,
                labels,
                *config["center"],
                config["sample_radius"],
            )
            print(number, " ".join(f"{key}={value:.3f}" for key, value in medians.items()))
            level = sum(medians.values())
            if level > brightest_level:
                brightest, brightest_level = signal, level
        print("radial", radial_profile(brightest, *config["center"], config["edge_radii"]))


if __name__ == "__main__":
    main()
