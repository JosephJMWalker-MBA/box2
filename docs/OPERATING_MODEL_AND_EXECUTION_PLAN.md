# BOX2 — Integrated Business Model & Codex Execution Plan

**Canonical operating plan — October 9, 2026.** This document assembles established owner decisions, the current implementation in PR #1 (`codex/secure-box2-mvp`, last inspected at `a3edc6ae42238dd552275771c91e92293f9bf446`), and the newest privacy-first broadcast and Top 5 requirements. Read with `AGENTS.md`, `docs/PRODUCT.md`, `docs/IMPLEMENTATION.md`, `docs/WEEKLY_TOP_5.md`, `docs/ARRIVAL_PARKING_AND_OUTREACH.md`, `docs/LEGACY_UI_RECONCILIATION.md`, `docs/RUNBOOK.md`, `docs/RELEASE_READINESS.md`, and `docs/LAUNCH.md`.

**Priority of authority:** owner-approved directions and current repo canon > past prototypes / visual references / brainstormed optional features. In code, prefer the simplest proven behavior consistent with the contract. GitHub remains canonical; this plan is **not** permission to merge PR #1, deploy, run advertisements, invite in-person traffic, change recording equipment, or turn on consent/booking gates.

## Executive thesis — one stage, two products, one flywheel

1. **The primary service:** a predictable, welcoming, privacy-first **comedy rehearsal room** at BOX2, where anyone with original comedy—from first-timer to touring professional—can reserve a short set and practice with working lights, camera, audio, projector/teleprompter options, a host and an optional online audience. The room works even when few or no comedians arrive. Someone can perform, receive any opted-in feedback, and leave; social participation is primarily online.
2. **The always-on programming format (during declared six-night windows):** `cantonrefinery` Twitch becomes a hosted **interruptible studio show**. Between eligible acts, the host can give talks about projects, test jokes, paint a wall, do physical training, present original sketches, or run BOX2/other owner-business promotions. A clear recurring invitation says, for example, **“Bored yet? Book a slot and take over the stage.”** Bookings interrupt programming at the **scheduled slot**, not instantaneously; a broadcast delay creates additional timing lag.
3. **The flagship output:** **one weekly vertical short, “BOX2 — Top 5 Jokes This Week,”** curating up to five different *eligible joke moments* from recorded performances. Publish the rights-cleared master/variants on TikTok, Instagram Reels, Facebook Reels and YouTube Shorts. These are **highlights, not an elimination contest, not a ranking of comedians, and not guaranteed inclusion**. If fewer than five qualify, publish fewer or skip the week.
4. **The acquisition loop:** flyers/QR, Facebook organic groups/events and later lawful retargeting, Reddit native sharing, neighbor referrals and footage lead to stage bookings; bookings lead to original material and voluntary weekly features; the weekly reel reaches new audiences and sends them back to BOX2. Track the real funnel rather than assuming all views become performers.
5. **The ecosystem loop:** joke writers may submit original work with independent grants to host performance, video publication, AI visuals/trailers and music/Suno interpretation; host practice and moderated, *voluntary* tag feedback build additional contributors. Potential future intersection with Big Joke/MicMap should respect separate product boundaries, not force a platform rewrite.

**Positioning:** “Come Tell It Here First.” “Everybody starts somewhere. Start here.” “Bring your joke. Everything else is here.” “Focus on stage time. Socialize online.” “This isn't a comedy club. This is a rehearsal room.” Avoid marketing BOX2 as revenge against established clubs. Continue supporting outside comedy stages, including regular Tuesday trips and one Wednesday + one Friday outside stage per month, with explicit date exceptions or guest hosts.

## Operating model already decided

