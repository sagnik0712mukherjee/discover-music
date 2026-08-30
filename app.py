"""
app.py

Streamlit entrypoint. Wires together:
    config          -> API keys, anchor tag map, tunables
    services/*       -> Last.fm, YouTube, Spotify clients
    core/cache        -> per-session memoization
    core/recommender  -> position -> Song list, and song -> similar Song list
    ui/*             -> the draggable map and the bubble grid / now-playing card

Two Streamlit-specific behaviors are handled deliberately here, not
incidentally:

1. Streamlit reruns this entire script top-to-bottom on every interaction
   (dragging the circle, clicking PLAY — anything). Naively recomputing
   the recommendation on every rerun would re-fire Last.fm calls on
   reruns that have nothing to do with the map (e.g. a PLAY click).
   `_position_changed()` guards against that: the bubble grid is only
   recomputed from the map position when the position has genuinely
   moved since the last time it was used.

2. When PLAY is clicked, that click is detected inside
   ui.bubble_grid.render_bubble_grid() *during* the same rerun that also
   drew the (still-old) bubble grid to the page. Session state is
   updated after that render call, then st.rerun() is called explicitly
   to force one more clean rerun — that second pass is what actually
   draws the new "now playing" card and the new similar-track bubbles.
   Skipping the explicit rerun would leave the old bubbles on screen
   until some unrelated interaction happened to trigger the next render.
"""

import streamlit as st

import config
from core.cache import SessionCache
from core.recommender import MusicRecommender
from models.song import Song
from services.lastfm_client import LastFmClient
from services.youtube_client import YouTubeClient, YouTubeQuotaExceededError
from ui.bubble_grid import render_bubble_grid, render_now_playing
from ui.map_widget import render_mood_map

# How far (on the 0-100 grid) the circle must move before it's treated as
# a genuine new drag rather than an incidental value from an unrelated
# rerun (e.g. re-rendering the map while processing a PLAY click).
_POSITION_EPSILON = 1.0


@st.cache_resource
def _get_lastfm_client(api_key: str) -> LastFmClient:
    return LastFmClient(api_key)


@st.cache_resource
def _get_youtube_client(api_key: str, daily_search_budget: int) -> YouTubeClient:
    """
    Cached as a single shared instance for the whole deployed app process
    (st.cache_resource is process-wide, not per browser session) — and
    that's actually the technically correct scope here, not a shortcut.
    YouTube's real quota is tied to the API key/project, not to any one
    visitor's session, so every user of this deployed app is genuinely
    drawing from the same quota bucket. (services/youtube_client.py's own
    docstring describes the budget loosely as "per session" — this is the
    more precise framing: per deployed app process, shared across
    whoever is using it at the time.)
    """
    return YouTubeClient(api_key, daily_search_budget)


@st.cache_resource
def _build_recommender(_lastfm_client: LastFmClient, bubble_count: int, nearest_tag_count: int) -> MusicRecommender:
    # Leading underscore on _lastfm_client tells Streamlit not to try
    # hashing that argument for cache-key purposes (it's an object, not
    # a plain value) — standard st.cache_resource convention.
    return MusicRecommender(
        lastfm_client=_lastfm_client,
        anchor_tags=config.ANCHOR_TAGS,
        genre_tags=config.GENRE_TAGS,
        bubble_count=bubble_count,
        nearest_tag_count=nearest_tag_count,
    )


def _position_changed(new_position: tuple[float, float], last_position: tuple[float, float] | None) -> bool:
    if last_position is None:
        return True
    return (
        abs(new_position[0] - last_position[0]) > _POSITION_EPSILON
        or abs(new_position[1] - last_position[1]) > _POSITION_EPSILON
    )


def _handle_play(
    song: Song,
    youtube_client: YouTubeClient,
    recommender: MusicRecommender,
    cache: SessionCache,
) -> None:
    """
    Resolve everything a PLAY click needs — a video ID (cache first, then
    a live YouTube search) and the similar-track replacement bubbles
    (cache first, then a live Last.fm call) — and write it all into
    session state for the rerun that follows this call.
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
    st.caption("Drag the circle onto the map to find songs that match that spot.")

    settings = config.load_settings()

    lastfm_client = _get_lastfm_client(settings.lastfm_api_key)
    youtube_client = _get_youtube_client(settings.youtube_api_key, settings.youtube_daily_search_budget)
    # Spotify is intentionally not instantiated here — the core loop is
    # Last.fm (tags + similarity) and YouTube (playback) only. See
    # services/spotify_client.py's docstring: it's kept ready for future
    # new-release freshness work, wired back in here only when that
    # feature is actually turned on.

    recommender = _build_recommender(lastfm_client, settings.bubble_count, settings.nearest_tag_count)

    if "cache" not in st.session_state:
        st.session_state["cache"] = SessionCache()
    cache: SessionCache = st.session_state["cache"]

    st.session_state.setdefault("current_bubbles", [])
    st.session_state.setdefault("last_position", None)
    st.session_state.setdefault("now_playing", None)
    st.session_state.setdefault("now_playing_embed_url", None)

    position = render_mood_map(config.ANCHOR_TAGS)

    if position is not None and _position_changed(position, st.session_state["last_position"]):
        st.session_state["current_bubbles"] = recommender.get_songs_for_position(*position)
        st.session_state["last_position"] = position
        st.session_state["now_playing"] = None
        st.session_state["now_playing_embed_url"] = None

    if st.session_state["now_playing"] is not None:
        render_now_playing(st.session_state["now_playing"], st.session_state["now_playing_embed_url"])

    clicked_song = render_bubble_grid(st.session_state["current_bubbles"])

    if clicked_song is not None:
        _handle_play(clicked_song, youtube_client, recommender, cache)
        st.rerun()


if __name__ == "__main__":
    main()