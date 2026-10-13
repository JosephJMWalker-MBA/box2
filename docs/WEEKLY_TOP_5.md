# BOX2 — Weekly Top 5 Jokes (Flagship Distribution Format)

**Owner direction — 2026-10-09.** This is a canonical product/media requirement for BOX2's next Codex pass, not a claim the feature is implemented or that any external account is connected.

## Core concept

**The nightly room is the rehearsal workshop; the weekly Top 5 is the published show.** BOX2 operates its sober, privacy-first comedy rehearsal room six nights each week, with `cantonrefinery` Twitch programming that can include a delayed studio feed, host lectures, original sketches, studio maintenance, house promotions, on-stage performer intros and privacy-safe on-deck cards. A quiet or empty stage is normal and should not be disguised as an audience-filled club.

**Flagship show: “BOX2 — Top 5 Jokes This Week.”** Produce **ONE short-form vertical compilation containing five selected individual jokes/moments**, not five obligatory standalone shorts. Cross-publish that weekly episode to TikTok, YouTube Shorts, Instagram Reels, and Facebook Reels through approved creator accounts. Platform formatting and duration must be checked at publishing time; do not hardcode assumed current time limits or rely on licensed platform music reused on another platform. Optional later: standalone performer clips with separate rights clearance.

## Creative intent and trust

- The Top 5 selects **individual joke moments**, not a ranking of comedians or a public competitive league. No nightly voting, elimination, forced performance comparison, or score leaderboard.
- **Only choose eligible, usable and authorized material.** If fewer than five moments qualify, publish fewer moments or skip that week's episode rather than breach privacy, fill with weak material, fake crowd reactions or imply five performers were featured.
- Selection is **host/editor-curated**, based on joke quality, coherence out of context, shareability, and recorded intelligibility. Audience reactions or opt-in suggestions may inform editing; neither Twitch chat nor social popularity automatically decides the winners.
- The host may also be eligible for moments when appropriate, but avoid having every episode default to the host at the expense of emerging guests. Respect new comics and the relationship-first, welcoming stage culture.
- No promised feature, guaranteed views, payment or future invitation for being booked or performing. Copy: “With your permission, standout jokes may be included in BOX2's weekly Top 5.”
- Record performers' chosen public stage name, optional approved handle/profile link and pronouncing guidance for attribution. Do **not** disclose legal names, private contact, location of residence, backstage details, scripts/teleprompter text, or automatically tag a performer.
- If an original joke came from a submitted writer, verify that the writer granted **performance AND publication** and honor their agreed credit. Adaptation, AI visuals, or music require their own rights grants.

## Privacy-first release rules

1. Booking/entering venue does **not** grant livestream, archival, stage-name reveal, or highlight/clip rights. Each is an **explicit scope**; default OFF. A private rep remains off-stream and unrecorded. A delayed stream is **still a public stream**, not a substitute for private consent.
2. **Weekly cross-platform compilation publication** needs a clear, express permission for that scope and its destinations, including face/voice and credited stage name if used. Treat older/general “clip eligible” consent as insufficient if it did not clearly authorize the relevant platforms and uses; obtain an updated permission rather than expanding old grants retroactively.
3. Avoid assumed perpetual reuse, boosted advertising or paid promotions: any additional promotional/advertising permissions beyond ordinary organic reposting are separately disclosed/authorized. Do not silently use user clips in sponsor advertisements.
4. Editor confirms rights for each shot/audio layer, jokes, intro/outro, background footage, music and any visual inserts; no scraping of Twitch VOD, Reddit, Facebook or others outside allowed permissions. If no consented local recording exists, do not pretend the timestamp or a Twitch VOD automatically grants publication rights.
5. Give the featured comedian an optional final-preview and reasonable pre-publication objection window. Once already distributed to third-party platforms, BOX2 cannot guarantee copies are erased; provide clear post-publication takedown/contact procedure, with honest limitations.
6. Stream delay, holding graphics and private blocks require actual OBS/audio routing controls. The host must ensure no private audio/video is inadvertently transmitted or recorded. Never show named “on deck” cards unless the next performer consented to that public disclosure.
7. Source media / edit masters / exported clips use private storage, defined retention and restricted access. Do not place raw footage in public GitHub, analytics or unsecured server directories. Audit publication approvals and reversals.

