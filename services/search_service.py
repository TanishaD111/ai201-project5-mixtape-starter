"""
services/search_service.py — Mixtape

Handles song search logic.
"""

from app import db
from models import Song, Tag, song_tags


def search_songs(query: str) -> list[dict]:
    """
    Search for songs by title or artist name.

    Returns all songs where the title or artist contains the query string
    (case-insensitive), along with their associated tags.

    Args:
        query: The search string to match against title and artist fields.

    Returns:
        A list of song dicts. Each dict includes all song fields plus a
        'tags' list of tag name strings.
    """
    results = (
        db.session.query(Song)
        # BUG #3 FIX: the outer join to song_tags produced one row per tag (a fan-out),
        # so a song with 3 tags matched 3 times. The join is unnecessary — search filters
        # only on title/artist, and tags are loaded via the Song.tags relationship inside
        # to_dict(). Removing the join returns exactly one row per matching song.
        # .outerjoin(song_tags, Song.id == song_tags.c.song_id)
        .filter(
            db.or_(
                Song.title.ilike(f"%{query}%"),
                Song.artist.ilike(f"%{query}%"),
            )
        )
        .all()
    )

    return [song.to_dict() for song in results]


def get_song(song_id: str) -> dict:
    """
    Get a single song by ID.

    Args:
        song_id: The UUID of the song.

    Returns:
        A song dict, or raises ValueError if not found.
    """
    song = db.session.get(Song, song_id)
    if not song:
        raise ValueError(f"Song {song_id} not found")
    return song.to_dict()
