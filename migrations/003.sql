ALTER TABLE show_nights ADD COLUMN broadcast_source TEXT NOT NULL DEFAULT 'unknown' CHECK(broadcast_source IN ('unknown','off','stage','house'));
ALTER TABLE show_nights ADD COLUMN room_transmission TEXT NOT NULL DEFAULT 'unknown' CHECK(room_transmission IN ('unknown','off','on'));
ALTER TABLE show_nights ADD COLUMN room_recording TEXT NOT NULL DEFAULT 'unknown' CHECK(room_recording IN ('unknown','off','allowed'));
ALTER TABLE show_nights ADD COLUMN capture_assertions TEXT NOT NULL DEFAULT '{}';
ALTER TABLE show_nights ADD COLUMN capture_session_hash TEXT NOT NULL DEFAULT '';
ALTER TABLE show_nights ADD COLUMN capture_verified_at TEXT;
ALTER TABLE show_nights ADD COLUMN private_room_occupied INTEGER NOT NULL DEFAULT 0 CHECK(private_room_occupied IN (0,1));
UPDATE show_nights SET private_room_occupied=1 WHERE EXISTS (
 SELECT 1 FROM bookings b JOIN slots s ON s.id=b.slot_id
 WHERE s.show_night_id=show_nights.id AND b.status='checked_in' AND b.consent_level='private'
);
CREATE TABLE editorial_candidates (
 id TEXT PRIMARY KEY, booking_id TEXT NOT NULL REFERENCES bookings(id) ON DELETE CASCADE, week_date TEXT NOT NULL,
 source_reference TEXT NOT NULL, source_duration_ms INTEGER NOT NULL,
 in_ms INTEGER NOT NULL, out_ms INTEGER NOT NULL,
 title TEXT NOT NULL, note TEXT NOT NULL DEFAULT '',
 source_verified INTEGER NOT NULL DEFAULT 0, layers_cleared INTEGER NOT NULL DEFAULT 0,
 origin TEXT NOT NULL CHECK(origin IN ('performer_original','writer_submission','unclear')),
 writer_id TEXT REFERENCES writer_submissions(id),
 review_status TEXT NOT NULL DEFAULT 'candidate' CHECK(review_status IN ('candidate','approved','rejected','withdrawn')),
 created_at TEXT NOT NULL, CHECK(in_ms>=0 AND out_ms>in_ms AND out_ms<=source_duration_ms)
);
CREATE TABLE editorial_grants (
 candidate_id TEXT NOT NULL REFERENCES editorial_candidates(id) ON DELETE CASCADE,
 role TEXT NOT NULL CHECK(role IN ('performer','writer')),
 tiktok INTEGER NOT NULL DEFAULT 0, instagram INTEGER NOT NULL DEFAULT 0,
 facebook INTEGER NOT NULL DEFAULT 0, youtube INTEGER NOT NULL DEFAULT 0,
 face_voice INTEGER NOT NULL DEFAULT 0, credit_allowed INTEGER NOT NULL DEFAULT 0,
 public_credit TEXT NOT NULL DEFAULT '', public_handle TEXT NOT NULL DEFAULT '',
 version TEXT NOT NULL, consented_at TEXT NOT NULL, revoked_at TEXT,
 PRIMARY KEY(candidate_id,role)
);
CREATE TABLE editorial_tokens (
 token_hash TEXT PRIMARY KEY, candidate_id TEXT NOT NULL REFERENCES editorial_candidates(id) ON DELETE CASCADE,
 role TEXT NOT NULL CHECK(role IN ('performer','writer')),
 purpose TEXT NOT NULL CHECK(purpose IN ('grant','withdraw')),
 expires_at TEXT NOT NULL, used_at TEXT, version TEXT NOT NULL
);
CREATE TABLE weekly_reels (
 week_date TEXT PRIMARY KEY, master_reference TEXT NOT NULL DEFAULT '',
 review_status TEXT NOT NULL DEFAULT 'draft' CHECK(review_status IN ('draft','edited','published')),
 created_at TEXT NOT NULL
);
CREATE TABLE weekly_selections (
 week_date TEXT NOT NULL REFERENCES weekly_reels(week_date),
 candidate_id TEXT NOT NULL UNIQUE REFERENCES editorial_candidates(id) ON DELETE CASCADE,
 position INTEGER NOT NULL CHECK(position BETWEEN 1 AND 5),
 PRIMARY KEY(week_date,position)
);
CREATE TABLE weekly_posts (
 week_date TEXT NOT NULL REFERENCES weekly_reels(week_date),
 platform TEXT NOT NULL CHECK(platform IN ('tiktok','instagram','facebook','youtube')),
 url TEXT NOT NULL, recorded_at TEXT NOT NULL, removal_requested INTEGER NOT NULL DEFAULT 0,
 PRIMARY KEY(week_date,platform)
);
