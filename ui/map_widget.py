"""
ui/map_widget.py

Renders the draggable circle on the genre/mood map and returns the
circle's dropped position, normalized to the same 0-100 grid that
config.ANCHOR_TAGS coordinates use, so it can be handed straight to
core.mood_map.resolve_position_to_tags().

This is the only file in the app that depends on a third-party UI
component (streamlit-drawable-canvas) rather than plain Streamlit
widgets — native Streamlit has no click-and-drag primitive, and the
project's decision was real drag from day one over a click-to-place
substitute. No JavaScript is hand-written anywhere in this app: the
component's JS lives inside the pip package, not in this codebase.

The tag labels themselves are drawn onto a plain background image with
Pillow (no external font files needed — PIL's default font is used, so
there's nothing extra to bundle for deployment).
"""

from io import BytesIO

import streamlit as st
from PIL import Image, ImageDraw
from streamlit_drawable_canvas import st_canvas

CANVAS_SIZE = 520
CIRCLE_RADIUS = 18
CIRCLE_FILL_COLOR = "rgba(255, 99, 71, 0.75)"
CIRCLE_STROKE_COLOR = "#8B0000"
LABEL_COLOR = "#2b2b2b"

_CANVAS_KEY = "mood_map_canvas"


def _build_background_image(anchor_tags: dict[str, tuple[int, int]]) -> Image.Image:
    """
    Draw every anchor tag's label onto a plain CANVAS_SIZE x CANVAS_SIZE
    image, positioned at its (x, y) coordinate scaled from the 0-100
    grid in config.py up to actual canvas pixels.

    This image becomes the canvas's background_image — the draggable
    circle then sits visually on top of it, letting the user drop it
    near whichever label(s) fit what they're after.
    """
    image = Image.new("RGB", (CANVAS_SIZE, CANVAS_SIZE), color="white")
    draw = ImageDraw.Draw(image)

    for tag, (grid_x, grid_y) in anchor_tags.items():
        pixel_x = (grid_x / 100) * CANVAS_SIZE
        pixel_y = (grid_y / 100) * CANVAS_SIZE
        # anchor="mm" centers the text horizontally and vertically on
        # the point, so the label sits directly on its coordinate
        # rather than growing off to one side of it.
        draw.text((pixel_x, pixel_y), tag, fill=LABEL_COLOR, anchor="mm")

    return image


def _build_initial_circle_state() -> dict:
    """
    Build the fabric.js-format initial drawing state streamlit-drawable-canvas
    expects: one circle, centered on the canvas, with originX/originY set
    to "center" so its "left"/"top" fields directly represent the
    circle's center point (rather than a bounding-box corner) — this
    keeps the pixel-to-grid conversion in render_mood_map() simple, with
    no radius offset math needed.

    hasControls is False so the user can move the circle but not resize
    it — resizing would break the fixed CIRCLE_RADIUS assumption used
    when re-rendering on every rerun.
    """
    return {
        "version": "4.4.0",
        "objects": [
            {
                "type": "circle",
                "left": CANVAS_SIZE / 2,
                "top": CANVAS_SIZE / 2,
                "radius": CIRCLE_RADIUS,
                "fill": CIRCLE_FILL_COLOR,
                "stroke": CIRCLE_STROKE_COLOR,
                "strokeWidth": 2,
                "originX": "center",
                "originY": "center",
                "selectable": True,
                "hasControls": False,
            }
        ],
    }


def render_mood_map(anchor_tags: dict[str, tuple[int, int]]) -> tuple[float, float] | None:
    """
    Render the labeled map with a draggable circle and return the
    circle's current position as (x, y) on the same 0-100 grid as
    config.ANCHOR_TAGS.

    Returns None on the very first render before streamlit-drawable-canvas
    has produced any json_data yet — app.py should treat None as "no
    position chosen so far" and skip the recommendation call rather than
    resolving a nonsense default position.
    """
    background_image = _build_background_image(anchor_tags)

    canvas_result = st_canvas(
        fill_color=CIRCLE_FILL_COLOR,
        stroke_width=2,
        stroke_color=CIRCLE_STROKE_COLOR,
        background_image=background_image,
        height=CANVAS_SIZE,
        width=CANVAS_SIZE,
        drawing_mode="transform",  # lets the user move the existing circle;
        # does not let them draw new shapes.
        initial_drawing=_build_initial_circle_state(),
        update_streamlit=True,
        key=_CANVAS_KEY,
    )

    if canvas_result.json_data is None:
        return None

    objects = canvas_result.json_data.get("objects", [])
    if not objects:
        return None

    circle = objects[0]
    pixel_x = circle.get("left", CANVAS_SIZE / 2)
    pixel_y = circle.get("top", CANVAS_SIZE / 2)

    grid_x = (pixel_x / CANVAS_SIZE) * 100
    grid_y = (pixel_y / CANVAS_SIZE) * 100

    # Clamp in case a drag lands right at/past the canvas edge — keeps
    # the position sane for core.mood_map's distance calculations rather
    # than letting it drift outside the 0-100 grid the anchors live on.
    grid_x = max(0.0, min(100.0, grid_x))
    grid_y = max(0.0, min(100.0, grid_y))

    return grid_x, grid_y