"""Presna barevna stupnice z programu raw2lum 1.35 Jana Hollana."""

from __future__ import annotations

import math

import numpy as np

# Poradi je od nejtmavsi oblohy (nejnizsi luminance) po nejsvetlejsi.
NPS_PALETTE = np.asarray(
    [
        (30, 0, 0),
        (60, 0, 0),
        (60, 0, 25),
        (70, 0, 60),
        (105, 0, 105),
        (75, 0, 125),
        (40, 0, 140),
        (15, 0, 145),
        (25, 35, 170),
        (25, 75, 175),
        (0, 100, 175),
        (0, 120, 180),
        (0, 135, 180),
        (0, 160, 180),
        (0, 190, 190),
        (0, 200, 160),
        (30, 210, 140),
        (0, 205, 20),
        (95, 205, 0),
        (155, 205, 0),
        (185, 205, 0),
        (210, 225, 0),
        (215, 215, 0),
        (220, 205, 0),
        (210, 185, 0),
        (215, 155, 0),
        (230, 135, 0),
        (235, 120, 0),
        (230, 100, 0),
        (230, 80, 0),
        (230, 50, 0),
        (224, 0, 0),
        (224, 0, 63),
        (220, 0, 85),
        (230, 0, 128),
        (230, 0, 185),
        (215, 0, 215),
        (220, 95, 210),
        (225, 125, 205),
        (225, 155, 215),
        (215, 190, 215),
        (232, 225, 250),
        (228, 235, 250),
        (232, 254, 253),
        (235, 255, 240),
        (255, 255, 255),
    ],
    dtype=np.uint8,
)

NPS_BASE_LUMINANCE = 0.149e-3
NPS_STEPS_PER_DECADE = 25.0
NPS_HALF_STEP = math.log(10.0) / (2.0 * NPS_STEPS_PER_DECADE)

# Puvodni logaritmicka luminancni stupnice raw2lum 1.35.
# Kazda zakladni barva pokryva jednu dekadu a ma pet jasovych odstinu.
HOLLAN_LOG_BASE_LUMINANCE = 0.00004
HOLLAN_LOG_STEPS_PER_DECADE = 5.0
HOLLAN_LOG_BASE_COLORS = np.asarray(
    [
        (2, 1, 0),  # oranzova
        (0, 0, 2),  # modra
        (2, 0, 2),  # purpurova
        (0, 2, 2),  # azurova
        (2, 0, 0),  # cervena
        (0, 2, 0),  # zelena
        (2, 2, 0),  # zluta
        (0, 1, 2),  # modrozelena
        (2, 2, 2),  # bila
    ],
    dtype=np.uint16,
)
HOLLAN_LOG_SHADES = np.asarray((66, 92, 130, 182, 255), dtype=np.uint16)
HOLLAN_LOG_PALETTE = np.asarray(
    [
        tuple((base * shade // 2).astype(np.uint8))
        for base in HOLLAN_LOG_BASE_COLORS
        for shade in HOLLAN_LOG_SHADES
    ],
    dtype=np.uint8,
)
HOLLAN_LOG_HALF_STEP = math.log(10.0) / (2.0 * HOLLAN_LOG_STEPS_PER_DECADE)


def palette_indices(luminance: np.ndarray) -> np.ndarray:
    """Vrati indexy 0..45; -1 oznacuje hodnotu pod puvodni stupnici."""

    values = np.asarray(luminance, dtype=np.float64)
    valid = np.isfinite(values) & (values > 0)
    safe = np.where(valid, values, 1e-30)
    steps = np.log(safe / NPS_BASE_LUMINANCE) / (
        math.log(10.0) / NPS_STEPS_PER_DECADE
    )
    # Pascalovsky Round a numpy rint se pro bezne hodnoty shoduji.
    indices = np.rint(steps).astype(np.int16)
    below = (~valid) | (safe < NPS_BASE_LUMINANCE * math.exp(-NPS_HALF_STEP))
    indices = np.clip(indices, 0, len(NPS_PALETTE) - 1)
    indices[below] = -1
    return indices


def colorize(luminance: np.ndarray) -> np.ndarray:
    """Prevede luminanci na puvodni 46barevnou NPS skalu."""

    indices = palette_indices(luminance)
    rgb = NPS_PALETTE[np.clip(indices, 0, len(NPS_PALETTE) - 1)].copy()
    rgb[indices < 0] = 0
    rgb[~np.isfinite(luminance)] = 0
    return rgb
def hollan_luminance_indices(luminance: np.ndarray) -> np.ndarray:
    """Indexy puvodni logaritmicke stupnice cd/m2; -1 je pod rozsahem."""

    values = np.asarray(luminance, dtype=np.float64)
    valid = np.isfinite(values) & (values > 0)
    safe = np.where(valid, values, 1e-30)
    steps = np.log(safe / HOLLAN_LOG_BASE_LUMINANCE) / (
        math.log(10.0) / HOLLAN_LOG_STEPS_PER_DECADE
    )
    indices = np.rint(steps).astype(np.int16)
    below = (~valid) | (
        safe < HOLLAN_LOG_BASE_LUMINANCE * math.exp(-HOLLAN_LOG_HALF_STEP)
    )
    indices = np.clip(indices, 0, len(HOLLAN_LOG_PALETTE) - 1)
    indices[below] = -1
    return indices


def colorize_hollan_luminance(luminance: np.ndarray) -> np.ndarray:
    """Prevede cd/m2 na presnou 45barevnou logaritmickou skalu Pascalu."""

    indices = hollan_luminance_indices(luminance)
    rgb = HOLLAN_LOG_PALETTE[np.clip(indices, 0, len(HOLLAN_LOG_PALETTE) - 1)].copy()
    rgb[indices < 0] = 0
    rgb[~np.isfinite(luminance)] = 0
    return rgb

