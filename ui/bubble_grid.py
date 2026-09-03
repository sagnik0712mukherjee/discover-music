"""
ui/bubble_grid.py

Presentational layer for two things:
    1. The grid of song bubbles (title, artist, PLAY button).
    2. The "now playing" card — audio-only playback via a visually
       hidden YouTube iframe (change #4), with Python-driven
       Play/Pause and ±10s seek controls.

This module still knows nothing about Last.fm, YouTube quota, or
core/recommender.py, or core/playback.py's internals — it only ever
receives ready-to-render Song objects, a pre-built embed URL string,
and callback functions to wire up to its buttons. app.py owns what
those callbacks actually do.

WHY on_click CALLBACKS INSTEAD OF "return which button was clicked":
The previous version had these functions return an action string,
which app.py used to mutate state and then call st.rerun() to make
the change visible. That extra, explicit st.rerun() was resetting the
page's scroll position on every click. Streamlit already reruns the
whole script automatically the instant any button is clicked — an
on_click callback just runs BEFORE that automatic rerun repaints the
page, so by the time the script executes top-to-bottom again,
session_state already reflects the click. One natural rerun, nothing
extra, no scroll reset.

WHY A MARKER DIV INSTEAD OF st.container(border=True):
Song cards and the now-playing card ARE meant to have a visible white
border (everything else in the app — map, genre panel, buttons — stays
borderless). But st.container(border=True) can't be scoped to "just
these two" without the key= parameter, which isn't available on the
Streamlit version this project is pinned to (<1.37, kept for
streamlit-drawable-canvas compatibility) — and Streamlit's generic
container wrapper (data-testid="stVerticalBlockBorderWrapper") turns
out to wrap EVERY column/container app-wide, bordered or not, so
targeting it directly via CSS boxes everything, not just cards.
Fix: each of these two containers gets a plain st.container() (no
border) with an invisible marker div as its first child
(.bubble-card-marker / .now-playing-card-marker). ui/theme.py's CSS
uses the :has() selector to style only wrapper divs that contain that
specific marker — nothing else in the app has one, so nothing else
gets boxed, regardless of how many other columns/containers exist.

WHY THE IFRAME IS HIDDEN RATHER THAN REMOVED:
YouTube's embedded player is what's actually licensed/intended for
playing full official audio/video inline on a third-party page — the
Terms of Service problem is extracting/ripping the raw audio stream,
not embedding the player itself. So the same iframe source used
before is kept, just rendered at 1x1px and visually clipped, so only
audio is perceptible — no video box shown anywhere in the UI.

Uses only plain HTML/CSS via st.markdown(unsafe_allow_html=True) for
the hidden iframe (no JS) plus Streamlit's own st.button for controls.
"""

from datetime import time as time_of_day
from typing import Callable

import streamlit as st

from models.song import Song

_BUBBLES_PER_ROW = 5


def _chunk(items: list[Song], size: int) -> list[list[Song]]:
    """Split a flat list into row-sized chunks for st.columns layout."""
    return [items[i : i + size] for i in range(0, len(items), size)]


def render_bubble_grid(songs: list[Song], on_play: Callable[..., None], *on_play_args) -> None:
    """
    Render up to 10 song bubbles in rows of `_BUBBLES_PER_ROW`, each with
    a PLAY button wired to `on_play(song, *on_play_args)` via Streamlit's
    on_click.

    Button keys are derived from Song.identity_key() rather than list
    position, since the bubble contents change entirely after every
    PLAY click (new similar-track results) — position-based keys would
    let Streamlit confuse an old button state with a new song occupying
    the same grid slot.

    Note on the args tuple: `args=(song, *on_play_args)` is built fresh
    on every loop iteration and passed directly to st.button — this is
    what avoids the classic Python closure-in-a-loop bug (all buttons
    silently sharing the *last* loop's `song`). Never replace this with
    `on_click=lambda: on_play(song)` inside the loop.
    """
    for row in _chunk(songs, _BUBBLES_PER_ROW):
        columns = st.columns(len(row))
        for column, song in zip(columns, row):
            with column:
                with st.container():
                    st.markdown(
                        '<div class="bubble-card-marker"></div>',
                        unsafe_allow_html=True,
                    )
                    st.markdown(f"**{song.title}**")
                    st.caption(song.artist)
                    if not song.matched_by_mood:
                        st.caption("genre match")
                    st.button(
                        "▶ Play",
                        key=f"play_{song.identity_key()}",
                        on_click=on_play,
                        args=(song, *on_play_args),
                    )


def _render_hidden_player(embed_url: str) -> None:
    """
    Render the YouTube iframe at 1x1px, clipped and positioned off the
    visible layout, so only audio is perceptible. `allow="autoplay"`
    is required for the video to actually start without a user click
    inside the iframe itself (which the user can't reach anyway, since
    it's hidden) — some mobile browsers (iOS Safari in particular)
    may still block the very first autoplay without a direct tap
    elsewhere on the page; the visible Play/Resume button covers that.
    """
    st.markdown(
        f"""
        <div style="position:absolute; width:1px; height:1px;
                    overflow:hidden; clip:rect(0,0,0,0);">
            <iframe
                src="{embed_url}"
                width="1"
                height="1"
                frameborder="0"
                allow="autoplay; encrypted-media"
            ></iframe>
        </div>
        """,
        unsafe_allow_html=True,
    )


