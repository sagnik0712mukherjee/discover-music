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
# Anchor tag map
# ---------------------------------------------------------------------------
# Coordinates are normalized to a 0-100 grid on both axes, matching the
# canvas size ui/map_widget.py will render. Genre words and mood words are
# deliberately interleaved rather than split into strict quadrants — the
# product idea is a single "mash map" a user can drop a circle anywhere on,
# not two separate genre/mood axes.
#
# This list is intentionally small for the MVP. Extending coverage later
# (more genres, more moods, regional/world-music terms) means adding an
# entry here — no other file needs to change.
GENRE_TAGS: dict[str, tuple[int, int]] = {
    "rock": (15, 80),
    "pop": (75, 85),
    "sufi": (20, 20),
    "classical": (10, 50),
    "jazz": (35, 60),
    "electronic": (85, 60),
    "folk": (25, 35),
    "hip hop": (70, 70),
    "indie": (50, 75),
    "metal": (10, 90),
    "qawwali": (15, 15),
    "ghazal": (25, 25),
}

MOOD_TAGS: dict[str, tuple[int, int]] = {
    "dark": (15, 10),
    "romantic": (40, 15),
    "happy": (80, 30),
    "melancholy": (20, 45),
    "energetic": (85, 80),
    "calm": (45, 40),
    "nostalgic": (30, 55),
    "uplifting": (70, 20),
    "moody": (12, 35),
    "dreamy": (55, 30),
}

# Combined map, kept for anything that just wants "all anchors" without
# caring about the genre/mood distinction — e.g. core/mood_map.py's
# nearest-tag resolution, and ui/map_widget.py's label rendering.
# GENRE_TAGS and MOOD_TAGS are the source of truth; this is derived.
ANCHOR_TAGS: dict[str, tuple[int, int]] = {**GENRE_TAGS, **MOOD_TAGS}