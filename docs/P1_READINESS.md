# Issue #4 P1 Readiness

October 13, 2026. Focused successor to PR #1, stacked on its reconciled foundation.
Main through `e3db34fd7b321297cf54309de6207900e0c169bd` is included; no verified
implementation or baseline tests were discarded. No merge to main, deployment,
live OBS/device operation, real performer mail, venue publication or ads occurred.

## Implemented and synthetic evidence

- Normal nine-card / 5/10/15-minute / T−20..T−10 bookings remain intact, including
  unrecorded choices. Public nonpublic inventory is uniformly unavailable; private
  reservations do not change its public projection. Form-requested choices return
  only free times, not an occupied roster or cause. No guest names/entry notes,
  source state, legal/contact/script data or editorial titles flow to public views.
- Migration `003.sql` retains records and grants no old recording confirmation
  authority. New source/room states start unknown; old checked-in private occupancy
  remains held. Source assertions expire/tie to host session and code version.
  Failure, fault, restart declaration and changed session block admission. House
  continuity remains false by default; physical departure is separately asserted.
- Private editorial source/timecode ledger with clip-specific performer/writer
  capabilities, separate default-off destination/face/voice/credit grants, approved
  selections at positions 1–5, edit review and recorded HTTPS post URLs. Sixth and
  unauthorized/private/live-only/unclear-writer moments are denied. No actual
  recording, renderer, social API, uploader or automatic publishing is provided.
- Existing baseline suites: 78 core, 64 adjacent-block and 65 migration checks;
  setup/backup/restore/retention drill retained. New capture/privacy/editorial suite:
  64 checks. Expanded real loopback HTTP suite: 67 checks. Additional legacy-capture
  upgrade test verifies unknown/new states, occupied privacy and disabled gates.
- Responsive browser checks at 360px/1280px preserve all prior keyboard/onboarding,
  duration, state-preserving night change and booking/login cases; add a normal
  private 15-minute booking, anonymous projection privacy, a clip-specific default-off
  release, candidate approval/selection and populated private editorial layouts.
  Synthetic screenshots only; no old private screenshots are committed.
- PHP lint, JS syntax and patch checks run. CI requires backend/security/booking/
  migration/concurrency and responsive Chromium on both PHP 8.2 and PHP 8.5.
  Exact verified head/workflow links are recorded in the successor PR after CI.

## Scope and limitations

Software proves data/control rules, not OBS/Reolink storage, outgoing media,
VOD, a real post, identity or legal rights. `allow_bookings=false`,
`venue_public_enabled=false`, mail disabled and `allow_house_continuity=false`
remain shipped defaults. House assertions are permitted in synthetic tests only.
No absolute physical-location secrecy or specified/verified stream delay is promised.
Publication URLs are manually recorded, private attestations, not remote posting proof.
Raw media and actor credit never become public through this ledger.

Remaining production blockers: independently receiving-device-tested room/source
isolation including SD/NVR/cloud/events/buffers, actual source reset/reconnect and
guest departure procedures, approved terms/rights/retention and author identity
review, real host HTTPS/PHP/SQLite/cron/mail and Twitch parent verification, safe
premises/parking/access and approved walkthrough, old-site backup/staging restore
and separately approved cutover. Actual filming, editing/publishing, creator
accounts, ads, live OBS, bookings and venue activation remain separate approvals.
See `MANUAL_CAPTURE_AND_EDITORIAL.md`, `RUNBOOK.md` and canonical launch specs.
