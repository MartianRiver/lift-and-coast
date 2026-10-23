# Privacy

Lift and Coast doesn't collect anything about you. There are no analytics, no crash reporting, no update checks, and nothing is ever sent to me. Everything it records stays on your computer.

What does leave your computer is what the engineer and the strategy team need to answer you: they're language models, and unless you run one yourself, they run online. The rest of this page is the detail.

## What's sent, and where

**To the language model**, which is OpenRouter unless you've set `RE_LLM_URL` to something else. Each time the engineer answers or the strategy team runs, it sends:

- the race as text, the same brief you can print with `dev brief`: positions, gaps, tyres, fuel, weather, the race log, and the names of the drivers in the session (in an online lobby that includes the other players' names);
- your question as text, after speech-to-text. Never the audio;
- the last few exchanges on the radio, so a follow-up question makes sense, and what the engineer has said about tyres and stops this race, so it doesn't contradict itself;
- the name and pronouns you gave it, so it talks to you rather than about "the driver";
- for the strategy team, the brief you gave it ("damage control, few rewinds") and its own earlier notes from this race.

If the engineer's model hasn't started answering within a few seconds, the same request goes to a second model (Claude Haiku 5.5 unless you've picked another in Settings or with `--engineer-fallback`). OpenRouter passes the request to whichever provider runs the model. What they keep is up to their policies, and OpenRouter's account settings let you rule out providers that log or train on requests. If you'd rather nothing left your computer at all, run a model locally (Ollama, LM Studio, anything OpenAI-compatible) and point `RE_LLM_URL` at it.

Your API key is only sent to that endpoint, and it's never written to the log.

**Downloads.** Installing fetches the Python packages. The first start with voice downloads the speech model and the voice from Hugging Face (about 2.3 GB and 340 MB). Opening the Settings tab fetches the list of models from OpenRouter (a public list: no key or anything about you goes with it), or from the server `RE_LLM_URL` points at, with its key, at most once an hour. Apart from those and the model calls above, nothing in this project's code connects to anything outside your own network.

**On your own network**, the game sends telemetry to the computer over UDP, and the dashboard is only reachable from the computer itself (`localhost`).

## The microphone

With voice installed, the microphone stays open while the server runs, so that the first syllable isn't lost when you press the radio button. Until you press it, the audio only ever sits in a third of a second of memory that's constantly overwritten. Your system's microphone indicator will be on the whole time. Nothing is recorded or transcribed until you press the button, and speech-to-text runs on your computer. `--no-radio` keeps the microphone closed; typed questions still work.

## What's kept on your computer

All of it is in `captures/` (or wherever `RE_DATA_DIR` points), except your API key, which is in `.env`:

- `sessions/`: a recording of every session, the raw telemetry the game sent;
- `archive.db`: the catalogue of those sessions, what each model call cost and how long it took, the strategy team's notes, and your laps, fuel and tyre history across sessions;
- `radio/`: every radio clip you recorded, what the engineer said back (text and audio), and a log of both;
- `llm/`: every request sent to the models and the reply that came back, word for word, one file a day;
- `logs/`: a log of each run: what it was doing, errors, and what you said on the radio as text;
- `driver.json`, `settings.json`, `fixes.json`, `pitwall-brief.json`, `pitwall-prep.json`: your name and pronouns, what you set in the Settings tab, the speech-to-text corrections you taught it, your brief for the strategy team and the last race plan;
- `prompts/`: the versions of the prompts you edited on the Prompts page. Each model call in `llm/`, each answer in the radio log and each of the strategy team's notes says which prompt version it had.

Deleting any of it is safe. Deleting `captures/` entirely starts you from scratch.

## Debug bundles

When something goes wrong, a debug bundle puts everything needed to understand it into one file: the session's telemetry, your radio clips and their transcripts, what was sent to the models and what came back, the log, and your setup (version, operating system, options, which models, your Settings and your own prompt versions). It's made only when you ask for it, saved on your computer, and the app never uploads it anywhere. Before it's made you can leave out the audio or the telemetry, and the bundle lists everything inside it. It's saved in `captures/bundles/`, and the Diagnostics tab links to it. A long race comes out as two or three files, because GitHub takes up to 25 MB per attachment. Attaching it to a public issue makes everything in it public, including your voice and the name you gave the engineer, so leave out the audio if you'd rather.

It holds your voice, your name, whatever you said on the radio, and in online sessions other players' names. GitHub issues are public, so look through it before attaching it to one.
