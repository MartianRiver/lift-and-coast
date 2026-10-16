# Radio: what a real engineer would say, and when

Worked out from River's Montreal race (2026-10-13, 25 laps, won from pole) plus a few sourced conventions. This is the target behaviour for `engineer.py` and for the proactive layer after it, and it's deliberately not the in-game engineer.

## What the in-game engineer got wrong

It offered a stop under the safety car ("we'll be ready if you want it"), then on the run to pit entry said "stay out, stay out, there's no advantage to pitting now". River boxed anyway. **All 20 cars pitted that lap**, and waiting would have meant a full green-flag stop: Verstappen's green stop on L9 dropped him P3 → P15. Lessons:

- **Make the call; don't offer a menu.** It's a recommendation with a reason, and a way to overrule it.
- **Commit point.** Once a box call is made, it doesn't flip without new information, and never in the last ~600 m before pit entry (Montreal: pit entry ≈ 4004 m, so nothing after ≈ 3400 m on the back straight). If something changes after that, say "stay out" only if it is decisive, and say why.
- **"No advantage" has to be a number:** stop cost now vs a later green stop, and positions on rejoin. The brief has both.

## Sourced conventions

- **Timing:** talk on the straights, not in braking zones. Button on Verstappen's 2023 US GP radio, Sky F1 via [Sportskeeda](https://www.sportskeeda.com/f1/news-max-verstappen-s-irate-abusive-team-radios-race-engineer-backed-jenson-button): *"It's not hard for them to look at where the straights are, and speak on them."*
- **Drivers differ:** Laurent Mekies via [Motorsport.com](https://www.motorsport.com/f1/news/high-tech-f1-race-engineer-role/6687750/): *"Not all drivers want the same amount of information."* Some want lap times constantly, some want silence. So verbosity is a setting River can change by voice.
- **The engineer as funnel:** same source. The information includes weather forecasts, tyre condition of everyone on track, the car, and opponents' pace. That is our engineer/strategist split: strategists feed, the engineer decides what reaches the driver.

## When to talk: Montreal from River's laps

These are the stretches with throttle > 95%, no brake and steering < 0.15 for ≥ 2.5 s, consistent across L15–L20.

| window (lap distance) | duration | use for |
|---|---|---|
| 2750–3790 m, back straight after the hairpin | 13–15 s | anything that needs a reply or a decision: box calls, strategy, multi-part info |
| 1400–1900 m | ~7 s | gaps, one-liners |
| 2090–2570 m | ~7 s | gaps, one-liners |
| 390–650 m, after Turns 1–2 | ~4.5 s | very short ("Gap 3.2, steady") |
| 820–1000 m | ~3 s | too short; avoid |

Braking zones (no talking) start at ≈ 134 m (T1), 649 m (T3), 1161 m (T6), 1907 m (T8), 2572 m (hairpin), and 3793 m (final chicane, from 323 km/h). These windows should be **measured per track from River's own laps**, not hand-written; the method above works on any capture. Corner names are our labels from the speed profile.

## Proactive calls: this race, replayed

What a good engineer would have said, where, and the data that triggers it. "✓ brief" means the number is already in `brief.py`.

| when | trigger (data) | call | where |
|---|---|---|---|
| end L1 | first lap line; P1, HAM +1.22 | "P1. Hamilton 1.2 behind." | 1400 m |
| L1 contact | COLL with TSUNODA at 74 m (severity 0) | "Contact with Tsunoda there — car feels OK?" (check damage packet first; skip if zero) | next window |
| L2, L7 | PENA warning, corner cutting at 3923–3970 m | after the 2nd: "That's two track-limits warnings, both at the last chicane. One more is a penalty." | 1400 m |
| L9 | VER pit entry under green, rejoins P15 | "Verstappen's boxed, he'll come out around P15." Relevant because it shows the green stop cost | next window |
| L11 SC out | SCAR deployed at 816 s, River at 2019 m, ~2 km before pit entry | "Safety car, safety car. Box this lap, box box — new mediums, everyone will come in." One call, then silence until the box | immediately, it's urgent and still ~25 s to commit |
| L11–13 | SC laps | stay quiet except procedure: "Stay above the delta." "Your fuel's going up — plus 2.6 now" | straights |
| L13 SC in | SCAR "returning" at 1046.8 s, River at 2569 m | "Safety car in this lap. Battery's at 98% — use it on the restart. Tyres will be cold, careful into 3 and 6." | back straight |
| L14 restart | inner tyre temps 63–70 °C (vs 83–89 normal); lost ≈0.5 s at 750–1250 m | the warning above is the call; afterwards: "Good restart — 3.3 clear of Hamilton." | 1400 m on L15 |
| L15 | DRSE at 1163.6 s | "DRS enabled." (him behind could use it too) | 390 m |
| L18, L19 | RTMT COLAPINTO, SAINZ (terminal damage) | low priority: "Colapinto's out." Only if quiet | any window |
| L19→ | HAM gap peaks 6.46 at L19, then closes: 6.17 → 5.86 → 5.16 → 3.69 | from L21: "Hamilton's on the hards, closing 0.4 a lap. Gap 5.2, four to go — he'll be about 3.5 at the flag." Needs a **gap-at-the-flag projection** (not in the brief yet) | 2090 m |
| L20→ | RL wear 25% → 46%, lap times 75.6 → 79.0 | "Rear-left's the limit, look after traction out of the hairpin." | back straight |
| late race | fuel delta +2.6 laps, 5.5 kg left at L25 | "Fuel's good, you can use it." (rich mix / no lift-and-coast) | any window |
| L25 | last lap, HAM +2.27 | "Last lap. Gap 2.3. Bring it home." | 390 m |
| flag | CHQF / final classification P1 | "P1! Get in there!" — one celebratory line, then the result from packet 8 | after the line |

What it would **not** say: lap times every lap unless asked, chatter under the SC beyond procedure, and anything in the braking zones above.

## What River will ask: data needed, and gaps

| question | answer needs | status |
|---|---|---|
| gap ahead / behind, is he catching | gap at the line + trend in words | ✓ brief |
| what's the gap going to be at the flag / when does he catch me | trend × laps left; laps until gap < 1 s (DRS) | ✓ brief (flag projection for the cars either side; DRS range not yet) |
| how are my tyres / how many laps on these | wear per corner, %/lap, game `lifeSpan` | ✓ brief |
| what tyres is X on, how old, how are his | per-car compound/age/wear | ✓ brief |
| where am I losing time (to X / vs my best) | sectors + per-distance zones, apex/top speed, braking point | ✓ brief (`trace.py`); zones are in metres until we write corner names per track |
| where am I killing the tyres | per-corner temps/slip from River's traces | **not yet** |
| should we box / what's the plan | pit loss (green vs SC), rejoin, undercut range, rain | ✓ brief, **SC stop cost missing** |
| fuel? can I push? | fuel delta laps (MFD value) | ✓ brief (fixed: it's the delta, not laps in the tank) |
| battery? | ERS store %, mode | ✓ brief; "battery for the restart" needs an SC flag in the prompt |
| how many warnings have I got | lap-data warning counters + where each happened | ✓ brief (RACE LOG) |
| any damage? | damage packet | ✓ brief |
| is it going to rain / when | forecast → lap; "after the flag" when beyond it | ✓ brief |
| who's out / what happened | RTMT, COLL, PENA, stops for others | ✓ brief (RACE LOG) |

## Confirm with RS

The engineer proposes, River confirms with RS (UDP Action 2) or ignores it.
- **Box call:** "Box this lap?" → RS = "Copy, we're ready", and then no more talk about it. No RS by the commit point → the engineer's recommendation stands if it was a "box box"; a question ("want to box?") defaults to staying out. Real teams make the call and the driver follows or refuses, so prefer calls over questions.
- **Name check:** a mishearing that changed a name ("Tsunoda, you mean?") → RS = yes; ignored = answer anyway and say the name back.
- **Standing requests:** "gap to the leader every lap" → "Every lap, at the back straight. Confirm?" → RS.

## Later: debrief mode

After the flag, a text debrief from the engineer plus a browser view. It should show:
- the race timeline: start, contacts, warnings and penalties, stops, SC, flashbacks, retirements;
- a lap chart of position and gaps;
- stints with deg and wear;
- where time was gained and lost by distance, e.g. the restart lap: +0.9 s from Overtake mode on the straights, −0.5 s from cold tyres in T3–T6;
- energy use;
- "noteworthy" moments, chosen by the same triggers as the proactive calls above.

It reads the capture, so it works on any old race.
