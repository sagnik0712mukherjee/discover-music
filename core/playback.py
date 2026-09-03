"""
core/playback.py

Pure-Python (no JS) playback-state tracking for the hidden YouTube
iframe used as an audio-only player (see ui/bubble_grid.py, change #4).

WHY WALL-CLOCK ESTIMATION, NOT A REAL "CURRENT POSITION" QUERY:
Streamlit has no way to ask a running <iframe> what second it's on
without JavaScript, which this project is deliberately avoiding. So
this module tracks playback position the way a stopwatch would: it
remembers (a) the offset the iframe was last told to start() from,
and (b) the real wall-clock time that start happened at. "Where is
playback right now" is then just base_offset + elapsed real seconds,
for as long as is_playing stays True.

This is an approximation — it assumes the video began playing at
roughly the moment the iframe was rendered, with no buffering stalls.
Good enough for a seek/pause UI; not frame-accurate.

WHY "PAUSE" REMOVES THE IFRAME RATHER THAN PAUSING IT:
There's no JS IFrame Player API call available (player.pauseVideo())
without JS. The only way to actually stop the audio is to stop
rendering the iframe at all — removing the DOM node kills playback.
Resuming re-creates the iframe with start=<remembered offset>.

IMPORTANT FOR CALLERS (see app.py):
This module only tracks *state* (offset, playing/paused, which video).
It deliberately does NOT build the YouTube embed URL itself — that
stays services/youtube_client.py's job, so this module has no
knowledge of YouTube's URL format. app.py is the glue that calls
start()/pause()/seek() here AND rebuilds the embed URL string, and
does so only inside button-click handling — never on every rerun —
so the iframe's src stays byte-identical across unrelated reruns
(a genre toggle, a map drag) and doesn't restart the song. This is
what change #5 depends on.
"""

import time

import streamlit as st

_STATE_KEY = "playback"


def _default_state() -> dict:
    return {
        "video_id": None,
        "base_offset": 0.0,          # seconds — position the iframe was last started from
        "started_wall_time": None,   # time.time() when it last started playing; None if paused
        "is_playing": False,
    }


def _get_state() -> dict:
    if _STATE_KEY not in st.session_state:
        st.session_state[_STATE_KEY] = _default_state()
    return st.session_state[_STATE_KEY]


def start(video_id: str, offset_seconds: float = 0.0) -> None:
    """
    Begin playback of a video from offset_seconds. Called on PLAY
    click from the bubble grid (fresh song, offset=0) or on RESUME
    after a pause (same song, remembered offset).
    """
    state = _get_state()
    state["video_id"] = video_id
    state["base_offset"] = max(0.0, offset_seconds)
    state["started_wall_time"] = time.time()
    state["is_playing"] = True


def pause() -> None:
    """
    Freeze the current estimated position and mark as paused. The
    caller (app.py) is responsible for actually not re-rendering the
    iframe when is_playing is False — that's what stops the audio.
    """
    state = _get_state()
    if state["is_playing"]:
        state["base_offset"] = current_offset()
    state["started_wall_time"] = None
    state["is_playing"] = False


def seek(delta_seconds: float) -> float:
    """
    Jump forward/back by delta_seconds (negative = back). Works
    whether currently playing or paused. Returns the new offset so
    the caller can rebuild the embed URL with it if playback is live.

    Never goes below 0 seconds.
    """
    state = _get_state()
    new_offset = max(0.0, current_offset() + delta_seconds)
    state["base_offset"] = new_offset
    if state["is_playing"]:
        state["started_wall_time"] = time.time()
    return new_offset


def seek_to(absolute_seconds: float) -> float:
    """
    Jump to an absolute position (used by the progress slider, as
    opposed to seek()'s relative ±10s jumps). Same mechanics as
    seek(), just expressed as a target position rather than a delta.

    Never goes below 0 seconds.
    """
    state = _get_state()
    new_offset = max(0.0, absolute_seconds)
    state["base_offset"] = new_offset
    if state["is_playing"]:
        state["started_wall_time"] = time.time()
    return new_offset


def current_offset() -> float:
    """
    Best-estimate current playback position in seconds, per the
    wall-clock approximation described at the top of this file.
    """
    state = _get_state()
    if state["is_playing"] and state["started_wall_time"] is not None:
        return state["base_offset"] + (time.time() - state["started_wall_time"])
    return state["base_offset"]


def is_playing() -> bool:
    return _get_state()["is_playing"]


def active_video_id() -> str | None:
    return _get_state()["video_id"]


def reset() -> None:
    """
    Clear all playback state. Called when a brand-new search
    (Surprise me) replaces the results — see change #5, which is the
    only place this gets called from besides first load.
    """
    st.session_state[_STATE_KEY] = _default_state()

def has_ended(duration_seconds: float | None) -> bool:
    """
    True if playback is currently active AND the wall-clock-estimated
    offset has reached/passed the song's known duration.

    Used by app.py's change #6 auto-play check. duration_seconds=None
    (Last.fm had no duration for this track) always returns False —
    with no known end point, there's nothing to compare against, so
    auto-play deliberately does nothing rather than guessing.
    """
    if duration_seconds is None:
        return False
    if not is_playing():
        return False
    return current_offset() >= duration_seconds