# Changelog

What changed in each release, for someone using it. How versions work: [docs/releasing.md](docs/releasing.md).

## 0.2.0

This version is about trusting what the engineer says and finding out what went wrong when it doesn't.

- **Numbers are checked before they're said.** Every figure in an answer is matched against what the engineer was given, a sentence at a time. A sentence with a number that isn't there is held back, and it shows on the Radio tab. If nothing's left, it says it can't give a solid number.
- **Gaps from the game's live timing.** Right after a pass, the gap used to come from the lap before, sometimes with the wrong sign. Now it's live, for the engineer, the calls and the strategy team.
- **When the model doesn't answer.** If the engineer's model hasn't started answering within 5 seconds, the question goes to a second model (Claude Haiku 5.5 by default, `--engineer-fallback` to change it). If neither answers, it says it lost the data, instead of going quiet for up to a minute.
- **A quick brief on a second button.** Bind UDP Action 2 and one press says, straight away and without a model: your position, the gaps either side and the worst tyre in a race; where you stand in qualifying; last lap against your best in practice.
- **Which tyre, and why not the other.** When there's a stop to make, the brief lists each set you can fit this lap, how much quicker it is, and how worn your worst tyre would be on it at the flag at your own wear rate. It names the quickest one that makes it.
- **Race prep that knows the weekend.** Tyre life as the race will have it (qualifying shows about twice as much), the new Hard every race gives you, and sprints planned without a stop.
- **Red flags called as red flags,** with the free tyre change in the brief. A call the strategy team made in one session is no longer said in the next.
- **The same damage called once.** Two hits that read the same were said twice; Imola's opening lap said one five times.
- **The whole radio on the race's clock.** Your clips, the answers, the calls and the engineer's voice are kept with when they happened, along with what each model was sent and said and a log of every run. A debug bundle (Diagnostics tab) puts a session's recording, radio, model calls, log and setup in one zip to look through or attach to an issue.
- **The version** shows on the Diagnostics tab, in the log and with `--version`.
- Stopping the server mid-session no longer kills the telemetry thread, and a dashboard tab left open while the server was off reconnects when it's back.

**To do when you update:** run `uv sync`. Bind UDP Action 2 in the game if you want the quick brief (any button; `--quick-button` picks another). The first start upgrades `captures/archive.db` in place; 0.1.0 can still open it if you go back.

When the engineer's model is slow, the same question (the race brief, your question, the last few exchanges) now goes to a second model too, Claude Haiku 5.5 unless you pick another. [PRIVACY.md](PRIVACY.md) has the detail; `--engineer-fallback none` turns it off.

## 0.1.0 (2026-10-16)

First public version. A voice race engineer for F1 25 and F1 24 on UDP telemetry: ask it things over the radio, unprompted calls, a strategy team, race prep, a dashboard, and dev tools over your recorded sessions. The voice needs an Apple Silicon Mac; the rest should run anywhere Python does (only tried on macOS so far).

Default models: `moonshotai/kimi-k3` for the engineer; `anthropic/claude-sonnet-5.5` and `google/gemini-3.8-flash` for the strategy team.
