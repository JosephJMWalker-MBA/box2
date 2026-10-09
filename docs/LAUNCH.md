# BOX2 — Launch, Deployment and Risk Gates

**Status:** launch checklist. No certificate repair, PHP hosting verification, email provider setup, publicly advertised event, or venue compliance review has been completed by creating this repository.

## Separate technical rebuild from production repair

The owner reports the current BOX2 website HTTPS/SSL as broken. A new codebase **does not automatically repair DNS, TLS, reverse proxies, cert renewals, or server configuration**. Resolve HTTPS at the target hostname before accepting submissions or bookings. The existing site's files live on the owner's hosting; they **must be backed up** with permissions, .htaccess, config, uploads, and the old SQLite database (if present), then inventoried. Do not run destructive cleanup or overwrite production without approval, backup and rollback plan.

1. Confirm exact serving hostname(s), DNS A/CNAME, hosting control panel account, docroot, active SSL certificate chain/expiry, redirect behavior, and the owner’s access to the host. Use reversible diagnostics; do not guess host paths.
2. Test hosting PHP version >=8.2, PDO SQLite extension enabled, file permissions, `flock`/transactions, cron support, and outgoing SMTP transport. Record real results.
3. Stage code under non-public docroot or a protected preview; configure `BASE_URL`, secrets outside webroot, Twitch embed parent, backup paths, writable SQLite directory, error logs, file upload limits, and content security policy.
4. Enforce HTTPS for public/admin and form POSTs **only after a valid cert serves the hostname**; session cookies Secure/HttpOnly/SameSite; no PII form submission over HTTP. HSTS only after full hostname/certificate verification and rollback assessment.
5. Restore/seed only synthetic test data in staging, exercise actual booking/check-in/scheduled reminders, mobile player, forms, uploads, and web security. Validate rate limits and nightly retention behavior.
6. Back up old production. Arrange reversible cutover (symlink/atomic directory swap where supported) and rollback. Smoke-test with real host; do **not** send mail to real performers without permission.
7. Only then enable public bookings, publish verified venue instructions, promote Facebook/TikTok/Reddit, and consider ads.

## Premises and onsite safety

Proposed address: **2735 Harrison Ave NW, Canton, OH 44709**. Before publicly inviting walk-ins, verify that the lease, zoning/allowed use, occupancy/fire code, exits, parking rights, restroom access, building condition, insurance and recording/privacy arrangements accommodate recurring public comedy sessions. Owner has separately noted property maintenance/safety concerns in past conversations; inspect and address them before public access. Do not assume residence-adjacent activity or 2 AM hours are permitted. Distinguish a remote/stream-only soft opening from a physically open stage if approvals are not ready.

Venue rules include sober stage, late-night quiet, lobby waiting, no talking while a comedian performs, no disruptive mobile phones in the performance room, no unauthorized filming, comedy only except portable-instrument musical comedy, and an option to come perform and leave rather than mingle. Use a parking/entry walkthrough video **only after actual designated parking/access routes are approved**; add written alternatives and captions for accessibility.

Cleaning: microphone/surface cleaning between sets; stage-left restroom and lobby high-touch surfaces checked/disinfected each hour with appropriate products/contact times; documented log. Do not promise a sterile, germ-free or infection-free environment. Have illness cancellation route.

## Rights, consent and data handling

- Final Terms of Service, Privacy Policy and performer release must be reviewed for applicable legal requirements and actual practices before launch; drafted policy alone does not secure consent.
- Records of streamed performances can document when identifiable material was performed; they cannot conclusively establish original authorship or "first ever". A timestamp from ordinary DB writes alone is not independently tamper-evident proof.
- Clarify VOD platform retention, optional clips, purpose/retention of event evidence, third-party copies, and writer submission licenses. Do not retain unapproved clips to issue proof; distinguish storage after VOD expiration from absence of retained evidence.
- The host must actually stop Twitch/OBS/audio record for private rehearsals; no automated switch is assumed.
- Keep stage names/public session info separate from legal name/contact data. No performer email, legal name, phone, private scripts or original writer material in share cards, advertising analytics, URLs, logs or public API.
- Security include backups, file/SQLite exposure check, restore drill, patching/updates, anti-spam, admin lockouts, and incident contacts.

## Promotion and Meta tracking

- Public metadata for each show's canonical URL, Facebook share button, Reddit submit link, mobile native share. **No Reddit API integration.**
- Facebook Pages/Event/Ads interest and campaign analytics may be used externally; site stores campaign parameters and booking attribution without claiming to read private Facebook engagement automatically.
- Retargeting with a Meta Pixel is a **separate, gated activation**: add clear notice/permission as appropriate, default off for non-consenting users, allow revocation, do not send performer identifying info/joke scripts, verify events and deduplication. Minors and sensitive categories require additional caution; avoid targeting tactics that surprise visitors. Conversion tracking cannot guarantee total identity-level reach; interpret aggregated ad metrics honestly.
- Start with organic shares, measure actual reservations and attended performances; no automatic paid campaigns, budgets, or posts without owner approval.

## Launch definition

The platform may publicly say "Booking open" only after SSL, database persistence, duplicate prevention, email confirmation behavior/disabled-label, venue status, admin authorization and cancellation are proven on production infrastructure.

The owner may promote BOX2's **concept, livestream, and interest form** earlier if disclaimers clearly say walk-in bookings aren't yet open and consent/secure data collection is not exposed over HTTP.

## Handoff and rollback evidence

Every deploy plan must state:
- Actual host and versions verified.
- Production environment secrets/settings needed (not values).
- Exact command/file paths for migrating DB, backing up, turning on/off bookings, setting cron and testing `cantonrefinery` iframe on actual parent host.
- Date/time test report (including after-midnight and DST).
- Readiness of venue/public walk-in access separately from web readiness.
- Known deficiencies and a five-minute rollback path (restore files and DB atomically or cancel bookings).
- Version and changelog; explicitly distinguish proposed design, local tests, staging tests, and production verification.

## One-step Codex directive

Build to `docs/PRODUCT.md` and `docs/IMPLEMENTATION.md`, follow `AGENTS.md`, write tests, and propose a PR with local proof; do not deploy or claim HTTPS/booking readiness before infrastructure tests and explicit approval.
