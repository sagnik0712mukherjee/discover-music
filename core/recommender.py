"""
core/recommender.py

Orchestrates mood position + genre selection into a final ranked list
of Song objects for the UI bubble grid.

Two inputs drive every recommendation call:
    1. (x, y) drop position on the mood map → mood tags via bilinear
       interpolation (core/mood_map.py)
    2. selected_genres list → genre tags from the chip panel

Both are sent to services/lastfm_client.py and merged into one deduped,
ranked candidate pool. The split between mood and genre candidates is:
    - Both active:    60% mood pool, 40% genre pool
    - Mood only:      100% mood pool
    - Genres only:    100% genre pool
    - Neither active: empty list (no results yet)
"""

from core.mood_map import TagMatch, resolve_position_to_mood_tags
from models.song import Song
from services.lastfm_client import LastFmClient, LastFmError

# Pull this many × bubble_count candidates per tag before ranking down
# to the final bubble count. Gives dedupe/ranking room to work with.
_CANDIDATE_POOL_MULTIPLIER = 3

# When both mood and genre signals are active, mood gets this share of
# the total candidate pool; genres get the remainder.
_MOOD_SHARE = 0.6


class MusicRecommender:
    """
    Stateless orchestration over a LastFmClient.

    No song data is held between calls — every call fetches live from
    Last.fm. Callers (app.py) hold the returned Song lists in Streamlit
    session state for the duration of a single render.
    """

    def __init__(
        self,
        lastfm_client: LastFmClient,
        mood_corners: dict[str, dict],
        mood_weight_threshold: float,
        bubble_count: int,
    ) -> None:
        self._lastfm_client = lastfm_client
        self._mood_corners = mood_corners
        self._mood_weight_threshold = mood_weight_threshold
        self._bubble_count = bubble_count

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get_songs_for_position(
        self,
        x: float,
        y: float,
        selected_genres: list[str],
    ) -> list[Song]:
        """
        Resolve a drop position + genre selection to a ranked Song list.

        Parameters
        ----------
        x, y : float
            Circle position on the 0-100 mood map grid.
        selected_genres : list[str]
            Genre names checked in the genre panel. Empty list = no
            genre filter (mood only). None of the genres selected
            effectively means mood-only mode.
        """
        mood_tags = resolve_position_to_mood_tags(
            x=x,
            y=y,
            mood_corners=self._mood_corners,
            weight_threshold=self._mood_weight_threshold,
        )

        has_mood = bool(mood_tags)
        has_genres = bool(selected_genres)

        if not has_mood and not has_genres:
            return []

        total_pool = self._bubble_count * _CANDIDATE_POOL_MULTIPLIER

        if has_mood and has_genres:
            mood_pool_size = round(total_pool * _MOOD_SHARE)
            genre_pool_size = total_pool - mood_pool_size
        elif has_mood:
            mood_pool_size = total_pool
            genre_pool_size = 0
        else:
            mood_pool_size = 0
            genre_pool_size = total_pool

        pool: dict[str, Song] = {}

        if has_mood and mood_pool_size > 0:
            pool = self._collect_mood_candidates(mood_tags, mood_pool_size)

        if has_genres and genre_pool_size > 0:
            self._collect_genre_candidates(selected_genres, genre_pool_size, pool)

        ranked = sorted(pool.values(), key=lambda s: s.relevance_score, reverse=True)
        return ranked[: self._bubble_count]

    def get_similar_songs(self, played_song: Song) -> list[Song]:
        """
        Fetch songs similar to the one the user clicked PLAY on.

        Returns an empty list (rather than raising) if Last.fm has no
        similarity data — the UI treats this as 'no similar songs found'.
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

        ranked = sorted(deduped.values(), key=lambda s: s.relevance_score, reverse=True)
        return ranked[: self._bubble_count]

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _collect_mood_candidates(
        self,
        mood_tags: list[TagMatch],
        total_mood_slots: int,
    ) -> dict[str, Song]:
        """
        Query Last.fm once per mood tag, sized proportionally to that
        tag's weight, and return a deduped pool.

        A song appearing under multiple mood tags gets its relevance_score
        boosted — matching under more than one tag is a stronger signal.
        """
        pool: dict[str, Song] = {}

        for match in mood_tags:
            per_tag_limit = max(5, round(match.weight * total_mood_slots))
            try:
                tag_songs = self._lastfm_client.get_tracks_by_tag(match.tag, limit=per_tag_limit)
            except (LastFmError, Exception):
                continue

            for song in tag_songs:
                song.relevance_score *= match.weight
                key = song.identity_key()
                if key in pool:
                    pool[key].relevance_score += song.relevance_score
                    pool[key].tags.extend(song.tags)
                else:
                    pool[key] = song

        return pool

    def _collect_genre_candidates(
        self,
        genres: list[str],
        total_genre_slots: int,
        pool: dict[str, Song],
    ) -> None:
        """
        Mutates `pool` in place, adding songs from the selected genres.

        Slots are distributed equally across selected genres. Songs
        already in the pool (from mood tags) get their relevance_score
        boosted instead of being added as duplicates — genre overlap
        with mood is an additional positive signal.
        """
        if not genres:
            return

        per_genre_limit = max(5, round(total_genre_slots / len(genres)))
        genre_weight = 1.0 / len(genres)  # equal weight per genre

        for genre in genres:
            try:
                genre_songs = self._lastfm_client.get_tracks_by_tag(genre, limit=per_genre_limit)
            except (LastFmError, Exception):
                continue

            for song in genre_songs:
                song.relevance_score *= genre_weight
                key = song.identity_key()
                if key in pool:
                    # Already in pool from mood tags — boost its score.
                    pool[key].relevance_score += song.relevance_score * 0.5
                    if genre not in pool[key].tags:
                        pool[key].tags.append(genre)
                else:
                    song.matched_by_mood = False  # came from genre, not mood position
                    pool[key] = song