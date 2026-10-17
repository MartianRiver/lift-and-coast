"""The race engineer: answers the driver's radio messages from the live brief, streamed as text.

One worker thread answers questions in order. Each call gets a fresh brief (the state moves on
between questions) plus the last few exchanges, so follow-ups like "and Piastri?" work.
"""
import queue
import re
import threading
import time
from collections import deque
from pathlib import Path

from . import brief, driver, log, numbers, radiolog, usage
from .llm import LLMError, api_key, stream

_log = log.get("engineer")

DEFAULT_MODEL = "moonshotai/kimi-k3"
# acknowledgements get no reply, like on a real radio (yes/no left out: they may answer a question)
ACKS = {"copy", "copy that", "ok", "okay", "mm hmm", "mhm", "roger", "understood",
        "got it", "thanks", "thank you", "cheers"}
# a bare yes/no or filler only means something as the answer to a question we just asked; otherwise it's
# a stray press or the mic catching them mid-corner, and a human engineer would let it go
ANSWERS = {"yeah", "yes", "yep", "yup", "yeah yeah", "no", "nope", "nah", "uh", "um", "er", "erm", "hmm", "ah", "oh"}
ASKED_SECS = 30
HISTORY = 6  # exchanges (and radio calls) kept for follow-ups
# ...and only this recent: older answers got repeated as if current ("the set's fresh" 10 laps into it)
HISTORY_SECS = 90
CHECKING = "Copy, checking."
UNSURE = "Can't give you a solid number on that one."  # said when every sentence of a reply was held back
SENTENCE = re.compile(r"[.!?](?=\s)")  # "0.7" and "P1." at the end of a chunk don't count

SYSTEM = (Path(__file__).resolve().parent / "prompts" / "engineer.md").read_text()  # the live brief follows it


