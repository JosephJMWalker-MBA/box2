# BOX2 — Legacy UI Inspiration → Current Model (Codex Pass 2)

**Status:** design reconciliation for **PR #1**, not a deployment authorization. Owner supplied screenshots of the previous live booking site on 2026-10-09. **Those are visual/interaction references, NOT the canonical policy or code.** Read `AGENTS.md`, `docs/PRODUCT.md`, `docs/IMPLEMENTATION.md`, `docs/LAUNCH.md`, `docs/ARRIVAL_PARKING_AND_OUTREACH.md`, and `docs/RUNBOOK.md` on the PR branch before implementation. Preserve PR #1 security, data, and tests.

## Reuse from the previous site

- Branded visual voice: warm lined-paper/cream canvas, confident oversized black type, black outlined/shadowed cards, orange buttons, restrained yellow accents. Maintain readable responsive layouts, keyboard accessibility, accessible error messages, and no horizontal overflow.
- Progressive onboarding: **nine separate “I understand” cards**, one at a time, progress indication, backward navigation, and a complete independently readable rules page. Don't replace this with one long unacknowledged checkbox or with a heavy wizard that loses entered form state.
- Book → perform → optional approved clip → return, with clear booked time, check-in expectations, venue orientation, and meaningful off-stream alternatives.
- Strong room copy: “This isn't a comedy club. This is a rehearsal room.” “Come Tell It Here First.” “Everybody starts somewhere. Start here.” “Focus on stage time. Socialize online.” Keep the spirit welcoming, not threatening or competitive.
- Simple three-step booking scaffolding, expandable to accurately handle multiple block lengths. Retain laundry-set candidate concept as host-granted special longer set, not an entitlement.

## Corrections required before site launch (highest priority)

1. **Never copy deprecated parking text.** Remove recommendations to park at Jerzee's, use the gravel lot, a resident's spaces, trails or other third-party lots, and any invented parking stall geometry. Owner's real annotated aerial is reference: blue preferred movement, green only vetted bays next to the long white BOX2 building, red keep-clear; **1 lower/south entry, 2 upper/north exit**. No generated map is approved for public use. The authoritatively approved walkthrough, exact permissions, accessible entrance, and map must be verified onsite first. No public VIP/rear-door routing. Use an honest unpublished-state message until approved.
2. **Nine-card content must match current philosophy**: (1) performer philosophy, (2) arrival/parking, (3) finding BOX2, (4) check-in flow, (5) performance environment, (6) health/facility + cleaning, (7) sober room culture, (8) audience + livestream/recording, (9) BOX2 mindset. Use individually acknowledged cards in the booking flow and readable source content on `/rules`. Include optional spectating; no lingering obligation; no talking/scrolling in performance room; socializing primarily online. Cleaning microphones/shared surfaces between performers and lobby + stage-left bathroom high-touch surfaces hourly is an **actual logged operating duty**, not proof of an infection-free space. Dogs/rail noises are possible, but never normalize unsafe building conditions or shift venue safety responsibility to visitors.
3. **Performance categories**: allow stand-up, comedy sketches/characters, host practice, musical comedy with hand-carried instruments. Remove **general Music, Poetry/Spoken Word, Other** as permitted performance options in legacy screenshots. These screenshots are a deprecated menu.
4. **Recording/rights**: keep distinct opt-in for livestream, archival recording, approved host clips, adaptations, feedback and writers' medium-specific grants. All default OFF; do not select clip consent by default. “Best jokes WILL make the weekly reel” is incorrect: *approved candidates may be considered for clips*, never automatic and never guaranteed. No copyright/first-authorship proof claim. No sharing private teleprompter/writer content. Private rehearsal is truly off-stream/off-record, contingent on host confirming hardware state; live-only cannot silently record VOD.
5. **Scheduling lengths**: the old UI offered 5/10/15-minute “set lengths”; current MVP reserves one 10-minute calendar block per five-minute performance. Introduce configurable **1, 2, 3 adjacent 10-minute allocation reservations**, representing 5, 10, 15 onstage minutes respectively with host/reset buffer, only if slots are actually consecutive and available. Make the distinction between **stage minutes** and **calendar reservation length** obvious. Enforce atomic range reservation, collision checks, cancellation/release of the entire block, midnight/DST correctness, correct host lineup and emails. Don't claim this exists until implemented/tested. Longer sets require genuinely contiguous open allocations, not simply multiple independent reservations.
6. **Arrival-time contradiction requires an owner decision:** earlier text simultaneously says “arrive no more than 20 minutes early” and “check in by 20 minutes before your set.” Do NOT ship a misleading one-minute check-in window. Propose a bounded arrival window (e.g., 10–20 minutes before, check in on arrival and be on deck by 10 minutes prior), but **obtain owner confirmation** before changing the operational policy. All booking receipts, reminder emails, onboarding, and countdowns must agree.
7. **Email/SMS truthfulness**: email queue is durable but provider acceptance does not prove inbox delivery; claim “reminders on” only when actual production sending and recipient receipt have been verified and configured. SMS is not shipped. Do not show fake “text me” controls as if live, or imply automated rescheduling/host notifications beyond demonstrated capabilities. Preserve email confirmation/cancellation behavior.
8. **Security + launch gating**: old screenshot showed browser “Not Secure” on `https://box2.yurrmom.com`; repair/verify TLS independently and keep `allow_bookings=false`, `venue_public_enabled=false` until readiness. No fake maps, live metrics, available slots, receipts or guaranteed audiences. Maintain backup/restore, server-side contact privacy, and legally reviewed releases before public walk-ins.
9. **Social**: Facebook share and native Facebook event promotion; basic UTM attribution and future optional consent-gated Pixel/retargeting *after* owner authorizes. Reddit = native share/link only, no API, comment scraping or bots. Twitch `cantonrefinery` embedded when valid HTTPS and parent host. Consent before any public clips or submitted joke adaptations.

