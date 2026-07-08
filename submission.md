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

### Issue #3 — The same song keeps showing up twice in search

**How I reproduced it.** The report said searching "Anthem" returned "Crown Heights Anthem" three times, and that this song has three tags while single-result songs did not. I wrote `reproduce/reproduce_bug3.py`, which seeds that exact song with three tags and searches for it. This is where I hit something unexpected: `search_songs("Anthem")` returned the song *once*, not three times, and the existing `test_search.py` duplicate tests already passed. So I dug into why the reporter saw duplicates when the service function did not. Running the search query as a column select (`db.session.query(Song.title).outerjoin(song_tags, ...)`) returned three identical rows, confirming the duplication is real in the query — the reporter genuinely saw three copies. The reason my `search_songs` call showed one is environment-specific (below), so I made the reproduction assert the real underlying behavior (raw rows) rather than only the masked result.

**How I found the root cause.** From `GET /songs/search` in `routes/songs.py` into `search_songs` in `services/search_service.py`. The query is `db.session.query(Song).outerjoin(song_tags, Song.id == song_tags.c.song_id).filter(title/artist ilike ...)`. The moment of confidence was noticing that `song_tags` is joined but never used — it appears in neither the `filter` nor the selected columns. An outer join to a child table with multiple matching rows multiplies the parent row once per child. `song_tags` has one row per (song, tag) pair, so a 3-tag song produces 3 result rows. That exactly matches "songs with more tags duplicate more, tagless songs appear once."

**The root cause.** `search_songs` outer-joined the `song_tags` association table, which fans out the result to one row per tag on each matching song. A song with three tags therefore matched three times; a song with no tags matched once. The join served no purpose — the search only filters on `title`/`artist`, and each song's tags are loaded independently through the `Song.tags` relationship inside `Song.to_dict()`. (Why the reporter saw the duplicates but my `search_songs` call did not: this project's SQLAlchemy version de-duplicates ORM *entity* results — `query(Song).all()` — by primary key, which collapses the 3 fan-out rows back to 1 for this specific call. That masking is version- and query-shape-dependent; a column select, an older SQLAlchemy, or a 2.0-style `select()` without `.unique()` all expose the duplicates, which is the path the reporter was on. The query is wrong regardless of whether a given ORM layer happens to hide it.)

**My fix and side-effect check.** I removed the unnecessary `.outerjoin(song_tags, ...)` line from the query (left commented in place with an explanation). This eliminates the fan-out at its source, so the query returns exactly one row per matching song on every SQLAlchemy path — I preferred this over adding `.distinct()`, which would leave a pointless join that fans out and then collapses. To confirm I hadn't broken anything: the result still includes each song's tags (verified `['rap', 'hip-hop', 'boom bap']` on the search result), because tags come from the relationship in `to_dict()`, not from the join; the column-select version of the fixed query returns 1 row where the joined version returned 3; and all 5 tests in `tests/test_search.py` pass (matching search, empty search, and the no-duplicate tests for 0-, 1-, and multi-tag songs).

**AI usage.** This bug is where AI was most useful as an *explainer*. Once I had found the unused `song_tags` join, I confirmed with AI that an outer join to a one-to-many child table multiplies parent rows by the number of child matches, and — after I noticed `search_songs` returned one row despite the 3-row join — I asked AI why, which surfaced that SQLAlchemy's legacy `Query` auto-uniquifies entity results by identity. I verified both claims by running the queries myself (column select showed 3 rows; entity query showed 1). AI explained the mechanism; the reproduction confirmed it.

### Issue #4 — Notified when a friend adds my song to a playlist, but not when they rate it

**How I reproduced it.** From the report: playlist-add notifications work, rating notifications never arrive. I wrote `reproduce/reproduce_bug4.py` following the reporter's steps — aaliya shares a song, kenji rates it 5 stars via the same path the route uses (`rate_song`), then I read aaliya's notifications with `get_notifications`. Before the rating she had 0 notifications; after kenji's 5-star rating she still had 0. The rating itself was saved (the `Rating` row exists), which matches "rating shows on the song but no notification is created," confirming the write succeeded and only the notification was missing.

**How I found the root cause.** The report gave me a working reference case and a broken one, so I compared the two handlers side by side in `services/notification_service.py`. `add_to_playlist` (the working case, reached from `POST /playlists/<id>/songs`) ends by calling `create_notification(user_id=song.shared_by, ...)` guarded by `if song.shared_by != added_by_user_id`. `rate_song` (the broken case, reached from `POST /songs/<id>/rate`) creates or updates the `Rating`, calls `db.session.commit()`, and returns — with no call to `create_notification` anywhere in the function. That side-by-side made it obvious: this wasn't a wrong condition or a notification sent to the wrong user, it was a missing step. `rate_song` simply never notified anyone.

