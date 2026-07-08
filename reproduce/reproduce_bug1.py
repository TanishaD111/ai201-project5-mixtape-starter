"""
reproduce_bug1.py — Reproduce Bug #1: listening streak resets on Sunday.

Run:  python reproduce_bug1.py

Simulates a user listening on two consecutive days (Saturday then Sunday).
The streak should climb to 2, but the bug resets it to 1 on Sunday.
"""
from datetime import datetime, timezone
from app import create_app, db
from models import User
from services.streak_service import update_listening_streak

app = create_app({"TESTING": True, "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:"})

with app.app_context():
    db.create_all()
    user = User(username="me", email="me@example.com")
    db.session.add(user)
    db.session.commit()

    saturday = datetime(2024, 6, 15, 12, 0, 0, tzinfo=timezone.utc)  # weekday() == 5
    sunday = datetime(2024, 6, 16, 12, 0, 0, tzinfo=timezone.utc)    # weekday() == 6

    update_listening_streak(user, saturday)
    print(f"After Saturday listen: streak = {user.listening_streak}  (expected 1)")

    update_listening_streak(user, sunday)
    print(f"After Sunday listen:   streak = {user.listening_streak}  (expected 2)")

    print()
    if user.listening_streak == 2:
        print("PASS — streak incremented correctly. Bug is not present.")
    else:
        print(f"BUG REPRODUCED — streak reset to {user.listening_streak} on Sunday instead of incrementing to 2.")
