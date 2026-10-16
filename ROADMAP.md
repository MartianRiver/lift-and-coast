# Roadmap

What I'm working on and what I'd like to get to. The order shifts depending on what bothers me in the races I'm playing, so read it as intentions rather than a schedule. If something here matters to you, or something's missing, open an issue.

## Now

**Trying it on real races.** Most of the unprompted calls, the strategy team and the race prep were tuned on replays of a handful of races. Driving with it is where I find out which calls are noise and which are missing.

**Practice programmes.** In practice the team should say what it wants to learn before the race (a long run on the mediums, a few laps on the hards) and keep track of it as you go. The pace and wear it measures per compound then feed the race prep. At the moment the prep can't tell two sensible one-stop plans apart and sometimes picks a different one each time you ask.

**A lap-time model.** The thing a real strategist leans on most and this doesn't have yet: lap time against tyre age, fuel and compound, from your own laps and from how the AI ran on each compound at the same track. With it the team can compare plans in seconds, two-stops included, and pick a stop lap instead of a window that covers half the race.

**A quick brief on a second button.** One press, no talking: gaps and tyres in a race, the delta in qualifying, last lap against best in practice. The button is already wired up; it just doesn't say anything yet.

## Next

- **The out-lap call.** After your own stop: where you came out and who's around you, on what tyres.
- **Who still has to stop.** The order once everyone has made their stops, from each car's stint history, so a car ahead that hasn't stopped yet isn't treated as a car you need to pass.
- **Penalties and red flags in the sums.** Your own time penalty in the stop cost and the gap at the flag, other cars' penalties in the timing, and a red flag treated as the free tyre change it is.
- **Gaps right after a pass.** For a moment after you pass someone, the brief can still show the gap from the lap before, with the wrong sign.
- **Calls in qualifying:** the provisional position after a lap, a deleted lap, whether there's time for another run.
- **Resumed saves.** Loading a mid-race save starts a new session as far as the game is concerned, so lap history, gap trends and wear rates start again from that lap. They can be rebuilt from the recording of the earlier part.
- **Confirming by button.** The engineer suggests something ("box this lap?", "Tsunoda, you mean?") and a press says yes.
- **Standing requests** like "gap to the leader every three laps", delivered at a sensible point on the lap.
- Volume and mute for the engineer's voice, and rear grip on the race screen. It's only in the calls for now.
- **A sample race to download,** so the dev tools work without recording your own first, with a few eval cases that go with it.
- Checking it properly on Windows and Linux.

## Strategy that still rests on guesses

- **What a stop under a safety car costs.** For now it's a rule of thumb, because in every safety car I've raced so far the whole field pitted together and there was nobody to compare against.
- **When a tyre is actually finished.** 70% wear is a placeholder. Your own pace against wear, across sessions, should set it.
- **Pit loss at a new track.** At a track with no recorded races and no stop seen yet, the brief has no figure for what a stop costs.
- **Weather the other way round.** The switch from inters to slicks has been through a real race. A dry race turning wet has only been run in a synthetic one.
- **The engineer's judgement.** The default model sometimes tacks a gap trend onto a simple acknowledgement, and answers "should I be managing my tyres?" differently on different days. Now and then it adds detail the data doesn't support.

## Later

- **How hard it is to pass at each track,** counted from the overtakes in your recordings, so "you'd rejoin behind Gasly" comes with whether you'd get stuck there. Also the overcut, which the team doesn't weigh yet.
- Yellow flags in the calls.
- **Voice beyond Apple Silicon.** Speech recognition and the voice run on MLX today. A cross-platform route would bring the radio to Windows.
- **Landmarks per track,** so it can say "worst into the chicane" rather than only "sector 2". The game doesn't send corner positions, so they'd be mapped by hand, a few per track.
- **Talk windows per track,** worked out from your own laps, instead of detecting straights as you drive. Notes in [docs/radio.md](docs/radio.md).
- **A debrief after each session:** the engineer's summary, plus a page with the lap chart, stints, where the time went and the moments worth looking at. It reads the recording, so it would work on old races too.
