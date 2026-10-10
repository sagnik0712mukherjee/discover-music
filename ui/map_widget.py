"""
ui/map_widget.py

Renders the 2-axis mood map and returns the current marker position,
normalized to the 0-100 grid:
    x=0 -> Dark,       x=100 -> Positive
    y=0 -> Energetic,  y=100 -> Calm   (y=0 is the top of the canvas)

The map shows only 4 axis labels - no genre labels. Genres live in
the separate chip panel (ui/genre_panel.py).

HISTORY OF THIS WIDGET (read before changing the drag mechanism again):

1. streamlit-drawable-canvas (original choice) - dropped after THREE
   separate failures, the last being a silent blank-canvas render on
   Streamlit Cloud with zero Python-side error (confirmed: identical
   Python call chain runs clean locally via AppTest, so the bug was in
   that package's own unmaintained 2021-era bundled JS).

2. streamlit-image-coordinates (first replacement) - fixed the blank
   render (it's actively maintained), but has NO client-side drag
   feedback: the marker can only move after a full round trip to the
   Python server and back for every drag event. On a hosted free tier
   that's the "laggy, RUNNING on every drag" problem that was reported
   next - an architectural limitation of that package, not a bug to
   patch.

3. THIS custom component (current) - a small, self-written, static
   HTML/CSS/vanilla-JS page (no npm, no build step, no third-party
   package to go stale) declared via Streamlit's built-in
   components.v1.declare_component. It moves the marker with plain
   Pointer Events entirely inside the browser - zero server calls
   while dragging - and tells Python the final position exactly ONCE,
   on release. That's what made approach #1 feel smooth in the first
   place; this gets the same feel without depending on an abandoned
   package. The actual frontend lives in
   ui/components/mood_map_frontend/index.html - its own docstring
   covers the wire protocol in detail.

The background image (quadrant tints, crosshair lines, the 4 axis
labels) is still built with PIL exactly as before and cached with
st.cache_resource, then handed to the component as a base64 PNG data
URL - the component just overlays a marker div on top of it and
reports back where that marker ends up.
"""

import base64
from io import BytesIO
from pathlib import Path

import streamlit as st
import streamlit.components.v1 as components
from PIL import Image, ImageDraw, ImageFont

CANVAS_SIZE = 480
CIRCLE_RADIUS = 16

_MARKER_FILL_CSS = "rgba(99, 102, 241, 0.8)"     # indigo, ~80% opacity
_MARKER_STROKE_CSS = "rgba(67, 56, 202, 1)"      # solid indigo outline

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

_COMPONENT_DIR = Path(__file__).parent / "components" / "mood_map_frontend"
_mood_map_component = components.declare_component(
    "mood_map_native_drag", path=str(_COMPONENT_DIR)
)


def _load_font(size: int) -> ImageFont.ImageFont:
    """
    Try to load a clean, BOLD sans-serif font from common system paths
    (bold variants listed first). Falls back to PIL's built-in default
    if none are found, so the app always renders even on a minimal
    deployment image without these fonts installed.

    Only ever called once per process, from inside
    _get_cached_background_data_url.
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
    Does NOT include the marker - the frontend component draws and
    moves that itself (see ui/components/mood_map_frontend/index.html)
    so dragging never needs to touch this image again.
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


@st.cache_resource
def _get_cached_background_data_url() -> str:
    """
    Build the static background exactly once per server process and
    encode it as a base64 PNG data URL ready to hand straight to the
    frontend's <img> tag. Shared across every visitor - safe, since
    the image is never mutated (no marker baked into it anymore).
    """
    img = _build_background_image()
    buffer = BytesIO()
    img.save(buffer, format="PNG")
    encoded = base64.b64encode(buffer.getvalue()).decode("ascii")
    return f"data:image/png;base64,{encoded}"


def render_mood_map() -> tuple[float, float]:
    """
    Render the labeled 2-axis mood map with a marker the user can
    click or drag to reposition, and return the current position as
    (x, y) on the 0-100 grid.

    Dragging is handled entirely client-side by the component in
    ui/components/mood_map_frontend/index.html - Python only hears
    about the NEW position once, when the component calls
    streamlit:setComponentValue on release. That single value is what
    `result` holds below.

    Never returns None - the position is always initialized (dead
    center on first render) and persisted in st.session_state, so
    callers don't need to handle a "no position chosen yet" case.
    app.py's existing `position or fallback` handling still works
    fine against this, since a real tuple is always truthy.
    """
    if _POSITION_STATE_KEY not in st.session_state:
        st.session_state[_POSITION_STATE_KEY] = _DEFAULT_POSITION

    current_x, current_y = st.session_state[_POSITION_STATE_KEY]

    result = _mood_map_component(
        width=CANVAS_SIZE,
        marker_radius=CIRCLE_RADIUS,
        marker_fill_color=_MARKER_FILL_CSS,
        marker_stroke_color=_MARKER_STROKE_CSS,
        background_image_data_url=_get_cached_background_data_url(),
        x=current_x,
        y=current_y,
        key=_WIDGET_KEY,
        default={"x": current_x, "y": current_y},
    )

    if result is not None and "x" in result and "y" in result:
        new_x = max(0.0, min(100.0, float(result["x"])))
        new_y = max(0.0, min(100.0, float(result["y"])))
        st.session_state[_POSITION_STATE_KEY] = (new_x, new_y)

    return st.session_state[_POSITION_STATE_KEY]