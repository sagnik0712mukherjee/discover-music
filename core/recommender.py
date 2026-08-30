"""
core/recommender.py

The orchestrator that turns a drop position (or a "play this song"
event) into the final list of Song objects the UI renders as bubbles.

This is the only module that combines core/mood_map.py's geometry with
services/lastfm_client.py's data — ui/bubble_grid.py and app.py should
only ever talk to MusicRecommender, never to LastFmClient directly, so
the merge/dedupe/fallback rules stay in exactly one place.
"""

from core.mood_map import TagMatch, resolve_position_to_tags
from models.song import Song
from services.lastfm_client import LastFmClient, LastFmError

# How large a candidate pool to pull per tag before ranking down to the
# final bubble count. Pulling more than we need gives dedup/ranking room
# to work with, rather than locking in whatever the first N results were.
_CANDIDATE_POOL_MULTIPLIER = 3


class MusicRecommender:
    """
    Stateless orchestration over a LastFmClient. Holds no song data
    itself between calls — every method fetches live, per the app's
    "don't store a catalog" requirement. Callers (app.py) are expected
    to hold the *returned* Song lists in Streamlit session state for the
    duration of a single render, not this class.
    """

    def __init__(
        self,
        lastfm_client: LastFmClient,
        anchor_tags: dict[str, tuple[int, int]],
        genre_tags: dict[str, tuple[int, int]],
        bubble_count: int,
        nearest_tag_count: int,
    ) -> None:
        self._lastfm_client = lastfm_client
        self._anchor_tags = anchor_tags
        self._genre_tag_names = set(genre_tags.keys())
        self._bubble_count = bubble_count
        self._nearest_tag_count = nearest_tag_count

    def get_songs_for_position(self, x: float, y: float) -> list[Song]:
        """
        Resolve a drop position to songs: nearest anchor tags → weighted
        Last.fm lookups per tag → merged, deduped, ranked pool → genre-only
        fallback if that pool comes up short → top `bubble_count` Songs.
        """
        tag_matches = resolve_position_to_tags(
            x=x,
            y=y,
            anchor_tags=self._anchor_tags,
            nearest_tag_count=self._nearest_tag_count,
        )

        pool = self._collect_weighted_candidates(tag_matches)

        if len(pool) < self._bubble_count:
            self._fill_with_genre_fallback(pool, tag_matches)

        ranked = sorted(pool.values(), key=lambda song: song.relevance_score, reverse=True)
        return ranked[: self._bubble_count]

    def get_similar_songs(self, played_song: Song) -> list[Song]:
        """
        Fetch songs similar to the one the user just clicked PLAY on —
        these are what replace the 9 bubbles that disappear.

        Returns an empty list (rather than raising) if Last.fm has no
        similarity data for this track or the call fails — the UI should
        treat that as "no similar songs found" rather than an error state,
        since a song having no similarity data is a normal, expected case.
        """
        try:
            candidates = self._lastfm_client.get_similar_tracks(
                artist=played_song.artist,
                title=played_song.title,
                limit=self._bubble_count * _CANDIDATE_POOL_MULTIPLIER,
            )
        except (LastFmError, Exception):
            return []

        played_key = played_song.identity_key()
        deduped: dict[str, Song] = {}
        for candidate in candidates:
            key = candidate.identity_key()
            if key == played_key or key in deduped:
                continue
            deduped[key] = candidate

        ranked = sorted(deduped.values(), key=lambda song: song.relevance_score, reverse=True)
        return ranked[: self._bubble_count]

    def _collect_weighted_candidates(self, tag_matches: list[TagMatch]) -> dict[str, Song]:
        """
        Query Last.fm once per resolved tag, sized proportionally to that
        tag's weight, and merge results into one deduped pool keyed by
        Song.identity_key(). A song's relevance_score is boosted by the
        tag weight it was found under, so a strong match on a
        heavily-weighted tag outranks a weak match on a lightly-weighted
        one.
        """
        pool: dict[str, Song] = {}

        for match in tag_matches:
            per_tag_limit = max(5, round(match.weight * self._bubble_count * _CANDIDATE_POOL_MULTIPLIER))
            try:
                tag_songs = self._lastfm_client.get_tracks_by_tag(match.tag, limit=per_tag_limit)
            except (LastFmError, Exception):
                # One tag failing (rate limit, transient network issue)
                # shouldn't blank out the whole result — continue with
                # whatever other tags succeed.
                continue

            for song in tag_songs:
                song.relevance_score = song.relevance_score * match.weight
                key = song.identity_key()
                if key in pool:
                    # Song matched under more than one resolved tag —
                    # that's a stronger signal, not a duplicate to discard.
                    pool[key].relevance_score += song.relevance_score
                    pool[key].tags.extend(song.tags)
                else:
                    pool[key] = song

        return pool

    def _fill_with_genre_fallback(self, pool: dict[str, Song], tag_matches: list[TagMatch]) -> None:
        """
        Mutates `pool` in place, adding more songs when the weighted
        mood-tag pool came up short of bubble_count.

        Per the app's stated behavior: a song with thin/no mood-tag data
        should still be shown, placed by genre only. This widens the
        search using the nearest *genre* tag among the resolved matches
        (falling back to the single nearest tag overall if none of the
        resolved matches happen to be a genre), and marks anything added
        this way as matched_by_mood=False so the UI can distinguish it
        later if needed.
        """
        genre_match = next(
            (match for match in tag_matches if match.tag in self._genre_tag_names),
            tag_matches[0],  # no genre among the resolved matches — use nearest overall
        )

        needed = self._bubble_count - len(pool)
        try:
            fallback_songs = self._lastfm_client.get_tracks_by_tag(
                genre_match.tag,
                limit=needed * _CANDIDATE_POOL_MULTIPLIER,
            )
        except (LastFmError, Exception):
            return

        for song in fallback_songs:
            key = song.identity_key()
            if key in pool:
                continue
            song.matched_by_mood = False
            pool[key] = song
            if len(pool) >= self._bubble_count:
                break