### Physical room and performer journey
- **Hours:** Sun/Mon/Wed/Thu/Fri/Sat **9 PM–2 AM America/New_York** (30 operating hours/week); Tuesday reserved for outside performances. Show date is evening date even for next-day 00:00–02:00 sets. Publish scheduled exceptions truthfully.
- **Host:** owner intends to take the stage **at least twice per BOX2 night** unless supporting another venue. Host may work at the computer between appearances, play original sketches/promotions, and invite guest hosts to learn transitions. Nothing assumes a paid floor manager.
- **Bookings:** tested MVP now supports **5/10/15 stage minutes** using **1/2/3 contiguous 10-minute allocations** respectively, plus host/reset buffer, concurrency protection, and cancellation of the whole reserved range. A standard five-hour night has 30 ten-minute allocations, initially 22 designated public, 6 held, 2 private; longer sets consume proportionally more allocations. Host can adjust holds, private blocks and date exceptions. Public bookings never imply rights to be recorded.
- **Arrival APPROVED:** arrive **T−20 through T−10**; check in **immediately upon arrival**; **on deck at T−10**. Do not arrive earlier than T−20. Arrive for a booked performance, perform, then depart; optional attentive support for another scheduled act is welcome within room capacity, **but BOX2 is not a hangout, open gathering, or place to linger**. No idle parking/lobby occupation or social congregation outside. Check-in and reminders show actual calendar date/time including after midnight.
- **Group showbuilding (owner clarification, 2026-10-09): RECOMMENDED, NOT REQUIRED.** Invite comics to sign up together for **adjacent, individually authorized sets** and collaboratively arrange order, intros, thematic handoffs, callbacks or complementary styles to make an intentional audience show; encourage **voluntary carpooling** to reduce demand on scarce approved parking. Maintain **equal solo access** and no friendship/network eligibility gate. A group is not an exception to 5/10/15-minute allocation rules, arrival windows, venue capacity, performer privacy, recording grants, release rights or quiet-neighbor/quick-turnover requirements. In v0.2.0, the host can help book/co-ordinate adjacent existing slots; do not build group accounts, reserved parking or group-based privileges. Only consider a simple group-request feature if actual operations show repeated unmet demand.
- **Venue discipline:** sober, original **comedy only**: stand-up, comic sketch/character work, hosting practice, and musical comedy with self-carried instruments. No standalone spoken-word or general music stage. No badgering/roasting previous performers to steal laughs. No conversation, scrolling/disruptive phones or unauthorized filming in the room during a set. Online is where people can chat and offer tags if opted in; performer controls feedback.
- **Health and maintenance:** appropriately clean shared microphones/contact surfaces **between acts**; log hourly high-touch cleaning of lobby and **stage-left restroom**; compatible cleaning products/contact times, hand hygiene, options for a compatible personal microphone, and a stay-home-if-ill policy. Do not call this “germ-free,” “germ-safe,” sterile or medically protected. Dogs barking, incidental outside noise, dinner and occasional distractions may be real, but never excuse unsafe premises.
- **Audience experience:** authentic in-room response and optional livestream audience are different feedback channels. Do not promise a full room, view count, live laughter, first-tell exclusivity, or guaranteed feature.

### Address, parking and neighbors
- **Candidate site**: 2735 Harrison Ave NW, Canton, OH 44709; a real public invitation requires confirmation of premises, lease/use, occupancy/fire/accessibility, insurance, night operation and prior maintenance concerns.
- Use **only the owner's actual annotated aerial reference**: blue = preferred traffic movement; 1 **lower/south ENTER**, 2 **upper/north EXIT**; green = actual indicated parking by long white BOX2 building, not speculative stalls; red = keep-clear residential/access areas. A preferred route is not evidence of approved one-way controls. **Never publish AI-fabricated property geometry** or infer parking permissions, overflow at Jerzee's, private apartment spaces, gravel lots or trails.
- On-site verify actual bays, access, lighting, safe route, permitted circulation, emergency access, and entry door. Then create a faithful labeled photo/diagram with text fallback and a host-uploaded **parking/door walkthrough video** plus transcript/captions. Until approved, keep public parking media/address access gating OFF.
- Quiet, predictable arrival/departure near neighboring families. **Private VIP/rear-door guest entry** is possible only as a discreet host-arranged alternative after venue/access approval; never advertise the path on the public site.
- **Hall of Fame Apartments** nearby is a *post-redeployment, opt-in community outreach prospect*: seek leasing office authorization to share QR invite/newsletter to **walking-distance residents**, never treat resident parking as BOX2 visitor parking. Separate QR/UTM source for aggregated booking conversions; no resident lists or unit numbers.

