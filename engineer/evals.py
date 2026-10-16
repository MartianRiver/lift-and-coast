"""Strategy evals: moments from real races, the engineer's answer, and a judge's verdict.

    uv run python -m engineer.evals [--model a,b] [--repeat 3] [--case sil-l11-box,...] [--judge <model>]

Cases are in evals/cases.toml (gitignored: they point at your own recorded sessions). `ask` cases rebuild the brief at the moment and ask the engineer
model exactly as the live server would; a stronger model then checks the answer against what
really happened (`facts`, which the engineer never sees). `calls` cases replay the race through
the proactive caller. Every answer is also checked for length and for stepping out of the race
world ("the game says"). Results land in evals/results/evals-<time>.json.
"""
import argparse
import json
import re
import time
import tomllib
from pathlib import Path

from . import brief, dev, log
from .engineer import DEFAULT_MODEL, prompt
from .llm import LLMError, stream

_log = log.get("evals")

ROOT = Path(__file__).resolve().parent.parent
CASES = ROOT / "evals" / "cases.toml"
RESULTS = ROOT / "evals" / "results"
JUDGE = "anthropic/claude-sonnet-5.5"
MAX_WORDS = 40  # mid-lap they can't take more; a case can allow more with max_words
OFF_WORLD = re.compile(r"\b(the game|game says|game's|telemetry|the data|the brief)\b", re.I)

JUDGE_PROMPT = (ROOT / "engineer" / "prompts" / "judge.md").read_text()


def load_cases(only=None):
    if not CASES.exists():
        raise SystemExit(f"no eval cases: {CASES} isn't in the repo, and each case points at a recorded session of your own")
    cases = tomllib.loads(CASES.read_text())["case"]
    if only:
        wanted = set(only.split(","))
        cases = [c for c in cases if c["id"] in wanted]
    return cases


def moment(case, cache={}):
    key = (case["session"], case.get("lap"), case.get("into", 0.0), case.get("at"))
    if key not in cache:
        _, files = dev.resolve(case["session"])
        st, _ = dev.load(files, case.get("lap"), case.get("into", 0.0), case.get("at"))
        cache[key] = brief.build(st)
    return cache[key]


def ask(model, data, question, why=None):
    out = []
    stats = stream(model, prompt(data, question), out.append, role="eval", why=why)
    return "".join(out).strip(), stats


def judge(case, answer, model):
    checks = [(f"must{i + 1}", "MUST", t) for i, t in enumerate(case.get("must", []))]
    checks += [(f"never{i + 1}", "NEVER", t) for i, t in enumerate(case.get("never", []))]
    prompt = JUDGE_PROMPT.format(facts=case["facts"].strip(), question=case["question"], answer=answer,
                                 checks="\n".join(f"- {cid} ({kind}): {text}" for cid, kind, text in checks))
    out = []
    stream(model, [{"role": "user", "content": prompt}], out.append, effort="medium", role="judge", why=case["id"])
    text = "".join(out)
    try:
        # models sometimes escape apostrophes, which JSON doesn't allow
        verdicts = json.loads(text[text.index("{"):text.rindex("}") + 1].replace("\\'", "'"))["checks"]
    except (ValueError, KeyError) as e:
        raise LLMError(f"judge reply wasn't the JSON asked for: {text[:200]!r}") from e
    texts = {cid: text for cid, _, text in checks}
    return [{**v, "check": texts.get(v["id"], "?")} for v in verdicts]


def house_rules(case, answer):
    """Checks that need no judge: length and staying in the race world."""
    out, words = [], len(answer.split())
    limit = case.get("max_words", MAX_WORDS)
    out.append({"id": "short", "pass": words <= limit, "why": f"{words} words (max {limit})", "check": "punchy"})
    hit = OFF_WORLD.search(answer)
    out.append({"id": "in-world", "pass": not hit, "why": f"said {hit[0]!r}" if hit else "ok",
                "check": "never mentions the game, data or telemetry"})
    return out


def run_ask(case, models, repeat, judge_model):
    data = moment(case)
    results = []
    for model in models:
        for _ in range(repeat):
            try:
                answer, stats = ask(model, data, case["question"], case["id"])
                checks = judge(case, answer, judge_model) + house_rules(case, answer)
            except LLMError as e:
                _log.error("eval call failed", exc=False, case=case["id"], model=model, error=str(e))
                results.append({"case": case["id"], "model": model, "error": str(e), "pass": False})
                continue
            results.append({"case": case["id"], "model": model, "answer": answer, "checks": checks,
                            "pass": all(c["pass"] for c in checks), "firstMs": stats.get("firstMs")})
    return results


def run_calls(case):
    _, files = dev.resolve(case["session"])
    calls = list(dev.replay_calls(files, case.get("until_lap")))
    if "expect" in case:
        want = case["expect"]
        hits = [c for c in calls if c["topic"] == want["topic"] and re.search(want.get("text", ""), c["text"], re.I)]
        ok, why = bool(hits), (hits[0]["text"] if hits else f"no {want['topic']} call matching {want.get('text')!r}")
    else:
        hits = [c for c in calls if c["topic"] == case["absent"]["topic"]]
        ok, why = not hits, (f"said: {hits[0]['text']} (L{hits[0]['lap']})" if hits else "nothing said")
    said = [f"L{c['lap']} [{c['topic']}] {c['text']}" for c in calls]
    return [{"case": case["id"], "model": "calls", "pass": ok, "why": why, "said": said}]


def report(r):
    mark = "PASS" if r["pass"] else "FAIL"
    if r["model"] == "calls":
        print(f"{mark}  {r['case']:<22} calls   {r['why']}")
        return
    if "error" in r:
        print(f"FAIL  {r['case']:<22} {r['model']}  error: {r['error']}")
        return
    print(f"{mark}  {r['case']:<22} {r['model']}  [{r['firstMs']} ms] {r['answer']}")
    for c in r["checks"]:
        if not c["pass"]:
            print(f"        x {c['id']}: {c['check']} -- {c.get('why', '')}")


def summary(results):
    by = {}
    for r in results:
        by.setdefault(r["model"], []).append(r["pass"])
    print()
    for model, passes in by.items():
        print(f"  {model:<36} {sum(passes)}/{len(passes)} passed")


def main():
    ap = argparse.ArgumentParser(description="strategy evals over real race moments")
    ap.add_argument("--model", default=DEFAULT_MODEL, help="engineer model(s), comma-separated")
    ap.add_argument("--judge", default=JUDGE)
    ap.add_argument("--repeat", type=int, default=1)
    ap.add_argument("--case", help="only these case ids, comma-separated")
    args = ap.parse_args()

    results = []
    for case in load_cases(args.case):
        out = run_calls(case) if case["kind"] == "calls" else run_ask(case, args.model.split(","), args.repeat, args.judge)
        for r in out:
            report(r)
        results += out
    summary(results)
    RESULTS.mkdir(parents=True, exist_ok=True)
    path = RESULTS / f"evals-{time.strftime('%Y%m%d-%H%M%S')}.json"
    path.write_text(json.dumps({"judge": args.judge, "results": results}, indent=1))
    print(f"  -> {path.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