**The root cause.** `rate_song` persisted the rating but never created a notification, so the song's sharer was never told their song had been rated. The notification code exists and works (`create_notification`), and the parallel action `add_to_playlist` calls it — `rate_song` just omitted the equivalent call. It is a missing side effect, not a broken one: nothing in `rate_song` attempted to notify and failed; the notification logic was simply absent.

**My fix and side-effect check.** After the existing `db.session.commit()` in `rate_song`, I added a `create_notification` call addressed to `song.shared_by`, with type `"song_rated"` and a body naming the rater, the song, and the score — mirroring `add_to_playlist`. I reused its self-notification guard, `if song.shared_by != user_id`, so a user rating their own shared song is not notified. This is purely additive (no existing line changed), which fits the "missing step" root cause. Checks I ran afterward: the repro now shows aaliya receiving exactly one notification with body `kenji rated your song 'My Track' 5/5.`; rating one's own song produces 0 notifications (guard verified); re-running the full test suite showed no new failures introduced by this change (the only remaining failures are the two Issue #5 playlist tests, which are unrelated). I also confirmed `rate_song` still creates-or-updates the `Rating` and returns it as before — the notification is an addition at the end, so the existing rating behavior and the route's `201` response are unchanged.

**AI usage.** I used AI only to sanity-check the notification wording and that reusing the `song.shared_by != user_id` guard was the right way to avoid self-notifications. The diagnosis itself came from reading the two functions side by side — the report's "works for playlists, not for ratings" framing pointed straight at comparing `add_to_playlist` and `rate_song`, and the missing call was visible on inspection, not something AI needed to find.

### Issue #5 — The last song in a playlist never shows up

**How I reproduced it.** From the report: a playlist reports N songs but returns N−1, and the missing one is always the most recently added; adding another song frees the previously-missing one and hides the new one. I wrote `reproduce/reproduce_bug5.py` to model both halves: I built a 7-song "Friday Energy" playlist and called `get_playlist_songs` (it returned 6 — Song 1 through Song 6, with the last-added Song 7 missing), then added an 8th song and re-fetched (it returned 7 — Song 7 now appeared and Song 8 became the missing one). That reproduced the exact "always hides whatever was added last" behavior the reporter described, including the "adding a song frees the previous one" detail.

**How I found the root cause.** From `GET /playlists/<id>/songs` in `routes/playlists.py` into `get_playlist_songs` in `services/playlist_service.py`. The function queries the songs joined through `playlist_entries` and orders them by ascending `position`, so the last element of the list is always the highest-position (most recently added) song. The final line was `return [song.to_dict() for song in songs[:-1]]`. The `[:-1]` slice was the whole bug: it returns every element except the last. Because the query is ordered by position, "the last element" is always the newest song — which is precisely why the missing song was always the most recent one, and why adding a new song shifted which song sat in the dropped final slot.

**The root cause.** `get_playlist_songs` sliced the ordered song list with `songs[:-1]` before serializing, discarding the last item. Since the list is sorted by ascending playlist position, the dropped item is always the most recently added song. The count elsewhere (e.g. "7 songs") comes from the playlist's actual membership, so it stayed correct while the returned list was always one short — matching "says 7 but shows 6."

**My fix and side-effect check.** I changed the return to iterate the full list — `return [song.to_dict() for song in songs]` — and left the incorrect `songs[:-1]` line commented directly above it. This is a one-token fix that touches only the faulty slice; the query and ordering are unchanged, so songs still come back in position order. Because this is a boundary/off-by-one bug, I checked the small-list edges specifically: an empty playlist returns `[]` (0 songs) and a single-song playlist returns that one song — the single-song case is the important one, because the old `[:-1]` would have turned a one-song playlist into an empty result. I also re-ran the full test suite: `tests/test_playlists.py` now passes both previously-failing tests (`test_playlist_returns_all_songs` and `test_playlist_returns_songs_in_order`), the empty-playlist test still passes, and the entire suite is green (13 passed), confirming no regressions in the other services.

**AI usage.** None needed for the diagnosis — the `[:-1]` slice was visible on reading the function, and the report's "always the most recently added" detail matched the position-ordered query immediately. I used AI only to confirm the Python slicing semantics I already expected (that `list[:-1]` returns everything except the final element, and that on a length-0 or length-1 list it yields an empty list), which is what motivated the explicit empty/single-song edge checks.
