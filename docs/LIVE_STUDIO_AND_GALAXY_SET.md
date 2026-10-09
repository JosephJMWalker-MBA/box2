# BOX2 — Live Studio, Evolving Galaxy Set & Production Cutover

**Owner update — 2026-10-09, witnessed in OBS screenshots.** This is a real operating milestone and an implementation/operations handoff, **not** a claim that the new Codex website is deployed, public bookings are enabled, OBS privacy is verified, or premises have been approved for public attendance. Keep these distinctions explicit in the site and release notes.

## A. Observed evidence, and limits

- Owner reports BOX2 is **streaming now**, and an OBS 32.2.2 screenshot showed a **“Stop Streaming”** control, running time/counter, green network indicator and a `Reolink` scene. The OBS preview displays a wide shot of the workshop stage with jukebox, stool, ladder, small raised platform and renovation space. This establishes an **active OBS streaming session at the captured instant**, but not Twitch playback to an independent viewer, VOD policy, audio isolation, latency/delay, public identity controls, or ongoing reliability.
- Owner reports that the stage room has been **closed off from dogs**, preventing further routine indoor urination/defecation and permitting its gradual refurbishment. **Animal exclusion does not itself certify decontamination or a safe floor.** Assess/clean residual contamination, moisture, damaged concrete and active building issues before painting or opening to performers.
- **Chosen visual direction:** progressively paint walls and floor **pure black** to create a minimal dark stage; keep the existing colorful jukebox and adaptable stage lighting as visual anchors. Over time, **selected comedians who contribute meaningfully to the room may optionally be invited to add a paint splatter/star/constellation**, creating a unique galaxy backdrop that physically records the room's developing community. This is **a creative possibility, not a promised prize, a public rank, a mandatory rite, or a feature to monetize.** The empty black room progressing into a galaxy is itself potential long-term promotional footage with appropriate permissions.
- Last observed browser screenshot for `box2.yurrmom.com` displayed **Chrome “Not Secure” while reporting a valid certificate**. The cause was not established; inspect DevTools Security/Console/Network and form/resource URLs before treating HTTPS as solved.
- DirectAdmin shows the subdomain document root `/domains/box2.yurrmom.com/public_html`. Owner selected account-global **PHP 8.5**, with PDO SQLite and several required extensions enabled in the panel, and reports the parent `yurrmom.com` site continued loading on mobile afterward. **Per-domain isolation is disabled by hosting administrator**; do not infer filesystem/datastore isolation from the domain names. Verify actual PHP `phpinfo` equivalent *privately* with nonsecret output, CLI/web SAPI, writable private path and cron on the real host.
- The publicly served website visible in screenshots is still the **legacy booking/site design**. Codex's PHP/SQLite v0.2.0 PR #1 remains an undeployed candidate until protected staging and acceptance checks.
- Do not commit camera credentials, actual stream keys, owner contact information, raw private screenshots or third-party copyright-protected audiovisual media.

## B. Studio design and safe renovation sequence

**Objective:** Make a recognizable, camera-friendly working rehearsal environment without waiting for full cosmetic completion and without masking safety-critical hazards.

1. **Secure stage**: prevent animal entry; remove ladders, tools, exposed or unstable renovation materials and tripping obstacles from public routes for any visiting performer; inspect walls, roof/water ingress, mold-like surfaces, electrical outlets/wiring, egress and lighting. Any suspected serious hazard requires a competent assessment/remediation rather than attendee waivers. Don't invite others into a work area while active work makes it unsafe.
2. **Clean and dry before coating**: clean/disinfect previously affected surfaces appropriately for the contaminant and surface, address underlying moisture, degrease/prepare concrete and test coating compatibility. Record chosen coating safety instructions. Use a suitable **floor-rated, slip-resistant** product and observe manufacturer preparation, ventilation and full cure requirements. Avoid projecting a wet/coating work zone as available performance space.
3. **Black foundation:** prioritize camera-facing walls and safe floor treatment after preparation. Pure black must **not erase clearly visible stage edges, stairs/changes of elevation, entry/exit routes, fire/emergency equipment or accessible paths**. Mark those conspicuously, including in low light. Lighting and camera exposure must still allow an audience to see a human performer and their expressions.
4. **Camera continuity:** maintain an approximately repeatable framing/photo of the same set on successive build days, to tell the story of the room's transformation. No obligation to stream every construction task, and keep house camera/stream off where work might reveal private data, copyrighted audio or people who did not consent.
5. **Galaxy contributions:** only after paint has cured and the room is operationally ready, host may invite an individual comedian to place a small approved splatter/mark in a designated safe wall/backdrop region, **not the performance floor, slip zones, emergency markers, lighting/equipment, or protected exits**. Host supplies compatible low-odor paint, protective coverings and cleanup; participants opt in. No public ranking/pressured participation; don't treat invitation as a prize that guarantees a weekly Top 5 placement. Attribution/capture/publicity separate opt-ins. Permission to paint doesn't imply permission to film or post the painter.
6. **Jukebox:** aesthetic anchor, but any music/audio played into Twitch, recordings or social short-form needs copyright clearance or permitted licensed use. The visual presence of the jukebox is not clearance for copyrighted audio. Test stage performer contrast/exposure against the black background before choosing lighting settings.

## C. Privacy-first OBS operational procedure — immediate priority

**Stream is already running; prioritize actual routing and manual controls before adding UI automation.** OBS scenes and website “status” are not proof that sources have stopped.