## Visual and copy safety

- Screenshots include personal contact information. **Do not commit, embed or redistribute the raw screenshots**. Use text descriptions or redacted derivative mockups.
- Older screenshots include outdated options/policies; visual imitation alone is not acceptance.
- Facility language should be specific and truthful without implying that construction hazards become acceptable if attendees sign a waiver. If premises or public-access permissions are unresolved, hold public bookings.
- Public parking map must match owner-verified geometry and never be repainted as a fictitious aerial graphic.
- Default repeat-visit flow should remain simple, but the nine current terms must be reviewable; never assume consent from a former acceptance after material policy changes.
- If exact original images/assets are unavailable or unlicensed for reuse, construct original styles and omit unverified maps.

## Acceptance evidence for Codex

1. In new screenshots at ~360px and ~1280px: brand visual consistency, nine cards, one step per explicit acknowledgment, back navigation, keyboard access, no JS errors/overflow, no accidental loss of entered form information.
2. Show fresh tests for 5/10/15 option availability, each reserving the correct **1/2/3** consecutive allocation blocks, concurrent overlap protection, cancellation releasing every block, after-midnight times and DST.
3. Demonstrate no public PII/teleprompter exposure and opt-in rights by medium, with no forced clip default or false email/SMS state.
4. Search user-facing pages/code for **Jerzee**, general **Music**, **Poetry**, unsafe/improper parking text, unverified map/venue claims, and unsupported “reminders on” claims. Document exceptions explicitly.
5. Update README/runbook/terms only where behavior actually changes, keep repo canonical, rerun PHP 8.2/8.5 CI and browser/HTTP checks. Work on PR #1 branch, reconcile later `main` documentation without dropping parking corrections, and return evidence. **No merge, no deploy, no permission-state enablement.**

## Decisions to ask the owner only if blocking

- Exact late-arrival/check-in policy (20-minute contradiction).
- Whether any early featured slots may require clip eligibility, given the stated goal of making stage time broadly accessible and giving performers publication control. Do not infer from the old screenshot; default to the current separate grants model and label any featured-slot limitation explicitly if later approved.

Aim for a **focused delta**, not a redesign or addition of another app stack.
