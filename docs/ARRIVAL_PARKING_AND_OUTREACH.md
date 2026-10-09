# BOX2 — Parking, Arrival and Neighborhood Access

**Status: draft operational diagram specification — verify all ingress/egress, stalls and property rights onsite before website publication.** This document supersedes preliminary AI-generated parking graphics, which incorrectly swapped entry/exit and showed unsupported overflow parking. The annotated owner map supplied October 9, 2026 is the directional source of truth, subject to onsite validation.


## Correction after owner review — October 9, 2026

The owner rejected the earlier generated diagrams because they **did not match the physical aerial image or the owner's markings**. The inaccurate `docs/box2-arrival-draft.svg` was deleted. **Do not reuse it, regenerate the underlying satellite site plan, draw imaginary buildings, add fabricated parking stall lines, or promote an AI-reconstructed aerial to public directions.** The authoritative geometry is the exact, original user-supplied, unannotated Google Maps aerial screenshot together with the owner's edited markup, not the prior AI imagery or the deleted SVG.

In the owner's markup: **BLUE is the intended vehicle route**, including **1 lower/south entrance and 2 upper/north exit**; **GREEN is only the paved parking immediately next to the long white building where the white car appears**; **RED is restricted/no parking/access space around the residence and cross-drive lanes**. The blue route must not pass through red marked areas, the neighboring home, or nonexistent roads. The owner's posted arrows should be traced accurately, not improvised. No Jerzee's overflow and no walkway/trail guidance.

**Asset publication block:** no parking map is approved for deployment yet. A photographic overlay using the actual source pixels can be prepared as a review draft, but don't confuse it with a surveyed or owner-approved map. First obtain confirmation of each driveway, the route, specific green parking area, any no-parking strip, actual entrance, permitted hours, and fire/emergency clearance. Public page must wait for verification.

## Owner-annotated color key

- **BLUE — vehicle traffic flow**, with directional arrows and **numbered access points**.
  - **1 = ENTER at the SOUTH / LOWER driveway** from Harrison Avenue NW (closer to Hillcrest Road).
  - Follow the shared maneuvering lane toward the BOX2 parking bays next to the white/long rectangular studio building.
  - **2 = EXIT via the NORTH / UPPER driveway** to Harrison Avenue NW (closer to Ferndale Road).
  - This is the desired *predictable route*, **not** a claim of formally approved one-way traffic; verify before posting mandatory signage.
- **GREEN — BOX2 parking bays only**, directly alongside the white/long rectangular building (the building with the white car in the owner's original aerial photograph). Show only the owner-marked bays; number and precise stall geometry must be verified on site before declaring a count. **Do not mark the general gravel lot or neighbors' parking as BOX2 parking.**
- **RED — KEEP CLEAR**, including driveway/access strips by the neighboring residence and southern access zone. Do not park, idle, queue or block access in these areas. Red must not be misrepresented as the drivable path.

## Never publish inaccurate guidance

- Prior AI illustrations swapped entrance/exit: **do not use them** unless corrected.
- Remove all mentions/maps of **Jerzee’s** as suggested overflow parking. Do not imply that any other business's or apartment resident's spaces are available to BOX2 performers.
- Do not invite visitors onto the nearby trail or promise a pedestrian route from offsite parking.
- Don't label the white building as a music studio; it is the **BOX2 comedy rehearsal/performance space**.
- Neighbors live immediately beside the maneuvering area; show the residence plainly as **PRIVATE RESIDENCE — NO PARKING / NO WAITING**.
- Do not publish private rear entrances or VIP routes in public visitor material. The host may coordinate a private guest entrance directly with an authorized booked guest after verifying legality, accessibility, and building safety.
- Do not say that the diagram authorizes parking in a lot or traffic direction solely from a screenshot; obtain/confirm venue rights and signage.

## Public visitor instructions

**Arrive on time, not early.** **Approved window: 10–20 minutes before** your booked set; **check in upon arrival** and be **on deck 10 minutes before** your stage time. Do not arrive more than 20 minutes early; wait in the designated lobby until called. BOX2 spaces are for actively arriving/departing performers. Use **only designated green-marked BOX2 bays** beside the long white building. If full, contact the host; **do not improvise parking in residential, shared, or access areas**. Follow the displayed blue preferred arrival/exit flow when safe and legal. Keep all red-marked areas and driveways completely open. Do not confront a blocking driver; inform the host. Keep voices, headlights and exterior noise considerate of neighboring homes; leave promptly after your set. **Focus on stage time. Socialize online.**

## Publication workflow and code requirements

1. Verify access points and route onsite, confirm owner/landlord designations and permitted hours. Check physical entry surface, direction/turning radius, night lighting, snow/ice season, ADA access/parking, and Fire/EMS access.
2. Produce **two views**: (a) mobile-first uncomplicated schematic (stored in repo SVG, scalable and accessible); (b) optional original on-site video walkthrough, showing actual legal parking and pedestrian entry. Satellite imagery can be a supplementary reference when licensed appropriately, not the sole instruction.
3. Page: `/arrival`; mandatory booking orientation card 2; reminder emails link to the same stable page. Provide alt text and text-only instructions, not color alone. Diagram legend must say **BLUE vehicle route, GREEN designated parking, RED keep clear**, with numbered **1 SOUTH ENTER** / **2 NORTH EXIT**.
4. Keep `/arrival` as draft/not publicly linked until #1 passes. Avoid implying the generated schema is surveyed or that alternate commercial lots are permitted.
5. Bring back user approval for the exact bay count, side-door indication, preferred route and sign locations before go-live.

## Local partner outreach (after site redeploy and site/venue readiness)

The nearby **Hall of Fame Apartments** is a potential community invitation, not a parking facility for BOX2 guests. Seek property management's permission to place a QR-code flyer or newsletter mention offering nearby residents a walkable, sober, beginner-friendly comedy rehearsal experience. Residents can walk from home; **do not advertise their private resident parking for outside visitors**. Use aggregate QR campaign attribution, not apartment numbers or resident lists. Launch outreach only after the BOX2 website, HTTPS, booking flow, and in-person readiness are verified.
