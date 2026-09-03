"""
app.py

Streamlit entrypoint. Wires together:
    config          -> MOOD_CORNERS, GENRES, settings
    services/*      -> Last.fm, YouTube clients
    core/cache      -> per-session memoization
    core/recommender -> (position + genres) -> Song list, song -> similar Song list
    core/playback   -> Play/Pause/Seek/auto-play state for the hidden-audio player
    ui/map_widget   -> 2-axis mood map (Dark/Positive × Energetic/Calm)
    ui/genre_panel  -> oval genre chip selector
    ui/bubble_grid  -> song bubbles + now-playing card (audio-only, change #4)

Layout:
    [ mood map (left) | genre panel (right) ]
    [ song bubbles — full width             ]

Streamlit-specific behaviors handled deliberately:

1. Rerun guard: a new recommendation is fired only when the map position
   changes meaningfully (_position_changed) OR when the genre selection
   changes. Genre-only changes don't need the position epsilon guard
   since chip clicks are discrete events, not continuous slider values.

2. PLAY / PAUSE / SEEK clicks are wired via on_click callbacks
   (_on_play, _on_toggle_play, _on_seek), NOT "detect a click, mutate
   state, then call st.rerun()". Streamlit already reruns the whole
   script automatically the instant a button is clicked. An on_click
   callback runs BEFORE that automatic rerun repaints the page, so the
   new state is already in session_state by the time the script
   executes top-to-bottom again — no extra, manually-triggered
   st.rerun() needed. That extra rerun (an earlier version's approach)
   is what was resetting the page's scroll position on every click.
   Same fix is applied in ui/genre_panel.py for the genre chips.

3. Change #6 (auto-play) AND the "needs two clicks while something is
   playing" bug: both traced back to the same root cause. The earlier
   version used streamlit_autorefresh to force a full-page rerun every
   few seconds while a song played, so it could notice the song ending.
   But a full-page rerun is exactly that — the WHOLE script reruns,
   including the bubble grid's PLAY buttons — so a user's click and the
   timer's own rerun could land close enough together to race, and the
   click's effect got lost until a second click landed cleanly.
   The fix: _render_now_playing_section below is an
   st.experimental_fragment(run_every=_AUTO_ADVANCE_POLL_SECONDS) — its
   periodic timer reruns ONLY that fragment, never the bubble grid, so
   there's nothing left for a PLAY click to race against. A PLAY click
   still triggers a normal full-page rerun (fragments run inline as
   part of those too), so the new song reflects immediately — no
   second click needed either way. No third-party polling package
   needed anymore; run_every is native to the fragment.
"""

from functools import partial

import streamlit as st

import config
from core.cache import SessionCache
from core.recommender import MusicRecommender
from models.song import Song
from services.lastfm_client import LastFmClient
from services.youtube_client import YouTubeClient, YouTubeQuotaExceededError
from core import playback
from ui.bubble_grid import render_bubble_grid, render_now_playing
from ui.genre_panel import render_genre_panel
from ui.map_widget import render_mood_map
from ui.theme import inject_global_css, render_app_header

# Minimum position delta to treat as a genuine new drag (not a
# re-render artifact from a PLAY click or genre toggle).
_POSITION_EPSILON = 1.0

# How many seconds a single ⏪ / ⏩ click jumps.
_SEEK_STEP_SECONDS = 10.0

# How often (seconds) the now-playing fragment re-checks "has the song
# ended" / refreshes the progress slider, while something is playing.
# 3s is frequent enough that the gap isn't noticeable, without
# rerunning so often it's wasteful. This now drives st.experimental_fragment's
# own run_every, not a separate polling component — see
# _render_now_playing_section below for why that distinction matters.
_AUTO_ADVANCE_POLL_SECONDS = 3


@st.cache_resource
def _get_lastfm_client(api_key: str) -> LastFmClient:
    return LastFmClient(api_key)


@st.cache_resource
def _get_youtube_client(api_key: str, daily_search_budget: int) -> YouTubeClient:
    """
    Process-wide singleton — YouTube quota is per API key, not per
    browser session, so sharing this instance across all visitors is
    the correct scope (not a shortcut).
    """
    return YouTubeClient(api_key, daily_search_budget)


@st.cache_resource
def _build_recommender(
    _lastfm_client: LastFmClient,
    bubble_count: int,
) -> MusicRecommender:
    # Leading underscore prevents Streamlit from trying to hash the
    # client object for cache-key purposes.
    return MusicRecommender(
        lastfm_client=_lastfm_client,
        mood_corners=config.MOOD_CORNERS,
        mood_weight_threshold=config.MOOD_WEIGHT_THRESHOLD,
        bubble_count=bubble_count,
    )


def _position_changed(
    new: tuple[float, float],
    old: tuple[float, float] | None,
) -> bool:
    if old is None:
        return True
    return abs(new[0] - old[0]) > _POSITION_EPSILON or abs(new[1] - old[1]) > _POSITION_EPSILON


