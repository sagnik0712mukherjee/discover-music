"""
ui/bubble_grid.py

Presentational layer for two things:
    1. The grid of song bubbles (title, artist, PLAY button).
    2. The "now playing" card that shows the inline YouTube embed for
       whichever song is currently playing.

This module deliberately knows nothing about Last.fm, YouTube, or
core/recommender.py — it only ever receives ready-to-render Song objects
and, for the now-playing card, an embed URL string that app.py has
already resolved (via services/youtube_client.py + core/cache.py). That
keeps this file swappable/restylable without touching any data-fetching
logic, and keeps data-fetching logic testable without Streamlit involved.

Uses only Streamlit's built-in components (st.columns, st.container,
st.button, st.components.v1.iframe) — no extra UI package, no
hand-written HTML/JS beyond the embed URL itself, which is just a plain
src attribute Streamlit's own iframe component renders.
"""

import streamlit as st

from models.song import Song

_BUBBLES_PER_ROW = 5
_EMBED_HEIGHT_PX = 100


def _chunk(items: list[Song], size: int) -> list[list[Song]]:
    """Split a flat list into row-sized chunks for st.columns layout."""
    return [items[i : i + size] for i in range(0, len(items), size)]


def render_bubble_grid(songs: list[Song]) -> Song | None:
    """
    Render up to 10 song bubbles in rows of `_BUBBLES_PER_ROW`, each with
    a PLAY button.

    Returns the Song whose PLAY button was clicked on this render, or
    None if nothing was clicked. Streamlit's rerun-on-interaction model
    means this function naturally gets called again immediately after a
    click, at which point the clicked button's own return value is True
    for exactly that render — so no manual event bus is needed here.

    Button keys are derived from Song.identity_key() rather than list
    position, since the bubble contents change entirely after every
    PLAY click (new similar-track results) — position-based keys would
    let Streamlit confuse an old button state with a new song occupying
    the same grid slot.
    """
    clicked_song: Song | None = None

    for row in _chunk(songs, _BUBBLES_PER_ROW):
        columns = st.columns(len(row))
        for column, song in zip(columns, row):
            with column:
                with st.container(border=True):
                    st.markdown(f"**{song.title}**")
                    st.caption(song.artist)
                    if not song.matched_by_mood:
                        st.caption("genre match")
                    if st.button("▶ Play", key=f"play_{song.identity_key()}"):
                        clicked_song = song

    return clicked_song


def render_now_playing(song: Song, embed_url: str | None) -> None:
    """
    Render the "now playing" card above the bubble grid: the song's
    name, and either the inline YouTube embed (full song, playing in
    place) or a short message if no playable video could be found.

    embed_url is expected to already be a complete URL from
    services.youtube_client.YouTubeClient.build_embed_url() — this
    function only renders it, it never resolves one itself.
    """
    with st.container(border=True):
        st.markdown(f"### Now playing: {song.display_name()}")
        if embed_url:
            st.components.v1.iframe(embed_url, height=_EMBED_HEIGHT_PX)
        else:
            st.warning(
                "Couldn't find a playable version of this song right now. "
                "Try another one from the grid below."
            )