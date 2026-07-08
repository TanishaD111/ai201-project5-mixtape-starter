"""
reproduce_bug2.py — Reproduce Bug #2: "Friends Listening Now" shows people from yesterday.

Run:  python reproduce_bug2.py

A friend listens ~23 hours ago. Because the feed's RECENT_THRESHOLD is 24 hours,
that stale listen still shows up in the "listening NOW" feed.
"""
from datetime import datetime, timezone, timedelta
from app import create_app, db
from models import User, Song, ListeningEvent
from services.feed_service import get_friends_listening_now

app = create_app({"TESTING": True, "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:"})

with app.app_context():
    db.create_all()

    viewer = User(username="viewer", email="viewer@example.com")
    friend = User(username="friend", email="friend@example.com")
    db.session.add_all([viewer, friend])
    db.session.flush()
    viewer.friends.append(friend)

    song = Song(title="Old News", artist="Yesterday's Band", shared_by=friend.id)
    db.session.add(song)
    db.session.flush()

    hours_ago = 23
    stale_time = datetime.now(timezone.utc) - timedelta(hours=hours_ago)
    db.session.add(ListeningEvent(user_id=friend.id, song_id=song.id, listened_at=stale_time))
    db.session.commit()

    feed = get_friends_listening_now(viewer.id)
    print(f"Friend last listened {hours_ago} hours ago.")
    print(f"'Listening now' feed returned {len(feed)} entr(y/ies): "
          f"{[e['friend']['username'] for e in feed]}")

    print()
    if feed:
        print(f"BUG REPRODUCED — a listen from {hours_ago}h ago still shows in 'listening now' "
              f"(the 24h window is too wide for a 'now' feed).")
    else:
        print("PASS — stale listen excluded from 'listening now'. Bug is not present.")