def _format_time(seconds: float | None) -> str:
    """MM:SS display, used for the elapsed/total caption beside the slider."""
    if seconds is None or seconds < 0:
        return "--:--"
    total_seconds = int(seconds)
    minutes, secs = divmod(total_seconds, 60)
    return f"{minutes}:{secs:02d}"


def _seconds_to_time_of_day(seconds: float) -> time_of_day:
    """
    Convert a plain seconds count into a datetime.time, so st.slider can
    be given time_of_day values instead of raw ints — Streamlit natively
    renders time-typed sliders using a real MM:SS-style format string
    (format="mm:ss" below), which is what actually fixes the slider
    showing raw seconds (e.g. "197") instead of "3:17". Clamped to a
    valid time-of-day range; song durations are always well under 24h.
    """
    total_seconds = max(0, int(seconds))
    hours, remainder = divmod(total_seconds, 3600)
    minutes, secs = divmod(remainder, 60)
    return time_of_day(hour=min(hours, 23), minute=minutes, second=secs)


def render_now_playing(
    song: Song,
    video_id: str | None,
    embed_url: str | None,
    is_playing: bool,
    current_offset_seconds: float,
    duration_seconds: float | None,
    on_toggle_play: Callable[..., None],
    on_seek_back: Callable[..., None],
    on_seek_fwd: Callable[..., None],
    on_seek_to: Callable[..., None],
) -> None:
    """
    Render the "now playing" card: song name, audio-only playback (no
    visible video), Pause/Resume + ±10s controls, and a progress slider
    with elapsed/total time.

    Parameters
    ----------
    song : Song
        The currently active song.
    video_id : str | None
        None means no playable YouTube match was ever found for this
        song — controls are hidden and a message is shown instead.
    embed_url : str | None
        A complete URL from services.youtube_client.YouTubeClient
        .build_embed_url(), already reflecting the current seek
        position — or None when paused (nothing should render, since
        an absent iframe is what stops the audio). This function only
        renders whatever URL it's given; it never builds one itself.
    is_playing : bool
        Drives the Pause/Resume button label and whether the hidden
        iframe is drawn this render.
    current_offset_seconds : float
        core/playback.py's wall-clock-estimated current position —
        this function only displays it, never computes it itself.
    duration_seconds : float | None
        The song's known length from Last.fm, or None if unknown. When
        None, the slider is hidden entirely (there's no sane range to
        seek within) rather than guessing a fake maximum.
    on_toggle_play, on_seek_back, on_seek_fwd, on_seek_to : Callable
        Pre-bound callbacks (e.g. via functools.partial in app.py) —
        already carry whatever arguments they need. on_seek_to
        receives the slider's chosen absolute position in seconds as
        its first argument (Streamlit passes a slider's on_change
        callback no value automatically — app.py's callback reads it
        back out of st.session_state, see the widget key used below).
    """
    with st.container():
        st.markdown(
            '<div class="now-playing-card-marker"></div>',
            unsafe_allow_html=True,
        )
        st.markdown(f"### 🎧 Now playing: {song.display_name()}")

        if video_id is None:
            st.warning(
                "Couldn't find a playable version of this song right now. "
                "Try another one from the grid below."
            )
            return

        if embed_url:
            _render_hidden_player(embed_url)

        if duration_seconds is not None and duration_seconds > 0:
            clamped_offset = max(0.0, min(current_offset_seconds, duration_seconds))
            slider_col, time_col = st.columns([5, 2])
            with slider_col:
                st.slider(
                    "Progress",
                    min_value=time_of_day(0, 0, 0),
                    max_value=_seconds_to_time_of_day(duration_seconds),
                    value=_seconds_to_time_of_day(clamped_offset),
                    format="mm:ss",
                    key=f"seek_slider_{song.identity_key()}",
                    label_visibility="collapsed",
                    on_change=on_seek_to,
                    args=(f"seek_slider_{song.identity_key()}",),
                )
            with time_col:
                st.caption(f"{_format_time(clamped_offset)} / {_format_time(duration_seconds)}")

        col_back, col_toggle, col_fwd = st.columns(3)
        with col_back:
            st.button(
                "⏪ 10s",
                key=f"seek_back_{song.identity_key()}",
                use_container_width=True,
                on_click=on_seek_back,
            )
        with col_toggle:
            label = "⏸ Pause" if is_playing else "▶ Resume"
            st.button(
                label,
                key=f"toggle_play_{song.identity_key()}",
                use_container_width=True,
                on_click=on_toggle_play,
            )
        with col_fwd:
            st.button(
                "10s ⏩",
                key=f"seek_fwd_{song.identity_key()}",
                use_container_width=True,
                on_click=on_seek_fwd,
            )