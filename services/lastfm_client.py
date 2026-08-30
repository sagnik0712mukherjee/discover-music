"""
services/lastfm_client.py

Thin wrapper around the Last.fm API (https://www.last.fm/api). This is the
app's primary source of genre/mood signal and "more like this" data — the
two things Spotify's free API no longer provides (see project notes).

All methods here are read-only and require no user authentication, only
an API key (see config.load_settings().lastfm_api_key). Every method
returns models.song.Song objects, not raw Last.fm JSON, so the rest of
the app never needs to know Last.fm's response shape.

Network calls are intentionally simple synchronous `requests` calls —
Streamlit's execution model reruns the script top-to-bottom on every
interaction, so there is no long-lived event loop to hang async calls off
of. Callers are expected to use core/cache.py to avoid re-issuing the
same call within a session.
"""

import requests

from models.song import Song

_BASE_URL = "https://ws.audioscrobbler.com/2.0/"
_TIMEOUT_SECONDS = 8


class LastFmError(Exception):
    """Raised when Last.fm's API returns an error payload (its 'error' field)."""


class LastFmClient:
    """
    Client for the small slice of the Last.fm API this app needs.

    One instance is created at app startup (see app.py) with the API key
    from config.Settings, then reused for every request during the
    session — Last.fm's API key is not a secret that needs re-fetching
    per call.
    """

    def __init__(self, api_key: str) -> None:
        self._api_key = api_key

    def _get(self, method: str, params: dict[str, str]) -> dict:
        """
        Issue a single GET request to the Last.fm API and return the
        parsed JSON body.

        Raises LastFmError if Last.fm responds with an error payload
        (e.g. rate limit, invalid params), or requests.RequestException
        if the network call itself fails — callers should be prepared to
        catch either, since a Last.fm outage shouldn't crash the whole
        Streamlit page (see core/recommender.py for how failures are
        absorbed and surfaced as "no results" rather than a stack trace).
        """
        query = {
            "method": method,
            "api_key": self._api_key,
            "format": "json",
            **params,
        }
        response = requests.get(_BASE_URL, params=query, timeout=_TIMEOUT_SECONDS)
        response.raise_for_status()
        payload = response.json()

        if "error" in payload:
            raise LastFmError(
                f"Last.fm error {payload['error']}: {payload.get('message', 'unknown error')}"
            )
        return payload

    def get_tracks_by_tag(self, tag: str, limit: int = 30) -> list[Song]:
        """
        Fetch the top tracks Last.fm users have tagged with `tag`
        (e.g. "romantic", "sufi"), ordered by tag count.

        This is the primary call behind core/mood_map.py's resolution of
        a dropped map position into actual songs: once a position resolves
        to one or more anchor tags, this method is called once per tag and
        the results are merged/deduped by core/recommender.py.
        """
        payload = self._get(
            "tag.gettoptracks",
            {"tag": tag, "limit": str(limit)},
        )
        raw_tracks = payload.get("tracks", {}).get("track", [])

        songs: list[Song] = []
        for raw in raw_tracks:
            artist_name = raw.get("artist", {}).get("name", "Unknown Artist")
            songs.append(
                Song(
                    title=raw.get("name", "Unknown Title"),
                    artist=artist_name,
                    tags=[tag],
                    matched_by_mood=True,
                    relevance_score=float(raw.get("@attr", {}).get("rank", 0) or 0),
                    sources=["lastfm"],
                )
            )
        return songs

    def get_similar_tracks(self, artist: str, title: str, limit: int = 30) -> list[Song]:
        """
        Fetch tracks Last.fm considers similar to (artist, title), based
        on real listening data — the free replacement for Spotify's
        deprecated Recommendations/Related Artists endpoints.

        Called when the user clicks PLAY on a bubble, to populate the
        songs that replace the 9 that disappear.
        """
        payload = self._get(
            "track.getsimilar",
            {"artist": artist, "track": title, "limit": str(limit)},
        )
        raw_tracks = payload.get("similartracks", {}).get("track", [])

        songs: list[Song] = []
        for raw in raw_tracks:
            artist_name = raw.get("artist", {}).get("name", "Unknown Artist")
            songs.append(
                Song(
                    title=raw.get("name", "Unknown Title"),
                    artist=artist_name,
                    matched_by_mood=False,  # similarity-based, not tag-position-based
                    relevance_score=float(raw.get("match", 0) or 0),
                    sources=["lastfm"],
                )
            )
        return songs

    def get_top_tags(self, artist: str, title: str, limit: int = 10) -> list[str]:
        """
        Fetch the top user-supplied tags for a specific (artist, title).

        Used by core/recommender.py to check whether a song has enough
        genuine mood-tag coverage to be "matched_by_mood=True", versus
        falling back to genre-only placement for thin/untagged tracks
        (new releases, niche genres) per the app's stated fallback rule.
        """
        payload = self._get(
            "track.gettoptags",
            {"artist": artist, "track": title},
        )
        raw_tags = payload.get("toptags", {}).get("tag", [])
        return [raw.get("name", "") for raw in raw_tags[:limit] if raw.get("name")]