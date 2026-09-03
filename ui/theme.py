"""
ui/theme.py

Visual theming for the app, kept separate from layout/data modules so
styling changes never touch app.py's wiring logic or any other ui/*
module's rendering logic.

Holds:
    render_app_header()   — top-center page title, single line (change #1)
    inject_global_css()   — page-wide gradient background, white text,
                             no boxes/borders anywhere (change #2)

Both are pure st.markdown(..., unsafe_allow_html=True) calls — CSS only,
no JS.

DESIGN NOTE (final): after two failed attempts at scoping a custom
border color via CSS (one boxed the whole page, the next missed song
cards specifically — see ui/bubble_grid.py's docstring for the full
account), this stylesheet no longer tries to style the card border at
all. That border comes entirely from st.container(border=True) in
ui/bubble_grid.py, a Python-level prop, not something CSS pattern-
matching has to guess at — guaranteed correct scope at the cost of a
custom border color, which is a much safer trade to make.

Also fixed the mismatched red slider: .streamlit/config.toml still had
primaryColor = "#8B0000" (dark red) left over from the very first
version of this app, before the teal/blue redesign — Streamlit's
native slider (and other "primary"-themed native controls) render
using that value directly, which plain CSS can't override reliably
since it's applied via the theme, not a fixed class name. Updated it
to match the app's teal accent instead — see .streamlit/config.toml.

Also fixes a real layout bug here (not just color): the mood-map's
custom component (streamlit_drawable_canvas) renders its own iframe
wider than the actual 480px canvas it draws, leaving a blank strip of
the iframe's default white background visible beside the map. That's
not our container CSS misbehaving — it's the component stretching to
fill its column. Fixed by capping that specific iframe's width via its
`title` attribute (visible in Streamlit's own component badge as
"streamlit_drawable_canvas.st_canvas"), so nothing beyond the actual
480x480 canvas is rendered, and the gradient shows through the rest of
that column instead.
"""

import streamlit as st

_HEADER_HTML = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Orbitron:wght@700;900&display=swap');

.app-header-wrap {
    text-align: center;
    margin-top: -8px;
    margin-bottom: 4px;
}

.app-header-title {
    font-family: 'Orbitron', sans-serif;
    font-weight: 900;
    font-size: 2.6rem;
    letter-spacing: 0.06em;
    margin: 0;
    line-height: 1.15;
    white-space: nowrap;
    color: #ffffff;
}

.app-header-title .accent {
    font-weight: 500;
    opacity: 0.85;
    letter-spacing: 0.15em;
}

@media (max-width: 640px) {
    .app-header-title {
        font-size: 1.25rem;
        white-space: normal;
    }
}
</style>

<div class="app-header-wrap">
    <div class="app-header-title">🎵 MUSIC <span class="accent">— OUT OF THE BLUE</span></div>
