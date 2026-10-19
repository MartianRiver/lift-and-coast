# Pit wall: the team behind the engineer

The engineer is the one voice on the radio. Behind it sits a small team: one or two stronger models
that think about strategy, and talk to each other where I can read it. They never speak to me
directly; what they agree goes to the engineer.

The team makes the decisions, the engineer relays them, like a real pit wall. The engineer only
decides by itself when there's no time to ask: an SC as I'm approaching pit entry, a puncture, a
direct "box or stay?" a few hundred metres from the box. Then it uses whichever plan already
covers that case, and the team reviews the call straight after. Otherwise a strategy question
gets "copy, checking" and the team's answer.

Today some decisions are made in code and said straight away: box for slicks, the rain plan, a
stop under the SC. Once the team exists those become triggers for a team run. The code still does
the arithmetic, and the team owns the call.

Built (`engineer/pitwall/`): triggers, gathering, the heartbeat and budget, the lead + second
opinion, plans A/B/C, "copy, checking" for strategy questions, "go plan B", the Pit wall tab and the
plan on the Race tab. Not yet: practice data goals.

## Strat chat

A Pit wall tab with the team's discussion as a feed: who wrote it, the lap, why they were asked
(the trigger), what it cost. Each run reads the same computed brief the engineer does plus the
plans below, and posts a short note. Two models disagreeing is worth seeing: if they do, the note
says so and the engineer gets both sides in one line.

The engineer's brief gets a PIT WALL section: the active plan and the last note or two, dropped
once they're a few laps old (old answers repeated as current facts was a real problem before).

## Plans A, B, C

Built before the race (on entering the race session, from practice and quali) and kept current:

- A: the plan if nothing happens, e.g. medium → hard, box L12–15.
- B: what changes it, e.g. SC before L8: box under it for hards to the flag.
- C: weather, e.g. rain ≥ 50% inside 6 laps: stay out and go to inters when it lands.

The numbers come from code (stint length from my measured wear rate on each compound at this
track, pit loss per track, the sets I have left); the model picks between them and writes the
reasoning. Each plan has the condition that switches to it, so the engineer can say "Plan B,
box this lap" and I can say "go plan B" over the radio. The active plan shows on the Race tab.

## Practice: what the team wants to see

In practice and quali the team says what data it wants for the race, and the brief tracks it
against what's been run: e.g. "5 clean laps on mediums for deg", "a run on the hards",
"a lap with more fuel". Measured per compound and track (wear %/lap, deg, pace) and kept in the
archive, so a later race at the same track starts with numbers instead of the game's estimates.

## When the team runs

Models are only called when something has changed, so it stays cheap but responsive:

- **Events** (code-side triggers): race start (confirm the plan), SC/VSC deployed, a red flag (which set for the free change before the restart), rain lap moves
  3+ laps or crosses 50%, slicks crossover, a car within 3 places stops (undercut), pit window
  opens, a tyre ≤ 5 laps from worn, new damage, plan deviation (past the planned box lap, a set
  lasting much longer or shorter than planned), and me asking a strategy question (the engineer
  says "copy, checking" and answers when the team has).
- **Coalescing:** triggers within ~10 s become one run with every reason listed. At most one run
  a lap unless it's urgent (SC, rain, damage, my question).
- **Heartbeat:** if nothing has run for 5 laps or 8 minutes, a review run anyway.
- **Budget:** a per-race cap; past it, only urgent triggers and my questions run. Shown on the
  Diagnostics tab.

## Cost and diagnostics

Every model call is logged with what it was for: time, session, session type, track, role
(engineer / strategist / judge), model, provider, tokens, cost, first-word and total ms, trigger.
Stored in the archive so it survives restarts and joins to sessions. A Diagnostics tab shows:

- cost this session, today, per race, and per session type; cost per answer and per team run
- latency: engineer first word p50/p90, STT ms, release → text, TTS synth ms, call queue delay
- calls made, expired before a straight, dropped as stale; answers cut off by me keying the radio
- feed: packet rates, decode errors, silences (already on the Packets tab, linked from here)
