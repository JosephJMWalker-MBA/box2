# BOX2 — Come Tell It Here First

A Canton, Ohio comedy development stage and livestream. **Everybody starts somewhere. Start here.**

This repository is the **canonical source for the new BOX2 site**, replacing an older host-only deployment after verification. The existing server files must be backed up; do not overwrite them blindly.

## Build handoff

- Read [AGENTS.md](AGENTS.md) for implementation invariants.
- Read [docs/OPERATING_MODEL_AND_EXECUTION_PLAN.md](docs/OPERATING_MODEL_AND_EXECUTION_PLAN.md) for the complete business model, current PR inventory, gap analysis and release sequence.
- Read [docs/LIVE_STUDIO_AND_GALAXY_SET.md](docs/LIVE_STUDIO_AND_GALAXY_SET.md) for the observed live OBS milestone, black-to-galaxy studio plan, privacy-safe broadcast operation and host readiness checklist.
- Read [docs/PRIVATE_REHEARSAL_BROADCAST_CONTINUITY.md](docs/PRIVATE_REHEARSAL_BROADCAST_CONTINUITY.md) for normal private performer bookings while the isolated Twitch house ads/sketches continue, including source-isolation tests and confidential guest protection.
- Read [docs/PRODUCT.md](docs/PRODUCT.md) for product, audience, program, stage culture, and consent requirements.
- Read [docs/IMPLEMENTATION.md](docs/IMPLEMENTATION.md) for data model, PHP/SQLite stack, rollout phases, and tests.
- Read [docs/LAUNCH.md](docs/LAUNCH.md) before touching DNS, SSL, deployment, or publicity.

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

Current status: **Codex PHP/SQLite MVP exists in PR #1 and has passed local/CI checks, but is not verified deployed**. Owner demonstrated an active OBS stream of the evolving studio on 2026-10-09; Twitch playback, stream delay, actual private audio/video isolation and viewer-facing VOD are not yet independently verified. The legacy website remains visible; HTTPS browser trust displayed a warning despite a valid certificate. Do not claim the replacement site is deployed, bookings or venue entry enabled, HTTPS fully fixed, reminders delivered or clip publication operational until verified.

## Codex task

> Build BOX2 from this repo's AGENTS.md and docs as canonical scope. Implement the smallest secure runnable PHP/SQLite MVP; add tests and deploy instructions; do not touch live hosting or real people without explicit approval. Preserve all phase boundaries and mark missing integrations as disabled/configuration-required, never pretend they work.
