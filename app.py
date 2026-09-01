"""
app.py

Streamlit entrypoint. Wires together:
    config          -> MOOD_CORNERS, GENRES, settings
    services/*      -> Last.fm, YouTube clients
    core/cache      -> per-session memoization
    core/recommender -> (position + genres) -> Song list, song -> similar Song list
    ui/map_widget   -> 2-axis mood map (Dark/Positive × Energetic/Calm)
    ui/genre_panel  -> oval genre chip selector
    ui/bubble_grid  -> song bubbles + now-playing card

Layout:
    [ mood map (left) | genre panel (right) ]
    [ song bubbles — full width             ]

Two Streamlit-specific behaviors are handled deliberately:

1. Rerun guard: a new recommendation is fired only when the map position
   changes meaningfully (_position_changed) OR when the genre selection
   changes. Genre-only changes don't need the position epsilon guard
   since chip clicks are discrete events, not continuous slider values.

2. PLAY click → st.rerun(): the click is detected in render_bubble_grid()
   during the same rerun that drew the old bubbles. Session state is
   updated, then st.rerun() forces a clean second pass to render the
   now-playing card and new similar-track bubbles.
"""

import streamlit as st

import config
from core.cache import SessionCache
from core.recommender import MusicRecommender
from models.song import Song
from services.lastfm_client import LastFmClient
from services.youtube_client import YouTubeClient, YouTubeQuotaExceededError
from ui.bubble_grid import render_bubble_grid, render_now_playing
from ui.genre_panel import render_genre_panel
from ui.map_widget import render_mood_map

# Minimum position delta to treat as a genuine new drag (not a
# re-render artifact from a PLAY click or genre toggle).
_POSITION_EPSILON = 1.0


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


def _handle_play(
    song: Song,
    youtube_client: YouTubeClient,
    recommender: MusicRecommender,
    cache: SessionCache,
) -> None:
    """
    Resolve everything a PLAY click needs — video ID (cache → YouTube)
    and similar-track replacements (cache → Last.fm) — then write into
    session state for the rerun that follows.
    """
    video_id = cache.get_video_id(song)
    if video_id is None:
        try:
            video_id = youtube_client.resolve_video_id(song.artist, song.title)
        except YouTubeQuotaExceededError:
            video_id = None
        if video_id is not None:
            cache.set_video_id(song, video_id)

    embed_url = youtube_client.build_embed_url(video_id) if video_id else None

    similar_songs = cache.get_similar_tracks(song)
    if similar_songs is None:
        similar_songs = recommender.get_similar_songs(song)
        cache.set_similar_tracks(song, similar_songs)

    st.session_state["now_playing"] = song
    st.session_state["now_playing_embed_url"] = embed_url
    st.session_state["current_bubbles"] = similar_songs


def main() -> None:
    st.set_page_config(page_title="Music Discovery", layout="wide")
    st.title("🎵 Music Discovery")
    st.caption("Set the mood, pick your genres, and discover music that fits right now.")

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

    # ── Two-column input panel ──────────────────────────────────────────
    map_col, genre_col = st.columns([3, 2], gap="large")

    with map_col:
        position = render_mood_map()

    with genre_col:
        selected_genres = render_genre_panel(config.GENRES)

    # ── Rerun guard: only re-query when inputs genuinely change ─────────
    position_changed = position is not None and _position_changed(
        position, st.session_state["last_position"]
    )
    genres_changed = selected_genres != st.session_state["last_genres"]

    if position_changed or genres_changed:
        effective_position = position or st.session_state.get("last_position") or (50.0, 50.0)
        st.session_state["current_bubbles"] = recommender.get_songs_for_position(
            *effective_position,
            selected_genres=selected_genres,
        )
        if position_changed:
            st.session_state["last_position"] = position
            # Clear now-playing when the user drags to a new mood zone
            st.session_state["now_playing"] = None
            st.session_state["now_playing_embed_url"] = None
        st.session_state["last_genres"] = selected_genres

    # ── Results ─────────────────────────────────────────────────────────
    if st.session_state["now_playing"] is not None:
        render_now_playing(
            st.session_state["now_playing"],
            st.session_state["now_playing_embed_url"],
        )

    clicked_song = render_bubble_grid(st.session_state["current_bubbles"])

    if clicked_song is not None:
        _handle_play(clicked_song, youtube_client, recommender, cache)
        st.rerun()


if __name__ == "__main__":
    main()