</div>
"""

_GLOBAL_CSS = """
<style>
/* Page-wide gradient background */
[data-testid="stAppViewContainer"],
[data-testid="stHeader"] {
    background: linear-gradient(135deg, #1b4f72 0%, #1f7a8c 55%, #17a398 100%);
    background-attachment: fixed;
}
[data-testid="stHeader"] {
    background: transparent;
}

/* Default text color: white, app-wide, including captions (Streamlit
   renders st.caption as a <small> tag with its own muted color). */
[data-testid="stAppViewContainer"],
[data-testid="stAppViewContainer"] p,
[data-testid="stAppViewContainer"] span,
[data-testid="stAppViewContainer"] label,
[data-testid="stAppViewContainer"] small,
[data-testid="stAppViewContainer"] h1,
[data-testid="stAppViewContainer"] h2,
[data-testid="stAppViewContainer"] h3,
[data-testid="stAppViewContainer"] h4,
[data-testid="stAppViewContainer"] .stMarkdown,
[data-testid="stAppViewContainer"] .stCaption {
    color: #ffffff !important;
}
[data-testid="stAppViewContainer"] small {
    opacity: 0.85;
}

/* Buttons: soft translucent fill, NO border/outline — a visible
   stroke is exactly what read as "boxy". The fill alone is enough to
   signal "clickable" without drawing a hard rectangle. */
[data-testid="stAppViewContainer"] button[kind="secondary"] {
    background-color: rgba(255, 255, 255, 0.10) !important;
    color: #ffffff !important;
    border: none !important;
    box-shadow: none !important;
}
[data-testid="stAppViewContainer"] button[kind="secondary"]:hover {
    background-color: rgba(255, 255, 255, 0.22) !important;
}
[data-testid="stAppViewContainer"] button[kind="primary"] {
    background-color: rgba(46, 196, 182, 0.55) !important;
    color: #ffffff !important;
    border: none !important;
    box-shadow: none !important;
}
[data-testid="stAppViewContainer"] button[kind="primary"]:hover {
    background-color: rgba(46, 196, 182, 0.78) !important;
}

/* Song cards and the now-playing card get their box entirely from
   st.container(border=True) in ui/bubble_grid.py — a Python-level
   prop Streamlit itself renders, not something this stylesheet needs
   to (or safely can) target. Two earlier attempts at recoloring that
   border via a CSS selector on Streamlit's generic wrapper testid
   each leaked onto unintended elements in a different way — see
   ui/bubble_grid.py's docstring for the full account. Deliberately
   no CSS rule here at all for that border: correctness of WHICH
   elements are boxed matters far more than the exact border color,
   and every attempt to influence that color via CSS also risked
   redrawing borders elsewhere. Cards render in Streamlit's own
   default border color/weight for now.
*/

/* Progress slider polish: bigger, cleaner white text for the 0/max
   endpoint labels and the floating current-value bubble, in the same
   font as the rest of the app, instead of Streamlit's small default
   grey numerals. Thumb/track color itself now comes from
   .streamlit/config.toml's primaryColor (teal, matching the rest of
   the app) rather than being fought with CSS here. */
[data-testid="stAppViewContainer"] [data-testid="stSlider"] {
    padding-top: 6px !important;
    padding-bottom: 2px !important;
}
[data-testid="stAppViewContainer"] [data-testid="stSlider"] * {
    font-family: 'Orbitron', sans-serif !important;
}
[data-testid="stAppViewContainer"] [data-testid="stSlider"] div[data-testid="stTickBar"] {
    font-size: 0.85rem !important;
    font-weight: 600 !important;
    color: rgba(255, 255, 255, 0.85) !important;
}
[data-testid="stAppViewContainer"] [data-testid="stSlider"] div[data-baseweb="slider"] div[role="slider"] ~ div {
    font-size: 0.85rem !important;
    font-weight: 700 !important;
    color: #ffffff !important;
}

/* Mood-map fix: streamlit_drawable_canvas renders its component
   iframe wider than the 480x480 canvas it actually draws, leaving a
   blank white strip of the iframe's own default background visible
   beside the map. Capping the iframe's own width to the canvas size
   removes that strip — the gradient (the column's real background)
   shows through the freed space instead. */
[data-testid="stAppViewContainer"] iframe[title="streamlit_drawable_canvas.st_canvas"] {
    width: 480px !important;
    max-width: 480px !important;
    display: block !important;
}
</style>
"""


def render_app_header() -> None:
    """
    Render the top-center app title, single line, in a distinct
    display font (Google Fonts 'Orbitron', loaded via CSS @import —
    no JS, no extra package, just a stylesheet link like any normal
    webpage uses).
    """
    st.markdown(_HEADER_HTML, unsafe_allow_html=True)


def inject_global_css() -> None:
    """
    Apply the app-wide blue/teal gradient background, white default
    text color, borderless "soft fill" buttons, and the mood-map
    iframe width fix described in the module docstring.

    Call once per run, early in app.py's main() — before any other
    ui/* render function. Safe to call every rerun.
    """
    st.markdown(_GLOBAL_CSS, unsafe_allow_html=True)