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

## What you need

- F1 25 (including the 2026 Season Pack) or F1 24, on any platform. The game sends telemetry over your local network.
- A computer on the same network with [uv](https://docs.astral.sh/uv/) installed. The text side (dashboard, typed questions, calls on screen, the strategy team) is plain Python and should run anywhere, though I've only run it on macOS.
- For voice: an Apple Silicon Mac. Speech recognition and the engineer's voice run locally on MLX. You'll also need `brew install espeak-ng`.
- An [OpenRouter](https://openrouter.ai) API key, or any OpenAI-compatible endpoint, including a model running on your own machine. With the default models a race costs a few tens of cents, and the strategy team has a per-session spending cap.

## Setup

```
git clone https://github.com/MartianRiver/lift-and-coast.git && cd lift-and-coast
uv sync
echo 'OPENROUTER_API_KEY=sk-or-...' > .env
uv run python -m engineer.server
```

Then open http://localhost:8077. The first time, it asks who's driving: the name the engineer should call you and your pronouns. If the game has already sent your name, it fills that in. On a Mac, the first start also downloads the speech model (about 2.3 GB).

In the game, under Settings → Telemetry: UDP on, broadcast off, the IP of the computer running the server (worth giving it a fixed address on your router), port 20777, send rate 20 Hz, and the newest UDP format your game offers.

In the controller settings, bind **UDP Action 1** to something you can reach while driving. I use the left stick click. Hold it to talk, release to send. If you'd rather use a different button, `--radio-button "Right Stick Click"` takes any controller button or another UDP action number.

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

## Issues and ideas

I'm not taking pull requests. It's a personal project and I'd like to keep the code in one head. Bug reports and feature requests are very welcome as issues, though. For a bug, it helps to know the game, the platform, the UDP format and what the server printed. There's a bit more in [CONTRIBUTING.md](CONTRIBUTING.md).

## Licence

MIT. The UDP specification is EA's and isn't included here; [docs/game-quirks.md](docs/game-quirks.md) says where to find it.
