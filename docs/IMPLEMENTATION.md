# BOX2 — Implementation Contract for Codex 6.1 Ultra

Implement in `JosephJMWalker-MBA/box2`. This repo began empty; this is the new codebase. Respect `AGENTS.md` and `docs/PRODUCT.md`. Ship a simple secure MVP, not a speculative platform. Default to visible factual states; no mocked bookings or active-stream indicators in production.

## Stack and directory direction

Use PHP 8.2+ with **PDO SQLite**, PHP sessions, HTML templates, CSS, vanilla JS. Make it operate without Composer or npm in production (dev tools/tests may be optional). All `*.php` scripts must use centralized config, DB connection, auth/session/CSRF helpers, output encoding, and error handling.

Suggested layout (change only if simpler):

```
public/
  index.php                 # routes: /, /book, /rules, /writers, /terms, /privacy, /admin, /admin/*
  assets/site.css
  assets/site.js
  assets/logo.svg           # optional original art
app/
  bootstrap.php
  db.php
  booking.php
  schedule.php
  reminders.php
  mail.php
  auth.php
  views/
bin/
  migrate.php
  cron-reminders.php
  backup.php
config.example.php          # placeholder values only; actual config outside web root
migrations/
tests/
docs/
```

If hosting document root is fixed to `public_html`, supply an alternate supported layout so app files, SQLite, uploads, config, logs and backups remain **outside** public webroot; if host restrictions make that impossible, block launch rather than expose secrets/data. No public `box2.sqlite`. No .env credentials tracked.

## Config

- `BASE_URL` + optional base path for `box2.yurrmom.com` or `yurrmom.com/box2` if routing later arranged.
- `APP_TIMEZONE=America/New_York`; all stored instants UTC ISO 8601.
- `TWITCH_CHANNEL=cantonrefinery`, `TWITCH_PARENT` as actual deployed host(s); HTTPS and 400px minimum player width where practical; graceful offline/error fallback.
- Host `ADMIN_PASSWORD_HASH` (password_hash/verify), secret for signed links and CSRF, trusted HTTPS proxy config if relevant.
- Optional SMTP/transactional sender, `EMAIL_FROM`, mail transport `disabled|smtp|local` explicitly; never fake success.
- `META_PIXEL_ID` optional and **disabled until consent**; separate production/staging tracking settings.
- Optional Facebook Page / TikTok / Reddit share routes as URL-only links. No social API keys in phase 1.
- Event address `2735 Harrison Ave NW, Canton, OH 44709` only publish after `VENUE_PUBLIC_ENABLED` is true and host verifies allowed public access.
- `ALLOW_BOOKINGS` starts off until HTTPS, DB, host, and permissions are validated.

## Data model (minimal normalized schema)

Use SQLite migration(s), foreign keys, indices and constraint checks, with data-structure justification:

- `show_nights`: `id`, `show_date` (local YYYY-MM-DD), `timezone`, `start_at_utc`, `end_at_utc`, `status`, `override_note`, `created_at`. Generate six nights/week; exception nights can close or move times / guest host; idempotent schedule generation. Never overwrite human edits automatically.
- `slots`: `id`, `show_night_id`, `start_at_utc`, `end_at_utc`, `visibility` (public/hold/private), `status` (open/closed). Unique (show_night_id,start_at_utc), 30 ten-minute slots for regular 5-hour show, max initially 22 public unless admin overrides. Store actual time, not 9pm "string".
- `bookings`: `id` opaque booking reference, `slot_id`, `stage_name`, `full_name` optional, `email`, `phone` optional, `social_handle` optional, `performance_type` (standup/musical_comedy/host_practice etc), `consent_level` (clip_eligible/live_only/private), `teleprompter_text` optional, `terms_version`, `consented_at`, `status`, `check_in_at`, `performed_at`, `created_at`, `updated_at`; unique **active** booking per slot via partial index or transaction-safe equivalent; cancelled bookings retained for audit, not occupying a slot.
- `booking_tokens`: opaque high-entropy hashed action tokens, booking ref, purpose, expiry, used timestamp; no guessable admin links.
- `reminders`: booking, type, channel, due_at_utc, sent_at, attempt_count, status, error_message, unique booking+type+channel; timezone-correct, idempotent, retries bounded.
- `writer_submissions`: text, name/alias, optional contact, permission flags per medium, preferred credit, submission status, terms version/timestamps; keep private. Escaping, length limits, spam throttling, no automatic publication.
- `media_assets`: arrival-walkthrough file metadata and optional approved performer footage references. Media never executable. Size limits, MIME inspection, admin-only upload, allowlist, sanitized filenames, random disk names, file storage outside webroot with controlled serving, transcript/caption support.
- `host_actions`: minimal administrative audit (when, action, booking ref), no private content in logs.
- `sanitation_checks`: time, location (mic/lobby/bathroom), host-confirmed; suitable cleaning procedures from operating docs.
- `clip_candidates`: booking, tags (best_joke/good_premise/good_delivery/clip_this/invite_back/highlight/laundry), review status; never auto-publish.
- `performance_receipts` future/pending: only record if real evidence; no claimed proof of originality.

