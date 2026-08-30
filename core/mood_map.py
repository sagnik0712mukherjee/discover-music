"""
core/mood_map.py

Turns a raw (x, y) drop position from the draggable canvas into one or
more anchor tags from config.ANCHOR_TAGS, which core/recommender.py then
uses to query services/lastfm_client.py.

This module knows nothing about Streamlit, the canvas widget, or Last.fm
— it's pure geometry over the anchor coordinates in config.py, which
keeps it trivially testable and keeps "how do we interpret a drop
position" logic in exactly one place.
"""

import math
from dataclasses import dataclass


@dataclass
class TagMatch:
    """
    A single anchor tag's relevance to a resolved drop position.

    weight is normalized so that all TagMatch.weight values returned for
    one drop sum to 1.0 — core/recommender.py uses this to decide how many
    tracks to request from each tag (e.g. a tag with weight 0.7 should
    contribute roughly 70% of the candidate pool, not an equal share).
    """

    tag: str
    distance: float
    weight: float


def resolve_position_to_tags(
    x: float,
    y: float,
    anchor_tags: dict[str, tuple[int, int]],
    nearest_tag_count: int,
) -> list[TagMatch]:
    """
    Given a drop position and the full anchor tag map, return the
    `nearest_tag_count` closest tags, weighted by inverse distance.

    Inverse-distance weighting (rather than e.g. equal weighting across
    the nearest N) means a drop that lands almost exactly on "romantic"
    with "dreamy" only nearby-ish will weight romantic heavily and dreamy
    lightly — matching the intuition that dragging closer to a label
    should mean more of that label, not a flat blend.

    Raises ValueError if anchor_tags is empty or nearest_tag_count < 1 —
    both indicate a config problem, not a runtime edge case to silently
    paper over.
    """
    if not anchor_tags:
        raise ValueError("anchor_tags is empty — check config.ANCHOR_TAGS")
    if nearest_tag_count < 1:
        raise ValueError("nearest_tag_count must be at least 1")

    distances: list[tuple[str, float]] = []
    for tag, (anchor_x, anchor_y) in anchor_tags.items():
        distance = math.hypot(x - anchor_x, y - anchor_y)
        distances.append((tag, distance))

    distances.sort(key=lambda item: item[1])
    nearest = distances[:nearest_tag_count]

    # Guard against a drop landing exactly on an anchor (distance == 0),
    # which would otherwise divide by zero in the inverse-distance step.
    # A tiny epsilon keeps the math well-defined without meaningfully
    # skewing weights for any non-exact drop.
    epsilon = 0.01
    inverse_distances = [1.0 / (distance + epsilon) for _, distance in nearest]
    total = sum(inverse_distances)

    return [
        TagMatch(tag=tag, distance=distance, weight=inverse_distance / total)
        for (tag, distance), inverse_distance in zip(nearest, inverse_distances)
    ]