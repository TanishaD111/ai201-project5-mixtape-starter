"""
reproduce_bug5.py — Reproduce Bug #5: the last song in a playlist never shows up.

Run:  python reproduce_bug5.py

A playlist is built with 5 songs. get_playlist_songs should return all 5,
but the bug drops the final one.
"""
from app import create_app, db
from models import User, Song, Playlist, playlist_entries
from services.playlist_service import get_playlist_songs

app = create_app({"TESTING": True, "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:"})

with app.app_context():
    db.create_all()

    user = User(username="dj", email="dj@example.com")
    db.session.add(user)
    db.session.flush()

    songs = [Song(title=f"Track {i}", artist="Various", shared_by=user.id) for i in range(1, 6)]
    db.session.add_all(songs)
    db.session.flush()

    playlist = Playlist(name="My Playlist", created_by=user.id)
    db.session.add(playlist)
    db.session.flush()

    for i, song in enumerate(songs):
        db.session.execute(
            playlist_entries.insert().values(
                playlist_id=playlist.id, song_id=song.id, position=i + 1, added_by=user.id
            )
        )
    db.session.commit()

    result = get_playlist_songs(playlist.id)
    print(f"Playlist has 5 songs. get_playlist_songs returned {len(result)}:")
    print("  " + ", ".join(s["title"] for s in result))

    print()
    if len(result) == 5:
        print("PASS — all 5 songs returned. Bug is not present.")
    else:
        print(f"BUG REPRODUCED — only {len(result)} of 5 songs returned; "
              f"the last one ('Track 5') is missing.")
