"""
core/mood_map.py

Turns a raw (x, y) drop position from the draggable canvas into a
weighted list of Last.fm mood tags, which core/recommender.py then
uses to query services/lastfm_client.py.

The map is a pure 2-axis mood space:
    x: 0 = Dark  →  100 = Positive
    y: 0 = Energetic  →  100 = Calm   (y=0 is top of canvas)

The 4 corners each map to a set of Last.fm tags. A drop position is
decomposed into 4 corner weights using bilinear interpolation, and
those weights are flattened into per-tag weights for the recommender.

This module knows nothing about Streamlit, the canvas widget, or
Last.fm — it's pure geometry, trivially testable.
"""

from dataclasses import dataclass


@dataclass
class TagMatch:
    """
    A single Last.fm tag's relevance to a resolved drop position.

    weight is normalized so all TagMatch.weight values for one drop
    sum to 1.0 — core/recommender.py uses this to decide how many
    tracks to request per tag.
    """

    tag: str
    weight: float


def resolve_position_to_mood_tags(
    x: float,
    y: float,
    mood_corners: dict[str, dict],
    weight_threshold: float = 0.05,
) -> list[TagMatch]:
    """
    Decompose a drop position into weighted Last.fm mood tags via
    bilinear interpolation across the 4 mood corners.

    Parameters
    ----------
    x, y : float
        Position on the 0-100 canvas grid.
        x=0 is Dark, x=100 is Positive.
        y=0 is Energetic (top), y=100 is Calm (bottom).
    mood_corners : dict
        config.MOOD_CORNERS — maps corner name → {pos, tags}.
    weight_threshold : float
        Corners with weight below this value are skipped entirely,
        keeping the tag list focused on what actually matters at
        this position.

    Returns
    -------
    list[TagMatch]
        Tags ordered by descending weight, summing to ~1.0.
        Empty only if mood_corners is empty (config problem).

    How the math works
    ------------------
    Bilinear weights for the 4 corners (assuming corners are at the
    4 exact axis extremes — (0,0), (100,0), (0,100), (100,100)):

        w_dark_energetic = (1 - x/100) * (1 - y/100)   ← top-left
        w_pos_energetic  = (x/100)     * (1 - y/100)   ← top-right
        w_dark_calm      = (1 - x/100) * (y/100)        ← bottom-left
        w_pos_calm       = (x/100)     * (y/100)         ← bottom-right

    These always sum to 1.0 by construction, before threshold filtering.

    A tag shared by multiple corners (unlikely in the current config,
    but possible if someone adds overlapping tags) gets its weights
    summed — stronger overall signal, not a duplicate.
    """
    if not mood_corners:
        return []

    nx = x / 100.0
    ny = y / 100.0

    # Corner weights via bilinear interpolation.
    # Assumes corners are pinned to the 4 extremes of the 0-100 grid.
    corner_weights: dict[str, float] = {
        "dark_energetic": (1 - nx) * (1 - ny),
        "pos_energetic":  nx       * (1 - ny),
        "dark_calm":      (1 - nx) * ny,
        "pos_calm":       nx       * ny,
    }

    # Accumulate per-tag weights, merging any tag that appears in
    # multiple corners.
    tag_weights: dict[str, float] = {}
    for corner_name, corner_weight in corner_weights.items():
        if corner_weight < weight_threshold:
            continue
        corner = mood_corners.get(corner_name)
        if not corner:
            continue
        tags: list[str] = corner["tags"]
        if not tags:
            continue

        # Distribute the corner's weight equally across its tags.
        # The first tag in the list gets a small priority bonus
        # (10% extra) to keep the "most representative" tag for that
        # corner slightly dominant when weights are close.
        n = len(tags)
        base = corner_weight / n
        for i, tag in enumerate(tags):
            bonus = base * 0.10 if i == 0 else 0.0
            tag_weights[tag] = tag_weights.get(tag, 0.0) + base + bonus

    if not tag_weights:
        return []

    # Normalize so all weights sum to 1.0 after threshold filtering.
    total = sum(tag_weights.values())
    return sorted(
        [TagMatch(tag=tag, weight=w / total) for tag, w in tag_weights.items()],
        key=lambda tm: tm.weight,
        reverse=True,
    )