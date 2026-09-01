"""
ui/map_widget.py

Renders the 2-axis mood map with a draggable circle and returns the
circle's dropped position, normalized to the 0-100 grid:
    x=0 → Dark,       x=100 → Positive
    y=0 → Energetic,  y=100 → Calm   (y=0 is the top of the canvas)

The map shows only 4 axis labels — no genre labels. Genres live in
the separate chip panel (ui/genre_panel.py).

Each quadrant is tinted with a very faint color to give an ambient
hint of the mood zone the circle is in, without cluttering the space.
"""

from io import BytesIO

import streamlit as st
from PIL import Image, ImageDraw, ImageFont
from streamlit_drawable_canvas import st_canvas

CANVAS_SIZE = 480
CIRCLE_RADIUS = 16
CIRCLE_FILL_COLOR = "rgba(99, 102, 241, 0.80)"   # indigo, semi-transparent
CIRCLE_STROKE_COLOR = "#4338CA"

_CANVAS_KEY = "mood_map_canvas"

# Quadrant tints (RGBA) — very faint, just enough to signal mood zones.
# Order: top-left (dark+energetic), top-right (positive+energetic),
#        bottom-left (dark+calm), bottom-right (positive+calm)
_QUADRANT_COLORS = [
    (180, 40,  40,  18),   # dark+energetic → faint red
    (255, 200,  40,  18),  # positive+energetic → faint yellow
    (60,  60, 160,  18),   # dark+calm → faint blue
    (40, 160,  80,  18),   # positive+calm → faint green
]

# Axis label text and their anchor positions on the canvas
_AXIS_LABELS = [
    ("Energetic", (CANVAS_SIZE // 2, 14),  "mt"),   # top center
    ("Calm",      (CANVAS_SIZE // 2, CANVAS_SIZE - 14), "mb"),  # bottom center
    ("Dark",      (18, CANVAS_SIZE // 2),  "lm"),   # left center
    ("Positive",  (CANVAS_SIZE - 18, CANVAS_SIZE // 2), "rm"),  # right center
]


def _build_background_image() -> Image.Image:
    """
    Render the mood map background:
      - Light grey base
      - 4 faint quadrant tints
      - Thin crosshair lines
      - 4 axis labels (bold, positioned at edges)
    """
    img = Image.new("RGB", (CANVAS_SIZE, CANVAS_SIZE), color=(248, 248, 252))
    draw = ImageDraw.Draw(img, "RGBA")

    cx = CANVAS_SIZE // 2
    cy = CANVAS_SIZE // 2

    # Quadrant tints
    tint_rects = [
        (0,  0,  cx, cy, _QUADRANT_COLORS[0]),   # top-left
        (cx, 0,  CANVAS_SIZE, cy, _QUADRANT_COLORS[1]),   # top-right
        (0,  cy, cx, CANVAS_SIZE, _QUADRANT_COLORS[2]),   # bottom-left
        (cx, cy, CANVAS_SIZE, CANVAS_SIZE, _QUADRANT_COLORS[3]),  # bottom-right
    ]
    for x0, y0, x1, y1, color in tint_rects:
        draw.rectangle([x0, y0, x1, y1], fill=color)

    # Crosshair lines (light grey)
    line_color = (200, 200, 210, 200)
    draw.line([(cx, 0), (cx, CANVAS_SIZE)], fill=line_color, width=1)
    draw.line([(0, cy), (CANVAS_SIZE, cy)], fill=line_color, width=1)

    # Outer border
    draw.rectangle([0, 0, CANVAS_SIZE - 1, CANVAS_SIZE - 1],
                   outline=(180, 180, 195), width=1)

    # Axis labels — use PIL default font (no external font files needed)
    label_color = (60, 60, 80)
    for text, (px, py), anchor in _AXIS_LABELS:
        draw.text((px, py), text, fill=label_color, anchor=anchor)

    return img


def _build_initial_circle_state() -> dict:
    """
    Fabric.js initial state: one circle centered on the canvas.
    hasControls=False prevents resizing; only dragging is allowed.
    originX/Y='center' means left/top directly represent the circle
    center — no radius-offset math needed when reading back the position.
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


def render_mood_map() -> tuple[float, float] | None:
    """
    Render the labeled 2-axis mood map and return the circle's current
    position as (x, y) on the 0-100 grid.

    Returns None on the very first render before the canvas has produced
    any json_data — app.py treats None as 'no position chosen yet'.
    """
    background_image = _build_background_image()

    canvas_result = st_canvas(
        fill_color=CIRCLE_FILL_COLOR,
        stroke_width=2,
        stroke_color=CIRCLE_STROKE_COLOR,
        background_image=background_image,
        height=CANVAS_SIZE,
        width=CANVAS_SIZE,
        drawing_mode="transform",
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

    # Clamp to 0-100 in case of edge drags
    grid_x = max(0.0, min(100.0, grid_x))
    grid_y = max(0.0, min(100.0, grid_y))

    return grid_x, grid_y