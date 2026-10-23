# Versions and releases

## Version numbers

`0.MINOR.PATCH` until 1.0.

- **0.x.0** for new features, and for anything you have to do something about when you upgrade: an option renamed or removed, a change to what's stored in `captures/` that needs a reindex, a different default model, a game format dropped. The release notes say what to do.
- **0.x.y** for fixes only: no new options, nothing stored differently, no changed defaults. Safe to take without reading the notes.

Each release is a tag (`v0.2.0`) with release notes on GitHub. To use a particular one:

```
git clone --branch v0.2.0 https://github.com/MartianRiver/lift-and-coast.git
git checkout v0.1.0 && uv sync      # go back from a newer one
```

`uv.lock` pins every dependency, so a tag installs what was tested. The models can't be pinned: they run on OpenRouter, which can reprice or retire them whatever version you're on. Each release's notes list its default models.

## Branches

- `main` is the latest release and nothing else. It only moves when a release is made.
- `next` is what will become the next version. Work happens on a branch off `next` and is squash-merged back once its own checks pass (tests, every changed line covered by a test or deliberately not, a read of the whole diff, and a live race if it changes how the radio, the voice or the strategy team runs during one). A change to what the brief says or which calls are made can go in on a replay of a recorded race instead: the full weekend on `next` before a release is its live race.
- A release merges `next` into `main` with a merge commit, so `main`'s history reads one release at a time, then tags it.
- An urgent fix goes on a branch off `main`, is released as 0.x.y, and `main` is merged back into `next`.

## What's kept in captures/ across versions

- Recordings are the raw packets the game sent, so every version can read every recording.
- A prompt that's been in a release never changes: `engineer/prompts/<role>/v1.md` stays as it was, and a change is the next file, `v2.md`, with a line on why at the top (the repo's checks refuse an edit to a released one). Your own versions in `captures/prompts/` are never touched, and one you're using stays in use when a new version ships; the Prompts page says it's out and shows what changed.
- The archive database only ever gains tables and columns; nothing is renamed or dropped, so an older version can still open a newer database. From 0.2 it carries a schema version, and each version upgrades it in small steps on start. Paths to the recordings stay absolute, because 0.1 reads them as they are; each version points them at the files where they are now when it opens the database. The catalogue tables can be rebuilt from the recordings (`archive reindex`); what models cost, the timings and the strategy team's notes can't, so nothing is allowed to throw them away.
- A change that can't keep to this makes the next version a 0.x.0, and its notes say what to do.

## Making a release

When everything listed for the version in [ROADMAP.md](../ROADMAP.md) is on `next`, or has been moved to a later version:

1. Everything since the last release passes the repo's checks and the tests, and every changed line is covered by a test or deliberately left out.
2. A clean clone of `next` installs and runs: the tests pass on macOS, Linux and Windows, and a first start with an empty `captures/` works.
3. The previous release's `captures/` (recordings and archive database) opens and works.
4. What the engineer would say across the recorded races (the brief at set laps, every unprompted call) is compared with the last release, and every difference is one that was meant: `dev snapshot` on each version, then `dev snapshot --diff`.
5. The evals, three times each: no case does worse than it did for the last release.
6. A full race weekend on `next` (practice, qualifying, race prep, race) with the voice on, and the radio log and debug bundle from it look right.
7. The README, `docs/architecture.md`, the roadmap and the changelog match the code; the version is bumped in `pyproject.toml` and `uv.lock`, and `engineer/pitloss.json` is rebuilt from the races recorded since (`dev pits --write`).

Then merge `next` into `main`, and make the release on GitHub with the changelog entry as its notes.

## Changelog

[CHANGELOG.md](../CHANGELOG.md) is written at release time from the commits on `next` since the last release (`git log --first-parent main..next`), in plain words: what changed for someone using it, then anything they need to do.