### Privacy, rights, and performer respect
- **Default OFF** for livestream, archival recording, host clips, creative/AI adaptation, public display of real names, and feedback. Distinguish performer stage-name graphic consent from performance video authorization. No requirement to publish to get reps. Clear private slots available (current ratio is configurable; further adjustment is an operator decision).
- **Private rep:** physically ensure broadcast, VOD and **every microphone/audio source/camera/local recorder** is not capturing the private rehearsal. Showing a “private” graphic over an active mic feed is **not** privacy. A delayed broadcast is still public and is not a substitute for consent. App status acknowledgments cannot control OBS/Twitch/hardware.
- **Live only:** allow delayed live broadcast if expressly permitted; **turn off VOD/local recording** before the set; do not consider live-only footage eligible for a weekly reel. Streaming users could copy independently, even after VOD expires.
- **Clip / Top 5:** explicit informed, logged **cross-platform publication scope** for the comedian's face, voice, stage name and clip, separately from general livestream permission. Legacy “clip eligible” wording may be insufficient—do not silently grandfather people into new permissions. Separate writer grants and third-party music/video rights still apply. Ask before promotional advertising/boosting beyond agreed organic sharing. Preview/objection window where practical; removal requests honored within operator control, no promise of third-party erasure.
- **Timestamp provenance:** actual authorized recordings may document that a named person performed a particular joke at an observed time, not prove they invented it first or constitute copyright registration. Don't build fake originality certificates.
- **Data:** protect contact, legal name, scripts, writer drafts and guest identity from public pages, streaming graphics, metadata, analytics, and exported social posts. Set explicit retention, deletion, backup and access rules. Consent to broadcast/feature/advertising are never conflated.

## Current live studio milestone and evolving set (2026-10-09)

Owner demonstrated an OBS session actively streaming the **Reolink camera** view of the rehearsal room, including the existing lit jukebox and renovation area. Owner reports the room is now physically closed to dogs, and will progressively prepare/paint **walls and floor black**, with optional safe star/galaxy paint additions by contributing comedians over time. **OBS broadcasting is underway**, but this is separate from new Codex website deployment, public visitor access, third-party Twitch playback, proven streaming delay, VOD consent and private audio/video shutdown. Treat the studio renovation as real physical work with appropriate cleaning of old animal waste, moisture assessment, floor-rated slip-resistant coatings, visible stage edges/exits, ventilation/cure and removal of ladders/tools before entry. **Do not require a digital reward program or leaderboard for the galaxy wall.** See [LIVE_STUDIO_AND_GALAXY_SET.md](LIVE_STUDIO_AND_GALAXY_SET.md) for the current operational checklist, scene-state safety requirements and cutover dependencies. Last Chrome screenshot of the legacy BOX2 site still showed “Not Secure” even though the certificate was listed valid; diagnose before accepting PII.

## Live production format — new, not implemented

A minimal **broadcast state machine** should be designed around the existing admin rather than inventing a separate CMS:

| State | Public scene | Required control |
| --- | --- | --- |
| Starting / waiting | BOX2 branded holding card and booking invite | Never claim a performer/viewer is present |
| Host studio / interruptible programming | lectures, host jokes, painting/lifting, original sketches or house ads | Rights-clear any video/music; avoid revealing private equipment, contact screens or guests |
| Now on stage | consented performer's stage name / act type card and live performance | Name/stream grants checked, intro aligns with stream delay |
| On deck | optional consented stage name or generic “Next performer preparing” | Avoid publishing future roster / exact private activity; no involuntary disclosure |
| Reset / sanitation | visual break or public-safe prerecorded materials | Mics cleaned/logged and privacy-safe audio mix |
| Private rehearsal | **fully isolated/streaming and recording actually OFF** | No live camera/audio from the private room; if a holding graphic runs externally it must originate from isolated media sources with no studio mic/camera routing |
| Session closed | honest offline / next scheduled evening | No fake “LIVE”, guaranteed audience or constant studio activity |

- Configure actual **Twitch/OBS stream delay** as a tested **operator setting** (target delay unspecified until owner sets it); never invent a delay number or promise instant intervention.
- A host-facing cue/OBS scene checklist may derive *only explicitly consented* public fields from the booked lineup. Never output phone, email, legal name, private script, private stage slot, backstage VIP route, or private rehearsal details.
- "Interrupt this lecture" is a **scheduled booking CTA**, not arbitrary real-time heckling or unscheduled access. House programming pauses when the booked comedian's host-controlled set begins, with actual time plus platform buffering/delay clearly understood.
- First production version can use manually prepared cards/scenes and manually scheduled media in OBS. **No autonomous streaming controls, social bots or video-editing engine needed for launch.** Decide later whether a privacy-safe status endpoint for OBS offers enough leverage.

## Flagship weekly production — next bounded software increment

One compiled vertical weekly short with up to 5 **joke moments**. Host/editor selects quality and coherence, not online popularity alone. Host's own jokes may qualify but don't automatically dominate. Workflows begin **manually** and can produce episode #1 without a platform API.

