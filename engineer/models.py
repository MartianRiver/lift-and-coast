"""The models a role can use, for the Settings tab: OpenRouter's list (public, no key sent) or, with
RE_LLM_URL set, that server's own, with what each would cost a race at its listed price."""
import json
import threading
import time
import urllib.request

from . import llm, log

_log = log.get("models")

# per race at 35% distance, from the races recorded so far: runs, tokens in, tokens out a run
RUNS = {"engineer": (6, 3900, 150), "lead": (6.4, 5100, 390), "second": (6.4, 2600, 50)}
KEEP = 3600  # s before the list is asked for again
TIMEOUT = 10

_cache = {}
_lock = threading.Lock()


def _fetch(url, key):
    req = urllib.request.Request(url, headers={"User-Agent": "lift-and-coast", **({"Authorization": f"Bearer {key}"} if key else {})})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        return json.loads(r.read())


def per_race(prices, role):
    """$ a race for the role at these $-per-token prices, or None when there are none (a local server)."""
    try:
        runs, tokens_in, tokens_out = RUNS[role]
        return round(runs * (tokens_in * float(prices["prompt"]) + tokens_out * float(prices["completion"])), 4)
    except (KeyError, TypeError, ValueError):
        return None


def _row(m):
    prices = m.get("pricing")
    return {"id": m["id"], "name": m.get("name") or m["id"], "context": m.get("context_length"),
            "expires": m.get("expiration_date"), "race": {role: per_race(prices, role) for role in RUNS}}


def _talks(m):
    arch = m.get("architecture") or {}
    return "text" in arch.get("output_modalities", ["text"]) and "text" in arch.get("input_modalities", ["text"])


def listing(fetch=_fetch, now=time.time):
    """{"models": [...], "local": bool} -> raises llm.LLMError when the list can't be had."""
    url = llm.base_url() + "/models"
    with _lock:
        got = _cache.get(url)
        if got and now() - got[0] < KEEP:
            return got[1]
    t = time.perf_counter()
    try:
        data = fetch(url, None if llm.openrouter() else llm.api_key())["data"]
    except Exception as e:
        _log.error("couldn't get the model list", exc=False, url=url, error=str(e))
        raise llm.LLMError(f"couldn't get the model list from {url}: {e}") from None
    out = {"models": sorted((_row(m) for m in data if _talks(m)), key=lambda r: r["name"].lower()), "local": not llm.openrouter()}
    _log.info("model list", url=url, models=len(out["models"]), ms=round((time.perf_counter() - t) * 1000))
    with _lock:
        _cache[url] = (now(), out)
    return out
