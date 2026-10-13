CREATE TABLE IF NOT EXISTS show_nights (
 id INTEGER PRIMARY KEY, show_date TEXT NOT NULL UNIQUE, timezone TEXT NOT NULL,
 start_at_utc TEXT NOT NULL, end_at_utc TEXT NOT NULL,
 status TEXT NOT NULL DEFAULT 'open' CHECK(status IN ('open','closed')),
 override_note TEXT NOT NULL DEFAULT '', guest_host TEXT NOT NULL DEFAULT '',
 recording_mode TEXT NOT NULL DEFAULT 'unknown' CHECK(recording_mode IN ('unknown','public','confirmed_off')),
 recording_confirmed_at TEXT, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS slots (
 id INTEGER PRIMARY KEY, show_night_id INTEGER NOT NULL REFERENCES show_nights(id),
 start_at_utc TEXT NOT NULL, end_at_utc TEXT NOT NULL,
 visibility TEXT NOT NULL CHECK(visibility IN ('public','hold','private')),
 status TEXT NOT NULL DEFAULT 'open' CHECK(status IN ('open','closed')),
 UNIQUE(show_night_id,start_at_utc), CHECK(end_at_utc > start_at_utc)
);
CREATE TABLE IF NOT EXISTS bookings (
 id TEXT PRIMARY KEY, slot_id INTEGER NOT NULL REFERENCES slots(id), stage_name TEXT NOT NULL,
 full_name TEXT NOT NULL DEFAULT '', email TEXT NOT NULL, phone TEXT NOT NULL DEFAULT '',
 social_handle TEXT NOT NULL DEFAULT '', performance_type TEXT NOT NULL,
 consent_level TEXT NOT NULL CHECK(consent_level IN ('clip_eligible','live_only','private')),
 livestream_allowed INTEGER NOT NULL CHECK(livestream_allowed IN (0,1)),
 archive_allowed INTEGER NOT NULL CHECK(archive_allowed IN (0,1)),
 clips_allowed INTEGER NOT NULL CHECK(clips_allowed IN (0,1)),
 adaptation_allowed INTEGER NOT NULL DEFAULT 0 CHECK(adaptation_allowed IN (0,1)),
 feedback_allowed INTEGER NOT NULL DEFAULT 0 CHECK(feedback_allowed IN (0,1)),
 teleprompter_text TEXT NOT NULL DEFAULT '', terms_version TEXT NOT NULL,
 consented_at TEXT NOT NULL, orientation_version TEXT NOT NULL,
 status TEXT NOT NULL DEFAULT 'booked' CHECK(status IN ('booked','confirmed','checked_in','performed','cancelled','no_show')),
 check_in_at TEXT, performed_at TEXT, host_note TEXT NOT NULL DEFAULT '',
 created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
 CHECK(clips_allowed <= archive_allowed AND archive_allowed <= livestream_allowed),
 CHECK(consent_level != 'private' OR (livestream_allowed=0 AND archive_allowed=0 AND clips_allowed=0 AND adaptation_allowed=0))
);
CREATE UNIQUE INDEX IF NOT EXISTS active_slot ON bookings(slot_id) WHERE status != 'cancelled';
CREATE INDEX IF NOT EXISTS booking_status ON bookings(status);
CREATE TABLE IF NOT EXISTS booking_tokens (
 id INTEGER PRIMARY KEY, booking_id TEXT NOT NULL REFERENCES bookings(id) ON DELETE CASCADE,
 token_hash TEXT NOT NULL UNIQUE, purpose TEXT NOT NULL CHECK(purpose IN ('confirm','cancel')),
 expires_at TEXT NOT NULL, used_at TEXT
);
CREATE TABLE IF NOT EXISTS reminders (
 id INTEGER PRIMARY KEY, booking_id TEXT NOT NULL REFERENCES bookings(id) ON DELETE CASCADE,
 type TEXT NOT NULL, channel TEXT NOT NULL DEFAULT 'email', due_at_utc TEXT NOT NULL,
 sent_at TEXT, attempt_count INTEGER NOT NULL DEFAULT 0,
 status TEXT NOT NULL DEFAULT 'pending' CHECK(status IN ('pending','sending','accepted','failed','disabled','skipped','uncertain')),
 error_message TEXT NOT NULL DEFAULT '', claim_id TEXT, claimed_at TEXT,
 payload TEXT NOT NULL, UNIQUE(booking_id,type,channel)
);
CREATE TABLE IF NOT EXISTS writer_submissions (
 id TEXT PRIMARY KEY, text TEXT NOT NULL, alias TEXT NOT NULL, contact TEXT NOT NULL DEFAULT '',
 credit TEXT NOT NULL DEFAULT '', perform_allowed INTEGER NOT NULL DEFAULT 0,
 publish_allowed INTEGER NOT NULL DEFAULT 0, ai_allowed INTEGER NOT NULL DEFAULT 0,
 music_allowed INTEGER NOT NULL DEFAULT 0, withdrawal_hash TEXT NOT NULL UNIQUE,
 status TEXT NOT NULL DEFAULT 'submitted' CHECK(status IN ('submitted','withdrawn','in_production')),
 terms_version TEXT NOT NULL, consented_at TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS media_assets (
 id TEXT PRIMARY KEY, kind TEXT NOT NULL DEFAULT 'arrival', disk_name TEXT NOT NULL UNIQUE,
 mime TEXT NOT NULL, size INTEGER NOT NULL, transcript TEXT NOT NULL,
 approved INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS host_actions (
 id INTEGER PRIMARY KEY, action TEXT NOT NULL, reference TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS sanitation_checks (
 id INTEGER PRIMARY KEY, show_night_id INTEGER NOT NULL REFERENCES show_nights(id),
 location TEXT NOT NULL CHECK(location IN ('mic','lobby','bathroom')), created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS clip_candidates (
 booking_id TEXT NOT NULL REFERENCES bookings(id) ON DELETE CASCADE, tag TEXT NOT NULL,
 review_status TEXT NOT NULL DEFAULT 'candidate', PRIMARY KEY(booking_id,tag)
);
CREATE TABLE IF NOT EXISTS rate_limits (
 bucket TEXT PRIMARY KEY, window_start INTEGER NOT NULL, hits INTEGER NOT NULL
);
