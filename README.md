# Lift and Coast

A race engineer for the F1 games that you can actually talk to. Hold a button, ask "how are the rears looking?" or "can I make the end on these?", and it answers from the game's live telemetry. It also speaks up on its own when something matters: a safety car, a car closing on you, a tyre going off faster than everyone else's, rain on the way.

Behind the engineer sits a small strategy team, a couple of larger models that decide when to stop, what to fit and how much fuel to start with. They work from your own history rather than the game's assumptions, and the engineer passes on what they decide, which is roughly how a real pit wall works.

I built it for myself. I play career mode on an Xbox with a MacBook Air next to me, and I use this every time I race. That also means it has been tuned on one person's races, so expect rough edges.

## What it does

**Answers questions**, spoken or typed. Every number it quotes is worked out in code before the model sees it: gaps and which way they're trending, tyre wear by sector against cars on the same compound, what a pit stop costs at this track, where you'd rejoin. Language models make poor strategy calls when they do their own arithmetic, so they aren't asked to.

**Calls things out unprompted**: safety cars, penalties, track-limits warnings, cars closing or dropping back, tyres wearing faster than the field, the rears starting to slide in one sector, rain, when to box for slicks. Calls wait for a straight and never talk over you. Say "less chat" or "more info" to change how much it tells you.

**Plans the race.** After qualifying it works out the fuel load, starting tyre and stops from your previous races. The game's own suggestion assumes the AI's tyre wear and leaves a couple of laps of fuel spare; this one uses how you actually drive. During the race the team revisits the plan when something changes and keeps plans A, B and C that you can switch between over the radio.

**Records every session**, so you can replay any race, see what the engineer would have said at any moment, or ask it something after the fact.

**A dashboard** in the browser: race overview, timing tower, car details, the strategy team's discussion, and a diagnostics page with what the models have cost and how quickly they answered.

## What it can't do

**It can only listen to the game.** The telemetry goes one way: the game sends what's happening, and nothing can be sent back. So the engineer can tell you to box and what to fit, but you still drive into the pits yourself, and the tyres you get are the ones set in the game's own pit menu. Change them there when the plan changes. The same goes for the fuel at the strategy screen, the ERS mode and anything else you'd set in the car: it can suggest, and you do it.

**It only knows what the game sends.** It doesn't hear the game's own engineer, so the two can disagree. The game sends no corner names, so it talks in sectors and metres. Nothing about the race arrives until you're past the strategy screen, which is why the race plan is made after qualifying. In online sessions, what you see of another player's car depends on their own "Your Telemetry" setting, which is restricted by default: their fuel, ERS, tyre wear and damage then all arrive as zero, so they're unknown.

**Other limits for now:** the voice only runs on Apple Silicon Macs (speech recognition and the voice run on MLX today; Windows and Linux are text-only until they get their own), it only speaks and understands English, the engineer needs an internet connection unless you run a model yourself, and it's been built and raced on 2025-regulation careers (the 2026 cars' active aero and overtake mode aren't used).

## What you need

