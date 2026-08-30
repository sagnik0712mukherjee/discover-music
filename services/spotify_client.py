"""
services/spotify_client.py

Narrow-scope Spotify wrapper. This app does NOT use Spotify for playback,
audio features, or recommendations — those free endpoints are dead (see
project notes). The one thing Spotify's free API is still good for is
being the fastest place to learn a brand-new release exists, before
Last.fm's crowd-sourced tags have caught up to it.

Uses the Client Credentials flow: no end-user login, just this app's own
client ID/secret authenticating as itself. That's enough for Search and
New Releases, which is all this file touches.
"""

import time

import requests

from models.song import Song

_TOKEN_URL = "https://accounts.spotify.com/api/token"
_NEW_RELEASES_URL = "https://api.spotify.com/v1/browse/new-releases"
_TIMEOUT_SECONDS = 8


class SpotifyClient:
    """
    Minimal Client Credentials client, scoped to new-release discovery.

    Access tokens from this flow are short-lived (Spotify typically issues
    ~1 hour tokens). This class fetches one lazily on first use and
    re-fetches automatically once it expires — callers never need to
    think about tokens at all.
    """

    def __init__(self, client_id: str, client_secret: str) -> None:
        self._client_id = client_id
        self._client_secret = client_secret
        self._access_token: str | None = None
        self._token_expires_at: float = 0.0

    def _ensure_token(self) -> str:
        """Return a valid access token, fetching a fresh one if needed."""
        if self._access_token and time.time() < self._token_expires_at:
            return self._access_token

        response = requests.post(
            _TOKEN_URL,
            data={"grant_type": "client_credentials"},
            auth=(self._client_id, self._client_secret),
            timeout=_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        payload = response.json()

        self._access_token = payload["access_token"]
        # Subtract a small buffer so we refresh a little early rather than
        # risking a request landing right on the expiry boundary.
        self._token_expires_at = time.time() + payload.get("expires_in", 3600) - 30
        return self._access_token

    def get_new_releases(self, limit: int = 20) -> list[Song]:
        """
        Fetch Spotify's currently-featured new album releases and flatten
        them into Song entries (one per album, using the album's primary
        artist — good enough for the "does this exist yet" freshness
        check this method exists for, not meant to be track-accurate).

        These Songs come back with matched_by_mood=False and empty tags,
        since Spotify has no mood-tag data to offer for free anymore —
        core/recommender.py is responsible for deciding whether/how to
        blend these into results (per the genre-only fallback rule).
        """
        token = self._ensure_token()
        response = requests.get(
            _NEW_RELEASES_URL,
            headers={"Authorization": f"Bearer {token}"},
            params={"limit": str(limit)},
            timeout=_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        albums = response.json().get("albums", {}).get("items", [])

        songs: list[Song] = []
        for album in albums:
            artists = album.get("artists", [])
            artist_name = artists[0]["name"] if artists else "Unknown Artist"
            songs.append(
                Song(
                    title=album.get("name", "Unknown Title"),
                    artist=artist_name,
                    tags=[],
                    matched_by_mood=False,
                    sources=["spotify"],
                )
            )
        return songs