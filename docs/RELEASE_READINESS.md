# BOX2 0.2.0 Readiness Evidence

Release-readiness pass for PR #1, October 9, 2026. **Review/staging candidate,
not production-ready. No PR merge, deployment, DNS/TLS changes, real mail, or
venue publication was performed.** `allow_bookings=false` and
`venue_public_enabled=false` remain the shipped configuration defaults.

## Reconciliation and implemented behavior

- Main documentation through `adc1f3a` was integrated into
  `codex/secure-box2-mvp`. Existing implementation, migrations, and tests were
  preserved. The deleted inaccurate parking graphic was not resurrected.
- Nine individually acknowledged cards cover philosophy, arrival/parking,
  finding BOX2, check-in flow, environment, facility/cleaning, sober culture,
  audience/recording, and mindset. Shared content is readable on `/rules`.
  Warm lined-paper/cream, oversized black type, outlined/shadowed cards, orange
  controls, and restrained yellow accents remain the visual system.
- Three booking steps preserve entered data through back navigation and live
  schedule refreshes. New reservations require the current orientation version.
- Arrival is T−20 through T−10, check-in is immediate on arrival, and on-deck is
  T−10. Shared timing helpers drive receipts, reminders and host views; stage
  date/time is separate from the show's evening date.
- 5/10/15 stage minutes atomically reserve 1/2/3 adjacent ten-minute allocations.
  Every allocation is protected, cancellation releases the whole range, and
  hosts cannot edit occupied tails. Stage and calendar durations are explicit.
- Only stand-up, sketches/characters, host practice, and portable-instrument
  musical comedy are accepted. Livestream/archive/clips/adaptation/feedback
  remain separate and default off. Private and live-only hardware/VOD gates
  remain enforced, with no automatic OBS control or publication.
- Twitch, Facebook/Reddit/native sharing, writer privacy/grants/withdrawal,
  booking security, reminder claims/retries, and backup/restore remain intact.
  Email defaults disabled; provider acceptance is not proof of inbox delivery.

## Reproducible local verification

Local PHP 8.5.7/PDO SQLite and isolated Chrome results:

| Suite | Result | Coverage |
| --- | --- | --- |
| `php tests/run.php` | 78 checks pass | Existing security, scheduling, consent, cancellation, signed links, retries and process collision coverage |
| `php tests/blocks.php` | 64 checks pass | All lengths, real contiguous options, overlap/tail protection, whole-range cancellation, stale consent, categories, midnight/DST and different-start concurrent range race |
| `php tests/migrations.php` | 65 checks pass | Safe legacy backfill, no invented new consent, unchanged tokens and outbox identities/due times/attempts/claims, no message replay |
| `php tests/http.php` | 50 checks pass | Real SSR/POST flow, private data/auth/CSRF, long-set receipts/host view, aliases/subpath/sharing, copy scan and disabled-gate enforcement |
| `php tests/ops.php` | 3 groups pass | Private setup/defaults, consistent backup/atomic synthetic restore, retention |
| `node tests/browser.cjs` | Pass | Nine-card progression/back/keyboard, three steps, actual length filtering, retained input on night changes, default-off grants, full booking/login, no-JS fallback, no JS errors/overflow |
| PHP lint / JS syntax / diff checks | Pass | All application, CLI, migration-test and deployment PHP; vanilla JS; clean patch whitespace |

Browser evidence includes fresh screenshots at 360px and 1280px. Artifacts are
generated from synthetic fixtures outside the repository; no owner legacy
screenshots, personal contact images, or unapproved maps are committed. Test
fixtures alone enable booking/venue flags to exercise behavior on loopback.
The HTTP suite also explicitly disables both and verifies denial/withholding.

CI now runs PHP/security/concurrency/upgrade suites and the responsive Chromium
suite independently against **PHP 8.2 and 8.5**. Playwright is a pinned,
development-only CI dependency installed outside the application. Production
requires neither Node nor a frontend build. The final verified commit and exact
workflow results are recorded on [PR #1](https://github.com/JosephJMWalker-MBA/box2/pull/1).
Screenshot artifacts are named `box2-responsive-php-8.2` / `box2-responsive-php-8.5`.

### Representative timing evidence (synthetic)

- Friday show 2030-10-11, stage 23:50 EDT: a 15-minute set ends Saturday 00:05
  EDT, while its three calendar allocations end 00:20 EDT. Arrival is Friday
  23:30–23:40 EDT, check-in on arrival, on-deck 23:40 EDT.
- Stage Saturday 00:10 EDT belongs to Friday's show. Arrival crosses midnight:
  Friday 23:50 through Saturday 00:00 EDT; on-deck Saturday 00:00 EDT.
- Fall-back stage 2030-11-03 01:50 EDT (`05:50Z`) ends 01:05 EST (`06:05Z`)
  after 15 real minutes. Three contiguous allocations end `06:20Z`; timezone
  labels distinguish repeated wall times. Spring invalid endpoints still close
  for explicit host correction; ambiguous endpoints are rejected.

## Copy and privacy audit

Runtime pages, configuration defaults, README, and runbook contain no obsolete
T−20 check-in deadline, commercial overflow recommendation, gravel-lot advice,
non-comedy performance option, unapproved map, or unsupported “reminders on”
claim. Private scripts/contact data stay out of public slots/share metadata.
`/arrival` withholds address, configured directions, and media before approval;
navigation does not advertise it until venue publication is enabled.

Intentional source/history exceptions: canonical parking/reconciliation docs
retain prohibited examples as owner instructions; negative tests name rejected
categories; the upgrade fixture contains old check-in wording to prove its safe
replacement. Accepted/claimed/uncertain historical outbox payloads remain intact
for audit and are not replayed. None are public guidance.

## Remaining production blockers

1. Verify real host PHP/SQLite/permissions/cron, valid HTTPS/certificate chain,
   exact serving host/base path, and protected staging. No SSL repair is claimed.
2. Review premises, permitted public access, safety, parking rights/bays, routes,
   accessible entrance, lighting, emergency clearance, and actual walkthrough.
   No generated diagram, satellite reconstruction, neighboring lots, or private
   routing is approved for public use.
3. Review actual terms/releases, recording/VOD retention, hardware stop/resume
   procedures, and cleaning operations/logs. New code does not authorize hazards.
4. Configure sender/provider/domain authentication and verify real confirmation,
   cancel links, reminders and recipient receipt with approval. SMTP acceptance
   and local tests do not demonstrate inbox delivery. SMS remains unimplemented.
5. Verify Twitch on the real HTTPS parent and maintain actual off-stream/private
   blocks. No live state or viewer counts are invented.
6. Back up old site/database/config/uploads, rehearse restore and reversible
   cutover in protected staging, and resolve earlier booked-performer policy
   notices. Final permission-state changes require explicit launch approval.

See `RUNBOOK.md` and `LAUNCH.md` for procedures. Automated media production,
Meta/marketing analytics, SMS, payments, public profiles, waitlist, and proof of
originality remain deferred. This pass changes no live infrastructure.
