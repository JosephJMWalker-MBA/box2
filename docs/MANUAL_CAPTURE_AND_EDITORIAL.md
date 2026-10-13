# Manual Capture and Editorial Checklist

P1 software and operator handoff, October 13, 2026. **Actual OBS/Reolink/NVR,
Twitch isolation, delay/VOD and real-device tests are NOT completed by CI.** No
live settings, source devices, bookings, venue permissions or ads were changed.
Issues #2/#3 cover operational verification; this increment addresses Issue #4.

## Before any unrecorded guest enters

1. Operate devices manually: disconnect every room camera/video/virtual-camera,
   microphone/ambient capture route, macOS desktop/screen/audio source, private
   notifications and control-panel capture. In-room amplification can remain
   separate from capture; lights and normal stage/host support remain available.
2. Verify independent Reolink SD/NVR/cloud/event snapshots/motion capture/mobile
   alerts and every other potential room recorder. Hiding an OBS scene is not
   enough. Resolve any building-security obligations separately before promising
   unrecorded use; do not guess which devices are safe.
3. Inspect outgoing buffers/delay, Twitch VOD, local recording/replay, monitoring,
   virtual-camera routes and automatic reconnection. Do not hardcode or claim a
   delay. Disable reconnect paths that can restore room sources after restart.
4. Prefer full OFF fallback until isolation is actually proven. If separately
   approved, use an independent prerecorded house source with cleared audio/video
   rights, not an overlay over a hot mic or room feed. House-only VOD can be allowed
   only if it contains no room media. No performer endorsement or paid-ad claim.
5. Test actual outgoing Twitch on an independent receiving device, including
   all audio, buffered frames, delayed output and retained VOD. Record a private
   test reference. **If uncertain, STOP STREAMING and recording.**
6. Only after real checks, record current assertions in the authenticated host
   desk. Software checks their scope/freshness; it does not operate or certify
   hardware. `allow_house_continuity` stays false until separately approved proof.

## During and after the set

- Keep normal T−20..T−10 arrival, check-in upon arrival and T−10 on-deck flow.
  Check-in fails closed without fresh room-off assertions. Do not announce a
  private/VIP name, plan, entry, location clue or presence publicly.
- Use equivalent house programming in ordinary resets/idle periods too, so an
  interlude does not announce a guest. Never share the host/editor dashboard.
- On uncertainty, source change, restart, interruption or device reconnect:
  stop the unsafe feed and mark fault/restart in the app. Reverify; no automatic
  OBS restart detection or reconnect control is shipped.
- Mark completion/cancellation separately from actual departure. Verify the guest
  is out of the full capture zone, clear occupancy, then recheck permitting stage
  content before restoring room sources. A completed DB booking does not prove
  the person left. New host sessions require new assertions.

## Privacy-safe manual scene copy

Use only when actually appropriate; these are copy templates, not live-state claims:

| Scene | Generic copy |
| --- | --- |
| Host programming | HOST AT WORK — Scheduled stage time can interrupt the program. |
| Consented performance | ON STAGE — Give the performer the room. |
| Preparation | ON DECK — Next performer preparing. |
| Independent interlude | HOUSE PROGRAM — Original sketches and reviewed house media. |
| Transition | RESET — Preparing the next segment. |
| Stopped channel | OFF AIR — See the declared studio schedule. |

This increment exports no performer names or automatic stage/on-deck cards.
Do not infer name-graphic permission from booking, livestream, Top 5 credit or
feedback grants. Never append private guest names, booked times, backstage routes
or a reason announcing a private session. No OBS plugin/control API is installed.

## One manual weekly Top 5

1. Log a real performed, recorded/clip-permitted source reference and valid
   in/out timecodes in `/admin/editorial`. Nothing is uploaded or generated.
2. Record original/writer origin and review every audiovisual/IP layer. Unclear
   origins fail closed. Linked writer performance/publication grants are necessary
   but do not substitute for clip-specific destination rights.
3. Privately route each candidate's signed performer/writer release to the actual
   rights holder. Confirm identity and legal rights outside the app; bearer links
   are not legal identity certification. Every grant starts OFF. Scope is one
   weekly organic compilation on four named destinations; no ownership transfer,
   paid boost, sponsor endorsement, AI/music adaptation or another person's credit.
4. Approve eligible moments; select/order at most five. Do not fill missing rights
   or exclude new/solo comics by popularity. Offer/handle preview and objections.
5. Manually produce a captioned vertical master, review intro/outro/music and all
   layers, then publish manually through separately approved creator accounts.
   Check current platform rules at publishing time; no limits are hardcoded here.
6. Record the actual platform URLs privately. The app does not verify the posts,
   send media, automate social posting, run ads, or measure reach. Post URLs and
   selected credit never appear on anonymous pages or analytics.
7. Before posting, withdrawal removes future selection and invalidates edit refs.
   After posting, handle flagged removal requests manually within BOX2's control;
   do not promise third-party erasure. Retain required rights/history privately
   under the approved policy and review aging source/media records separately.

## Real-device evidence still required before production

Record operator/date/configuration, enumerated independent devices and storage,
receiving-device proof, actual buffer/VOD checks, repeated stage → house/room-off
→ stage transitions, fault/restart/reconnect tests, guest-clear handling and stop
fallback. None of those facts can be inferred from the synthetic software suite.
Hosting/HTTPS/cron/mail, parking/premises/terms, backup/rollback and owner approval
remain separate launch gates. Never enable production from these test fixtures.