def _start_song(
    song: Song,
    youtube_client: YouTubeClient,
    recommender: MusicRecommender,
    cache: SessionCache,
    lastfm_client: LastFmClient,
) -> None:
    """
    Shared logic for "make this song the one that's playing, from
    0:00" — used both by a manual PLAY click (_on_play) and by
    change #6's automatic advance (_maybe_auto_advance). Resolves the
    video ID, duration, and similar-track replacements (all cached
    after the first lookup), then starts playback.
    """
    video_id = cache.get_video_id(song)
    if video_id is None:
        try:
            video_id = youtube_client.resolve_video_id(song.artist, song.title)
        except YouTubeQuotaExceededError:
            video_id = None
        if video_id is not None:
            cache.set_video_id(song, video_id)

    duration_seconds = cache.get_duration(song)
    if duration_seconds is None:
        try:
            duration_seconds = lastfm_client.get_track_duration_seconds(song.artist, song.title)
        except Exception:
            duration_seconds = None  # missing duration just disables auto-play for this song
        if duration_seconds is not None:
            cache.set_duration(song, duration_seconds)

    similar_songs = cache.get_similar_tracks(song)
    if similar_songs is None:
        similar_songs = recommender.get_similar_songs(song)
        cache.set_similar_tracks(song, similar_songs)

    st.session_state["now_playing"] = song
    st.session_state["now_playing_duration_seconds"] = duration_seconds
    st.session_state["current_bubbles"] = similar_songs

    if video_id is not None:
        playback.start(video_id, offset_seconds=0.0)
        st.session_state["now_playing_embed_url"] = youtube_client.build_embed_url(
            video_id, autoplay=True, start_seconds=0.0
        )
    else:
        playback.reset()
        st.session_state["now_playing_embed_url"] = None


def _on_play(
    song: Song,
    youtube_client: YouTubeClient,
    recommender: MusicRecommender,
    cache: SessionCache,
    lastfm_client: LastFmClient,
) -> None:
    """
    on_click callback for a bubble's PLAY button (see
    ui/bubble_grid.py's render_bubble_grid — args are bound per-song
    via st.button's args= tuple, not a closure, so this is safe to
    reuse across every bubble in the grid). Runs BEFORE Streamlit's
    natural rerun, so no explicit st.rerun() is needed here.
    """
    _start_song(song, youtube_client, recommender, cache, lastfm_client)


def _on_toggle_play(youtube_client: YouTubeClient) -> None:
    """on_click callback for the Pause/Resume button."""
    video_id = playback.active_video_id()
    if video_id is None:
        return

    if playback.is_playing():
        playback.pause()
        st.session_state["now_playing_embed_url"] = None
    else:
        offset = playback.current_offset()
        playback.start(video_id, offset_seconds=offset)
        st.session_state["now_playing_embed_url"] = youtube_client.build_embed_url(
            video_id, autoplay=True, start_seconds=offset
        )


def _on_seek(delta_seconds: float, youtube_client: YouTubeClient) -> None:
    """on_click callback for the ⏪10s / 10s⏩ buttons."""
    video_id = playback.active_video_id()
    if video_id is None:
        return

    new_offset = playback.seek(delta_seconds)
    if playback.is_playing():
        st.session_state["now_playing_embed_url"] = youtube_client.build_embed_url(
            video_id, autoplay=True, start_seconds=new_offset
        )
    # else: still paused after seeking — embed_url stays None, the new
    # offset is remembered and used on the next Resume.


def _on_seek_to_slider(slider_key: str, youtube_client: YouTubeClient) -> None:
    """
    on_change callback for the progress slider. Streamlit doesn't pass
    a widget's new value into its on_change callback automatically —
    the callback reads it back out of st.session_state[slider_key],
    which is already updated by the time on_change fires. The slider
    is time-typed (see ui/bubble_grid.py — needed for the native
    format="mm:ss" display), so the value read back is a datetime.time,
    not a raw number; converted back to plain seconds here.
    """
    video_id = playback.active_video_id()
    if video_id is None:
        return

    slider_value = st.session_state[slider_key]
    target_seconds = float(
        slider_value.hour * 3600 + slider_value.minute * 60 + slider_value.second
    )
    new_offset = playback.seek_to(target_seconds)
    if playback.is_playing():
        st.session_state["now_playing_embed_url"] = youtube_client.build_embed_url(
            video_id, autoplay=True, start_seconds=new_offset
        )