**Needed lightweight private editorial ledger** on top of existing `clip_candidates` (not a video-hosting SaaS):
1. Flag candidate **booking + actual source recording reference + time-in/time-out + private note**.
2. Verify **per-performer consent** (clip and per-destination distribution, stage credit), writer permissions if present, music/other IP, safety and no live-only/private records.
3. Candidate → rights review → approved → edited → published or rejected/withdrawn before publication. Don't expose raw jokes in share URLs or to social platforms during review.
4. Shortlist up to five, order the moments, document opted-in performer credit and link approved assets. No automatic publication.
5. Export a single captioned original 9:16 edit with branded opening and close, optional platform-specific variants; publish manually on TikTok, Instagram Reels, Facebook Reels and YouTube Shorts. Verify current platform requirements/rights before upload.
6. Record published post URLs, date and available aggregate post metrics; close each episode with **“Everybody starts somewhere. Start here.”** + `box2.yurrmom.com` and a booking invitation. Promotion is contingent on a working site and genuine participation.

**Rights fail closed.** Fewer than five approved means fewer than five or no episode. The nightly stage is not an audition with competitive eliminations. See `docs/WEEKLY_TOP_5.md` for specifics.

## Business economics: real inventory vs assumptions

**What exists as an economic asset:**
- A physical workroom, owned/managed stage production setup, recurring host availability, recorded **if authorized** talent development, access to one's own site, original material from owner and opt-in contributors, an existing Twitch channel, owner-branded promotions/sketches, a reusable weekly short, and potential local network/community relationships.
- Stage capacity is **time inventory**, not guaranteed demand or attendance. Six nights × five hours = **30 open hours/week** if the host operates all sessions; 30 allocations per ordinary night, subject to private/hold reserves and varying set length.
- Low-friction participation can be a competitive advantage. **No performer ticket price, free promise, sponsor rate, pay split, compensation policy, or revenue guarantee has been approved.** Do not add payments or sale language to the MVP.

**Candidate revenues / benefits (hypotheses, not committed products):**
- **Near term:** promote the owner's creative businesses, approved original sketches/merchandise/products, build audience relationships and marketing assets, and reduce the host's travel/waiting costs by using existing workstation hours. Those are marketing/efficiency benefits, not booked revenue.
- **Later subject to separate decision:** opt-in sponsorship of weekly short or studio interludes, ads clearly distinguished from programming, original merch with a distinctive BOX2/YurrMom payoff, paid special shows, commercial comedy production and approved creator collaborations. Avoid compromising creative trust by making newcomers buy stage time or surrender rights; don't infer a paid tier.
- **Costs to track before monetization:** site+SSL/hosting/backup, equipment maintenance and electricity, safe venue operation and liability/insurance, sanitation, editing/captions, mail/SMS if used, potential promotion budget, host time and permitted operations. No ungrounded break-even estimates.

**Primary north-star:** **unique first-time performers who actually complete a set**, plus repeat performers over time, not raw stream viewers.

**Funnel:** Facebook reach/events or referral views → unique BOX2 landing sessions (if measured lawfully) → scheduling views → bookings → actual check-ins → performed sets → optional consented candidates → published Top 5 → social referral visits/bookings. Keep observed and inferred attribution clearly separated; deduplicate retries and don't send private fields to Meta. Facebook Page/Event analytics and eventually consent-gated Pixel/retargeting; Reddit share URL only, **no Reddit API/comment scraping**; Twitch playback; TikTok + Reels + Shorts manual publishing. First-party UTM codes for flyers, neighbor QR and share links; do not claim a marketing integration currently works.

**Operator weekly scorecard (no inflated vanity metrics):** actual open hours, available/reserved/used stage minutes, bookings/cancellations/no-shows/check-ins, unique new performers, repeat performers, guest host hours, creator permissions granted, number of authorized candidate jokes and published moments, episode output, organic links/clicks/bookings by source where supported, editing hours/costs, sanitation compliance, noise/parking incidents, and downstream referral relationships. Track denied/private data without exposing it in public analytics.

## Reconcile with Codex PR #1 — truthful implementation inventory

