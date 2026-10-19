"""Model calls: the streamed reply, what's kept of each call, and errors that don't leak the account."""
import io
import json
import os
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import patch

from engineer import llm

ASKED = [{"role": "system", "content": "BRIEF"}, {"role": "user", "content": "gap?"}]


def sse(*events):
    return [f"data: {json.dumps(e)}\n".encode() for e in events] + [b"data: [DONE]\n"]


class Reply(io.BytesIO):
    def __init__(self, lines):
        super().__init__()
        self.lines = lines

    def __iter__(self):
        return iter(self.lines)


def chunk(text):
    return {"choices": [{"delta": {"content": text}}]}


class Calls(unittest.TestCase):
    def setUp(self):
        for p in (patch.dict(os.environ, {"OPENROUTER_API_KEY": "x"}), patch.object(llm, "ENV_FILE", Path("no.env"))):
            p.start()
            self.addCleanup(p.stop)
        os.environ.pop("RE_LLM_URL", None)
        os.environ.pop("RE_LLM_KEY", None)
        self.folder = Path(tempfile.mkdtemp()) / "llm"

    def call(self, lines, trace=True, **kw):
        got = []
        with patch.object(llm, "TRACE", self.folder if trace else None), \
                patch("urllib.request.urlopen", lambda req, timeout: Reply(lines)):
            stats = llm.stream("some/model", ASKED, got.append, role="engineer", at=("42", "Race", "Zandvoort"),
                               why="question", **kw)
        return got, stats

    def kept(self):
        files = list(self.folder.glob("*.jsonl"))
        return [json.loads(line) for f in files for line in f.read_text().splitlines()]

    def test_reply_streams_and_the_call_is_kept_as_the_model_saw_it(self):
        usage = {"prompt_tokens": 900, "completion_tokens": 12, "cost": 0.0011}
        got, stats = self.call(sse(chunk("Gap is 1.2, "), {"provider": "Groq", **chunk("holding.")}, {"choices": [], "usage": usage}))
        self.assertEqual(got, ["Gap is 1.2, ", "holding."])
        self.assertEqual((stats["provider"], stats["inTokens"], stats["outTokens"], stats["cost"]), ("Groq", 900, 12, 0.0011))
        [row] = self.kept()
        self.assertEqual({k: row[k] for k in ("role", "why", "session", "model", "messages", "reply")},
                         {"role": "engineer", "why": "question", "session": "42", "model": "some/model",
                          "messages": ASKED, "reply": "Gap is 1.2, holding."})
        self.assertEqual(row["stats"], stats)
        self.assertNotIn("error", row)

    def test_a_call_that_fails_halfway_is_kept_with_what_came_and_why(self):
        with self.assertRaises(llm.LLMError):
            self.call(sse(chunk("Box"), {"error": {"message": "provider overloaded"}}))
        [row] = self.kept()
        self.assertEqual((row["reply"], row["error"]), ("Box", "provider overloaded"))
        self.assertNotIn("stats", row)

    def test_nothing_is_kept_unless_the_server_turned_it_on(self):
        self.call(sse(chunk("Copy.")), trace=False)
        self.assertFalse(self.folder.exists())

    def test_a_trace_that_cant_be_written_doesnt_lose_the_answer(self):
        self.folder.parent.mkdir(exist_ok=True)
        self.folder.write_text("")  # a file where the folder should be
        got, stats = self.call(sse(chunk("Copy.")))
        self.assertEqual(got, ["Copy."])
        self.assertEqual(stats["model"], "some/model")

    def test_an_http_error_shows_the_message_not_the_account(self):
        body = json.dumps({"error": {"message": "Invalid model", "metadata": {"user_id": "user_123"}}}).encode()
        err = urllib.error.HTTPError("u", 400, "Bad Request", {}, io.BytesIO(body))

        def refuse(req, timeout):
            raise err
        with patch("urllib.request.urlopen", refuse), self.assertRaises(llm.LLMError) as e:
            llm.stream("some/model", ASKED, lambda t: None)
        self.assertEqual(str(e.exception), "HTTP 400: Invalid model")

    def test_no_key_is_an_error_before_anything_is_sent(self):
        with patch.object(llm, "_env", lambda name: None), patch("urllib.request.urlopen") as sent:
            with self.assertRaises(llm.LLMError):
                llm.stream("some/model", ASKED, lambda t: None)
        sent.assert_not_called()


if __name__ == "__main__":
    unittest.main()
