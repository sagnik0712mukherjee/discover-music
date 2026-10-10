"""
ui/map_widget.py

Renders the 2-axis mood map and returns the current marker position,
normalized to the 0-100 grid:
    x=0 -> Dark,       x=100 -> Positive
    y=0 -> Energetic,  y=100 -> Calm   (y=0 is the top of the canvas)

The map shows only 4 axis labels - no genre labels. Genres live in
the separate chip panel (ui/genre_panel.py).

WHY THIS ISN'T streamlit-drawable-canvas ANYMORE: that package (last
touched ~2021) broke in three separate, unrelated ways across this
project - an AttributeError from a moved Streamlit internal
(image_to_url), a TypeError from st.container(key=...) not existing
on our pinned Streamlit version, and finally a silent blank-canvas
render on Streamlit Cloud with no Python-side error at all (verified:
the exact same Python call chain runs clean locally via AppTest, so
the failure is inside that package's own 2021-era bundled JS, which
we don't control and nobody maintains anymore). A community "-fix"
fork exists but was checked and rejected: its patched import
(streamlit.elements.image_utils) doesn't exist on ANY Streamlit
version from 1.37 through the latest 1.64 release - the real path is
streamlit.elements.lib.image_utils, so the fork is itself stale.

Replaced with streamlit-image-coordinates (maintained by a Streamlit
staffer, modern single-file bundle, actively updated). It has no
built-in draggable shape - it's a plain image plus a click/drag
listener - so this module draws its own marker circle onto the
composed image every render (see _build_marker_image) and reads back
where the user clicked or released a drag via click_and_drag=True,
which reports the mouse-down point as (x1, y1) and the mouse-up point
as (x2, y2). Using the release point (x2, y2) as the new position
gives the same practical feel as dragging a real shape - press
anywhere, drag, release, the marker jumps there - just without a
shape that visually follows the cursor mid-drag.
"""

import streamlit as st
from PIL import Image, ImageDraw, ImageFont
from streamlit_image_coordinates import streamlit_image_coordinates

CANVAS_SIZE = 480
CIRCLE_RADIUS = 16

# PIL-native RGBA tuples (0-255 per channel, including alpha) - not the
# CSS rgba(...) string format the old canvas-based version used, since
# PIL's own drawing calls want actual tuples here.
_MARKER_FILL_COLOR = (99, 102, 241, 204)     # indigo, ~80% opacity
_MARKER_STROKE_COLOR = (67, 56, 202, 255)    # solid indigo outline

_WIDGET_KEY = "mood_map_widget"
_POSITION_STATE_KEY = "mood_map_position"
_DEFAULT_POSITION = (50.0, 50.0)  # dead center

# Quadrant tints (RGBA) - very faint, just enough to signal mood zones.
_QUADRANT_COLORS = [
    (180, 40,  40,  18),   # dark+energetic -> faint red
    (255, 200,  40,  18),  # positive+energetic -> faint yellow
    (60,  60, 160,  18),   # dark+calm -> faint blue
    (40, 160,  80,  18),   # positive+calm -> faint green
]

