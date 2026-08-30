"""
core/cache.py

A plain-Python, framework-agnostic cache for the three things this app
would otherwise re-fetch needlessly within a single user session:

    1. song -> resolved YouTube video_id   (avoids re-spending YouTube quota)
    2. tag -> Last.fm top-tracks result     (avoids re-hitting Last.fm if the
                                              user drags back near a tag
                                              they've already visited)
    3. played song -> similar-tracks result (avoids re-fetching if the same
                                              song is clicked again)

Deliberately has no dependency on Streamlit. app.py is responsible for
creating exactly one SessionCache and storing it in st.session_state, so
it lives for the duration of one user's browser session and is thrown
away when that session ends — this is intentionally NOT the persistent
catalog the app's requirements explicitly rule out; it never touches
disk and holds nothing once the session is gone.
"""

from models.song import Song


class SessionCache:
    """
    In-memory cache, scoped to one Streamlit session by whoever holds
    the instance (see app.py). Every method is a simple get/set — no
    expiry logic, since the natural lifetime of a Streamlit session
    (closed tab, refresh clears session_state) already bounds how long
    anything here can live.
    """

    def __init__(self) -> None:
        self._video_ids: dict[str, str] = {}
        self._tag_tracks: dict[str, list[Song]] = {}
        self._similar_tracks: dict[str, list[Song]] = {}

    # -- video ID cache ----------------------------------------------------

    def get_video_id(self, song: Song) -> str | None:
        """Return a previously resolved video_id for this song, if any."""
        return self._video_ids.get(song.identity_key())

    def set_video_id(self, song: Song, video_id: str) -> None:
        """Remember a resolved video_id so this song is never re-searched."""
        self._video_ids[song.identity_key()] = video_id

    # -- tag -> tracks cache -------------------------------------------------

    def get_tag_tracks(self, tag: str) -> list[Song] | None:
        """Return a previously fetched track list for this tag, if any."""
        return self._tag_tracks.get(tag)

    def set_tag_tracks(self, tag: str, songs: list[Song]) -> None:
        """Remember a tag's track list for the rest of this session."""
        self._tag_tracks[tag] = songs

    # -- similar-tracks cache -------------------------------------------------

    def get_similar_tracks(self, song: Song) -> list[Song] | None:
        """Return a previously fetched similar-tracks list for this song, if any."""
        return self._similar_tracks.get(song.identity_key())

    def set_similar_tracks(self, song: Song, similar_songs: list[Song]) -> None:
        """Remember a song's similar-tracks list for the rest of this session."""
        self._similar_tracks[song.identity_key()] = similar_songs