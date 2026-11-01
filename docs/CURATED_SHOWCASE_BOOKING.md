# BOX2 — Development Stage and Curated Showcase Booking Contract

**Owner decision — 2026-11-01.** This document establishes two complementary programming modes, without reclassifying existing bookings or weakening existing rights, privacy, access, safety, or launch requirements. It supplements AGENTS.md, PRODUCT.md, IMPLEMENTATION.md, WEEKLY_TOP_5.md and the operating plan. In a conflict, privacy/consent and actual operational readiness always win.

## Audience promise

**Development stage:** "Everybody starts somewhere. Start here." Comics can practice, test, fail, revise, and return. The posted schedule, booking confirmation, and player must make it clear that this is developing material, not a ticketed polished showcase.

**Curated showcase:** "You may not know every comedian on the lineup. You can trust the show has been deliberately curated." A showcase is an intentional, host-reviewed production. Do not claim guaranteed laughter, universal approval, a known headliner, or an audience response. Programming standards concern repeatable craft and preparedness, not a preferred comedy style, profanity, fame, friendship, demographics, or popularity metrics. Improv and other legitimate comedy formats can qualify if the act meets the same production expectations and the existing comedy-only scope.

**Tension versus distress:** A great set may create deliberate tension that resolves through comedy. Our goal is to avoid avoidable audience discomfort from unprepared acts, negligent hosting, misleading publicity, exploitative behavior, or coerced participation—not to ban challenging art.

## Booking invariants

1. The six-night development calendar, current 5/10/15-minute booking allocations, public availability, arrival T-20..T-10, check-in, private rehearsal, host holds, date overrides, cancellation, and consent pathways remain unchanged by default. A development booking does not imply showcase eligibility, an audition, a public clip, promotion, pay, or guaranteed audience.
2. Showcase inventory is **host-created and invitation/approval controlled**. Never expose it as first-come open-mic inventory. A performer may express interest without automatically receiving a slot; the host can also invite performers with no development-stage history.
3. Showcases require a distinct **event/lineup identity**, advertised show time, host/production owner and per-act slot confirmations. Showcase dates/allocations must be reserved atomically against the same physical stage inventory as development/private blocks. No double allocation, including across midnight or DST.
4. Before an act becomes **confirmed on the public showcase lineup**, a host must record an affirmative editorial decision based on a real observed set, a submitted recording, a credible live reference or a documented rehearsal. This is evidence of readiness, not proof of originality or future laughs. If no sample is available, state "review pending"; don't manufacture a score.
5. Suggested review rubric: material/premise and punch construction; delivery/timing; ability to recover or adjust to audience; professional stage conduct; readiness for the advertised slot length. Use descriptive host notes, not a public leaderboard or opaque AI eligibility score. Different voices and styles are welcome. Provide a path for declined candidates to continue development and seek another review.
6. No public lineup announcement from a request alone. The performer must accept the slot and relevant public-facing identity, date, and publicity choices. **Booking, livestream, room recording, public name, archival storage, clips, ads, and cross-platform publication remain independent, explicit, default-off permissions.** When required showcase capture/publicity permission is declined, offer a nonbroadcast format if viable or don't confirm; never coerce a general release.
7. Public views may show a specifically approved showcase name, approved public stage name and actual confirmed time. Never show rejected applicants, waiting-list identities, private bookings, real names, contact information, scripts, review notes, or private media. "Under review" and "not confirmed" stay private. Show cancellation and lineup changes truthfully.
8. Distinguish **showcase application / interest**, **host editorial approval**, **performer acceptance**, and **confirmed scheduled appearance**. No automatic confirmation email at application. A confirmed appearance receives the usual secure transactional notification and cancellation/host-change pathway; no claim of delivery without configured transport.
9. No performer charge, compensation promise, ticketed event, audience admission, or revenue share is authorized by this policy. The existing venue/parking/HTTPS/stream-isolation/consent launch gates remain OFF until explicitly approved and verified.
10. Weekly Top 5 is a **separate**, opt-in editorial distribution product. Being featured there is neither required nor sufficient to be booked for a showcase. Neither showcase participation nor a development set grants clip rights.

## Minimum host workflow (target, not yet implemented on main)

- Create a draft event with `kind=showcase`, an immutable event ID, local timezone-aware starts and ends, and reserved capacity. Default `public=false`, `booking_open=false`.
- Record an applicant/invitee and a minimally necessary evidence reference; no public profile required. Keep review notes private. Require host authorization, CSRF protection, and an audit trail for decision changes.
- Host moves `proposed -> reviewed_approved | reviewed_declined` with a rationale. Approval is not scheduling. Invite/offer a specific free allocation and expiration; acceptance must be affirmative and must recheck stage capacity inside a transaction.
- Confirm an act only after acceptance, capacity check, safety rules and applicable separate rights/identity choices. Publish only explicitly approved public display fields and the host-approved event status.
- Host may replace or cancel acts with an auditable reason; do not silently announce a substitute or pretend the original act is performing.
- Keep development calendars open on their own terms. Avoid hidden conversion of existing bookings into a selective, exclusionary process.

## Bounded implementation sequence

**Slice 1 (P1):** add a development-vs-showcase distinction to copy and an admin-only draft showcase/event model, without changing existing public booking semantics. Add tests proving legacy bookings remain unchanged and new inventory is hidden by default.

**Slice 2 (P1):** host review/invite/accept/confirm flow and transactional slot allocation across both modes, including a safe decline/retry experience. Test competing holds, rejected/pending identity leak, unsigned access, midnight/DST, cancellation and publicity default-off.

**Slice 3 (P2):** showcase-specific public event page, approved lineup, truthful changes, program-level host notes and simple operational checks; enable only behind explicit launch gates. No tickets, payments, public accounts, auto-review or AI judging in this iteration.

### Acceptance evidence before enabling

- Existing open booking and private rehearsal tests still pass.
- A non-approved performer cannot reserve or appear in showcase inventory, but can still use ordinary development-stage booking.
- No acceptance, host invite, or approval alone grants livestream or recording rights.
- Every public lineup entry refers to a real confirmed and consented scheduled appearance.
- A private/rejected/withdrawn candidate leaks no identity through schedule, metadata, sharing, notifications, or logs.
- Allocations don't overlap the physical room or cross DST/midnight incorrectly; cancellation frees inventory safely.
- Host can pause or cancel any showcase without fabricating attendance, booking confirmations or audience promises.

## Scope / status

This is a **policy and implementation handoff**, not a claim that showcase database tables, screens, calendar gating, staging checks, performer communication, or deployment exist. The PHP/SQLite MVP remains in review PRs; no production booking or audience changes are authorized here.
