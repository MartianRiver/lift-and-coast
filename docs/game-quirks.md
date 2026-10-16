# Game quirks

What the F1 games actually send, as opposed to what the spec suggests. All of it found on real sessions; most of it shaped some piece of code.

## Telemetry settings

In the game: Settings → Telemetry. UDP On · Broadcast Off · IP = the address of the machine running the server (give it a fixed one on your router) · Port 20777 · Send rate 20 Hz · Format: the newest the game offers (F1 25 with the 2026 Season Pack: 2026, a superset of 2025, so keep it even with 2025 cars; F1 24: 2024).

## The spec

EA publishes the UDP spec on its forums: the 2026 Season Pack post (blog id 12187347) and the F1 24 thread (8369125). The files go in `docs/` (gitignored: EA's licence is for reference). The forum pages return 403 to curl, so open them in a browser; the attachment links (`…/t5/s/tghpe58374/attachments/…`) download fine with curl. What's expected there:

- `docs/udp-spec-*` / `docs/udp-structs-*` — EA specs, gitignored: 2026 v1.2 PDF and text, F1 25 v3 PDF and text, F1 25 / 2026 C struct files, F1 24 v27.2x docx and text. Source: the attachments on the EA forums post "EA SPORTS F1 25: 2026 Season Pack UDP SPECIFICATION" (blog id 12187347) and the F1 24 thread (8369125). The forum pages return 403 to curl, so the attachment links come from Chrome; the `…/t5/s/tghpe58374/attachments/…` URLs themselves download fine with curl.

## Spec facts

- Header `gameYear` reads 25 even in 2026 format. Game version seen: 1.26.
- 24 car slots (22 in formats 2024/2025); check `resultStatus >= 2` for active cars. Empty slots and human drivers send id 65535 in 2026 format, 255 in older ones; padded slots from older formats read 0 (driver 0 = Sainz), so key off `name`/`resultStatus`, not ids.
- ID tables only grow between years (no id changes meaning between F1 24, 25 and 2026), so `lookups` is the 2026 appendix plus F1 24's extra ids.
- 2026 team IDs are 476–486 (Cadillac 486), not the ~220–230 the community notes claimed. Driver/team/network IDs are uint16 now.
- Wheel arrays: RL, RR, FL, FR.
- Restricted online players zero out fuel/ERS/wear/damage; offline AI data is complete.
- `BUTN` events carry the 32-bit button mask, including UDP Action 1–12 → candidate radio trigger.

## Observed

- **Game goes quiet** (pause, mid-session save, console off): no packets at all. The state keeps the last numbers, so everything stamps `silent_for()`: Race tab banner + dimmed panels after 15 s, calls stand down after 5 s, and after 5 min the brief starts with `FEED LOST` so the engineer says it has lost the feed instead of answering from frozen numbers (a short pause is *not* flagged: the state is still right). Silverstone race 2026-10-13: saved at L12/18 and switched the Xbox off; archived as #13.
- **Resuming a mid-session save gives a new sessionUID** (Silverstone 2026-10-14: #13 uid …1671 → …7870 at the same lap), so the server starts a fresh state: lap number, tyres, weather, damage come straight from the game and are right at once, but everything we accumulate (lap crossings, gap trends, wear rates, race log, pit loss) restarts from the resume lap. The game also loads in stages: weather read as dry for a few seconds, so the first call said "It's started to rain" in a rainy race. `triggers.scan` now only baselines for `SETTLE` = 20 s of session time after it first sees a session; rain calls re-arm only after a dry spell. Not built yet: seeding the new state from the archived earlier part of the same race (same track/type/total laps, last lap ≤ resume lap).
- **Stopping the server:** a server started with `&` from a script ignores SIGINT (non-interactive shells set it ignored). `kill -TERM <python pid>` always works and archives on the way out; a 250 MB race takes ~1–2 min to compress, so wait for it to exit before starting the next one, or the new server's startup sweep races the old one on the same file (happened once; the catalogue ended consistent and `xz -t` passed).

- **2025-regs careers** (Driver Career '25) send legacy team IDs 0–9 and `is2026Regulations = 0`, so the 2026 active-aero/overtake fields read zero. The UDP *format* stays 2026 regardless. Nothing here depends on those fields yet.
- `BUTN` fires for every controller button with separate press/release, in menus **and while driving** (confirmed on track). A raw button and its UDP Action binding report as separate bits.
- **Radio controls (confirmed on track, Xbox controller):** LS click = UDP Action 1 = radio, **hold to talk** (the default; `--radio-mode toggle` for tap on, tap off). RS click = UDP Action 2 = quick action (proposed: no-speech "quick brief"). Wheel buttons later.
- Cars sitting in the garage report `pitStatus = 1` (Pitting).
- In practice, `OVTK` events fire on timing-order changes (a car setting a lap "overtakes" everyone in the garage) — filter before using for callouts.
- **Flashbacks** (verified on a practice recording, a 15 s rewind): `FLBK` event gives target frame + sessionTime; then `sessionTime` and `frameIdentifier` jump back and *all* state (lap distance, lap time, fuel, wear) reverts. `overallFrameIdentifier` keeps increasing. Practice lap was not invalidated. **Rule for any accumulated history (analysis layer, events, LLM context): on FLBK drop everything with sessionTime > flashbackSessionTime; order samples by overallFrameIdentifier; tag laps that contained a flashback.** Current dashboard is latest-state only so it self-corrects (events log doesn't prune yet — cosmetic).
- Time acceleration (practice) jumps sessionTime forward — derive per-lap rates from laps driven, not elapsed session time.
- `fuelRemainingLaps` is the **MFD fuel delta** (laps over/under target), not laps in the tank. Confirmed in the race: it held +1.67 for the whole first stint, rose to +2.6 under the SC, and was +2.67 with 5.5 kg left on the last lap. (FP1's 13.4 was a delta against the short practice target.)
- Safety car: `SCAR` eventType 0 deployed → 1 "returning" (≈ SC in this lap) → 2 returned → 3 resume, at the line. `DRSD` on deploy; `DRSE` one lap after resume. `laps.py` tags each lap that ran under SC/VSC (`scLap`), and pit loss / ref pace / deg skip those laps.
- Tyre sets (packet 12, sent for every car): `lifeSpan` = laps left in that set (game's estimate), `usableLife` = recommended max, `wear` ≈ mean of the four corners, `lapDeltaTime` = ms/lap vs the fitted set (negative = quicker).
- Retirements lower `numActiveCars` (20 → 18 in the 2026-10-13 race) but cars keep their slot index (the player stayed idx 19). Never slice participants by `numActiveCars`; check names / `resultStatus` per slot.
- **End of a session:** the game finishes the AI's in-progress laps off-screen. Session history and Final Classification (packet 8) get the results, but lap data stops with stale `carPosition`. Quali 2026-10-13: PIASTRI was 2.7 km into a lap at the flag, then credited with a 1:13.825 lap that was never seen in lap data. The brief prefers packet 8 positions when present.
- Practice captures are thin for lap analysis: AI cars sit in the garage and time acceleration squashes laps (11 s "laps").
- Capture size ≈ 10 MB/min at 20 Hz (~600 MB/hr raw, ~65 MB/hr once archived as xz).
- **Track limits** (Montreal race): the 3rd corner-cutting warning gave a 3 s penalty, both times. Lap data's `cornerCuttingWarnings` / `totalWarnings` / `penalties` drop back after a flashback (3 → 2 and 3 s → 0, twice), so they're the source of truth, not PENA events. `RTMT` is re-sent for every retired car after each flashback.
- **Quali keeps one lap number** through a return to the garage, the out lap and the next flying lap (distance jumps back to the pit exit, then to ~0 at the line). **AI cars in quali** are driven off-screen while the player is in the garage: their lap data arrives in jumps (50–600 samples a lap instead of ~1,500), useless for traces.
- The SC flag (`safetyCarStatus`) stays set for a moment after the restart line; the player's fastest lap (L14, the restart lap) was nearly marked an SC lap.
- **Engine/gearbox damage is season-long component wear** in career (parts get rotated, often using the first of each in practice). The brief shows it as `power unit` with the change this race, never as damage.
- `pitStopRejoinPosition` moves a lot around the lap (Austria L6–7: P17 → P13 → P11), so pit loss read from it is a range and only used until a real stop is measured.
- **Restarting a race gives a new sessionUID**: Austria 2026-10-13 the first attempt (8 min) was archived as its own session (#7) and the restart recorded to a new file.
- `SEND` comes before the final classification (Austria FP3: SEND at +44.8 s, packet 8 at +96.9 s); a new session follows on a new uid.
