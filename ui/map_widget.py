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

WHY DRAGGING FELT LAGGY ("RUNNING" on every drag): every time this
component reports a new coordinate, Streamlit's default behavior is
to rerun the ENTIRE script top to bottom - not just this widget. That
meant every drag re-ran the whole of app.py: rebuilding the genre
panel, the header, the columns layout, and (worst offender) this
module's background image from scratch, including re-reading a font
file off disk via _load_font on every single rerun. None of that is
needed just to move a marker. Two fixes, both below:

  1. The static background (quadrant tints, crosshair lines, the 4
     axis labels, the font load) is now built ONCE and cached with
     st.cache_resource (_get_cached_background). Every subsequent
     drag just pastes a small marker circle onto a copy of that
     cached image - no redrawing, no font disk I/O.

  2. The interactive widget itself now lives inside its own
     st.experimental_fragment (_render_map_fragment). Streamlit
     reruns only the fragment's own code when something inside it
     changes - the rest of app.py (genre panel, header, buttons) is
     left untouched. That's what actually removes the full-page
     "RUNNING" round trip per drag; the cached image is just extra
     headroom for the remaining fragment-only rerun.

Position changes are still written to st.session_state from inside
the fragment, so main() can read the latest value through
render_mood_map()'s return value whenever it runs next (e.g. on the
"Surprise me!" click), exactly as before.
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

    Only ever called once now, from inside _get_cached_background -
    see that function's docstring for why this used to be the single
    biggest contributor to per-drag lag.
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
    which draws that on top of a fresh copy of the CACHED version of
    this (_get_cached_background) every render, so the marker always
    reflects the current position without needing to regenerate the
    background - tints, lines, labels, font load and all - from
    scratch on every drag.
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
def _get_cached_background() -> Image.Image:
    """
    Build the static background exactly once per server process (not
    once per session, not once per rerun - st.cache_resource shares
    this single Image object across every visitor, which is safe
    because nothing ever mutates it directly; see _build_marker_image,
    which always works on a .copy()).

    This is what removes the font-disk-read + full redraw that used
    to happen on every single drag event.
    """
    return _build_background_image()


def _build_marker_image(grid_x: float, grid_y: float) -> Image.Image:
    """
    Draw the position marker circle onto a COPY of the cached
    background, at the given 0-100 grid position converted to pixels.
    Never mutates the cached background itself.
    """
    img = _get_cached_background().copy().convert("RGBA")
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


@st.experimental_fragment
def _render_map_fragment() -> None:
    """
    The actual interactive widget, isolated in its own fragment.

    Streamlit's fragment behavior: when a widget INSIDE a fragment
    produces a new value, only the fragment's own function body is
    re-executed - the rest of app.py (genre panel, header, "Surprise
    me!" button, bubble grid) is left exactly as it was last drawn.
    That's the actual fix for the laggy "RUNNING" feeling: a drag used
    to mean "rerun everything", now it means "rerun this ~15-line
    function". The new position is written straight to
    st.session_state, which is all render_mood_map() needs to hand
    the latest value back to the rest of the app on its next real run.
    """
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
            new_position = (new_x, new_y)
            if new_position != st.session_state[_POSITION_STATE_KEY]:
                st.session_state[_POSITION_STATE_KEY] = new_position


def render_mood_map() -> tuple[float, float]:
    """
    Render the labeled 2-axis mood map with a marker the user can
    click or click-and-drag to reposition, and return the current
    position as (x, y) on the 0-100 grid.

    Never returns None - the position is always initialized (dead
    center on first render) and persisted in st.session_state, so
    callers don't need to handle a "no position chosen yet" case.
    app.py's existing `position or fallback` handling still works
    fine against this, since a real tuple is always truthy.
    """
    if _POSITION_STATE_KEY not in st.session_state:
        st.session_state[_POSITION_STATE_KEY] = _DEFAULT_POSITION

    _render_map_fragment()

    return st.session_state[_POSITION_STATE_KEY]