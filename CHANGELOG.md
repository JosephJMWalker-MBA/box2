# Changelog

## 0.2.0 — Release-readiness reconciliation (no deployment)

- Reconcile main's approved arrival and parking corrections into PR #1.
- Restore nine explicit orientation cards, readable rules, established poster
  styling, and three booking steps with preserved input during night changes.
- Apply T−20 through T−10 arrival, immediate check-in, and T−10 on-deck target
  consistently in orientation, receipts, reminders and host views.
- Reserve 1/2/3 consecutive calendar allocations atomically for 5/10/15-minute
  sets, prevent range overlap and occupied-tail edits, and release whole ranges.
- Add safe migration and legacy outbox wording refresh without replay or false
  updated consent. Preserve separate default-off recording and writer grants.
- Extend PHP/HTTP/security/upgrade/concurrency/DST tests and run responsive
  Chromium tests in PHP 8.2/8.5 CI. Keep launch permission gates disabled.

## 0.1.0 — Implementation for review

- Plain PHP/SQLite MVP with six-night recurring schedule, zoned UTC slots,
  public/held/private allocations, host exceptions, and atomic booking.
- Orientation cards with progressive HTML fallback; explicit recording and
  writer grants, expiring hashed/signed booking links, and cancellation.
- Private hardened host desk, walkthrough upload, cleaning record, candidate
  tags, walk-in import, writer desk, and provider queue diagnostics.
- Durable optional SMTP/local-mail reminder worker; disabled by default.
- Twitch configuration/fallback, Facebook/Reddit/native share links, original
  share artwork, privacy/terms drafts, version footer, and rollout runbook.
- Reproducible PHP, HTTP, optional browser, and backup/restore checks; CI targets
  PHP 8.2/8.5. Bookings, mail, and venue publication start disabled.
- No production deployment or operational readiness claim.
