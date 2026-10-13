# BOX2 — Private Rehearsals with Continuous House Programming

**Owner-approved product direction — 2026-10-09.** A performer, including a high-profile guest, may reserve **a normal BOX2 stage session with the standard booking and arrival experience** while choosing **PRIVATE / NO ROOM BROADCAST OR ROOM RECORDING**. During that time the public Twitch channel may continue showing **fully isolated prerecorded house ads, owner-business promotions, original sketches and other authorized programming**. A delayed stream may be configured later after measured tests; **delay is not a privacy mechanism** and is not yet verified.

**Two simultaneous products, not two camera views:** (a) a live in-room rehearsal whose camera/microphone/audio and any other room capture are not transmitted or recorded; (b) a separate, independently sourced advertising/entertainment feed suitable for public broadcast. Only the **house programming** may be recorded by OBS/Twitch while the room remains isolated. A simple video overlay on an active microphone feed is NOT private.

## Performer/guest booking experience

- Keep the existing 5/10/15-stage-minute booking system, individual nine-card orientation, T−20 to T−10 arrival/check-in window, legal/privacy notices and available private rehearsal choices. Normal stage lights, mic/teleprompter as appropriate, host support and in-person work remain available **without requiring camera capture, publicity or clips**.
- Performer selects PRIVATE as the booking/recording option and retains the same practical reservation/check-in/host experience; privacy does not require creating a public celebrity/VIP event or disclosing identity. The host may discreetly arrange a guest session using existing private or host-held contiguous blocks if capacity and safety allow, and must avoid double booking. No private tier, rate or preferential access assumed by default.
- The public schedule only reveals **generic unavailable/held blocks**. Never expose a private booking's stage name, legal name, exact arrival/departure plans, contact, number of guests, on-deck cue, publicity status, teleprompter text or private guest notes. Do not publish an invite, named status, personalized ad break, recognizable guest introduction, behind-the-scenes view or “A VIP is rehearsing now” notice. Prevent inadvertent metadata leaks via URLs, API responses, social cards, logs, screenshots, admin overlays and stream alerts.
- Private recording consent remains default OFF. A performer's decision not to be live does not prohibit them from performing in the room, obtaining private host feedback when opted in, or returning for another session.
- An absence from the stream or an ad break must not be presented as proof anyone is there. To reduce easy correlation between a particular booking and a break, **air the same house programming routinely during normal public resets and idle periods**, not exclusively when private bookings occur. Avoid announcing private session timing on a public calendar or stream.
- **Do not promise absolute location secrecy**: the venue's general address may eventually be public, local observers may see arrivals, and third parties may share information outside BOX2's control. The enforceable BOX2 promise is **not publicly disclosing a guest's identity, booking particulars or presence through BOX2 systems and transmissions**, absent explicit permission.

## Broadcast / physical source boundary (P0 before any private performer)

**Allowed channel continuity:** OBS or another producer can broadcast pre-reviewed prerecorded house video from a source that cannot capture room cameras/mics/screens. Twitch may retain VOD of this **house-only** output subject to configured policies and media rights.

**Forbidden during private rehearsal:** any live studio Reolink video/audio, room microphones, ambient/desktop/macOS audio capture, NVR/SD/cloud recordings or motion-triggered snapshots capturing the person, local recording/replay buffer, browser/screen capture of stage/admin details, automated alerts/labels or a delayed outgoing buffer containing the private performance. Disabling an OBS scene only addresses OBS routing; independently configured security cameras/NVR/cloud/mobile alerts may still record. Explicitly verify/disable all cameras' independent capture and storage and any other potentially recording devices in private rehearsal zones, consistent with building safety/security obligations.

### Manual state transitions

