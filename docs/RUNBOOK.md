# BOX2 MVP Runbook

Version 0.2.0. Implementation/test evidence only; no production deployment,
certificate repair, mail delivery, public venue access, or Twitch playback claim.
`PRODUCT.md`, `IMPLEMENTATION.md`, `LAUNCH.md`, and `AGENTS.md` remain canonical.
`LEGACY_UI_RECONCILIATION.md` and `ARRIVAL_PARKING_AND_OUTREACH.md` supersede
legacy visual references and parking/arrival instructions. Main through
`adc1f3a` was reconciled into the PR branch without replacing the implementation.

## Local and staging setup

Use PHP 8.2+ with PDO SQLite, mbstring, fileinfo, OpenSSL, sessions, and writable
private storage. `pcntl` is optional outside CI. PHP 8.5.7 with all these
extensions was verified locally. PHP 8.2 is a CI target, not a locally run claim.

1. Set the document root to this checkout's `public/`, never its root.
2. Run `php bin/setup.php --local` for loopback development. Omit `--local` for
   an approved staging/production host. Choose a password (12+ characters).
3. Edit ignored `config.local.php` outside `public/`. Alternatively set
   `BOX2_CONFIG` to an absolute private file returning the config array.
   Setup also accepts `BOX2_STORAGE` for an explicit private data directory.
4. Run `php bin/migrate.php`. Migrations are versioned, transactional, and
   idempotent. Re-running schedule generation does not overwrite host edits.
5. For development: `php -S 127.0.0.1:8080 -t public public/router.php`.

Default gates: `allow_bookings=false`, `venue_public_enabled=false`, mail
transport `disabled`, Twitch parents empty. No secrets are tracked. Local mode
permits HTTP only when PHP sees the remote address as loopback. Never enable
local mode on a public host or HTTP reverse-proxy listener.

### Configuration checklist

Configure values after host verification; do not publish secret values:

- `base_url`: exact serving origin plus optional path, e.g. approved
  `https://box2.yurrmom.com` or arranged `https://yurrmom.com/box2`.
- `public_path`: actual public document root. `storage_path`: absolute private
  directory with mode 0700; database/config files mode 0600 and owned by PHP.
- `secret`: 32+ random bytes; `admin_password_hash`: PHP password hash generated
  during setup. Changing the signing secret invalidates existing action links.
- `environment=production`: sensitive POSTs require PHP's own HTTPS flag.
  Forwarded headers are not trusted. TLS termination must supply verified HTTPS
  state through the trusted server/FastCGI configuration, not client headers.
- `venue_public_enabled`: publish verified address/walkthrough only after the
  premises and approved routes pass `LAUNCH.md`. Edit `arrival_text` to actual
  parking, walk, entry, access, and restroom instructions; no invented permissions.
- `allow_bookings`: enable only after infrastructure, consent/terms, venue,
  cancellation, persistence, mail unavailable/delivery behavior, and host checks.
- `set_lengths`: configurable subset of `[5,10,15]` stage minutes, requiring
  respectively 1/2/3 adjacent ten-minute calendar allocations. UI choices derive
  from real contiguous capacity; the server rechecks every allocation atomically.
- `twitch_channel=cantonrefinery`; `twitch_parents`: actual hostname(s), no
  scheme/path. Embed requires HTTPS and the configured serving host. On screens
  too narrow for Twitch's minimum player width, use the external watch link.
- `vod_retention_days`: disclosed BOX2 archival window. Hosts must implement
  actual media cleanup and platform settings; DB retention does not erase VODs.
- `retention_days`: default 90 for resolved bookings and writer text. Run the
  retention command and separately expire/encrypt backups under operator policy.
- `mail_transport=disabled|smtp|local`, `email_from`, SMTP host/port/user/password.
  SMTP uses STARTTLS with certificate verification. Local PHP mail is optional
  and must be proven on the host. No mail is sent during automated tests.
- `meta_pixel_id`: reserved only. No Pixel or retargeting implementation loads
  in this release; no sensitive attribution data is collected.

