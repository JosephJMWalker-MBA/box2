# BOX2 — Jetson / Reolink / OBS event timeline and community highlights

**Owner direction: November 2, 2026. Proposed integration contract; not a deployed feature or authorization to touch production.**

## Purpose and existing work

BOX2 runs its public-facing CantonRefinery stream while approved Reolink cameras/NVR retain roughly two weeks of rolling footage (owner-reported retention, not device-verified). Avoid duplicating continuous video on the Jetson simply to make editing possible: preserve **compact metadata indefinitely subject to an approved retention policy**, then **extract authorized clips before source footage rolls off**. Twitch VODs are an additional, shorter-lived discovery/publishing source, not the authoritative archive. Clip publishing must not depend on a Twitch VOD existing.

Preserve the booking/rights implementation in PR #1 (`codex/secure-box2-mvp`) and the private-room/manual Top 5 increment in stacked PR #5 (`codex/private-room-top5`). This document does not merge, rebase, or supersede them, and does not silently switch on booking, cameras, recording, nominations, voting, audience access or OBS control. Reconcile implementation with the merged/latest branches before code changes. PR #6 adds the distinct curated-showcase lane.

**Scope change under discussion:** the owner now wants eligible performers to bring audiences to nominate/vote on highlight clips for weekly/monthly visibility. This changes the older host-only selection policy in `WEEKLY_TOP_5.md` *as a proposal*, not as a retroactive consent change or an implemented public contest. Define and approve separate community-choice editorial rules and public-vote permissions before building/publicizing voting.

## Authoritative model: three distinct planes

1. **Capture/archive:** each physical Reolink camera, NVR, SD, cloud, snapshot and mic is an independent recorder. OBS scene hiding does not disable recording. Source camera identifier, NVR device, retention estimate, capture availability and clock health are tracked separately. No Jetson video-archive duplication by default.
2. **Production:** Jetson can read approved camera observations, schedule snapshots, and a private event queue; OBS is an optional scene/overlay controller, possibly on another host. Streaming remains continuous *only when the room is allowed to stream*, with independently verified, fully isolated house media for any approved private room continuity. Fail-stop if uncertain.
3. **Editorial/distribution:** time-indexed events and rights-cleared source excerpts become reviewable candidate clips. Performer approval, writer rights, voice/face/credit/destination grants, editorial review, withdrawal and publication audit are separate from capture and public vote.

## Event ledger (append-only state transitions, not a public activity log)

Use UTC instants plus `America/New_York` local display, recording source clock offset and capture time confidence, including DST fold; never rely on local clock strings as IDs. Minimum proposed fields:

- `event_id` UUID/ULID; `occurred_at_utc`; `ended_at_utc` nullable; `recorded_at_utc`; `event_type`; `camera_id`; `source_device_id`; `capture_clock_offset_ms` and `clock_verified_at`.
- Optional private `booking_id` or nonidentifying `show_slot_id`, `operator_id`, `confidence`, `manual_note`, `source_recording_locator`, `source_start_utc`/`source_end_utc`; locator is private and time-limited, never public filesystem/NVR URL.
- Optional `twitch_broadcast_id`, `twitch_vod_id`, `vod_offset_ms` and verified mapping anchors. Twitch and Reolink offsets **must be measured**, not assumed equal to wall time; stream delay, outages, reconnects, VOD splitting, drift and DST affect mapping.
- `privacy_class` and `capture_authorized` derived from **verified device/room state** plus consent, never just booking status. Default inaccessible/unusable when unknown. A metadata event is not a grant of footage rights.

Event types initially: `booking_checked_in`, `stage_occupied`, `performance_started`, `performance_ended`, `stage_cleared`, `alternate_camera_activity`, `scene_switch_proposed`, `scene_switch_confirmed`, `capture_fault`, `privacy_isolation_requested`, `privacy_isolation_verified`, `stream_interrupted`, `clip_candidate_marked`, `media_exported`. Event names alone do not imply a true fact: recorded transitions require provenance/manual confirmation, and occupancy detection isn't proof of identity or departure.

Retention: keep private minimal event history only for an approved purpose/period; purge or pseudonymize obsolete associations. NVR footage disappears at its configured retention, subject to storage/recording faults. Queue eligible candidate exports **before** rollover, with deadline/health alarms. Never silently archive private or unconsented footage. Source media/export and editing masters must use approved private storage, access controls, retention and deletion logs.

## First OBS experiment: stage → Parking Lot Center

**Initial behavior: stage is default and protected**. Secondary scene is `Parking Lot Center`, only after the stage is confirmed free, approved for public capture, alternative source is healthy, and the operator has enabled the experiment.

