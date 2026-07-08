"""
reproduce_bug5.py — Reproduce Bug #5: the last song in a playlist never shows up.

Run:  python reproduce_bug5.py

Scenario (from the issue report): the "Friday Energy" playlist has 7 songs but only
6 show, and the missing one is always the most recently added. Adding one more song
"frees" the previously-missing song and hides the new one instead. This script
reproduces both halves: fetch a 7-song playlist (expect 7), then add an 8th and
re-fetch (expect 8).
"""
from app import create_app, db
from models import User, Song, Playlist, playlist_entries
from services.playlist_service import get_playlist_songs

app = create_app({"TESTING": True, "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:"})

with app.app_context():
    db.create_all()

    darius = User(username="darius", email="darius@example.com")
    db.session.add(darius)
    db.session.flush()

    playlist = Playlist(name="Friday Energy", created_by=darius.id)
    db.session.add(playlist)
    db.session.flush()

    def add_song(title, position):
        song = Song(title=title, artist="Various", shared_by=darius.id)
        db.session.add(song)
        db.session.flush()
        db.session.execute(
            playlist_entries.insert().values(
                playlist_id=playlist.id, song_id=song.id, position=position, added_by=darius.id
            )
        )
        db.session.commit()

    # Build the 7-song playlist.
    for i in range(1, 8):
        add_song(f"Song {i}", i)

    first = get_playlist_songs(playlist.id)
    print(f"Playlist has 7 songs. get_playlist_songs returned {len(first)}:")
    print("  " + ", ".join(s["title"] for s in first))

    # simone adds an 8th song — the report says this should "free" Song 7.
    add_song("Song 8", 8)
    second = get_playlist_songs(playlist.id)
    print(f"\nAfter adding Song 8, playlist has 8 songs. Returned {len(second)}:")
    print("  " + ", ".join(s["title"] for s in second))

    print()
    if len(first) == 7 and len(second) == 8:
        print("PASS — every song is returned, including the most recently added.")
    else:
        missing_first = 7 - len(first)
        print(f"BUG REPRODUCED — {missing_first} song missing from the 7-song playlist "
              f"(the last-added 'Song 7'), and after adding 'Song 8' it is now the one hidden.")
