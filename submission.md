# Mixtape — Codebase Map

Mixtape is a social music app where friends share songs, build collaborative playlists, rate music, and keep listening streaks. It's a Flask app backed by SQLite via SQLAlchemy.

---

## Main Files

### Top level

| File | Responsibility |
|------|----------------|
| `app.py` | Application factory. `create_app()` configures the DB, registers the four route blueprints under their URL prefixes (`/songs`, `/playlists`, `/users`, `/feed`), and calls `db.create_all()`. |
| `models.py` | All SQLAlchemy models and the three association tables. The single source of truth for the data model. |
| `seed_data.py` | Populates `mixtape.db` with test data for running the live server. Not used by the tests. |
| `requirements.txt` | Flask, Flask-SQLAlchemy, pytest. |

### `models.py` — the data model

**Entities**

- **`User`** — `username`, `email`, `listening_streak`, `last_listened_at`. Owns songs, ratings, listening events, notifications, and playlists.
- **`Song`** — `title`, `artist`, `album`, `genre`, `shared_by` (FK → User), `share_note`. This `shared_by` field is what makes a song "shared" — every song belongs to the user who shared it.
- **`Tag`** — a named label; many-to-many with Song.
- **`ListeningEvent`** — one row per listen (`user_id`, `song_id`, `listened_at`). Drives both streaks and the feeds.
- **`Rating`** — a user's 1–5 score for a song, with a `UniqueConstraint(user_id, song_id)` so each user rates a song at most once.
- **`Playlist`** — `name`, `created_by`, `is_collaborative`.
- **`Notification`** — `user_id` (recipient), `notification_type`, `body`, `read` flag.

**Association tables**

- `friendships` — symmetric User↔User many-to-many.
- `song_tags` — Song↔Tag many-to-many.
- `playlist_entries` — Playlist↔Song many-to-many, but carries extra columns: `position` (ordering), `added_by`, `added_at`.

### `routes/` — HTTP layer (thin)

Each file is a Flask blueprint. Routes parse the request, validate required fields,
call a service, and `jsonify` the result. They contain **no business logic** — a
`ValueError` from a service becomes a 400/404 JSON error.

| File | Prefix | Endpoints |
|------|--------|-----------|
| `routes/songs.py` | `/songs` | `GET /search`, `GET /<id>`, `POST /<id>/rate`, `POST /<id>/listen` |
| `routes/playlists.py` | `/playlists` | `POST /`, `GET /<id>`, `GET /<id>/songs`, `POST /<id>/songs` |
| `routes/users.py` | `/users` | `GET /<id>`, `GET /<id>/streak`, `GET /<id>/notifications`, `POST /notifications/<id>/read` |
| `routes/feed.py` | `/feed` | `GET /<id>/listening-now`, `GET /<id>/activity` |

### `services/` — business logic (where the bugs live)

| File | Responsibility |
|------|----------------|
| `streak_service.py` | Record listening events and update the consecutive-day streak. |
| `feed_service.py` | "Friends listening now" (last 24h, deduped per friend) and the unfiltered activity feed. |
| `search_service.py` | Case-insensitive song search over title/artist, joined to tags. |
| `notification_service.py` | Create/read notifications, rate a song, add a song to a playlist. |
| `playlist_service.py` | Create playlists and fetch their songs in `position` order. |

### `tests/`

`test_streaks.py`, `test_search.py`, `test_playlists.py`. Each test spins up a fresh **in-memory** SQLite DB (`sqlite:///:memory:`) via the app factory and builds only the rows it needs — so tests are isolated and never touch `mixtape.db` or the seed data.

---

## Data Flow: adding a shared song to a playlist triggers a notification

This is the app's clearest cross-entity flow — it ties Song ownership, playlists, and notifications together. When user B adds user A's shared song to a playlist, user A (the original sharer) gets notified.

```
POST /playlists/<playlist_id>/songs        (client request)
        │   body: { song_id, added_by }
        ▼
routes/playlists.py :: add_song()          HTTP layer
        │   - reads song_id + added_by from JSON
        │   - 400 if either is missing
        ▼
notification_service.add_to_playlist(playlist_id, song_id, added_by)
        │
        │  1. Load Song, adder (User), Playlist — raise ValueError if any missing
        │  2. Append the song to playlist.songs (skip if already present), commit
        │  3. Compare song.shared_by to added_by_user_id
        │       └─ if the adder is NOT the original sharer:
        ▼
notification_service.create_notification(
        user_id = song.shared_by,          # notify the sharer
        notification_type = "song_added_to_playlist",
        body = "<adder> added your song '<title>' to '<playlist>'."
   )
        │   - inserts a Notification row, commit
        ▼
   The sharer later sees it via GET /users/<id>/notifications
        → users.py :: notifications() → notification_service.get_notifications()
```

**Key detail:** the notification recipient is `song.shared_by`, not the person taking the action. The `if song.shared_by != added_by_user_id` guard prevents notifying yourself about your own action.

*(Related open issue: `rate_song()` in the same file does **not** call `create_notification`, which is why rating a song produces no notification even though adding it to a playlist does.)*

---

## Patterns I Noticed

- **Every route delegates immediately to a service function.** The routes do input parsing and response formatting; all business logic lives in `services/`. So to understand any feature, read its service — the route just wires it up.

- **Errors are handled the same way everywhere.** A service raises `ValueError` when something is missing or invalid, and the route catches it and returns a JSON error. You'll see this `try/except ValueError` in every route.

- **Every model has a `to_dict()`.** That's how data gets turned into JSON for the response. If you want to know what a feature returns, look at the model's `to_dict()`.

- **IDs are UUID strings, not numbers.** Every record gets a random UUID as its primary key.

- **The three feature areas mirror each other.** Songs, playlists, users, and feed each have a route file and (mostly) a matching service file, all following the same shape. Once you've read one, the rest are familiar.
