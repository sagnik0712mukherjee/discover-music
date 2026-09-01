"""
config.py

Central configuration for the Music Discovery App.

Responsibilities:
    1. Load API credentials from environment variables (via a local .env
       file for development, or Streamlit Cloud "Secrets" in production).
    2. Define the anchor tag map: the fixed set of genre/mood words shown
       on the 2D map, each pinned to an (x, y) coordinate. When the user
       drops the draggable circle, core/mood_map.py measures distance from
       the drop point to every anchor here to decide which tag(s) apply.
    3. Hold small tunable constants (bubble count, cache behavior, etc.)
       in one place instead of scattering magic numbers across the app.

Nothing in this file talks to the network or to Streamlit — it is pure
configuration, safe to import from any other module without side effects.
"""

import os
from dataclasses import dataclass

from dotenv import load_dotenv

# Load variables from a local .env file if one exists. On Streamlit
# Community Cloud, secrets are injected as real environment variables
# directly, so this call is a harmless no-op there.
load_dotenv()


@dataclass(frozen=True)
class Settings:
    """
    Immutable bundle of runtime configuration, built once at import time.

    Using a frozen dataclass (rather than loose module-level variables)
    makes it obvious at a glance what configuration the app depends on,
    and prevents any code from accidentally mutating a setting mid-run.
    """

    lastfm_api_key: str
    youtube_api_key: str

    # Optional: Spotify is not called anywhere in the app right now (see
    # services/spotify_client.py's docstring — kept handy for future
    # new-release freshness, not part of the live flow). Left optional so
    # the app runs with just Last.fm + YouTube keys, since generating a
    # Spotify Client ID/Secret now requires an active Spotify Premium
    # subscription on the creating account.
    spotify_client_id: str | None = None
    spotify_client_secret: str | None = None

    # How many song bubbles are shown at once.
    bubble_count: int = 10

    # How many nearest anchor tags to blend when resolving a drop position.
    # 1 = only the single closest tag. 2-3 gives smoother, less "snappy"
    # results near the boundary between two tags.
    nearest_tag_count: int = 2

    # YouTube Data API v3 free tier is 10,000 quota units/day; a single
    # search.list call costs 100 units. This cap is a safety margin so a
    # burst of clicks in one session can't quietly exhaust the whole day's
    # quota. Video ID lookups are also cached per session (see core/cache.py)
    # so a song is only ever searched once per user session regardless of
    # this cap.
    youtube_daily_search_budget: int = 80


def _require_env(var_name: str) -> str:
    """
    Fetch a required environment variable, or fail loudly at startup.

    Failing fast here (instead of letting a service module raise a
    confusing error later, mid-request) makes missing configuration
    obvious the moment the app boots.
    """
    value = os.getenv(var_name)
    if not value:
        raise RuntimeError(
            f"Missing required environment variable: {var_name}. "
            f"Set it in your local .env file, or in Streamlit Cloud's "
            f"'Secrets' settings for deployed apps."
        )
    return value


def load_settings() -> Settings:
    """
    Build a Settings instance from the current environment.

    Called once from app.py at startup. Kept as a function (rather than
    a module-level constant) so tests can monkeypatch environment
    variables and call this fresh, without import-order headaches.
    """
    return Settings(
        lastfm_api_key=_require_env("LASTFM_API_KEY"),
        youtube_api_key=_require_env("YOUTUBE_API_KEY"),
        spotify_client_id=os.getenv("SPOTIFY_CLIENT_ID"),
        spotify_client_secret=os.getenv("SPOTIFY_CLIENT_SECRET"),
    )


# ---------------------------------------------------------------------------
# Mood map — 4-corner bilinear system
# ---------------------------------------------------------------------------
# The 2D canvas is a continuous mood space with 4 axis labels:
#   Energetic (top) ↔ Calm (bottom)   [y-axis, y=0 is top]
#   Dark (left)     ↔ Positive (right) [x-axis]
#
# Each corner maps to a set of Last.fm tags that characterise that mood
# quadrant. The draggable circle's (x, y) position is decomposed into
# weights for each corner via bilinear interpolation — see
# core/mood_map.py for the math.
#
# Tags per corner are ordered by priority; the first tag in the list is
# the strongest signal for that corner.
MOOD_CORNERS: dict[str, dict] = {
    "dark_energetic": {
        "pos": (0, 0),
        "tags": ["aggressive", "intense", "dark"],
    },
    "pos_energetic": {
        "pos": (100, 0),
        "tags": ["energetic", "happy", "dance"],
    },
    "dark_calm": {
        "pos": (0, 100),
        "tags": ["melancholy", "sad", "dark ambient"],
    },
    "pos_calm": {
        "pos": (100, 100),
        "tags": ["romantic", "calm", "acoustic"],
    },
}

# Minimum corner weight below which that corner's tags are excluded from
# the query — avoids spamming Last.fm with tags that have negligible
# influence on the final ranked pool.
MOOD_WEIGHT_THRESHOLD: float = 0.05

# ---------------------------------------------------------------------------
# Genre list — for the chip panel beside the mood map
# ---------------------------------------------------------------------------
# All genres are selected by default. User can deselect to narrow results.
# Genre tags are sent directly to Last.fm's tag.getTopTracks endpoint and
# are blended with the mood-tag candidates in core/recommender.py.
GENRES: list[str] = [
    "pop", "rock", "hip-hop", "jazz", "classical", "electronic",
    "r&b", "metal", "indie", "folk", "reggae", "blues", "soul",
    "punk", "country", "latin", "world", "ambient", "k-pop",
    "alternative", "funk", "house", "lo-fi", "afrobeats",
]

# ---------------------------------------------------------------------------
# Artist filter (disabled — open cross-artist discovery)
# ---------------------------------------------------------------------------
ARTIST_FILTER: str | None = None