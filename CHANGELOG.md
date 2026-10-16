# Changelog

What changed in each release, for someone using it. How versions work: [docs/releasing.md](docs/releasing.md).

## 0.1.0 (2026-10-16)

First public version. A voice race engineer for F1 25 and F1 24 on UDP telemetry: ask it things over the radio, unprompted calls, a strategy team, race prep, a dashboard, and dev tools over your recorded sessions. The voice needs an Apple Silicon Mac; the rest should run anywhere Python does (only tried on macOS so far).

Default models: `moonshotai/kimi-k3` for the engineer; `anthropic/claude-sonnet-5.5` and `google/gemini-3.8-flash` for the strategy team.
