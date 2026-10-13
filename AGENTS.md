# BOX2 Coding-Agent Contract

Read `README.md`, `docs/OPERATING_MODEL_AND_EXECUTION_PLAN.md`, `docs/LIVE_STUDIO_AND_GALAXY_SET.md`, `docs/PRIVATE_REHEARSAL_BROADCAST_CONTINUITY.md`, `docs/PRODUCT.md`, `docs/WEEKLY_TOP_5.md`, `docs/IMPLEMENTATION.md`, then `docs/LAUNCH.md` before coding. The integrated plan coordinates current scope and staged execution; domain rules, latest approved owner decisions and launch gates remain controlling. These are canonical. Build the smallest demonstrable slice before abstractions. Commit incremental working checkpoints with test evidence.

## Non-negotiables

1. **Architecture**: plain semantic HTML, responsive CSS, accessible vanilla JavaScript, small PHP backend, SQLite. No React, SPA framework, Node build requirement, Laravel, authentication service, payment system, third-party backend, or public accounts. Host/admin login may be a hardened password-based session. Keep adapters optional.
2. **Public product**: a real schedule for six nights, public 10-minute slot booking, performer onboarding, Twitch embed, orientation/parking walkthrough, and private writer submissions. Functional data flow only: never present fake availability, confirmations, counters, transmissions, or analytics.
3. **Comedian first**: BOX2 is for *original comedy*, beginners through working/touring performers. No poetry/spoken-word or general music sets; musical comedy with portable instruments is allowed. A sober, neighborhood-conscious, quick-turnover room. Respect each performer, no attacking prior comics to steal laughs.
4. **Consent**: livestream, archival recording, host clipping, and creative adaptation are separable informed choices. Private **room media** is **never broadcast or recorded**, including independent camera/NVR/cloud storage; an isolated prerecorded house-ad feed may remain on air after verified disconnection of all stage cameras and audio. Stop the stream when isolation is uncertain. Performers own their original material; submitting content is not an ownership transfer.
5. **Evidence**: performance timestamp/record may establish *that a set was performed when recorded*, **not** original authorship, global first performance, copyright registration, or provable theft. No unverifiable proof claims.
6. **Security and privacy**: no public SQLite, backups, credentials, uploaded files, admin endpoints without authorization, teleprompter text, joke submissions, or contact information. Prepared statements, CSRF protection, validation, output encoding, input limits, rate limiting, session hardening, upload controls, and email link token expiration. Do not commit secrets. Configure privacy/retention and opt-in marketing tracking.
7. **External services**: Twitch `cantonrefinery`; Reddit = link/share only, **no Reddit integration**; Facebook = sharing, interest measurement, optional consent-gated Meta Pixel/retargeting, no automated group posting or presumed API access. Email through pluggable transport; SMS later only with explicit opt-in and provider.
8. **Time**: recurring show-days Sun/Mon/Wed/Thu/Fri/Sat 21:00–02:00 America/New_York, crossing midnight. Tuesday reserved for outside performances. One Wednesday and one Friday each month may be overridden for outside gigs. Use actual zoned instants, DST-safe handling, immutable slot identity.
9. **Deployment**: HTTPS and host suitability are launch prerequisites. Do not change DNS, production hosting, audience disclosures, or publish venue walk-in access without explicit approval and operational verification. Back up old site before cutover.
10. **Scope discipline**: prioritize usable mobile booking, admin, consent, security, and orientation over novelty. Defer AI generation, automated clip editing, profiles, elaborate CRM, integrations, and advanced provenance proofs until after release.

## Evidence for completion

- PHPUnit or runnable PHP test scripts for booking collisions, overbooking, midnight/DST, cancellations, signed links, permissions, upload validation, reminder scheduling, and CSRF/auth.
- JS syntax/accessibility/manual mobile check; PHP lint for all PHP; no debug/credentials exposure.
- Document local development, DB initialization/migration, email cron behavior, backup/restore, SSL/Twitch/Meta configs, and deployment.
- Show tests run, failures/limitations, sample timestamps and screenshots if useful.
- Commit work to a feature branch + PR for review when practical; do **not** silently deploy.

## Short build order

Schema + booking/availability → secure admin + check-in → orientation/video + sober-stage rules → Twitch/share metadata → transactional email reminders → optional consent-gated Facebook instrumentation → tests/deployment handoff. See implementation document for precise acceptance.