- **Audit every source in all scenes**: Reolink video/audio, active `macOS Audio Capture` or desktop capture, media sources, monitor capture, embedded browser, microphones, alerts, replay/VOD and any Twitch auto-retained VODs. A disabled video source can leave audio hot. Screen sharing must never expose personal accounts, private GitHub repositories, credentials, booking emails, phone numbers, personal messages, scripts, hidden stage lineup or admin panel.
- **Verify actual viewer side**: from an independent browser/device, confirm the right Twitch channel (`cantonrefinery`), correct scene, desired picture/audio mix and whether a recording/VOD is created. Note effective end-to-end latency. Choose/configure a stream delay later; **no owner-approved delay duration yet**. Delay alone does not remove third-party ability to capture an authorized stream.
- **Separate safe scene family**:
  - `STARTING/WAITING`: branded safe media, future booking CTA, truthful on/off status.
  - `HOST WORKSHOP`: authorized host lecture, original comedy, creative/physical activity, studio build, owner house ads and sketches. Pause/review content when it includes login sessions or confidential material.
  - `PERFORMER LIVE`: only with explicit livestream permission, independent consent to the name/graphic if displayed, host-controlled handoff; house programming stops at booked time.
  - `ON DECK`: generic “Next performer preparing” unless next performer consented to identity disclosure. Never leak future/private lineup.
  - `RESET`: safe visual break plus *physically correct* live-room mic sanitation and performer transition.
  - `PRIVATE`: **stop/divert all room camera and audio from outgoing stream, stop unauthorized local/OBS/VOD recording and prevent the private set from entering buffered delayed output**; when unsure, **STOP STREAMING** before the set. An animated slate while room audio stays live is not private. Review Twitch VOD/clip settings and prior buffered frames.
  - `OFF AIR`: genuine end state, no misleading `LIVE` cues.
- **Test fail-closed transitions using synthetic rehearsal** (only owner/consenting tester): public → private → public; disconnect and reconnect; automatic audio capture; VOD; delay backlog; name/identity graphics; scene switching. Verify independent outgoing feed, not just local OBS preview. Keep a written host stop/restore checklist.
- The owner reports a livestream right now, **not** that new online booking or public visitor access is ready. Streamed host work may continue within platform/rights safety rules, but public bookings and venue publication flags remain OFF pending the launch checklist.

## D. Lightweight Codex integration

**Keep the application server-rendered PHP/SQLite.** Codex should not install OBS control plugins, Twitch bots, remote-control endpoints or expensive editing suites for this milestone.

Small supported website/application changes:
1. The homepage accurately explains that BOX2 broadcasts a **working rehearsal room**: host project talks, original sketches, room building, safe interludes and consenting performers, not a polished full-audience comedy show. “**Bored yet? Book a slot and take over the stage.**” is a **scheduled booking invitation**, not on-demand immediate access. Booking CTA may render while booking disabled but must truthfully indicate unavailable/not open.
2. Add a *privacy-safe* static `NOW ON STAGE`, generic `ON DECK`, `ROOM RESET`, `HOST AT WORK`, `PRIVATE / OFF AIR` copy/graphic guide or templates. Prefer **manual OBS scenes** over an automated endpoint and do not expose performer identity by default. No real camera footage or names embedded in repo.
3. The weekly Top 5 short remains the recurring **flagship external output**, not the raw 30-hour/week feed. Host may log eligible time-coded moments only after recording and cross-platform releases; consent review and manual editing/publishing initially. See `docs/WEEKLY_TOP_5.md`.
4. Studio “galaxy wall” is a **real-world evolving art project** and storytelling motif. It does **not** require a user profile system, digital rewards, leaderboard, photo wall or public ranking. A short truthful “room under construction/evolving” line may be useful once public facilities are approved.
5. Preserve six-night schedule, group signups recommended not required, no venue hangout, the approved T−20..T−10 arrival and parking safeguards, nine-card orientation, private-first consent and all existing passing tests.

## E. Next operator actions, in order

- [ ] Confirm stream reaches the intended Twitch channel from another device, with **only intended video/audio**, and inspect Twitch VOD/clip retention and scene routing. Do not add a private performer until private transition test passes.
- [ ] Check whether a stream delay is configured and measure actual public latency before setting an operational policy. Do not advertise a specific latency without checking it.
- [ ] Inventory and remediate any residual animal soiling, surface moisture, exposed construction and electrical hazards, and clear stage/egress; use paint rated for the particular wall/floor substrate, allow full cure and preserve visible edges.
- [ ] Record before/after fixed-angle images with appropriate permissions; ensure camera exposure works in black-painted room.
- [ ] Diagnose Chrome's `Not Secure` state despite valid certificate, and verify the parent domain didn't regress from account-global PHP 8.5.
- [ ] Create backup of old BOX2 public root and any data/config; confirm private storage and supported PHP 8.5 from actual web/CLI, verify cron and rollback; stage Codex app without touching live files.
- [ ] Test bookings, signed links, private writer data, reminder emails and disabled-by-default permissions in protected staging. Explicitly require owner approval before booking or venue publication.
- [ ] Approve real property parking/arrival instructions and safe facilities before inviting first outside performer.
- [ ] Test consented performer-to-OBS transitions and prepare the first manually edited **Top 5** with rights-check ledger; market only after the booking destination is secure and truthful.

**Definition of done:** The camera feed can run responsibly; a private rehearsal is demonstrably private; the room can physically host an approved performer safely; the replacement booking app is HTTPS secure and reversible; each authorized joke can flow through a manual editorial process to the weekly Top 5 without accidental disclosure. Each milestone is independently verifiable—none can be inferred merely from an OBS screenshot.