## Minimum weekly production workflow (initially manual)

```
Book + consent
   → Perform (optional authorized recording)
   → Host marks standout joke candidate with timecode and short editorial note
   → Eligibility check: recorded asset + performer/writer permissions + clip length
   → Editor selects at most 5 individual joke moments
   → Optional performer preview / pre-publish objection
   → Assemble ONE vertical, captioned short: countdown or 5 clearly delimited moments
   → Publisher manually posts to approved platforms
   → Log each destination link and basic performance metrics
   → Invite new comedians and writers back to BOX2
```

For each candidate, hold only needed data: `booking_id`, `performer_public_credit`, `source_asset_id`, `in_time`, `out_time`, `proposed_joke_title` (private until approved), `editor_note`, `weekly_show_date`, `rights_status`, `review_status`, `approved_at`, `published_at`, plus platform post URLs and dated metric snapshots where manually available. No automated editor/publisher is required for v1. An existing `clip_candidates` table may be extended with a separate minimal `weekly_reel_entries` table if needed; do not compromise consent/history.

Suggested statuses: `candidate` → `rights_review` → `approved` → `edited` → `published`, with `rejected` / `withdrawn_prepublication` outcomes. Fail closed when any permission cannot be established. A clip-candidate tag is **never** authorization to publish.

## Edit template / distribution

- Branded punchy opening: **BOX2 — TOP 5 JOKES THIS WEEK**.
- Five short, self-contained stand-up moments; preserve setup/punchline without deceptive splicing that changes joke meaning.
- On-screen stage name/approved handle for each, burned-in readable captions, optional numeral 5→1, no unwanted legal identity.
- Branded close: **“Everybody starts somewhere. Start here.”** + `box2.yurrmom.com` + concise call to book a slot / submit an original joke.
- Produce one neutral, clean vertical master and platform-specific variants as needed. Keep caption-safe areas clear of app overlays; no unlicensed cross-platform soundtracks or reused platform watermark.
- Default manual publishing. Copy/share metadata tracked with UTM-based campaign attribution; Facebook insights are for interest measurement. The actual booking/check-in conversion is measured first-party, respecting consent and privacy.
- Track each post's URL and available aggregate reach/views/engagement (do not claim exact unique individuals or bookings caused merely by impressions). Record referrals and bookings with privacy-respecting UTM data only.

## Codex implementation priority

- **Now:** add a prominent truthful homepage section explaining the weekly Top 5 and privacy/opt-in conditions; reflect its role in the product copy. Keep live stage schedule and booking prominent.
- **First post-MVP increment:** host can tag a timecoded joke candidate, inspect permissions, shortlist up to five, order them, track review status and capture published links. It is a **light editorial checklist**, not an AI editor, video-storage stack or direct publishing API.
- **Later, only with explicit approval:** richer clip library, preview links, automatic rendering, distribution adapters, revenue sharing or sponsorship. Never require social accounts, public profiles, or publication permission simply to get onstage.

## Acceptance tests

- Privately booked/live-only/no-clip material cannot be selected/published.
- Writer-submitted lines without writer publication permission are excluded.
- Clip consent and public credit are independently respected; explicit cross-platform scope is captured for newly selected participants.
- Timestamps are linked to actual consented recordings, not generated as originality certificates.
- Fewer than five authorized candidates never causes rights bypass.
- Preview and withdrawal prior to publication work; published clips can be requested for removal without guaranteeing erasure of copies.
- An unapproved candidate never appears in an automated stream graphic, preview metadata, public social card, or share link.
- No auto-posting, analytics overcollection, assumed revenue, false viewer numbers or forced exposure.

**Key principle: BOX2 is the daily practice environment. The weekly Top 5 is the voluntary distribution opportunity that makes the room discoverable and brings more people to the stage.**
