"""
core/recommender.py

Orchestrates mood position + genre selection into a final ranked list
of Song objects for the UI bubble grid.

Two inputs drive every recommendation call:
    1. (x, y) drop position on the mood map → mood tags via bilinear
       interpolation (core/mood_map.py)
    2. selected_genres list → genre tags from the chip panel

When artist_filter is None (the default), both are sent to
services/lastfm_client.py's global tag charts and merged into one
deduped, ranked candidate pool:
    - Both active:    60% mood pool, 40% genre pool
    - Mood only:      100% mood pool
    - Genres only:    100% genre pool
    - Neither active: empty list (no results yet)

When artist_filter is set (see config.ARTIST_FILTER), the pipeline
flips entirely — see _get_artist_catalog and the two
_get_artist_filtered_* methods below for why and how.
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

# Small weight given to an artist-catalog song's own popularity rank,
# on top of its tag-overlap score. Keeps ranking sane when a song has
# thin/no tag overlap with the current selection, and gently
# tie-breaks among otherwise-equal matches. Deliberately small — tag
# overlap should dominate the ranking, popularity is just a tiebreaker.
_ARTIST_POPULARITY_WEIGHT = 0.05


class MusicRecommender:
    """
    Stateless-per-call orchestration over a LastFmClient, with one
    exception: when artist_filter is set, this class holds a lazily
    built, shared artist catalog as an instance attribute (see
    _get_artist_catalog). That's a deliberate, narrow exception to
    "no state held between calls" — the catalog is the same for every
    visitor (it's the artist's own tracks + tags, nothing user- or
    session-specific), and this class is already a single
    st.cache_resource-scoped instance shared across the whole deployed
    app (see app.py) — so building it once, here, is the correct
    scope, not a shortcut. Per-user data still belongs in
    core/cache.py's SessionCache, never here.
    """

    def __init__(
        self,
        lastfm_client: LastFmClient,
        mood_corners: dict[str, dict],
        mood_weight_threshold: float,
        bubble_count: int,
        artist_filter: str | None = None,
        artist_catalog_size: int = 50,
    ) -> None:
        self._lastfm_client = lastfm_client
        self._mood_corners = mood_corners
        self._mood_weight_threshold = mood_weight_threshold
        self._bubble_count = bubble_count
        self._artist_filter = artist_filter
        self._artist_catalog_size = artist_catalog_size
        self._artist_catalog: list[Song] | None = None

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
        if self._artist_filter:
            return self._get_artist_filtered_songs(x, y, selected_genres)

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
        if self._artist_filter:
            return self._get_artist_filtered_similar(played_song)

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
                tag_songs = self._lastfm_client.get_tracks_by_tag(match.tag.lower(), limit=per_tag_limit)
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
                genre_songs = self._lastfm_client.get_tracks_by_tag(genre.lower(), limit=per_genre_limit)
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

    # ------------------------------------------------------------------
    # Artist-filter path (config.ARTIST_FILTER)
    # ------------------------------------------------------------------
    # Querying Last.fm's global tag charts and then checking whether
    # any result happens to be by one specific artist would almost
    # always come back empty — a global "romantic" chart isn't going
    # to be dominated by any one artist. So instead: fetch the
    # artist's OWN catalog once, and rank THAT by tag overlap with
    # whatever the user selected. This guarantees every result is by
    # the filtered artist, by construction — there's no "filter step"
    # to get wrong, because nothing outside the catalog is ever
    # fetched in the first place.

    def _get_artist_catalog(self) -> list[Song]:
        """
        Build (on first call) or return (on every call after) the
        filtered artist's own top tracks, each enriched with its own
        Last.fm tags.

        This costs 1 + N Last.fm calls the first time it's needed
        (1 for the track list, up to N = artist_catalog_size for
        per-track tags) — a real, one-time latency hit on whichever
        request happens to trigger it first, paid once for the whole
        deployed app's lifetime (see this class's docstring for why
        that's the correct scope), never repeated after.

        A track that Last.fm has no tags for keeps an empty tags list
        and matched_by_mood=False — it still shows up (ranked by
        popularity alone, via _ARTIST_POPULARITY_WEIGHT), it just
        can't be matched by mood/genre specifically.
        """
        if self._artist_catalog is not None:
            return self._artist_catalog

        try:
            catalog = self._lastfm_client.get_artist_top_tracks(
                self._artist_filter, limit=self._artist_catalog_size
            )
        except (LastFmError, Exception):
            catalog = []

        for song in catalog:
            try:
                tags = self._lastfm_client.get_top_tags(song.artist, song.title)
            except (LastFmError, Exception):
                tags = []
            song.tags = [tag.lower() for tag in tags]
            song.matched_by_mood = bool(tags)

        self._artist_catalog = catalog
        return catalog

    def _get_artist_filtered_songs(
        self,
        x: float,
        y: float,
        selected_genres: list[str],
    ) -> list[Song]:
        """
        Rank the artist's catalog by weighted tag overlap with the
        resolved mood position and selected genres.

        Unlike the open-discovery path, this never returns an empty
        list just because nothing is selected — the whole point of an
        artist filter is that there's always something to show for
        this artist. With no mood/genre signal at all, songs are
        ranked by catalog popularity alone (every overlap score is 0,
        so the popularity bonus is all that's left to sort by).
        """
        catalog = self._get_artist_catalog()
        if not catalog:
            return []

        mood_tags = resolve_position_to_mood_tags(
            x=x,
            y=y,
            mood_corners=self._mood_corners,
            weight_threshold=self._mood_weight_threshold,
        )

        combined_weights: dict[str, float] = {}
        for match in mood_tags:
            tag = match.tag.lower()
            combined_weights[tag] = combined_weights.get(tag, 0.0) + match.weight

        if selected_genres:
            # Equal weight per selected genre, on the same 0-1 scale as
            # mood weights — mirrors how the open-discovery path treats
            # genres as a parallel signal alongside mood, not a filter
            # that overrides it.
            genre_weight = 1.0 / len(selected_genres)
            for genre in selected_genres:
                tag = genre.lower()
                combined_weights[tag] = combined_weights.get(tag, 0.0) + genre_weight

        scored: list[tuple[float, Song]] = []
        for song in catalog:
            overlap_score = sum(
                weight for tag, weight in combined_weights.items() if tag in song.tags
            )
            popularity_bonus = song.relevance_score * _ARTIST_POPULARITY_WEIGHT
            scored.append((overlap_score + popularity_bonus, song))

        scored.sort(key=lambda pair: pair[0], reverse=True)
        return [song for _, song in scored[: self._bubble_count]]

    def _get_artist_filtered_similar(self, played_song: Song) -> list[Song]:
        """
        Rank the artist's OTHER catalog songs by tag overlap with the
        one just played — an in-catalog stand-in for Last.fm's
        track.getSimilar, which is cross-artist by design and would
        defeat the whole point of the filter (see this section's
        top-level comment).
        """
        catalog = self._get_artist_catalog()
        if not catalog:
            return []

        played_key = played_song.identity_key()
        played_tags = set(played_song.tags)

        scored: list[tuple[float, Song]] = []
        for song in catalog:
            if song.identity_key() == played_key:
                continue
            overlap = len(played_tags & set(song.tags))
            popularity_bonus = song.relevance_score * _ARTIST_POPULARITY_WEIGHT
            scored.append((overlap + popularity_bonus, song))

        scored.sort(key=lambda pair: pair[0], reverse=True)
        return [song for _, song in scored[: self._bubble_count]]