class Engineer:
    def __init__(self, hub, state, model=DEFAULT_MODEL, role="engineer", at=None):
        self.hub = hub
        self.role, self.at = role, at or (lambda: usage.where(state))  # what the spend is logged against
        self.state = state
        self.model = model
        self.replies = deque(maxlen=30)
        self.error = None if api_key() is not None else "no OPENROUTER_API_KEY in .env, engineer is off"
        self._history = deque(maxlen=HISTORY)
        self._session = None
        self._queue = queue.Queue()
        self._answering = False
        self.commands = []  # fn(text) -> spoken reply or None, tried before the model (e.g. "less chat")
        self.speak = lambda text, at=None: None  # told each finished sentence of a reply, as it streams
        self.wall = None  # the pit wall: strategy questions go to the team
        if self.error:
            _log.error("engineer disabled", exc=False, reason=self.error)
        threading.Thread(target=self._work, name="engineer", daemon=True).start()

    def ask(self, msg):
        """Called with every finished radio message; empty ones and acknowledgements are ignored."""
        text = msg.get("text") or ""
        why = ("nothing heard" if not text else "acknowledgement" if _plain(text) in ACKS
               else "nothing asked of him to answer" if _plain(text) in ANSWERS and not self._asked() else None)
        if why:
            _log.info("no reply", text=text, why=why)
            radiolog.record("reply", {"to": msg.get("id"), "status": "ignored", "why": why, "at": time.time()})
            return
        self._queue.put(msg)

    def _asked(self):
        """Did our last word to them, in the past ASKED_SECS, end in a question?"""
        if not self._history:
            return False
        at, _, said = self._history[-1]
        return time.time() - at <= ASKED_SECS and said.rstrip().endswith("?")

    def busy(self):
        return self._answering or not self._queue.empty()

    def said(self, text):
        """A call made unprompted, so "what do you mean?" has something to follow up."""
        self._history.append((time.time(), None, text))

    def _work(self):
        while True:
            msg = self._queue.get()
            self._answering = True
            try:
                self._answer(msg)
            except Exception as e:  # keep the worker alive whatever happens
                _log.error("answer crashed", error=str(e))
            self._answering = False

    def _answer(self, msg):
        reply = {"id": f"r{msg['id']}", "to": msg["id"], "question": msg["text"], "status": "thinking",
                 "text": "", "model": self.model, "at": time.time()}
        self._publish(reply)
        for command in self.commands:
            done = command(msg["text"])
            if done:
                self.speak(done, reply["at"])
                return self._publish(reply, status="done", text=done, local=True)
        route = self.wall and self.wall.routes(msg["text"])
        if route == "team":  # the team decides; it answers through the calls when it has
            self.wall.ask(msg["text"])
            self.speak(CHECKING, reply["at"])
            self._history.append((time.time(), _question(msg), CHECKING))
            return self._publish(reply, status="done", text=CHECKING, local=True)
        if self.error:
            return self._publish(reply, status="error", error=self.error)

        with self.state.lock:
            session = self.state.session_uid
        if session != self._session:
            self._session, self._history = session, deque(maxlen=HISTORY)
        data = brief.build(self.state)
        if not data:
            return self._publish(reply, status="done", text="No data from the car yet.", local=True)
        if self.wall:
            data += "\n\n" + self.wall.section()

        now = time.time()
        recent = [(q, a) for at, q, a in self._history if now - at <= HISTORY_SECS]
        messages = prompt(data, _question(msg), recent)
        _log.info("asking", model=self.model, question=msg["text"], brief_chars=len(data))

        spoken = ""  # streamed text not yet handed to the voice
        said, held = [], []
        given = data + "\n" + msg["text"]

        def say(sentence):
            wrong = numbers.unsupported(sentence, given)
            if wrong:
                held.append({"text": sentence, "numbers": wrong})
                _log.warn("number not in the brief, not said", sentence=sentence, numbers=wrong)
                return
            said.append(sentence)
            self.speak(sentence, reply["at"])

        def on_text(chunk):
            nonlocal spoken
            reply["text"] += chunk
            spoken += chunk
            self._publish(reply, status="streaming")
            while m := SENTENCE.search(spoken):
                say(spoken[:m.end()].strip())
                spoken = spoken[m.end():]

        try:
            stats = stream(self.model, messages, on_text, role=self.role, at=self.at(), why="question")
        except LLMError as e:
            _log.error("engineer call failed", exc=False, model=self.model, error=str(e))
            return self._publish(reply, status="error", error=str(e))
        reply["text"] = reply["text"].strip()
        if spoken.strip():
            say(spoken.strip())
        if held and not said:
            said.append(UNSURE)
            self.speak(UNSURE, reply["at"])
        # what was actually said, so a follow-up (or the team) doesn't build on a held-back figure
        heard = " ".join(said) if held else reply["text"]
        self._history.append((time.time(), _question(msg), heard))
        self._publish(reply, status="done", held=held or None, **stats)
        if route == "now":  # no time to ask: the team looks at what we said
            self.wall.answered(msg["text"], heard)

    def _publish(self, reply, **changes):
        reply.update(changes)
        if reply["status"] in ("done", "error"):
            self.replies.append(dict(reply))
            radiolog.record("reply", {k: reply.get(k) for k in ("to", "status", "text", "held", "model", "error", "local", "firstMs", "at")})
        self.hub.publish("reply", dict(reply))


def prompt(data, question, history=()):
    """What the model sees: the rules and the live brief, recent exchanges [(question or None, answer)], the question."""
    out = [{"role": "system", "content": driver.words(SYSTEM) + data}]
    for q, a in history:
        out += ([{"role": "user", "content": q}] if q else []) + [{"role": "assistant", "content": a}]
    return out + [{"role": "user", "content": question}]


def _plain(text):
    return " ".join(re.sub(r"[^a-z ]", " ", text.lower().replace("-", " ")).split())


def _question(msg):
    """The corrected question, noting what speech-to-text actually heard when it was changed."""
    if msg.get("changes"):
        return f'{msg["text"]}\n(speech-to-text heard: "{msg["heard"]}")'
    return msg["text"]
