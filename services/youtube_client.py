"""
services/youtube_client.py

Resolves a (artist, title) pair to a playable YouTube video ID, via the
YouTube Data API v3 search endpoint. This is the only source in the app
that plays full songs (see project notes on why Spotify/Deezer/Apple
can't do this for free).

Deliberately NOT called for all 10 bubbles up front — app.py / ui/bubble_grid.py
call resolve_video_id() only when the user actually clicks PLAY on a
specific song, and core/cache.py memoizes the result for the rest of the
session so the same song is never looked up twice. This is what keeps
usage far under the free tier's 10,000 quota units/day (a single search
costs 100 units — see config.Settings.youtube_daily_search_budget).
"""

import requests

_SEARCH_URL = "https://www.googleapis.com/youtube/v3/search"
_TIMEOUT_SECONDS = 8
_QUOTA_COST_PER_SEARCH = 100


class YouTubeQuotaExceededError(Exception):
    """
    Raised when this client's own soft budget (config.Settings.youtube_daily_search_budget)
    is exhausted for the current app session.

    This is a client-side safety margin, not the real Google-enforced
    quota — the in-memory counter resets whenever the app process
    restarts, so it approximates "per day" rather than guaranteeing it.
    If usage ever grows enough for that gap to matter, the fix is a
    persisted counter (e.g. a small SQLite row keyed by date) rather than
    anything in this file.
    """


class YouTubeClient:
    """
    Client for resolving playable video IDs, with a built-in soft cap on
    how many searches it will issue in the lifetime of this instance.
    """

    def __init__(self, api_key: str, daily_search_budget: int) -> None:
        self._api_key = api_key
        self._daily_search_budget = daily_search_budget
        self._searches_used = 0

    @property
    def searches_remaining(self) -> int:
        """How many more searches this instance will allow before refusing."""
        return max(0, self._daily_search_budget - self._searches_used)

    def resolve_video_id(self, artist: str, title: str) -> str | None:
        """
        Search YouTube for the given (artist, title) and return the top
        matching video's ID, or None if nothing usable was found.

        Callers should treat None as "couldn't find a playable version of
        this song" and handle it in the UI (e.g. disable PLAY, show a
        short message) rather than crashing the bubble grid.

        Raises YouTubeQuotaExceededError if this instance's soft budget
        is already used up — callers should catch this and surface a
        clear "search budget reached for now" message rather than letting
        Google's own 403 bubble up as a raw error.
        """
        if self._searches_used >= self._daily_search_budget:
            raise YouTubeQuotaExceededError(
                f"YouTube search budget ({self._daily_search_budget} searches) "
                f"used up for this session."
            )

        query = f"{artist} {title} official audio"
        params = {
            "part": "snippet",
            "q": query,
            "type": "video",
            "maxResults": 1,
            "key": self._api_key,
        }

        response = requests.get(_SEARCH_URL, params=params, timeout=_TIMEOUT_SECONDS)
        self._searches_used += 1  # count the attempt even on a bad response —
        # the quota unit was still spent on Google's side either way.
        response.raise_for_status()

        items = response.json().get("items", [])
        if not items:
            return None

        return items[0].get("id", {}).get("videoId")

    def build_embed_url(self, video_id: str, autoplay: bool = True) -> str:
        """
        Build a YouTube embed URL for the given video ID, suitable for
        dropping into an <iframe src="..."> in ui/bubble_grid.py via
        st.components.v1.html or st.video().

        No JavaScript is required — autoplay, controls, and start position
        are all driven by URL query parameters, which YouTube's embed
        player reads and handles internally.
        """
        autoplay_flag = "1" if autoplay else "0"
        return (
            f"https://www.youtube.com/embed/{video_id}"
            f"?autoplay={autoplay_flag}&rel=0"
        )