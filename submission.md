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

---

## Root Cause Analysis

### Issue #1 — My listening streak keeps resetting

**How I reproduced it.** I wrote a small script (`reproduce/reproduce_bug1.py`) that creates one user and calls `update_listening_streak` twice with fixed dates: Saturday 2024-06-15, then Sunday 2024-06-16 (two consecutive calendar days). After the Saturday call the streak was 1 (correct); after the Sunday call it was still 1, when a consecutive day should have made it 2. I used fixed dates in a script rather than the live `/songs/<id>/listen` endpoint because that endpoint stamps events with `datetime.now()`, so reproducing a Saturday→Sunday sequence through HTTP would mean waiting for a real weekend. The existing test `test_streak_increments_on_sunday` fails for the same reason, which confirmed the behavior independently.

**How I found the root cause.** Starting from the route: `POST /songs/<id>/listen` in `routes/songs.py` calls `record_listening_event` in `services/streak_service.py`, which creates the `ListeningEvent` and then delegates the streak math to `update_listening_streak`. Reading that function, the streak is only ever reset in one place — the `else` branch of the day-difference comparison (lines ~70–78). The moment I was confident: the `elif` guarding the increment read `elif days_since_last == 1 and today.weekday() != 6:`. The `days_since_last == 1` part is exactly the "consecutive day" case that should increment, so the extra `and today.weekday() != 6` clause was the only thing that could send a genuine consecutive day into the reset branch — and only when `today` is a Sunday.

**The root cause.** Python's `datetime.weekday()` returns 6 for Sunday. The condition required `today.weekday() != 6` *in addition to* the day being consecutive, so when a user listened on a Sunday exactly one day after their previous listen (e.g. Saturday then Sunday), the `elif` evaluated to `False`. Control fell through to the `else` branch, which sets `listening_streak = 1`. The result: any streak that continued into a Sunday was reset instead of incremented. A streak is about consecutive calendar days, so the day of the week is irrelevant — the weekday check never belonged there.

**My fix and side-effect check.** I removed the `and today.weekday() != 6` clause so the branch is simply `elif days_since_last == 1:` (the original line is left commented directly above the fix for reference). This is the smallest change that addresses the root cause — it touches only the faulty condition and no surrounding logic. To confirm I hadn't broken the other cases, I ran the full `tests/test_streaks.py` suite (all 5 pass): new user starts at 1, listening twice the same day doesn't double-count, a skipped day still resets to 1, an ordinary consecutive day (Mon→Tue) still increments, and the previously failing Sunday case now increments. I checked both sides of the boundary specifically — the consecutive-day increment now fires on every weekday including Sunday, and a two-day gap (`days_since_last == 2`) still correctly falls to the reset branch.

**AI usage.** After I had already read `update_listening_streak` and narrowed the problem to the weekday clause, I used AI to confirm my understanding of what `datetime.weekday()` returns for each day (Monday=0 … Sunday=6), which verified that `== 6` meant Sunday. I read the code and confirmed the diagnosis myself before changing anything; AI was used to explain a standard-library detail, not to locate the bug.

### Issue #2 — Friends Listening Now shows people from yesterday

**How I reproduced it.** The reported behavior: checking the feed at ~9am showed a friend (darius) whose last listen was 11pm the night before, even though he hadn't opened the app all morning — and yesterday-evening listens kept "hanging around until the same time the next day." I reproduced this in `reproduce/reproduce_bug2.py` by modeling the calendar-day boundary directly: I inserted one `ListeningEvent` at 23:59 *yesterday* (darius) and one at 00:01 *today* (mina), then called `get_friends_listening_now`. The buggy code returned darius — a listen from the previous evening appeared in a "now" feed the next day. I used a script with controlled `listened_at` values rather than the live endpoint because the endpoint stamps events with the current time, so I couldn't place an event at "late last night" through HTTP. The "hangs around until the same time next day" detail is the tell-tale sign of a rolling 24-hour window.

**How I found the root cause.** From the route `GET /feed/<user_id>/listening-now` in `routes/feed.py` into `get_friends_listening_now` in `services/feed_service.py`. I read the function top-down: it builds `cutoff = datetime.now(timezone.utc) - RECENT_THRESHOLD` and filters `ListeningEvent.listened_at >= cutoff`, where `RECENT_THRESHOLD = timedelta(hours=24)`. The comparison itself is correct, so I focused on what the cutoff actually computes. The moment it clicked was connecting the code to the "same time the next day" symptom: a cutoff of `now - 24h` is a *sliding* window, so at 9am it reaches back to 9am yesterday and still includes an 11pm-yesterday listen. The window wasn't just too long — it was the wrong *kind* of window. The expected behavior ("friends who have listened today") is a fixed calendar-day boundary, not a rolling 24-hour span.

**The root cause.** `get_friends_listening_now` defined "recent" as a rolling 24-hour window (`cutoff = now - timedelta(hours=24)`). A rolling window always trails the current clock time, so an event from late yesterday evening stays inside the window until that same clock time passes today — exactly the "darius at 9am" report. The feature's actual requirement is "listened during today's calendar day," which a rolling 24-hour span does not express: it both includes late-yesterday events (the bug) and, symmetrically, would exclude a listen from early this morning once 24 hours had elapsed. The defect was using an elapsed-time window where a day-boundary comparison was needed.

**My fix and side-effect check.** I replaced the rolling cutoff with the start of the current calendar day (UTC): `cutoff = now.replace(hour=0, minute=0, second=0, microsecond=0)`, and commented out both the old `cutoff = now - RECENT_THRESHOLD` line and the now-unused `RECENT_THRESHOLD` constant. The filter `listened_at >= cutoff` is unchanged, so only the cutoff's meaning changed. Because this is a boundary bug, I verified both sides of midnight: a listen at 00:00:01 today appears, and one at 23:59:59 yesterday does not. Crucially I also checked the case that a naive "just make the window shorter" fix would break — a friend who listened at 8am still appears when the feed is viewed later that morning (they listened *today*), which a short rolling window would have wrongly hidden. Finally I checked the sibling function `get_activity_feed`: it shares the table and friend lookup but is intentionally *not* filtered by recency and never referenced `RECENT_THRESHOLD`, so a yesterday event still appears there as designed — confirming I didn't change a feed that was meant to be unbounded. (This uses the UTC day boundary, consistent with how the app stores all timestamps in UTC.)

**AI usage.** My first instinct was to shrink the window to a few minutes ("listening now" ≈ the last several minutes). The issue report corrected that: it explicitly said the feed should show "what they've played today," and the 8am/9am example showed a short window would hide legitimate same-day listens. That reframed the fix from "smaller rolling window" to "calendar-day boundary." I used AI to confirm the mechanics of a rolling vs. fixed window (that `now - 24h` slides with the clock while a start-of-day cutoff is fixed), but the decisive input was the human-written symptom description, not the AI — which is a good example of why the reproduction/symptom detail matters more than a plausible-sounding diagnosis.
