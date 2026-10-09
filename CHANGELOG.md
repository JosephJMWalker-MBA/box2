# Changelog

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
