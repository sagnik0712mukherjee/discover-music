"""
models/song.py

Defines Song, the single shared representation of a track that flows
through the whole app: services/lastfm_client.py and services/spotify_client.py
produce them, core/recommender.py filters and orders them, services/youtube_client.py
attaches playback info to them, and ui/bubble_grid.py renders them.

Keeping one canonical Song shape here means no other module needs to know
the raw response format of Last.fm, Spotify, or YouTube — each client is
responsible for translating its own API response into a Song before
handing data off.
"""

from dataclasses import dataclass, field


@dataclass
class Song:
    """
    A single track, normalized across whichever source(s) supplied it.

    Fields are deliberately optional/defaulted where a given data source
    doesn't provide them, so a Song can be built incrementally: e.g.
    created from a Last.fm tag lookup with no video_id yet, then enriched
    with a video_id only once the user actually clicks PLAY (see the lazy
    YouTube resolution strategy in config.py / services/youtube_client.py).
    """

    title: str
    artist: str

    # Tags this song is known to carry (e.g. "sufi", "romantic"), as
    # returned by Last.fm. Empty if the song came from a source with no
    # tag data (e.g. a Spotify new-release lookup with no Last.fm match yet).
    tags: list[str] = field(default_factory=list)

    # True if this song had genuine mood-tag data behind its placement on
    # the map, versus being shown via the genre-only fallback because it's
    # too new or too niche to have accumulated mood tags on Last.fm.
    matched_by_mood: bool = True

    # Populated lazily: None until services/youtube_client.py resolves a
    # video ID for this exact song, which only happens when the user
    # clicks PLAY (see config.Settings.youtube_daily_search_budget).
    video_id: str | None = None

    # Popularity/relevance signal carried through from whichever source
    # ranked this song (e.g. Last.fm's tag-count or match score). Used by
    # core/recommender.py to order bubbles; not shown directly in the UI.
    relevance_score: float = 0.0

    # Which source(s) contributed to this Song, e.g. ["lastfm", "spotify"].
    # Useful for debugging why a particular song showed up.
    sources: list[str] = field(default_factory=list)

    def display_name(self) -> str:
        """Human-readable 'Artist – Title' string for bubble labels."""
        return f"{self.artist} – {self.title}"

    def identity_key(self) -> str:
        """
        Lowercase (artist, title) key used for deduplication when merging
        candidates from multiple tags or multiple sources. Last.fm and
        Spotify won't always agree on exact casing/punctuation, so this
        key is intentionally loose (normalized case, stripped whitespace)
        rather than doing an exact string match.
        """
        return f"{self.artist.strip().lower()}::{self.title.strip().lower()}"