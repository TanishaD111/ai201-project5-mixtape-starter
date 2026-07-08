"""
reproduce_bug4.py — Reproduce Bug #4: no notification when a friend RATES your song.

Run:  python reproduce_bug4.py

When a friend rates a song you shared, you should get a notification (just like
you do when they add it to a playlist). rate_song() never creates one.
"""
from app import create_app, db
from models import User, Song
from services.notification_service import rate_song, get_notifications

app = create_app({"TESTING": True, "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:"})

with app.app_context():
    db.create_all()

    sharer = User(username="sharer", email="sharer@example.com")
    friend = User(username="friend", email="friend@example.com")
    db.session.add_all([sharer, friend])
    db.session.flush()

    song = Song(title="My Track", artist="Me", shared_by=sharer.id)
    db.session.add(song)
    db.session.commit()

    before = get_notifications(sharer.id)
    print(f"Before: sharer has {len(before)} notification(s).")

    # Friend rates the sharer's song
    rate_song(friend.id, song.id, 5)

    after = get_notifications(sharer.id)
    print(f"After friend rated the song 5/5: sharer has {len(after)} notification(s).")

    print()
    if len(after) > len(before):
        print("PASS — rating produced a notification. Bug is not present.")
    else:
        print("BUG REPRODUCED — rating the shared song produced NO notification for the sharer.")
