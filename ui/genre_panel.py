"""
ui/genre_panel.py

Renders the genre chip panel beside the mood map.

Uses CSS-styled toggle buttons (compatible with Streamlit <1.37).
Each genre button is oval/pill-shaped via injected CSS. Clicking toggles
selection state stored in st.session_state.

All 24 genres are selected by default on first load.
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
        Currently selected genres (all selected by default on first load).
    """
    # Inject chip CSS
    st.markdown(_CHIP_CSS, unsafe_allow_html=True)

    # Initialize state — all selected by default
    if _STATE_KEY not in st.session_state:
        st.session_state[_STATE_KEY] = set(genres)

    st.markdown("#### 🎸 Genres")
    st.caption("Toggle genres to blend into your discovery.")

    # Select All / Clear All
    col_all, col_clear = st.columns(2)
    with col_all:
        if st.button("✓ Select All", key="genre_select_all", use_container_width=True):
            st.session_state[_STATE_KEY] = set(genres)
            st.rerun()
    with col_clear:
        if st.button("✕ Clear All", key="genre_clear", use_container_width=True):
            st.session_state[_STATE_KEY] = set()
            st.rerun()

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
                if st.button(
                    genre,
                    key=f"genre_{genre}",
                    type=btn_type,
                    use_container_width=True,
                ):
                    if is_selected:
                        st.session_state[_STATE_KEY].discard(genre)
                    else:
                        st.session_state[_STATE_KEY].add(genre)
                    st.rerun()

    return sorted(st.session_state[_STATE_KEY])
