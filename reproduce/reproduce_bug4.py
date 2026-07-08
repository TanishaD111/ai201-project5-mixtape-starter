"""
reproduce_bug4.py — Reproduce Bug #4: no notification when a friend RATES your song.

Run:  python reproduce_bug4.py

Scenario (from the issue report): aaliya shares a song; kenji rates it 5 stars.
aaliya should get a notification — just like she does when someone adds her song
to a playlist — but rate_song() never creates one.
"""
from app import create_app, db
from models import User, Song
from services.notification_service import rate_song, get_notifications

app = create_app({"TESTING": True, "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:"})

with app.app_context():
    db.create_all()

    aaliya = User(username="aaliya", email="aaliya@example.com")  # shared the song
    kenji = User(username="kenji", email="kenji@example.com")     # rates the song
    db.session.add_all([aaliya, kenji])
    db.session.flush()

    song = Song(title="My Track", artist="Me", shared_by=aaliya.id)
    db.session.add(song)
    db.session.commit()

    before = get_notifications(aaliya.id)
    print(f"Before: aaliya has {len(before)} notification(s).")

    # kenji rates aaliya's shared song
    rate_song(kenji.id, song.id, 5)

    after = get_notifications(aaliya.id)
    print(f"After kenji rated the song 5/5: aaliya has {len(after)} notification(s).")

    print()
    if len(after) > len(before):
        print("PASS — rating produced a notification. Bug is not present.")
        print(f"       Notification body: {after[0]['body']!r}")
    else:
        print("BUG REPRODUCED — rating the shared song produced NO notification for the sharer.")