def _maybe_auto_advance(
    youtube_client: YouTubeClient,
    recommender: MusicRecommender,
    cache: SessionCache,
    lastfm_client: LastFmClient,
) -> None:
    """
    Change #6: if the current song has finished (per
    core/playback.has_ended) and there's a next bubble available,
    start it automatically — "if the user gives no input" is
    satisfied structurally here: this only ever looks at
    st.session_state["current_bubbles"], which nothing except a
    PLAY click or a new Surprise-me search ever changes, so this
    can't accidentally advance into results the user didn't ask for.

    Runs inline in main(), before the now-playing section renders, so
    the switch is visible in the same pass — no st.rerun() needed.
    """
    duration = st.session_state.get("now_playing_duration_seconds")
    if not playback.has_ended(duration):
        return

    bubbles = st.session_state.get("current_bubbles") or []
    if not bubbles:
        # Nothing left to advance to — stop cleanly rather than
        # leaving a "finished but still marked playing" iframe up.
        playback.pause()
        st.session_state["now_playing_embed_url"] = None
        return

    next_song = bubbles[0]
    _start_song(next_song, youtube_client, recommender, cache, lastfm_client)


@st.experimental_fragment(run_every=_AUTO_ADVANCE_POLL_SECONDS)
def _render_now_playing_section(
    youtube_client: YouTubeClient,
    recommender: MusicRecommender,
    cache: SessionCache,
    lastfm_client: LastFmClient,
) -> None:
    """
    Auto-advance check + the now-playing card, as one fragment that
    reruns itself every _AUTO_ADVANCE_POLL_SECONDS. Being a fragment is
    what matters here, not just the periodic timer: a fragment's own
    run_every reruns ONLY this function, never the bubble grid below —
    see the module docstring's point 3 for why that's what actually
    fixes the "needs two clicks" bug, not merely a side effect of it.

    A PLAY click on a bubble (outside this fragment) still triggers a
    normal full-page rerun, which re-runs this fragment inline too —
    so a freshly-clicked song still shows up immediately, same as
    before.
    """
    _maybe_auto_advance(youtube_client, recommender, cache, lastfm_client)

    if st.session_state["now_playing"] is not None:
        render_now_playing(
            st.session_state["now_playing"],
            playback.active_video_id(),
            st.session_state["now_playing_embed_url"],
            playback.is_playing(),
            current_offset_seconds=playback.current_offset(),
            duration_seconds=st.session_state["now_playing_duration_seconds"],
            on_toggle_play=partial(_on_toggle_play, youtube_client),
            on_seek_back=partial(_on_seek, -_SEEK_STEP_SECONDS, youtube_client),
            on_seek_fwd=partial(_on_seek, _SEEK_STEP_SECONDS, youtube_client),
            on_seek_to=partial(_on_seek_to_slider, youtube_client=youtube_client),
        )


def main() -> None:
    st.set_page_config(page_title="Music - Out of the Blue", layout="wide")
    inject_global_css()
    render_app_header()

    settings = config.load_settings()

    lastfm_client = _get_lastfm_client(settings.lastfm_api_key)
    youtube_client = _get_youtube_client(
        settings.youtube_api_key, settings.youtube_daily_search_budget
    )
    recommender = _build_recommender(lastfm_client, settings.bubble_count)

    # Session state defaults
    if "cache" not in st.session_state:
        st.session_state["cache"] = SessionCache()
    cache: SessionCache = st.session_state["cache"]

    st.session_state.setdefault("current_bubbles", [])
    st.session_state.setdefault("last_position", None)
    st.session_state.setdefault("last_genres", None)
    st.session_state.setdefault("now_playing", None)
    st.session_state.setdefault("now_playing_embed_url", None)
    st.session_state.setdefault("now_playing_duration_seconds", None)

    # ── Two-column input panel ──────────────────────────────────────────
    map_col, genre_col = st.columns([3, 2], gap="large")

    with map_col:
        # Push the map down to visually align its top edge with the
        # "🎸 Genres" heading on the right.
        st.markdown("<div style='margin-top: 46px;'></div>", unsafe_allow_html=True)
        position = render_mood_map()

    with genre_col:
        selected_genres = render_genre_panel(config.GENRES)

    # ── Submit button — search only on explicit click ────────────────
    st.markdown("<div style='margin-top: 12px;'></div>", unsafe_allow_html=True)
    btn_col1, btn_col2, btn_col3 = st.columns([2, 2, 2])
    with btn_col2:
        surprise = st.button(
            "🎲 Surprise me!",
            type="primary",
            use_container_width=True,
            key="surprise_btn",
        )

    if surprise:
        effective_position = position or st.session_state.get("last_position") or (50.0, 50.0)
        st.session_state["current_bubbles"] = recommender.get_songs_for_position(
            *effective_position,
            selected_genres=selected_genres,
        )
        st.session_state["last_position"] = position
        st.session_state["last_genres"] = selected_genres
        st.session_state["now_playing"] = None
        st.session_state["now_playing_embed_url"] = None
        st.session_state["now_playing_duration_seconds"] = None
        playback.reset()

    # ── Results ─────────────────────────────────────────────────────────
    _render_now_playing_section(youtube_client, recommender, cache, lastfm_client)

    render_bubble_grid(
        st.session_state["current_bubbles"],
        _on_play,
        youtube_client,
        recommender,
        cache,
        lastfm_client,
    )


if __name__ == "__main__":
    main()