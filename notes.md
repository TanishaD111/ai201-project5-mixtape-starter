# Mixtape — Service Layer Notes

What each of the five service files does, function by function, plus where each bug lives.

---

## `streak_service.py` — listening streaks

Tracks how many consecutive days a user has listened to music.

- **`record_listening_event(user_id, song_id)`** — entry point from the `/listen` route. Creates a `ListeningEvent` row, stamps it with `now`, and calls `update_listening_streak`.
- **`update_listening_streak(user, now)`** — the core logic. Compares today's date to the user's `last_listened_at`:
  - no prior history → streak = 1
  - same day → no change
  - consecutive day → +1
  - gap → reset to 1
- **`get_streak(user_id)`** — reads back the current streak number.

> **Issue #1** lives here — line 73's `and today.weekday() != 6` special-cases Sunday and wrongly resets the streak.

---

## `feed_service.py` — the "listening now" feed

Two different feeds over friends' `ListeningEvent`s.

- **`get_friends_listening_now(user_id)`** — friends who listened *recently*. Computes a `cutoff` (now − 24h), pulls events newer than that, then dedupes so each friend appears once with their latest song.
- **`get_activity_feed(user_id, limit=20)`** — the *unfiltered* version: most recent N events from friends regardless of age, no dedup.

> **Issue #2** ("shows people from yesterday") — a 24h rolling window includes yesterday. The docstring says the feed is meant to be "listening now," so the recency logic here is the suspect.

---

## `search_service.py` — song search

- **`search_songs(query)`** — case-insensitive match on title *or* artist, `outerjoin`ing the tags table.
- **`get_song(song_id)`** — fetch one song by ID.

> **Issue #3** ("same song twice") — the `outerjoin` onto `song_tags` produces one row per tag, so a song with 3 tags appears 3 times. There's no `.distinct()`.

---

## `notification_service.py` — notifications

Creates alerts when friends interact with your songs.

- **`create_notification(...)`** — low-level: inserts a notification row.
- **`add_to_playlist(...)`** — adds a song to a playlist *and* notifies the sharer.
- **`rate_song(user_id, song_id, score)`** — validates 1–5, then creates or updates a `Rating`.
- **`get_notifications(...)`** / **`mark_as_read(...)`** — read and update helpers.

> **Issue #4** — `add_to_playlist` calls `create_notification`, but `rate_song` (lines 73–110) never does. That's the "notified on playlist-add but not on rating" gap.

---

## `playlist_service.py` — playlists

- **`create_playlist(...)`** — makes a new playlist row.
- **`get_playlist_songs(playlist_id)`** — returns songs ordered by position.
- **`get_playlist(...)`** / **`get_user_playlists(...)`** — metadata lookups.

> **Issue #5** ("last song never shows") — line 66: `return [... for song in songs[:-1]]`. The `[:-1]` slice drops the last element of the list.
