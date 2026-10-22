"""Streaming chat completions (stdlib only). OpenRouter by default; RE_LLM_URL points it at any
OpenAI-compatible endpoint (a local server, OpenAI itself) with RE_LLM_KEY as its key, if it needs one.

The live server and `dev prep --run` set TRACE, and every call's messages and reply then go in TRACE/<date>.jsonl, so a bad
answer can be read back exactly as the model saw it."""
import json
import os
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

from . import log, usage

_log = log.get("llm")

OPENROUTER = "https://openrouter.ai/api/v1"
ENV_FILE = Path(__file__).resolve().parent.parent / ".env"
TRACE = None  # a folder, or None: dev tools and evals aren't kept
_trace_lock = threading.Lock()


class LLMError(Exception):
    pass


def _env(name):
    """From the environment, else from .env."""
    return env_where(name)[0]


def env_where(name):
    """(value, "the environment" | ".env"), or (None, None)."""
    if os.environ.get(name):
        return os.environ[name], "the environment"
    try:
        for line in ENV_FILE.read_text().splitlines():
            if line.startswith(name + "="):
                got = line.split("=", 1)[1].strip().strip("'\"") or None
                return got, got and ".env"
    except FileNotFoundError:
        pass
    return None, None


def base_url():
    return (_env("RE_LLM_URL") or OPENROUTER).rstrip("/")


def openrouter():
    return base_url() == OPENROUTER


def api_key():
    """RE_LLM_KEY, or OPENROUTER_API_KEY for OpenRouter; None if it's missing. Never logged.
    A local server may need none: "" then."""
    key = _env("RE_LLM_KEY") or (_env("OPENROUTER_API_KEY") if openrouter() else None)
    return key or (None if openrouter() else "")


def stream(model, messages, on_text, effort="low", max_tokens=4000, timeout=60, role="other", at=usage.NOWHERE, why=None,
           first_by=None):
    """Stream a reply, calling on_text(chunk) as content arrives. -> stats dict. Raises LLMError.
    Every call is recorded with its cost: `role` (engineer, strategist, judge…), `at` = usage.where(state).
    first_by: seconds to the first word, and the longest the reply may then go quiet, before giving up."""
    started, got = time.time(), []

    def collect(text):
        got.append(text)
        on_text(text)
    try:
        stats = _stream(model, messages, collect, effort, max_tokens, timeout, first_by)
    except LLMError as e:
        usage.llm(role, model, at=at, why=why, error=str(e))
        _keep(started, role, why, at, model, messages, "".join(got), error=str(e))
        raise
    usage.llm(role, model, stats, at, why)
    _keep(started, role, why, at, model, messages, "".join(got), stats=stats)
    return stats


def _keep(started, role, why, at, model, messages, reply, **result):
    if TRACE is None:
        return
    row = {"at": round(started, 3), "role": role, "why": why, "session": at[0], "model": model,
           "messages": messages, "reply": reply, **result}
    try:
        with _trace_lock:
            TRACE.mkdir(parents=True, exist_ok=True)
            with (TRACE / time.strftime("%Y%m%d.jsonl", time.localtime(started))).open("a") as f:
                f.write(json.dumps(row) + "\n")
    except OSError as e:
        _log.error("couldn't keep model call", error=str(e))


def _stream(model, messages, on_text, effort, max_tokens, timeout, first_by=None):
    key = api_key()
    if key is None:
        raise LLMError("no OPENROUTER_API_KEY (or RE_LLM_KEY) in the environment or .env")
    body = {"model": model, "stream": True, "max_tokens": max_tokens, "messages": messages}
    if openrouter():
        # the driver's waiting on the answer mid-lap; OpenRouter's default routing picked a 4-6 s provider for some models
        body.update(usage={"include": True}, reasoning={"effort": effort}, provider={"sort": "latency"})
    else:
        body["stream_options"] = {"include_usage": True}
    headers = {"Content-Type": "application/json", "X-Title": "Lift and Coast"}
    if key:
        headers["Authorization"] = f"Bearer {key}"
    req = urllib.request.Request(base_url() + "/chat/completions", json.dumps(body).encode(), headers)
    t0 = time.perf_counter()
    first, spent, provider, chars = None, {}, None, 0
    _log.debug("llm request", model=model, messages=len(messages), prompt_chars=sum(len(m["content"]) for m in messages))
    try:
        with urllib.request.urlopen(req, timeout=first_by or timeout) as r:
            for raw in r:
                # OpenRouter keeps a waiting stream alive with comment lines, so the socket alone never times out
                if first_by and first is None and time.perf_counter() - t0 > first_by:
                    raise LLMError(f"no answer in {first_by:g} s")
                line = raw.decode().strip()
                if not line.startswith("data: ") or line == "data: [DONE]":
                    continue
                d = json.loads(line[6:])
                if "error" in d:
                    raise LLMError(str(d["error"].get("message", d["error"]))[:300])
                provider = d.get("provider", provider)
                spent = d.get("usage") or spent
                for c in d.get("choices", []):
                    text = (c.get("delta") or {}).get("content")
                    if text:
                        first = first or time.perf_counter() - t0
                        chars += len(text)
                        on_text(text)
    except urllib.error.HTTPError as e:
        raise LLMError(f"HTTP {e.code}: {_error_message(e.read())}") from e
    except TimeoutError as e:
        raise LLMError(f"no answer in {first_by or timeout:g} s") from e
    except (urllib.error.URLError, OSError) as e:
        raise LLMError(f"network: {e}") from e
    stats = {
        "model": model, "provider": provider,
        "firstMs": round(first * 1000) if first else None,
        "totalMs": round((time.perf_counter() - t0) * 1000),
        "inTokens": spent.get("prompt_tokens"), "outTokens": spent.get("completion_tokens"),
        "cost": spent.get("cost"),
    }
    _log.info("llm reply", chars=chars, **stats)
    return stats


def _error_message(raw):
    # OpenRouter's error body also carries the account's user id; show only the message
    try:
        return str(json.loads(raw)["error"]["message"])[:300]
    except (ValueError, KeyError, TypeError):
        return raw[:300].decode(errors="replace")