- Performer/speech on stage, an active performance, uncertain stage occupancy, any capture/privacy fault, loss of telemetry or stale occupancy data → **do not leave the protected stage output**. In a private/unrecorded session stage output is forbidden; use verified isolated house source or STOP, irrespective of occupancy.
- On an empty, public, consent-safe stage, switch to approved parking-lot video only after stability/hysteresis threshold. Stage entrant or scheduled approved performance takes priority, with transition back checked against actual OBS state. Stage scheduling alone is not proof that a performer is on camera, nor permission to transmit.
- Initial parking-lot experiment is **video only**; do not open ambient audio automatically, reveal nonconsenting neighbors/license plates, or use it to surveil arrivals. Confirm camera field-of-view/notice and lawful permissions before making a public scene.
- Provide operator manual override, explicit `automation_enabled=false` default, a dry-run proposal log, one-command disable, source health timeouts, scene whitelist, and a local-only OBS WebSocket integration with least-privilege authenticated access. Do not expose OBS WebSocket to the public Internet or to the website.
- Treat OBS acknowledgement as a command result, not proof of what Twitch viewers received. Validate independently against output, delayed buffers, recordings/VOD, NVR/SD/cloud capture, audio paths and reconnect/restart fault conditions.
- WiFi 12 garage/green room, multiple microphone switches and user-specific camera routing are later experiments requiring location-specific capture/consent rules. Individual audience camera selection cannot be achieved by switching one shared Twitch output; it would require separate authorized feeds and a dedicated viewer/player.

## Booking -> Jetson integration, without remote OBS access from PHP

Preferred minimal transport: the PHP/SQLite host writes **nonpublic, allowlisted, versioned events or a polling snapshot** to a private authenticated integration endpoint or outgoing queue; a *Jetson-initiated* poll over HTTPS is safer than publishing OBS controls. Return only public-eligible display fields, time range, stable opaque booking ID, and independent flags for stage name/on-deck announcement/streaming/recording/clip/destination rights. Ineligible/private bookings return no identity, schedule or public cue; the controller must not infer private occupancy from blank slots or broadcast changes.

Never send contact details, private location/entrance instructions, scripts, writer submissions, legal names, signed release links or admin session tokens. Apply narrow scoped tokens, TLS, replay protection, expiry, idempotent event IDs, bounded clock skew, audit and revocation. A revoked grant removes display/clip eligibility immediately on the next successful sync; offline/stale state defaults to generic safe scene/disabled name graphics, **not** last known public name. The application does not certify NVR/OBS privacy or auto-clear occupancy.

First overlay: synthetic approved performer identifier and *manual* onstage state, with OBS browser source loading a **local** Jetson page (or a reviewed local graphic) and a generic fallback. No production performer identity until stage-name/public graphic grants are verified. Later: separately consented `ON STAGE`, `ON DECK` and next-up cards; never automatically publicly reveal a private slot.

## Clip retrieval UX and staged roadmap

**Phase 0, read-only verification:** inventory actual Jetson ffmpeg/OBS process and host location, camera/NVR models/API/RTSP support, independent recording topology and real retention, system/NVR time sync, Twitch VOD history/duration and stream interruptions, storage and legal/privacy constraints. No changes to live stream.

**Phase 1, manual event index:** authenticated host can timestamp a performance and select a verified camera/date/start/end, note a candidate and copy the source reference. Add a sample exporter adapter against **synthetic or expressly authorized test footage**. Check that source is still retrievable and alert before expiry. A source timestamp is not an original-authorship certificate.

**Phase 2, OBS dry run:** establish authenticated local OBS WebSocket from the Jetson to observed scene collection, read current scene/source health, print *proposed* stage/parking transitions without issuing commands. Validate restart and stale-state handling.

**Phase 3, controlled live switch:** after real-device privacy proofs, approved camera placements, operator-arm switch, stage precedence, output/audio checks and stop fallback, enable just two whitelisted scenes; no open microphone switch and no autonomous private-session handling.

**Phase 4, booking-aware graphics:** safe read-only booking snapshot → onstage graphics with separate identity grant; manual check-in/state confirmation; expiry and withdrawal; independent outgoing video verification.

**Phase 5, community-highlight ballot (requires policy + consent update):** optional performer nomination of a bounded rights-cleared clip; public playback of **approved exports only**; basic abuse controls and auditable one-person/one-eligible-ballot policy (precise mechanism to decide), transparent opening/closing windows, moderation/takedowns. Distinguish `Community Choice` from `Editor's Pick`; fans may campaign but bot/duplicate votes must not set the ranking. Weekly winners may enter a separate, expressly authorized monthly showcase. No implicit permission for paid boosting, permanence or AI adaptation. Avoid storing unnecessary personal voting data; no fake votes or leaderboard.

## Acceptance gates

- Private/unrecorded booking: zero room footage stored *anywhere* in Reolink SD/NVR/cloud/alerts, OBS, Jetson or Twitch, with independently verified isolation or mandatory OFF fallback; no public event or identity leak.
- Verified public performance: exact UTC source start/end + measured Twitch anchor; correct selection over midnight/DST and a reconnect; clip request fails safely if footage missing, expired or uncleared.
- Stage busy/unknown means no parking switch; manual override and fault stop; newly occupied stage recovers without missing the approved performance opening. Video/audio are evaluated separately.
- Old/mismatched/replayed booking snapshots and withdrawn graphic/clip rights do not display names or trigger exports.
- Export remains private until independent performer/writer/face/voice/credit/destination approvals. No automatic publishing or votes on an unapproved candidate.
- No physical camera move, NVR changes, OBS settings, broadcast termination, public booking activation, new public ballot, production credentials or hosting deployment from this documentation PR.

## Next engineering proof to request

From the Jetson, capture sanitized outputs of process/service inventory, encoder/OBS installation/version, RTSP topology without secrets, OBS host and scene names, system/NVR clock status, and a tiny sample of timestamp metadata (not raw private footage). Identify whether OBS actually runs on the Jetson or another computer. Then choose the correct OBS WebSocket endpoint and prove **read-only** scene inventory before building a control client.