1. **Before admitting private guest:** confirm exact scheduled reserved slot, private permission, host-only identity; arrange safe access. Switch to an **isolated house media feed** before the room becomes occupied by the private performer; turn off/disconnect room audio, studio video, local/cloud/SD/NVR camera recording and photo/event capture. Verify delayed and buffered output cannot subsequently reveal the guest.
2. **Prove isolation:** test from a second device receiving actual Twitch output, not merely the OBS preview; check audio mixer, monitor, virtual-camera, notifications, replay buffer, VOD and local recording settings. If not certain, **STOP STREAMING AND RECORDING**; a silent or offline channel is safer than guessing.
3. **During private set:** perform the usual reserved stage slot and on-deck handoff privately. Public viewers see normal house ads/sketches or an ordinary branded interlude, with **no guest-identifying text**. If staff cannot guarantee isolation, suspend house stream. Keep private host control screens and notifications out of live media sources.
4. **After guest is finished and safely out of capture range:** verify the room is clear, recording devices intentionally restored only to a mode appropriate for the next consenting act, latency/delay backlog accounted for, and public scene/audio verified by a second device. No retrospective footage creation of private session.
5. **On faults/restarts:** reverts to **house-only or OFF**, never to auto-live Reolink/studio audio. A crash/restart or OBS scene reset cannot silently reconnect sensitive room sources. Document operator checklist and test repeated public -> private house programming -> public transitions.

## What counts as an advertisement

- **Now:** owner's original business spots, original comedy videos, authorized product demonstrations or pre-cleared programming. These can fund/inform audience development without disclosing a guest or putting private source audio in the stream. Label overt paid advertising/sponsorship clearly if introduced; follow platform and applicable advertising disclosure rules.
- **Later:** possible sponsor inventory and rate cards, but no automatic paid-ad system, campaign pricing, Twitch monetization guarantee or revenue attribution is already established. Any embedded music/video requires the rights necessary for live broadcast, platform VOD and cross-platform reuse where applicable. Advertising must not imply that a performer endorses an unrelated product.
- House media may remain live/recorded even while the **private ROOM** is not streamed or recorded, provided the outputs are verified separate. Public page can truthfully say `Studio programming continues between performances`; don't expose private stage scheduling as the cause of an ad break.

## Minimal code impact vs operator controls

- The existing `private` consent state and host-held/private blocks are the baseline; preserve individual booking simplicity, stage minutes, arrival, security and test coverage.
- Tighten public schedule and event/lineup rendering to **generic unavailability** for all nonpublic bookings, regardless of performer status; never show “private rehearsal in progress,” “VIP,” or private person's name. Admin remains protected.
- A host-facing non-public note/checklist may say **PRIVATE ROOM — HOUSE MEDIA VERIFIED / PHYSICAL CAMERA RECORDING OFF**, and log human confirmation with timestamp. **It is an acknowledgment, not automatic OBS/device control.** No change to `Twitch live` flag implies the room is streaming.
- Do not wire new streaming plugins, automation or ad systems until a tested, authenticated design is specifically requested. A manual OBS scene and playback source can fulfill the immediate workflow.
- Consider presenting permission state to performers as **“Private rehearsal — your set is neither streamed nor recorded”**, and to the operator as **“House program may remain on air only with all room capture confirmed OFF.”** Avoid implying that “private” means Twitch itself goes offline.
- Never put private performances into the weekly Top 5. Clip authorization requires distinct permissions and an actual permitted recording from a different consented appearance.

## Acceptance (not complete until tested)

- [ ] Performer can select private booking and complete ordinary 5/10/15-minute booking, orientation, check-in and cancellations, with no forced live/clip consent.
- [ ] Anonymous public availability displays only occupied/unavailable time, not names, private classifications, details or recognizable metadata. Public `ON DECK` never reveals the private guest.
- [ ] House commercial source continues to Twitch while **all** independent studio audio/video/recorders/NVR and previews that could retain guest images are confirmed disabled, with delay buffer inspected. Test on a separate receiving device.
- [ ] Normal idle/reset breaks use equivalent ads so house video does not uniquely signal a private booking.
- [ ] On scene faults, restart, camera reconnect, private-stage handoff or switch back to public, **no single audio or video frame** from private rehearsal is emitted or stored by BOX2 devices.
- [ ] A private guest is never selected by a Top 5 candidate/reel publication query; no marketer receives their identity; a house ad is never falsely attributed to performer participation.
- [ ] Operational procedures explain remaining real-world privacy risks and provide STOP STREAMING fallback. Exact delay not asserted until tested.

**Operating principle:** The audience can continue watching BOX2 programming without acquiring a window into who is in the rehearsal room.