**Confirmed implemented as code in PR #1 (per repo and tests, not verified on production):**
- Plain PHP + PDO SQLite + accessible HTML/CSS/vanilla JS; no React/accounts/payments.
- Recurring Sun/Mon/Wed/Thu/Fri/Sat schedule with midnight/DST handling, date exceptions, 30 normal slots (22 public/6 holds/2 private).
- Atomic 5/10/15 stage-minute booking with 1/2/3 allocation ranges, collision/cancellation protection, confirmation/cancel tokens; nine-card progressive onboarding; T−20..T−10 arrival; authorized host dashboard.
- Optional performer livestream/archive/clips/adaptation/feedback grants; private/live-only host-gated recording acknowledgments; writer submissions and independent permission flags.
- Twitch `cantonrefinery` embed gated to actual HTTPS parent, Facebook/Reddit/native share links; arrival text+host video upload *withheld until venue approval*; SMTP/local email reminder queue with disabled-by-default transport, retention and backup/restore scripts.
- Basic `clip_candidates` tagging, sanitation log, orientation and booking UI. Reported tests: 78 backend + 64 duration/range + 65 migration + 50 HTTP + operational and browser suites; release report says GitHub Actions matrix passed for PHP 8.2 and 8.5. **Check fresh CI after every new implementation change.**

**Not yet implemented / not established by those tests:**
- Operational Twitch delay, truly isolated private-stream OBS scene states, public/on-deck stage graphics and a controlled host content playlist. Those require real production equipment plus limited software support.
- The weekly Top 5 *editorial ledger*, timecoded candidate rights/credit tracking, post links, renderer, and external publishing. Manual editorial execution can begin first; platform APIs are not part of the near-term contract.
- Facebook Pixel/ads conversion measurement, ad spend, retargeting or reported Meta audience insights (config placeholder only). Instagram/TikTok/YouTube integrations not implied by share links.
- SMS, automatic attendee texts, automated clip production, performance proof certificate, integrated analytics/dashboard, paid bookings, ticketing, formal guest/rear-door access control.
- Actual HTTPS repaired, real SMTP delivery, real Twitch iframe on host, authorized parking diagram/walkthrough, approved venue, live recording privacy gates, or production backup/restore rehearsal. **Do not label the site publicly “open” from synthetic tests.**

**Branch relationship:** At initial planning review (2026-10-09), PR #1 was still OPEN and its head had reconciled earlier canonical documentation through `adc1f3a`; main has since added `docs/WEEKLY_TOP_5.md` and the updated `docs/PRODUCT.md` defining weekly release. Codex must reconcile newer main docs, this plan, and actual current PR head before further code changes; don't overwrite newer implementation with older docs.

## Staged execution — smallest safe increments

### Stage A — Merge-quality integration review (P0 engineering)
**Deliverable:** PR #1 or successor feature branch remains a runnable, testable, secure app with all already-established behavior, the new canonical specs reconciled, and clean CI. No extra framework or speculative feature. Confirm no drift in 9 cards, original comedy formats, set-length allocation tests, UTC/DST, T−20..T−10 and consent. Ask owner only for decisions actually blocking acceptance.

**Exit evidence:** full test matrix, responsive screenshots, migration/rollback and backup drill, code review of secrets/CSRF/auth/public views; explicit unresolved list. **No production deployment.**

### Stage B — Privacy-first broadcasting / weekly release operator tooling (P1 product)
**Deliverable:** Public copy accurately sets expectations (“studio window, not guaranteed live comedy”), scheduled-interruption CTA, Twitch channel and truthful offline state, operator scene/state guide for OBS, consent-safe **Now on Stage/On Deck** templates, manual playlist/house-ad rules, no silent state leaks; private candidate ledger to log timecodes, credited names, approval for multi-platform Top 5, and actual published URLs. Prioritize static, operator-confirmed controls before automated stream integration.

**Exit evidence:** tests showing private/live-only performers cannot be featured; stage-name reveal opt-in; unapproved writers excluded; scene cues show no private fields; manual end-to-end mock of one 5-moment episode (synthetic footage, **not** user performance media). No social post or OBS change without approval.

**Separation:** Stage B UI/editorial software can continue while real operations are verified, but do not let it delay a secure initial website launch with a truthful manual interim workflow. The first weekly release can be edited in ordinary tools from authorized local media.

### Stage C — Hosting and controlled production deployment (P0 operational)
**Deliverable:** verified TLS/DNS, approved hostname/docroot, real PHP 8.2+ PDO SQLite/extensions, private DB/config/upload separation, cron and mail, staging backup/restore rehearsal, rollback, live HTTPS Twitch embed/parent verification, visitor communications only when legally and physically ready. Existing server must be fully backed up before reversible cutover.