# Axis label text and anchor positions
_AXIS_LABELS = [
    ("Energetic", (CANVAS_SIZE // 2, 22),  "mt"),
    ("Calm",      (CANVAS_SIZE // 2, CANVAS_SIZE - 22), "mb"),
    ("Dark",      (28, CANVAS_SIZE // 2),  "lm"),
    ("Positive",  (CANVAS_SIZE - 28, CANVAS_SIZE // 2), "rm"),
]

_LABEL_FONT_SIZE = 26


def _load_font(size: int) -> ImageFont.ImageFont:
    """
    Try to load a clean, BOLD sans-serif font from common system paths
    (bold variants listed first). Falls back to PIL's built-in default
    if none are found, so the app always renders even on a minimal
    deployment image without these fonts installed.
    """
    candidates = [
        # macOS - bold first
        "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
        "/System/Library/Fonts/Helvetica.ttc",
        "/Library/Fonts/Arial.ttf",
        "/System/Library/Fonts/Supplemental/Arial.ttf",
        # Linux / Streamlit Cloud - bold first
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
    ]
    for path in candidates:
        try:
            return ImageFont.truetype(path, size)
        except (IOError, OSError):
            continue
    return ImageFont.load_default()


def _build_background_image() -> Image.Image:
    """
    Render the mood map background:
      - Light grey base
      - 4 faint quadrant tints
      - Thin crosshair lines
      - 4 axis labels
    Does NOT include the marker circle - see _build_marker_image,
    which draws that on top of a fresh copy of this every render, so
    the marker always reflects the current position without needing
    to regenerate the whole background from scratch each time.
    """
    img = Image.new("RGB", (CANVAS_SIZE, CANVAS_SIZE), color=(248, 248, 252))
    draw = ImageDraw.Draw(img, "RGBA")

    cx = CANVAS_SIZE // 2
    cy = CANVAS_SIZE // 2

    tint_rects = [
        (0,  0,  cx, cy, _QUADRANT_COLORS[0]),
        (cx, 0,  CANVAS_SIZE, cy, _QUADRANT_COLORS[1]),
        (0,  cy, cx, CANVAS_SIZE, _QUADRANT_COLORS[2]),
        (cx, cy, CANVAS_SIZE, CANVAS_SIZE, _QUADRANT_COLORS[3]),
    ]
    for x0, y0, x1, y1, color in tint_rects:
        draw.rectangle([x0, y0, x1, y1], fill=color)

    line_color = (200, 200, 210, 200)
    draw.line([(cx, 0), (cx, CANVAS_SIZE)], fill=line_color, width=1)
    draw.line([(0, cy), (CANVAS_SIZE, cy)], fill=line_color, width=1)

    draw.rectangle([0, 0, CANVAS_SIZE - 1, CANVAS_SIZE - 1],
                   outline=(180, 180, 195), width=1)

    font = _load_font(_LABEL_FONT_SIZE)
    label_color = (15, 71, 92)
    shadow_color = (255, 255, 255, 160)
    for text, (px, py), anchor in _AXIS_LABELS:
        draw.text((px + 1, py + 1), text, fill=shadow_color, anchor=anchor, font=font)
        draw.text((px, py), text, fill=label_color, anchor=anchor, font=font)

    return img


def _build_marker_image(grid_x: float, grid_y: float) -> Image.Image:
    """
    Draw the position marker circle onto a fresh copy of the
    background, at the given 0-100 grid position converted to pixels.
    A fresh copy each call - never mutates a cached background image.
    """
    img = _build_background_image().convert("RGBA")
    draw = ImageDraw.Draw(img, "RGBA")

    px = (grid_x / 100.0) * CANVAS_SIZE
    py = (grid_y / 100.0) * CANVAS_SIZE

    draw.ellipse(
        [px - CIRCLE_RADIUS, py - CIRCLE_RADIUS, px + CIRCLE_RADIUS, py + CIRCLE_RADIUS],
        fill=_MARKER_FILL_COLOR,
        outline=_MARKER_STROKE_COLOR,
        width=2,
    )
    return img


def render_mood_map() -> tuple[float, float]:
    """
    Render the labeled 2-axis mood map with a marker the user can
    click or click-and-drag to reposition, and return the current
    position as (x, y) on the 0-100 grid.

    Unlike the old canvas-based version, this never returns None -
    the position is always initialized (dead center on first render)
    and persisted in st.session_state, so callers don't need to
    handle a "no position chosen yet" case. app.py's existing
    `position or fallback` handling still works fine against this,
    since a real tuple is always truthy.
    """
    if _POSITION_STATE_KEY not in st.session_state:
        st.session_state[_POSITION_STATE_KEY] = _DEFAULT_POSITION

    current_x, current_y = st.session_state[_POSITION_STATE_KEY]
    marker_image = _build_marker_image(current_x, current_y)

    result = streamlit_image_coordinates(
        marker_image,
        key=_WIDGET_KEY,
        width=CANVAS_SIZE,
        click_and_drag=True,
        cursor="grab",
    )

    if result is not None:
        rendered_width = result.get("width") or CANVAS_SIZE
        rendered_height = result.get("height") or CANVAS_SIZE
        # click_and_drag=True reports mouse-down as x1,y1 and mouse-up
        # as x2,y2 - the release point is what should become the new
        # position (matches "press, drag, release" intuition). Falls
        # back to x1,y1 for a plain click with no real drag movement,
        # in case the frontend ever omits x2,y2 for that case.
        px = result.get("x2", result.get("x1"))
        py = result.get("y2", result.get("y1"))
        if px is not None and py is not None:
            new_x = max(0.0, min(100.0, (px / rendered_width) * 100.0))
            new_y = max(0.0, min(100.0, (py / rendered_height) * 100.0))
            st.session_state[_POSITION_STATE_KEY] = (new_x, new_y)

    return st.session_state[_POSITION_STATE_KEY]