Build migrations, seed **synthetic** data for tests only (never seed fake comedian bookings into public production). Avoid implementing 40 tables.

## Booking and scheduling

- Define show date by **evening local calendar date**. A slot at 1:20 AM for Friday night has Saturday actual local datetime and a corresponding UTC instant.
- Honor local IANA rules, midnight and DST. Never silently fabricate nonexistent local times; test DST fall-back repeated hours or explicitly reject any ambiguous mapping until resolved.
- API can return booked/available slots without exposing performer PII. Re-query capacity server-side in an atomic write transaction. Double-submit, rapid concurrent requests, and cancellation reopens slot safely.
- Mark reserved blocks as `held`; allow admin set holds and walk-ins.
- On successful booking, provide confirmation and actionable signed Confirm/Cancel links. Require contact email, rate-limit and spam-protect public forms. Don't put phone/email/teleprompter in URLs, analytics, emails to other performers, client-side storage, or rendered HTML metadata.
- **Approved arrival/check-in contract:** open the arrival window at stage start **minus 20 minutes**; planned arrival/check-in is within **T−20 to T−10**, checking in **upon arrival**; the performer must be **on deck at T−10**. Display window and on-deck time, not a fabricated check-in deadline of T−20. Confirmation must display **event/show date AND actual stage calendar date** for after-midnight slots, local timezone, arrival window and on-deck target.
- Cancellation and confirmation link authorization must not reveal other people's data. Avoid emailing legal names unnecessarily.
- For private slots, **all stage/room media capture and recording must be confirmed OFF at host level**, including independent camera recording (Reolink SD/NVR/cloud) and microphones; warn/block check-in until verified. **The independent prerecorded house-ad/sketch broadcast may remain ON** only after the host confirms it is isolated from every room source and buffered/delayed output, with independent receiving-device verification. If verification fails, stop Twitch/OBS streaming and recording before check-in. A host UI checkbox is an acknowledgment, not actual source control. See [PRIVATE_REHEARSAL_BROADCAST_CONTINUITY.md](PRIVATE_REHEARSAL_BROADCAST_CONTINUITY.md).

## Reminder design

Bookings create due reminders:
1. Booking confirmation immediately (transactional).
2. Day of show around **2:00 PM local**, only if future and after booking time.
3. 2 hours before stage.
4. 30 minutes before the approved **arrival window opens** (50 minutes before stage); make its wording say when to arrive, not that check-in is due at T−20.
5. 10 minutes before stage (**on-deck cue**), except skip as appropriate if already completed/cancelled. If a reminder type/name already exists for the prior T−20 policy, change its displayed meaning without silently replaying queued mail or breaking persisted reminders.
Avoid nuisance duplicates or reminders after status changes. Script runs from host cron every five minutes. Persist durable send attempts with idempotency locking/claimed state; use proper From address/domain authentication. Confirmation/cancel links in reminder messages. **Email first; SMS only later with explicit SMS-specific permission and a configured vendor.** Silence/failure of mail provider should surface "email delivery unverified" and admin diagnostics, never pretend it was delivered.

## Admin / hosting UX

