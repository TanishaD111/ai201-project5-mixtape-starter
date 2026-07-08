"""
reproduce_bug2.py — Reproduce Bug #2: "Friends Listening Now" shows people from yesterday.

Run:  python reproduce_bug2.py

Scenario (from the issue report): a friend's last listen was late last night
(e.g. 11pm). The next morning, "Friends Listening Now" still shows them, because
the old code used a rolling 24-hour window instead of "listened today".

This models the calendar-day boundary directly:
  - "darius" listened at 23:59 YESTERDAY  -> should NOT appear this morning
  - "mina"   listened at 00:01 TODAY      -> should appear
"""
from datetime import datetime, timezone, timedelta
from app import create_app, db
from models import User, Song, ListeningEvent
from services.feed_service import get_friends_listening_now

app = create_app({"TESTING": True, "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:"})

with app.app_context():
    db.create_all()

    viewer = User(username="viewer", email="viewer@example.com")
    darius = User(username="darius", email="darius@example.com")
    mina = User(username="mina", email="mina@example.com")
    db.session.add_all([viewer, darius, mina])
    db.session.flush()
    viewer.friends.append(darius)
    viewer.friends.append(mina)

    song = Song(title="Nightcap", artist="The Late Ones", shared_by=darius.id)
    db.session.add(song)
    db.session.flush()

    start_of_today = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    last_night = start_of_today - timedelta(minutes=1)   # 23:59 yesterday
    this_morning = start_of_today + timedelta(minutes=1)  # 00:01 today

    db.session.add(ListeningEvent(user_id=darius.id, song_id=song.id, listened_at=last_night))
    db.session.add(ListeningEvent(user_id=mina.id, song_id=song.id, listened_at=this_morning))
    db.session.commit()

    feed = get_friends_listening_now(viewer.id)
    names = [e["friend"]["username"] for e in feed]
    print(f"darius listened late last night; mina listened earlier today.")
    print(f"'Listening now' feed shows: {names}")

    print()
    if "darius" in names:
        print("BUG REPRODUCED — darius's listen from last night still shows this morning "
              "(rolling 24h window instead of 'today').")
    elif "mina" in names and "darius" not in names:
        print("PASS — only today's listeners appear (darius excluded, mina included).")
    else:
        print(f"UNEXPECTED — feed = {names}")