**Exit evidence:** written host checks, test book/confirm/cancel/duration/availability in staging, HTTPS browser tests, test mail to owned address and actual inbox receipt (or clearly disabled label), secure admin, published policy matched to actual equipment. Re-enable public bookings and venue access **separately** only with explicit owner approval and venue verification. Stage may first open as stream/information only, not physically walk-in.

### Stage D — Real room operation and first Top 5 (P1 editorial, then repeat weekly)
**Deliverable:** rehearsed host/guest-host operations, verified on-site arrival and sanitation process, opt-in recording workflow on actual devices, initial performers including host sets, at most five rights-approved moments, one weekly short posted manually on four platforms. Use no fabricated audience numbers or material. Include accessible captions, credit and per-platform post ledger.

**Exit evidence:** actual consent/asset match, safe scene transitions including private blocks and delay, real receipt/retention behavior as documented, post links, permission audit, first-week scorecard, lessons learned.

### Stage E — Demand validation and measured distribution (P2 growth)
**Deliverable:** share-enabled posts/flyer QR, respectful direct relationships with local comics, optional Krackpots conversation as a peer/supporter not a permission-seeking dependency, authorized Hall of Fame Apartments management outreach after site and venue readiness, Facebook event interest tracking, first-party UTM measurement, and later **consent-based** Meta Pixel/retargeting only if there's real return on spend. Ads spend is not automatic or approved.

**Exit evidence:** which channels produce **actually performed sets** and repeat performers, not just clicks; neighbor/parking disruption near zero; explicit budget if ads are later authorized.

### Stage F — Earned extensions (P3, no commitments)
Evaluate guest-host rotations, optional stage writer/tag feedback laboratory, longer Laundry Sets, creator/writer credit program, revenue-sharing or sponsor terms, more flexible private rehearsal inventory, clips archive/provenance and possible external tool integrations **only when actual usage and rights justify them**. No need to replicate MicMap, Big Joke, Facebook, Reddit or ad platforms.

## Launch blockers and concrete decisions

**Hard blockers before public walk-in:** premises/use/insurance/fire and safe conditions; verified real parking access and clear neighboring rights; actual compliant cleaning/recording operations; consent/terms privacy review; SSL/hosting/data protection; tested booking and cancellation; documented operator response when someone cannot park or must cancel; a real privacy-safe audio/video shutoff path. No assumed blanket legal protection from a consent checkbox.

**Operator decisions still open (do not invent answers):**
1. Whether all stage access is free or any future special sessions carry fees; currently **no paid-booking capability**.
2. Public capacity and onsite audience admission rules (if guests beyond performers are welcome); don't promise or solicit a crowd without suitability review.
3. The actual stream-delay duration and where implemented in the OBS/Twitch chain; keep configuration unset until tested.
4. Ratio and scheduling of private rehearsal blocks if privacy preference demands more than the current two slots per night.
5. Actual parking bay count and final verified diagram/walkthrough; the marked owner reference is adequate for design, **not** automatic approval to invite cars.
6. Featured segment release/credit language, retention/copy requests, sponsorship permissions, and pre-publication review window—finalize before first footage release.
7. Whether/when paid ads, sponsor inventory and staff/guest host delegation begin, each with budget, terms and responsibility.

**Owner has already approved:** 6-night schedule and Tuesday outside stages; 9 PM–2 AM, T−20..T−10 arrival/on-deck; stand-up/character/sketch/host comedy with portable musical comedy; sober, neighbor-respectful focused room; user-annotated blue/green/red parking intent; privacy preference; Twitch `cantonrefinery`; original writer contributions with separate grants; independent clips; Facebook measurement direction and **Reddit native sharing only**; the weekly Top 5 as the signature distributed show.

## Codex handoff contract

Codex should **read this plan before expanding the application** and transmit only the delta in prompts:
- **Change:** reconcile repo canon; privacy-first truthful stage/stream copy, operator scene template/spec, weekly Top 5 candidate/timecode/rights/post ledger.
- **Preserve:** PHP/SQLite, nine-card onboarding, arrival, consent, scheduling and tests; performer creative ownership and physically private sets.
- **Prove:** automated privacy/authorization tests, operational scene-check checklist, browser/CI evidence and explicit staging-only results.
- **Don't:** rewrite the app, build social APIs/editors, guess venue/map rights, merge/deploy or enable bookings/venue/Pixel/OBS without consent/approval.

**Strategic sequencing:** get a small, safe and authentic development room operating first; deliver a consent-cleared weekly short reliably; only then invest in audience acquisition and scaling. Every new integration must reduce total operating work or improve measured outcomes.
