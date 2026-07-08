"""
reproduce_bug3.py — Reproduce Bug #3: the same song shows up twice in search.

Run:  python reproduce_bug3.py

The search query outer-joins the song_tags table, which produces ONE ROW PER TAG
for each song. A song with 3 tags therefore matches 3 times.

Note: db.session.query(Song).all() (used by the real search_songs) hides this,
because SQLAlchemy's legacy Query API auto-deduplicates ENTITY results by primary
key. This script shows the underlying duplication two ways:
  1. The raw join really returns 3 rows (the actual bug in the query).
  2. A column-based select surfaces those 3 rows as visible duplicates.
The correct fix — adding .distinct() to search_songs — removes the duplication
at its source, independent of ORM version.
"""
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

    print(f"Song 'Crown Heights Anthem' has {len(tags)} tags.\n")

    # 1. The bug in the query itself: the join yields one row per tag.
    joined = (
        db.session.query(Song)
        .outerjoin(song_tags, Song.id == song_tags.c.song_id)
        .filter(Song.title.ilike("%Anthem%"))
    )
    raw_rows = db.session.execute(joined.statement).all()
    print(f"[1] Raw SQL rows from the join:          {len(raw_rows)}  (should be 1)")

    # 2. Surface those rows as visible duplicates via a column-based select.
    title_rows = (
        db.session.query(Song.title)
        .outerjoin(song_tags, Song.id == song_tags.c.song_id)
        .filter(Song.title.ilike("%Anthem%"))
        .all()
    )
    print(f"[2] Column select returns titles:        {[r[0] for r in title_rows]}")

    # 3. What the real endpoint returns today (ORM auto-dedupes entities).
    results = search_songs("Anthem")
    matches = [r for r in results if r["title"] == "Crown Heights Anthem"]
    print(f"[3] search_songs() (entity dedup) copies: {len(matches)}")

    print()
    if len(raw_rows) == 1:
        print("PASS — the join no longer duplicates rows. Bug is fixed at the source.")
    else:
        print(f"BUG REPRODUCED — the search join produces {len(raw_rows)} rows for one song "
              f"(one per tag). It's masked by ORM entity dedup today, but the query is wrong; "
              f"adding .distinct() fixes it.")
