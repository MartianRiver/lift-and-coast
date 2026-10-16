# Roadmap

What I'm working on and what I'd like to get to, grouped by the version it's meant for. A version is released once everything listed under it is done and has been through the checks in [docs/releasing.md](docs/releasing.md), including real races. Things move between versions when a race shows me something matters more; when that happens the release notes say so. If something here matters to you, or something's missing, open an issue.

## 0.2: trust it, and report it when it goes wrong

- **The whole radio on the race's timeline.** Your clips, the engineer's answers, its unprompted calls and its voice, all kept with when they happened, so a race can be gone through afterwards and the radio can be cut into game footage.
- **What the models were sent and what they said,** and a log file, saved with each session.
- **A debug bundle.** One file with the session, the radio, the model calls, the log and your setup, to look through yourself or attach to an issue. The dev tools can open it directly, so the moment can be replayed.
- **Radio for videos.** Your radio and the engineer's for a stretch of a race, as audio tracks that start at a moment you can find in the footage (lights out, a lap line), with subtitles. Optionally with your own lines re-voiced.
- **When the model doesn't answer.** If the connection drops, the engineer currently goes quiet for up to a minute. It should give up after a few seconds, try a second model, and say on the radio that it lost the data.
- **A quick brief on a second button.** One press, no talking: gaps and tyres in a race, the delta in qualifying, last lap against best in practice. It needs no model, so it also works when the connection doesn't.
- **Gaps right after a pass.** For a moment after you pass someone, the brief can still show the gap from the lap before, with the wrong sign, and the strategy team reads that too.
- **Prompt versions.** Every change to a prompt becomes a new version with a note on what changed and why, and every answer records which version produced it.
- **Going back a version without losing anything.** The recordings already work with any version; the archive database gets a schema version so an older release can still open it.
- The version on the dashboard and in the log, and the tests running on macOS, Linux and Windows on every push.

## 0.3: setting it up, and choosing models

- **Setup in the browser.** Step by step: who's driving, the game (the address to type in, and a light when telemetry arrives), your radio button, the OpenRouter key, models, voice, a mic check. Downloads for the speech model and the voices with progress, and what to check when nothing arrives from the game.
- **Hear the voices first.** Every voice saying the same few lines, plain and through the radio filter, before you download one.
- **Settings and an advanced section.** Pick a model for each job from everything on OpenRouter, or a local server, with its price; reasoning effort, the strategy team's budget; and every prompt, with its versions and the notes on why each changed.
- **A model check.** Run any model against moments from real races, scored on what it said, how quickly it started talking and what it cost, next to the recommended one. The cases ship with the repo, so it works before you've recorded anything.
- **Cost per race weekend** for each model and setting, worked out from how often each part actually runs in a weekend and what each call costs.
- **Recommended models,** chosen by a stated rule from the model check, updated each release.
- **A sample race to download,** so the dev tools work without recording your own first.
- Checking it properly on Windows and Linux, and wheel buttons for the radio, not just the controller.

## 0.4: strategy that knows the pace

- **A lap-time model.** The thing a real strategist leans on most and this doesn't have yet: lap time against tyre age, fuel and compound, from your own laps and from how the AI ran on each compound at the same track. Every race already has twenty cars' worth of that. With it the team can compare plans in seconds, two-stops included, and pick a stop lap instead of a window that covers half the race. At the moment the prep can't tell two sensible one-stop plans apart and sometimes picks a different one each time you ask.
- **Practice programmes.** In practice the team says what it wants to learn before the race (a long run on the mediums, a few laps on the hards) and keeps track of it as you go, so the lap-time model has your own numbers on each compound and not only the AI's. Optional: plenty of people barely drive practice.
- **Holding a box call to the pit entry.** Once the call to box is made it shouldn't flip in the last few hundred metres before the pit lane unless something decisive changes, and then only with the reason.
- **The out-lap call.** After your own stop: where you came out and who's around you, on what tyres.
- **Who still has to stop.** The order once everyone has made their stops, from each car's stint history, so a car ahead that hasn't stopped yet isn't treated as a car you need to pass.
- **Penalties and red flags in the sums.** Your own time penalty in the stop cost and the gap at the flag, other cars' penalties in the timing, and a red flag treated as the free tyre change it is.

## 0.5: qualifying and the rest

- **Calls in qualifying:** the provisional position after a lap, a deleted lap, whether there's time for another run.
- **Resumed saves.** Loading a mid-race save starts a new session as far as the game is concerned, so lap history, gap trends and wear rates start again from that lap. They can be rebuilt from the recording of the earlier part.
- **Confirming by button.** The engineer suggests something ("box this lap?", "Tsunoda, you mean?") and a press says yes.
- **Standing requests** like "gap to the leader every three laps", delivered at a sensible point on the lap.
- **Engineer personalities.** A handful to choose from in the settings, each with a few lines on how it talks: blunt and to the point, and it pushes back on a call it thinks is wrong; calm and steady; numbers first; quiet unless it matters. Each one comes with a voice that suits it and a default for how much it says unprompted, and the unprompted calls are worded in its style too. Only the way things are said changes: the numbers and the strategy calls stay the same, and every personality has to pass the model check before it's offered. They're styles, not impressions of real engineers.
- Volume and mute for the engineer's voice, and rear grip on the race screen. It's only in the calls for now.

## 1.0

When people other than me can set it up and use it without help: setup in the browser, the sample race, the debug bundle, checked on Windows and Linux, and no known bugs that put a wrong number in front of the engineer.

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
