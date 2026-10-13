"""Relativni barevna analyza oblohy z linearniho Bayerova RAWu."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class SkyColorSummary:
    """Robustni RGB pomery v male oblasti kolem skutecneho zenitu."""

    red_fraction: float
    green_fraction: float
    blue_fraction: float
    red_green_ratio: float
    blue_green_ratio: float
    valid_pixels: int

    def report(self) -> dict[str, object]:
        return {
            "method": "relative_dark_subtracted_linear_raw_rgb",
            "calibration_level": "experimental_camera_relative_index",
            "red_fraction": self.red_fraction,
            "green_fraction": self.green_fraction,
            "blue_fraction": self.blue_fraction,
            "red_green_ratio": self.red_green_ratio,
            "blue_green_ratio": self.blue_green_ratio,
            "valid_pixels": self.valid_pixels,
            "warning": (
                "RGB DSLR neni spektrometr. Hodnoty nejsou fotopicka, skotopicka "
                "ani melanopicka luminance a jsou srovnatelne jen s odpovidajicim "
                "profilem fotoaparatu, objektivu a clony."
            ),
        }


def compute_color_indices(
    red: np.ndarray,
    green: np.ndarray,
    blue: np.ndarray,
    valid_mask: np.ndarray | None = None,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Vrati B/(R+G+B), B/G a R/G; neplatne pixely jsou NaN."""

    r = np.asarray(red, dtype=np.float64)
    g = np.asarray(green, dtype=np.float64)
    b = np.asarray(blue, dtype=np.float64)
    if r.shape != g.shape or r.shape != b.shape:
        raise ValueError("RGB kanaly museji mit shodny rozmer.")
    valid = np.isfinite(r) & np.isfinite(g) & np.isfinite(b) & (r > 0) & (g > 0) & (b > 0)
    if valid_mask is not None:
        mask = np.asarray(valid_mask, dtype=bool)
        if mask.shape != r.shape:
            raise ValueError("Maska barevne analyzy ma jiny rozmer nez RGB kanaly.")
        valid &= mask
    blue_fraction = np.full(r.shape, np.nan, dtype=np.float32)
    blue_green = np.full(r.shape, np.nan, dtype=np.float32)
    red_green = np.full(r.shape, np.nan, dtype=np.float32)
    total = r + g + b
    blue_fraction[valid] = (b[valid] / total[valid]).astype(np.float32)
    blue_green[valid] = (b[valid] / g[valid]).astype(np.float32)
    red_green[valid] = (r[valid] / g[valid]).astype(np.float32)
    return blue_fraction, blue_green, red_green


def summarize_color(
    red: np.ndarray,
    green: np.ndarray,
    blue: np.ndarray,
    mask: np.ndarray,
) -> SkyColorSummary:
    """Pocita pomery z medianu kanalu, ne median jednotlivych pixelovych pomeru."""

    r = np.asarray(red, dtype=np.float64)
    g = np.asarray(green, dtype=np.float64)
    b = np.asarray(blue, dtype=np.float64)
    valid = (
        np.asarray(mask, dtype=bool)
        & np.isfinite(r)
        & np.isfinite(g)
        & np.isfinite(b)
        & (r > 0)
        & (g > 0)
        & (b > 0)
    )
    count = int(np.count_nonzero(valid))
    if count == 0:
        raise ValueError("V oblasti zenitu nejsou platna RGB data.")
    rm = float(np.median(r[valid]))
    gm = float(np.median(g[valid]))
    bm = float(np.median(b[valid]))
    total = rm + gm + bm
    return SkyColorSummary(
        red_fraction=rm / total,
        green_fraction=gm / total,
        blue_fraction=bm / total,
        red_green_ratio=rm / gm,
        blue_green_ratio=bm / gm,
        valid_pixels=count,
    )