Twitch iframe requirements follow [Twitch's embed documentation](https://dev.twitch.tv/docs/embed/video-and-clips/).
Actual channel/parent playback must still be verified on approved HTTPS staging.

## Supported web layouts

### Configurable document root

Keep the whole checkout private and point Apache/Nginx at `<release>/public`.
Apache must support `mod_rewrite` and the provided `.htaccess`; otherwise put
equivalent front-controller routing in server configuration. For Nginx, route
non-assets to `/index.php` with original query parameters; only this front
controller needs PHP execution. Disable directory listing. Do not add HSTS until
valid certificates and rollback assumptions have been checked.

### Fixed `public_html`

Supported without placing the app or SQLite under public_html:

```text
~/box2/             complete private checkout
~/public_html/     deploy/public_html/index.php copied here as index.php
                   public/.htaccess copied here
                   public/assets/ copied here as assets/
```

The launcher loads `../box2/public/index.php`. Set private config `public_path`
to the actual `~/public_html` path and `storage_path` to `~/box2/var` (expand `~`
to absolute paths). Serve only the launcher and static assets. If the host
cannot keep app/config/storage/uploads/backups outside the public root, block
launch and choose suitable hosting. This layout is supplied, not tested on a
real shared host.

## Show and host operations

Regular show dates are Sun/Mon/Wed/Thu/Fri/Sat, 21:00–02:00 America/New_York.
Slots store UTC identity, preserving repeated fall-back hours (36 actual blocks
on a six-hour DST night). Spring-forward nights with a nonexistent 02:00 endpoint
are generated closed with a visible note; the host must explicitly adjust valid
hours and open blocks. Ambiguous endpoints are rejected. A regular night has
30 ten-minute allocations; 22 public, six held, two private.

### Arrival and set-length contract

Arrive **T−20 through T−10**, never earlier; **check in immediately upon arrival**
and be **on deck at T−10**. Arriving at T−10 requires check-in and readiness at
once, not a guaranteed grace period. `arrival_times()` supplies UTC targets;
receipt, host, and email display helpers preserve the actual calendar date/time
and timezone, including windows crossing midnight or a repeated DST hour.

Five stage minutes reserve ten calendar minutes, ten reserve twenty, and fifteen
reserve thirty. The full reservation includes host/reset buffer. `bookings`
stores `duration_minutes` and `block_count`; `booking_allocations` reserves every
underlying slot with a unique active-slot index. A booking cannot span held,
closed, missing, occupied, or mixed private/public allocations. Hosts may import
authorized walk-ins into compatible held blocks. Cancelled allocations become
inactive but retain history; every block reopens together. Slot identities stay
immutable across schedule edits. Host views distinguish stage end from reserved
calendar end. Default permissions remain off; longer public sets do not require
clip or archive permission beyond the explicitly selected livestream grant.

The nine shared `/rules` cards drive progressive onboarding. No browser storage
remembers an old acceptance; new bookings must report the current orientation
version (`2026-10-09`). Back/forward navigation and schedule fetches preserve
entered performer data and explicit grants in the current form. Without JS,
all nine cards and the full form remain readable and server validation still
checks capacity and consent. Dynamic start filtering uses JS; without it the
server can reject a longer choice that no longer fits.

Parking maps, exact bays, entrances, accessible routing, and public venue access
remain unapproved. No generated map, third-party overflow parking, private/VIP
route, or invented geometry is supplied. `/arrival` is an honest unpublished
walkthrough state until approval; `/arrive` remains a compatible alias. Address,
configured directions, videos, and the public arrival navigation link stay
behind `venue_public_enabled`. Hosts must verify actual rights, routes, premises,
and cleaning procedures before opening either permission gate.

### Upgrade from 0.1.0

Migration `002.sql` adds length fields and backfills each existing booking as a
five-minute/one-allocation reservation. It preserves cancelled history and
original consent versions. Existing links, IDs, contact privacy, tokens, and
queue entries are retained. The cancellation trigger releases all active
allocations in the same transaction. Back up before migration and test restore.

Migration and the worker refresh only eligible unsent legacy payloads to the
approved arrival wording while preserving original links, due times, attempt
counts and states. Persisted `check_in_30` remains its original type/unique key,
but displays as an **arrival reminder**; `stage_10` displays as an **on-deck cue**.
Accepted, claimed, uncertain, and skipped messages are not rewritten or replayed.
Malformed old payloads become `uncertain` for host review rather than being sent.
Hosts must notify already-booked performers of material policy changes; the
upgrade does not fabricate a new consent acknowledgment or send old mail again.

Admin can close a night only after cancelling existing bookings and notifying
performers. Cancellation stops future reminders but does not currently send a
separate cancellation email; host notification is an explicit operational step.
Occupied slots cannot change time/visibility. Adjusted hours retain old slot IDs;
out-of-range slots close and new slots start held. Deliberately open them in the
host desk. Guest hosts and public exception notes appear to bookers.

For private rehearsal, actually stop Twitch/OBS, all VOD/local recording, and
other recording devices, then acknowledge `confirmed_off`. App check-in blocks
private sets until this acknowledgment. It cannot switch external equipment.
Finish/cancel the checked-in private rehearsal before recording public mode can
resume. Live-only check-in requires a separate per-set confirmation of disabled
Twitch VOD/local recording. Verify archive and clip grants before any publication.

Clip/Laundry tags are editorial candidates only. No publishing endpoint exists.
Writer performance/publication/AI/music grants are independent; a host marking
production begun must verify the relevant grants manually. No public writer feed
or social automation exists. Keep host pages off projectors and streams.

Uploads accept MP4/WebM <=25 MB inspected with fileinfo. Set host PHP
`upload_max_filesize=25M`, `post_max_size=28M` (or suitable bounds). Transcript is
required. Stored random filenames are private, nonexecutable, and served with
validated byte ranges only after venue publication. No public arbitrary-file
serving or performer upload exists. Caption-track authoring is not shipped;
the text walkthrough is the accessible alternative.

Record actual microphone cleaning between performers and lobby/stage-left
bathroom high-touch cleaning hourly, using suitable products/contact times.
Do not represent the log as infection-free certification.

## Email queue and cron

Configure cron using the actual PHP binary, private config, and release paths:

```cron
*/5 * * * * BOX2_CONFIG=/private/config.php /usr/bin/php /private/box2/bin/cron-reminders.php
10 12 * * * BOX2_CONFIG=/private/config.php /usr/bin/php /private/box2/bin/migrate.php
20 12 * * * BOX2_CONFIG=/private/config.php /usr/bin/php /private/box2/bin/retention.php
```

Book commits enqueue confirmation immediately plus future day-of 14:00, stage
minus two hours, arrival-window opening minus 30 minutes (T−50), and the
on-deck cue at stage minus ten minutes. Dates
use the show's evening, not the after-midnight stage date. The worker claims
rows in an atomic write transaction; other workers cannot claim the same row.
Retries stop after three attempts with backoff. Cancelled/no-show/performed
bookings and stale non-confirmation reminders are skipped. Disabled transport
does not claim delivery; enabling a verified transport permits eligible disabled
rows to be processed. Monitor the queue before enabling it on an old database.

`accepted` means transport/provider acceptance, not verified inbox delivery.
Lost SMTP DATA acknowledgment or an interrupted worker becomes `uncertain`
and is not retried automatically. Verify provider logs before manual requeue.
Exactly-once inbox delivery cannot be guaranteed by SMTP. No SMS vendor is wired.
Provider/domain authentication and real recipient delivery remain launch gates.

## Backup, restore, and rollback

```sh
BOX2_CONFIG=/private/config.php php bin/backup.php
```

This uses SQLite `VACUUM INTO` for a consistent copy under private `backups/`.
Also back up config, reviewed uploads, code version, permissions, and original
server inventory. Never replace the old site without an owner-approved backup.

Restore drill/rollback:

1. Disable bookings in private config; take the site out of service and stop
   all PHP workers and cron so no DB connection remains open.
2. Preserve the current DB/config/uploads and known-good release. Confirm backup
   integrity and file permissions; do not overwrite production speculatively.
3. Run `php bin/restore.php /private/backup.sqlite --confirm` with private config.
   It requires disabled bookings, refuses sidecars, validates integrity/schema,
   and atomically swaps the staged backup. It cannot prove workers were stopped.
4. Run migrate, integrity and smoke checks; restore the matching code/config
   release and tested uploads. Re-enable only after approved verification.

A five-minute rollback target is: stop access, disable booking, atomically
select the prior verified code release, restore its DB snapshot as above, and
smoke-test before reopening. Actual timing depends on host access and must be
measured in protected staging. No five-minute production guarantee is claimed.

## Local evidence and remaining limitations

Local tests run on PHP 8.5.7 / PDO SQLite and isolated Chrome:

- Runnable PHP suite: schedule/timezone/DST, collisions and two-process race,
  rollback/cancellation, token forgery/expiry/replay, consent/auth/CSRF, throttle,
  writer grants/withdrawal, MIME rejection, reminder timing/retries/uncertainty.
- Actual loopback HTTP suite: booking persistence, auth/CSRF/session rotation,
  escaped private host views, no PII in public slots or confirmation metadata,
  private paths denied, link GET safe from email scanners, explicit mail disabled.
  Show-date canonical permalinks and configured subpath assets are exercised.
- Synthetic backup/restore drill: consistent private snapshot, atomic restore,
  preserved slots, integrity check, retention CLI.
- Adjacent-block suite: 5/10/15 availability and reservations, overlapping
  different-start process race, full cancellation release, midnight and repeated
  DST-hour durations, withheld/closed boundaries, comedy categories, stale
  orientation rejection, private recording and live-only clip restrictions.
- Upgrade/outbox suite: additive migration, historical reservations/consent,
  token continuity, unchanged queue IDs/attempts/claims/due times and no replay.
- Browser suite: nine cards, exactly one step per acknowledgment, back navigation,
  keyboard completion, three booking steps, actual length filtering and preserved
  input during night changes, full form submit, host login, no JS errors, 360px/1280px
  layout without horizontal overflow. Screenshots generated outside repository.
- PHP lint and vanilla JS syntax. GitHub CI additionally targets PHP 8.2/8.5;
  see PR checks for remotely completed evidence.

Evidence for this pass is recorded in `RELEASE_READINESS.md` with the tested PR
head and CI results. All tests use synthetic data; they are not production
booking or email evidence.

Explicitly unverified: production HTTPS/certificates/DNS, hosting/cron behavior,
actual mail recipient delivery, actual Twitch embed, venue/legal terms approval,
real walkthrough/parking route, OBS operation, shared-host layout, and production
backup restore. No live server was changed. No automatic media cleanup,
publication, AI/Suno/clip generation, SMS, Meta instrumentation, ad analytics,
public profiles, payment, waitlist, or originality proof is provided. A consent
grant does not create an integration or ownership transfer.
