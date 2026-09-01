"""
ui/genre_panel.py

Renders the genre chip panel beside the mood map.

Uses st.pills (Streamlit ≥ 1.40) for native oval chip rendering.
All 24 genres are selected by default. The user can deselect any to
narrow results, or use 'Select All' / 'Clear All' for bulk control.

Returns the list of currently selected genre names, which app.py passes
directly into core/recommender.py alongside the mood map position.
"""

import streamlit as st


_SELECT_ALL_KEY = "genre_select_all"
_CLEAR_KEY = "genre_clear"
_PILLS_KEY = "genre_pills"


def render_genre_panel(genres: list[str]) -> list[str]:
    """
    Render a multi-select genre chip panel and return selected genres.

    Parameters
    ----------
    genres : list[str]
        The full list of available genre names (from config.GENRES).

    Returns
    -------
    list[str]
        The genres currently selected by the user. Defaults to all
        genres on first load.
    """
    st.markdown("#### 🎸 Genres")
    st.caption("Select genres to blend into your discovery.")

    col_all, col_clear = st.columns(2)
    with col_all:
        if st.button("Select All", key=_SELECT_ALL_KEY, use_container_width=True):
            st.session_state[_PILLS_KEY] = genres
    with col_clear:
        if st.button("Clear All", key=_CLEAR_KEY, use_container_width=True):
            st.session_state[_PILLS_KEY] = []

    # Default: all genres selected on first load
    if _PILLS_KEY not in st.session_state:
        st.session_state[_PILLS_KEY] = genres

    selected = st.pills(
        label="Genres",
        options=genres,
        selection_mode="multi",
        default=st.session_state[_PILLS_KEY],
        key=_PILLS_KEY,
        label_visibility="collapsed",
    )

    return selected if selected is not None else []
