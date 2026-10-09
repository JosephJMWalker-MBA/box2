# BOX2 — Come Tell It Here First

A Canton, Ohio comedy development stage and livestream. **Everybody starts somewhere. Start here.**

This repository is the **canonical source for the new BOX2 site**, replacing an older host-only deployment after verification. The existing server files must be backed up; do not overwrite them blindly.

## Build handoff

- Read [AGENTS.md](AGENTS.md) for implementation invariants.
- Read [docs/OPERATING_MODEL_AND_EXECUTION_PLAN.md](docs/OPERATING_MODEL_AND_EXECUTION_PLAN.md) for the complete business model, current PR inventory, gap analysis and release sequence.
- Read [docs/PRODUCT.md](docs/PRODUCT.md) for product, audience, program, stage culture, and consent requirements.
- Read [docs/IMPLEMENTATION.md](docs/IMPLEMENTATION.md) for data model, PHP/SQLite stack, rollout phases, and tests.
- Read [docs/LAUNCH.md](docs/LAUNCH.md) before touching DNS, SSL, deployment, or publicity.
- Read [docs/LEGACY_UI_RECONCILIATION.md](docs/LEGACY_UI_RECONCILIATION.md) and
  [docs/ARRIVAL_PARKING_AND_OUTREACH.md](docs/ARRIVAL_PARKING_AND_OUTREACH.md)
  for the nine-card flow, approved arrival window, and parking publication block.

## Product model

**Book → Show up → Perform → Optional feedback/tags → Optional clip → Return.**

We welcome first-time comics, developing performers, working comics, touring comics, hosts, and joke writers. This is a sober, comedy-only development room—not a roast-the-previous-comic competition. The performer owns their material and chooses publication permissions.

## Technical approach

Mobile-first, accessible, server-rendered **plain PHP + SQLite + HTML/CSS/vanilla JS**. No React, node frontend runtime, app framework, public user accounts, payments, complex dependencies, or required third-party login for v1.

Host/admin is authenticated, secure, and private. Bookings and writer submissions are private server-side data.

## Environments

- Primary known site: https://box2.yurrmom.com
- Potential share/alias route: https://yurrmom.com/box2 (only after routing is explicitly arranged)
- Twitch: https://www.twitch.tv/cantonrefinery
- Venue address is held in the launch/operations plan; only publish after verifying premises, permissions, and safety.

Current status: **MVP implementation for review, locally verified; not deployed**. Do not claim the replacement site is deployed, production booking enabled, SSL repaired, reminders delivered, or venue access approved until verified.

## Codex task

> Build BOX2 from this repo's AGENTS.md and docs as canonical scope. Implement the smallest secure runnable PHP/SQLite MVP; add tests and deploy instructions; do not touch live hosting or real people without explicit approval. Preserve all phase boundaries and mark missing integrations as disabled/configuration-required, never pretend they work.

## Run the MVP locally

Requires PHP 8.2+ with `pdo_sqlite`, `mbstring`, and `fileinfo`. No Composer,
npm, public accounts, or production frontend build is required.

```sh
php bin/setup.php --local
php -S 127.0.0.1:8080 -t public public/router.php
```

Setup prompts for a host password with hidden input, creates a hash and random
signing secret in ignored `config.local.php`, applies migrations, and generates
28 days of real schedule rows. Open `http://127.0.0.1:8080/` and `/admin/login`.
Use `BOX2_CONFIG=/absolute/private/config.php` to keep configuration elsewhere.
`public/` is the only web document root; never serve the repository root.

Defaults deliberately keep bookings, venue publication, and email disabled.
Only explicit `environment=local` on loopback permits forms without HTTPS.
Tests use isolated synthetic configuration to enable booking; production gates
are not changed by tests. Local login works after setup. Writer forms work in
explicit loopback local mode but remain private.

## What is implemented

- Six recurring show nights with UTC slot identities, 22 public blocks, six
  host holds, two labelled private blocks, date exceptions, and guest hosts.
- Atomic 5/10/15-minute sets reserve 1/2/3 adjacent ten-minute allocations.
  Stage duration and calendar reservation are displayed separately. Cancellation
  releases the entire reservation; occupied tail allocations cannot be changed.
- Nine individually acknowledged performer orientation cards and three booking
  steps, with a readable full-form fallback and preserved entered state,
  separate consent choices, exact show/stage dates and check-in times.
- Arrive T−20 through T−10, check in immediately upon arrival, and be on deck
  at T−10. Receipts, host views, orientation, and reminders share these times.
- Password-based private host desk with CSRF, throttling, idle expiration,
  status/notes/tags, walk-in import, slot controls, and sanitation records.
- Private original writer submissions, separate grants, credit preference,
  and prospective withdrawal before production.
- Host-approved MP4/WebM arrival walkthrough and text transcript, stored
  privately and served through a controlled endpoint after venue approval.
- Configured HTTPS Twitch iframe for `cantonrefinery`, with honest watch-link
  fallback and no invented live state. Facebook/Reddit links, native sharing,
  and original Open Graph artwork; no social APIs.
- Durable reminder queue, bounded retries, SMTP STARTTLS or optional local
  mail adapter, and provider acceptance diagnostics. Defaults to disabled.

## Automated verification

```sh
php tests/run.php
php tests/blocks.php
php tests/migrations.php
php tests/http.php
php tests/ops.php
find app public bin deploy tests -name '*.php' -exec php -l {} +
node --check public/assets/site.js
```

The PHP suites use disposable data, no external mail, and no real people.
The HTTP suite starts/stops a loopback server. Concurrency uses `pcntl` when
available (enabled in CI). Optional browser tests use development-only
Playwright plus Chrome:

```sh
# Install Playwright outside the production application, or use an existing runtime.
BOX2_PLAYWRIGHT=/absolute/path/to/playwright node tests/browser.cjs
```

CI runs PHP/security/concurrency/upgrade suites and responsive Chromium tests
against PHP 8.2 and 8.5. Browser test tooling is installed outside the production
application. See [the runbook](docs/RUNBOOK.md) for deployment,
backup/restore, cron, config, test evidence, and explicit limitations.

## Not verified on production

No live server, DNS, SSL, Twitch playback, SMTP delivery, venue permissions, or
public walk-in readiness was changed or verified by this implementation.
Performance receipts, automated clips/AI/music production, SMS, Meta Pixel,
marketing analytics, public profiles, payments, and a waitlist are not shipped.
All existing launch gates in [docs/LAUNCH.md](docs/LAUNCH.md) remain applicable.
