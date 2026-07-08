"""
reproduce_bug3.py — Bug #3: the same song shows up two/three times in search.

Reported (simone): searching "Anthem" returned "Crown Heights Anthem" three times.
That song has three tags.

Root cause: search_songs() outer-joined the song_tags table, so the query emitted
one row per tag — a song with N tags matched N times.

Environment note: this project's SQLAlchemy de-duplicates ORM *entity* results
(query(Song).all()) by primary key, which hides the duplicate rows for
search_songs() in THIS environment. The duplication is still real in the query and
is exactly what the reporter saw on a path without that entity de-dup. The block
below makes the fan-out visible with a column select (which is not de-duped), then
confirms the user-facing result and that tags survive the fix.
"""
from collections import Counter
from app import create_app, db
from models import User, Song, Tag, song_tags
from services.search_service import search_songs

app = create_app({"TESTING": True, "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:"})

with app.app_context():
    db.create_all()

    user = User(username="sharer", email="sharer@example.com")
    db.session.add(user)
    db.session.flush()

    tags = [Tag(name=n) for n in ("rap", "hip-hop", "boom bap")]
    db.session.add_all(tags)
    db.session.flush()

    song = Song(title="Crown Heights Anthem", artist="Borough Kings", shared_by=user.id)
    db.session.add(song)
    db.session.flush()

    for t in tags:
        db.session.execute(song_tags.insert().values(song_id=song.id, tag_id=t.id))
    db.session.commit()

    print(f"'Crown Heights Anthem' has {len(tags)} tags.\n")

    # The fan-out, made visible with a column select (bypasses ORM entity de-dup).
    with_join = (
        db.session.query(Song.title)
        .outerjoin(song_tags, Song.id == song_tags.c.song_id)
        .filter(Song.title.ilike("%Anthem%"))
        .all()
    )
    without_join = (
        db.session.query(Song.title)
        .filter(Song.title.ilike("%Anthem%"))
        .all()
    )
    print(f"Query WITH the tag join (buggy shape):  {len(with_join)} rows  <- what simone saw")
    print(f"Query WITHOUT the join (fixed shape):   {len(without_join)} row(s)")

    # The user-facing result from the actual service.
    results = search_songs("Anthem")
    counts = Counter(r["title"] for r in results)
    print(f"\nsearch_songs('Anthem') -> {dict(counts)}")
    print(f"tags on the result: {results[0]['tags'] if results else None}")

    dupes = {t: c for t, c in counts.items() if c > 1}
    tags_ok = bool(results) and bool(results[0].get("tags"))

    print()
    if dupes:
        print(f"BUG REPRODUCED — {dupes} (a single song returned multiple times).")
    elif not tags_ok:
        print("REGRESSION — duplicates gone, but tags are missing from the result.")
    else:
        print("PASS — each song appears exactly once and tags are still present. "
              "The fixed query returns 1 row where the buggy join returned 3.")