- F1 25 (including the 2026 Season Pack) or F1 24, on any platform. The game sends telemetry over your local network.
- A computer on the same network with [uv](https://docs.astral.sh/uv/) installed. The text side (dashboard, typed questions, calls on screen, the strategy team) is plain Python and should run anywhere, though I've only run it on macOS.
- For voice, for now: an Apple Silicon Mac. Speech recognition and the engineer's voice run locally on MLX. You'll also need `brew install espeak-ng`.
- An [OpenRouter](https://openrouter.ai) API key, or any OpenAI-compatible endpoint, including a model running on your own machine. Without one, the unprompted calls, the code's own strategy calls (box for slicks, the rain plan), the dashboard and the recording all still work; the answers and the strategy team are what need a model. With the default models a race costs a few tens of cents, and the strategy team has a per-session spending cap. What's sent to the model, and what stays on your computer: [PRIVACY.md](PRIVACY.md).

## Setup

```
git clone https://github.com/MartianRiver/lift-and-coast.git && cd lift-and-coast
uv sync
echo 'OPENROUTER_API_KEY=sk-or-...' > .env
uv run python -m engineer.server
```

Then open http://localhost:8077. The first time, it asks who's driving: the name the engineer should call you and your pronouns. If the game has already sent your name, it fills that in. On a Mac, the first start also downloads the speech model (about 2.3 GB).

In the game, under Settings → Telemetry: UDP on, broadcast off, the IP of the computer running the server (worth giving it a fixed address on your router), port 20777, send rate 20 Hz, and the newest UDP format your game offers.

**The radio button.** The game's control settings have a set of functions called UDP Action 1 to 12. They don't do anything in the game; they send the button press out with the telemetry, so a program like this one can react to it. Bind **UDP Action 1** to a button on your controller or wheel that you can reach while driving (I use the left stick click). Hold it to talk, let go to send.

While it's held, the server records from the computer's microphone: whichever input is the default in your system's sound settings, so a headset or USB mic connected to the computer works once it's set as the input. A headset plugged into the console or the controller doesn't: its sound goes to the console, and the game doesn't pass it on. The engineer answers through the computer's default output (`--audio-out` picks another). If you'd rather not bind a UDP Action, `--radio-button "Right Stick Click"` listens for a controller button directly, or for another UDP Action number.

## Options

`uv run python -m engineer.server --help` lists everything. The ones you're most likely to want:

```
--radio-fx                 band-limit the voice so it sounds like team radio
--no-calls                 only speak when spoken to
--no-pitwall               no strategy team; the engineer and the code make the calls
--engineer-model <id>      default moonshotai/kimi-k3: quick to the first word and consistent
--pitwall-models <a,b>     lead and second opinion; default Claude Sonnet 5.5 and Gemini 3.8 Flash
--pitwall-budget 2.0       the team's spending cap per session, in dollars
```

To use something other than OpenRouter, set `RE_LLM_URL` (for example `http://localhost:11434/v1` for Ollama) and `RE_LLM_KEY` if it needs one, in your environment or `.env`.

Everything it records goes in `captures/`: sessions (about 65 MB an hour once compressed), the archive database, radio clips and your settings. Set `RE_DATA_DIR` to keep them somewhere else.

## Poking around

```
uv run python -m engineer.dev sessions                # every recorded session
uv run python -m engineer.dev brief race --lap 10     # what the engineer could see at lap 10 of your last race
uv run python -m engineer.dev serve race --lap 10     # the dashboard and engineer frozen at that moment, on :8078
uv run python -m engineer.dev calls race              # everything it would have said unprompted
uv run python -m unittest
```

The `dev` tools work from recordings and never touch a running server. [docs/architecture.md](docs/architecture.md) goes through the code file by file, [docs/game-quirks.md](docs/game-quirks.md) covers what the game really sends as opposed to what the spec says, and [ROADMAP.md](ROADMAP.md) is what I'm working on next.

The strategy evals (`engineer.evals`) read moments to test from `evals/cases.toml`. Mine aren't in the repo because each one points at a race I recorded.

## Versions

`main` is always the latest release, so the clone above gets that; what's coming next lives on the `next` branch. Each release is tagged with notes on what changed and anything you need to do ([CHANGELOG.md](CHANGELOG.md)). To stay on one, clone it with `--branch v0.1.0`; to go back to one, `git checkout v0.1.0 && uv sync`. Your recordings work with every version. How versions are numbered and what's checked before a release: [docs/releasing.md](docs/releasing.md).

## Issues and ideas

I'm not taking pull requests. It's a personal project and I'd like to keep the code in one head. Bug reports and feature requests are very welcome as issues, though. For a bug, it helps to know the game, the platform, the UDP format and what the server printed. There's a bit more in [CONTRIBUTING.md](CONTRIBUTING.md).

## Licence

MIT. The UDP specification is EA's and isn't included here; [docs/game-quirks.md](docs/game-quirks.md) says where to find it.
