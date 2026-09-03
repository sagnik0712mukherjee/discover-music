"""
ui/genre_panel.py

Renders the genre chip panel beside the mood map.

Uses CSS-styled toggle buttons (compatible with Streamlit <1.37).
Each genre button is oval/pill-shaped via injected CSS. Clicking toggles
selection state stored in st.session_state.

All 24 genres are unselected by default on first load — the user
opts into whichever genres they want blended in.

State changes happen via on_click callbacks (see _toggle_genre,
_select_all, _clear_all below) rather than "detect the click, mutate
state, then call st.rerun()". Streamlit already reruns the whole
script automatically the instant a button is clicked — an on_click
callback just runs BEFORE that automatic rerun repaints the page, so
the new selection is visible in the very same rerun with no extra,
manually-triggered rerun needed. An explicit st.rerun() call (the
previous approach here) is what was resetting the page's scroll
position to the top on every click — see app.py's playback callbacks
for the same fix applied to Play/Pause/Seek.

Returns the list of currently selected genre names.
"""

import streamlit as st

_STATE_KEY = "selected_genres_set"


# Inject CSS once to style genre buttons as oval chips.
# We target buttons inside our specific container div.
_CHIP_CSS = """
<style>
/* Genre chip buttons */
div[data-testid="stHorizontalBlock"] button[kind="secondary"],
div[data-testid="stHorizontalBlock"] button[kind="primary"] {
    border-radius: 999px !important;
    padding: 4px 14px !important;
    font-size: 0.78rem !important;
    font-weight: 500 !important;
    min-height: 0 !important;
    line-height: 1.4 !important;
    transition: all 0.15s ease !important;
}
/* Utility buttons (Select All / Clear All) keep normal shape */
</style>
"""


def _toggle_genre(genre: str) -> None:
    selected = st.session_state[_STATE_KEY]
    if genre in selected:
        selected.discard(genre)
    else:
        selected.add(genre)


def _select_all(genres: list[str]) -> None:
    st.session_state[_STATE_KEY] = set(genres)


def _clear_all() -> None:
    st.session_state[_STATE_KEY] = set()


def render_genre_panel(genres: list[str]) -> list[str]:
    """
    Render a toggle-chip genre panel and return the list of selected genres.

    Parameters
    ----------
    genres : list[str]
        Full genre list from config.GENRES.

    Returns
    -------
    list[str]
        Currently selected genres (none selected by default on first load).
    """
    # Inject chip CSS
    st.markdown(_CHIP_CSS, unsafe_allow_html=True)

    # Initialize state — none selected by default
    if _STATE_KEY not in st.session_state:
        st.session_state[_STATE_KEY] = set()

    st.markdown("#### 🎸 Genres")
    st.caption("Toggle genres to blend into your discovery.")

    # Select All / Clear All
    col_all, col_clear = st.columns(2)
    with col_all:
        st.button(
            "✓ Select All",
            key="genre_select_all",
            use_container_width=True,
            on_click=_select_all,
            args=(genres,),
        )
    with col_clear:
        st.button(
            "✕ Clear All",
            key="genre_clear",
            use_container_width=True,
            on_click=_clear_all,
        )

    st.markdown("<div style='margin-top: 8px;'></div>", unsafe_allow_html=True)

    # Render genre chips in rows of 3
    _COLS = 3
    for i in range(0, len(genres), _COLS):
        row = genres[i : i + _COLS]
        cols = st.columns(len(row))
        for col, genre in zip(cols, row):
            with col:
                is_selected = genre in st.session_state[_STATE_KEY]
                # "primary" = selected (filled), "secondary" = unselected (outline)
                btn_type = "primary" if is_selected else "secondary"
                st.button(
                    genre,
                    key=f"genre_{genre}",
                    type=btn_type,
                    use_container_width=True,
                    on_click=_toggle_genre,
                    args=(genre,),
                )

    return sorted(st.session_state[_STATE_KEY])