- Hardened login for host via HTTPS session and server-side password hash, login throttling, logout/session rotation, idle timeout, CSRF for every modification. No general public accounts. Never publish dashboard on stream.
- View and filter tonight's real lineup; check in/no show/performed; mark candidate clips/laundry; host note; review submissions, toggle slots, exceptions, sanitize tasks, upload walkthrough, inspect pending/cancelled reminders.
- Editing remote changes must reflect in public availability immediately.
- Private rehearsal safety flow must be unambiguous: distinguish **public broadcast state** from **studio room capture state**. Before check-in, require host acknowledgment that stage audio/video and every studio recorder/SD/NVR/cloud recorder are physically isolated/off, and that any continuing Twitch feed contains **only isolated prerecorded house media**, with latency/VOD tested from a separate viewer. If not proven, host stops the stream and local recording. Restore stage feed only after guest leaves and the next performer explicitly consents. The existing `confirmed_off` gate in PR #1 currently assumes full Twitch stop; change semantics/schema/UI only through a reviewed backward-compatible migration/test, and **keep old fail-closed behavior until end-to-end isolation is proven**. Do not claim OBS device control from a database flag.

## Public UX and sharing

- Mobile first, good contrast, keyboard access, labels/errors live announcements, legible fixed bottom call-to-action when useful; no heavy bundle.
- Visual language: comedy stage, not generic event SaaS. Projector/emoji memory cards are an onstage tool; a separate host view can optionally render timed cue cards without exposing scripts to viewers.
- Twitch embed `https://player.twitch.tv/?channel=cantonrefinery&parent=<actual-host>&... `; never place PII in player URLs. If HTTPS unavailable, do not attempt insecure embed; show watch-on-Twitch link.
- Make each show night a shareable URL with Open Graph `og:title`, `og:description`, `og:image` (original generic art), and canonical meta; use Facebook Sharer and Reddit submit link, Web Share API when supported, and copy-link fallback. No social platform APIs required.
- Facebook analytics: UTM capture for attribution, first-party privacy-conscious aggregate engagement counters, optional consent-gated Meta Pixel for permitted events (viewed_schedule / started_booking / booked) without PII, scripts, submissions, or performer identity. Never double-fire conversion on page refresh. Attribution limits are documented. Ad audiences and retargeting are configured in Meta outside the app.
- No fabricated audience counts or claims of online viewers, first-tell exclusivity, or stage hours when closed.

## Acceptance checks and coverage

Produce reproducible tests and a README with results. At minimum:
- Regular Sun/Mon/Wed/Thu/Fri/Sat generate 30 slots crossing local midnight; Tuesday none; 22 max public; schedule exceptions and held slots.
- Exact local/UTC mapping for 9 PM and 1:50 AM, and tests across DST week(s).
- Two concurrent/duplicate bookings cannot claim same slot, cancellation returns availability, signed links cannot be forged/replayed.
- Missing/invalid email, oversize text, CSRF, XSS payload, request spam and privileged actions denied without login.
- A live-only or private booking cannot be added to highlight publication; a private set requires **room-capture-off verification**. A separate preapproved house program may remain live, but never a private person's images/audio/metadata.
- Client can view public slots but cannot access DB, teleprompter, private submissions, logs, uploaded media or admin.
- Reminder times for before and after midnight, cancellation, retries and disabled/unconfigured email.
- Performance receipt is disabled or labelled pending until real timestamp/recording evidence exists.
- Responsive 360px mobile, keyboard form navigation, Vimeo/Twitch offline fallback (Twitch only if actual embed configured); PHP lint and JS syntax; all DB tests pass on supported PHP PDO SQLite host.

## Scope progression

**P0 (first usable show)**: functional HTTPS website, nightly schedule, 10-minute slots, booking confirmation, check-in, private host admin, rules/orientation/parking text+admin-upload video, Twitch player, share cards, writer submission permissions, simple terms/privacy. P0 may omit transactional reminders **only if explicitly marked unavailable**; never advertise mail success without transport.

**P1 (attendance reliability)**: SMTP-backed confirmations/reminders, signed confirm/cancel, sanitation checklist, host notes, date overrides, stable clip-candidate tags, aggregate measurement and gated Meta Pixel, audio/video consent review.

**P2 (creative economics)**: advanced proof/receipt, host shifts, formal comedy tag labs, livestream moderation tools, performer history, editor clips, AI trailer and music adaptation only with separate creator authorization, eventual optional Big Joke integration. No AI-written jokes silently promoted into performers' work.
