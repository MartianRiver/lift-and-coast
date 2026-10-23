"""The Settings tab: where each value comes from, what can be changed, and the change reaching what's running."""
import json
import re
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from engineer import calls, llm, models, prompts
from engineer.calls import Caller
from engineer.calls.common import GROUP
from engineer.crew import Crew
from engineer.radio import button
from engineer.settings import SPECS, Settings
from tests.test_brief import Hub, raced

ENGINE = Path(__file__).resolve().parent.parent / "engineer"


def store(cli=None, env=None, saved=None):
    path = Path(tempfile.mkdtemp(prefix="re-settings-")) / "settings.json"
    if saved is not None:
        path.write_text(json.dumps(saved))
    env = env or {}
    return Settings(cli, path, env=lambda name: (env[name], ".env") if name in env else (None, None))


class Sources(unittest.TestCase):
    def test_command_line_then_environment_then_file_then_default(self):
        saved = {"engineerModel": "file/model", "voice": "kokoro:bm_lewis", "budget": 3}
        s = store({"--engineer-model": "cli/model"}, {"RE_ENGINEER_MODEL": "env/model", "RE_VOICE": "kokoro:bf_emma"}, saved)
        self.assertEqual(s.resolve("engineerModel"), ("cli/model", "--engineer-model"))
        self.assertEqual(s.resolve("voice"), ("kokoro:bf_emma", "RE_VOICE in .env"))
        self.assertEqual(s.resolve("budget"), (3.0, "file"))
        self.assertEqual(s.resolve("calls"), ("normal", "default"))
        self.assertEqual(s.all()["engineerModel"], "cli/model")
        view = s.view()
        self.assertEqual((view["engineerModel"]["locked"], view["budget"]["locked"]), ("--engineer-model", None))

    def test_the_team_comes_from_one_option(self):
        s = store({"--pitwall-models": "a/lead"})
        self.assertEqual((s.get("lead"), s.get("second")), ("a/lead", None))  # no second opinion
        self.assertEqual(s.view()["second"]["locked"], "--pitwall-models")
        self.assertEqual(store({"--pitwall-models": "a/lead,b/second"}).get("second"), "b/second")

    def test_none_turns_the_fallback_off(self):
        self.assertIsNone(store({"--engineer-fallback": "none"}).get("engineerFallback"))
        self.assertIsNone(store(saved={"engineerFallback": None}).get("engineerFallback"))

    def test_a_bad_value_falls_back_on_the_default(self):
        s = store(saved={"calls": "loud", "budget": "lots", "topics": {"gaps": False}})
        self.assertEqual((s.get("calls"), s.get("budget")), ("normal", 2.0))
        self.assertFalse(s.get("topics")["gaps"])
        self.assertTrue(s.get("topics")["tyres"])  # a switch not in the file is on
        self.assertEqual(store({"--radio-button": "Nose Button"}).resolve("radioButton"), ("UDP Action 1", "--radio-button"))

    def test_unreadable_file_is_the_defaults(self):
        path = Path(tempfile.mkdtemp(prefix="re-settings-")) / "settings.json"
        path.write_text("{not json")
        self.assertEqual(Settings(path=path, env=lambda name: (None, None)).get("engineerModel"), SPECS["engineerModel"].default)


class Saving(unittest.TestCase):
    def test_saves_and_reads_back(self):
        s = store()
        self.assertEqual(s.set({"calls": "quiet", "budget": "1.5", "engineerFallback": ""}),
                         {"calls": "quiet", "budget": 1.5, "engineerFallback": None})
        again = Settings(path=s.path, env=lambda name: (None, None))
        self.assertEqual((again.get("calls"), again.get("budget"), again.get("engineerFallback")), ("quiet", 1.5, None))

    def test_refuses_a_locked_or_bad_value_and_saves_nothing(self):
        s = store({"--engineer-model": "cli/model"})
        with self.assertRaisesRegex(ValueError, "set by --engineer-model"):
            s.set({"engineerModel": "other/model"})
        s = store()
        for bad in ({"budget": 0}, {"budget": 51}, {"engineerModel": "has spaces"}, {"voice": "robot"},
                    {"radioButton": "Nose Button"}, {"topics": {"gossip": True}}, {"radioFx": "yes"}, {"nope": 1},
                    {"prompts": {"lead": "v9"}}):
            with self.assertRaises(ValueError):
                s.set({"calls": "quiet", **bad})
        with self.assertRaises(ValueError):
            s.set(["calls", "quiet"])
        self.assertFalse(s.path.exists())


    def test_every_voice_on_offer_saves_as_listed(self):
        from engineer.tts import VOICES
        s = store()
        for v in VOICES:
            self.assertEqual(s.set({"voice": v}), {"voice": v})


class Applying(unittest.TestCase):
    def crew(self):
        eng = SimpleNamespace(model="m", fallback="f")
        speaker = SimpleNamespace(voice=SimpleNamespace(name="kokoro", voice="bm_george", fx=False))
        from engineer.tts import Speaker
        speaker.use = lambda spec, fx: Speaker.use(speaker, spec, fx)
        radio = SimpleNamespace(trigger=0, quick=1, mode="hold", snapshot=lambda: {})
        wall = SimpleNamespace(models=("a", "b"), budget=2.0)
        caller = Caller(raced(3).st, Hub())
        hub = SimpleNamespace(sent=[], publish=lambda kind, data: hub.sent.append(kind))
        return Crew(eng, radio, speaker, caller, wall, hub)

    @patch.dict(prompts._using, clear=True)
    def test_each_change_reaches_what_is_running(self):
        crew, s = self.crew(), store()
        s.set({"engineerModel": "x/eng", "engineerFallback": "", "lead": "x/lead", "second": "", "budget": 4,
               "calls": "off", "topics": {"gaps": False}, "radioButton": "Left Stick Click", "quickButton": "3",
               "radioMode": "toggle", "voice": "kokoro:bf_emma", "radioFx": True, "prompts": {"lead": "v1"}})
        self.assertEqual(crew.apply(s, [k for k in SPECS if k != "audioOut"]), {})
        self.assertEqual((crew.engineer.model, crew.engineer.fallback), ("x/eng", None))
        self.assertEqual((crew.wall.models, crew.wall.budget), (("x/lead",), 4.0))
        self.assertEqual(crew.caller.level, "off")
        self.assertNotIn("gaps", crew.caller.topics)
        self.assertIn("tyres", crew.caller.topics)
        self.assertEqual((crew.radio.trigger, crew.radio.quick, crew.radio.mode), (button("Left Stick Click"), button("3"), "toggle"))
        self.assertIn("radio", crew.hub.sent)
        self.assertEqual((crew.speaker.voice.voice, crew.speaker.voice.fx), ("bf_emma", True))
        self.assertEqual(prompts._using, {"lead": "v1"})

    def test_another_voice_engine_or_device_waits_for_a_restart(self):
        crew, s = self.crew(), store()
        s.set({"voice": "qwen3:ryan", "audioOut": "Headphones"})
        self.assertEqual(set(crew.apply(s, ["voice", "audioOut"])), {"voice", "audioOut"})
        self.assertEqual(crew.speaker.voice.voice, "bm_george")

    def test_a_part_thats_off_is_left_alone(self):
        crew, s = self.crew(), store()
        crew.wall = crew.engineer = None
        s.set({"lead": "x/lead", "engineerModel": "x/eng"})
        self.assertEqual(crew.apply(s, ["lead", "engineerModel"]), {})


class Topics(unittest.TestCase):
    def test_every_call_topic_has_a_switch(self):
        used = set()
        for path in [*ENGINE.glob("calls/*.py"), *ENGINE.glob("pitwall/*.py"), ENGINE / "crew.py"]:
            used |= set(re.findall(r'\bcall\((?:\(.*?\)|\w+), "(\w+)"', path.read_text(encoding="utf-8")))
        self.assertGreater(len(used), 15)
        self.assertEqual(used - set(GROUP), set())

    def found(self):
        return [{"key": n, "topic": n, "prio": p, "text": lambda b, n=n: n, "ttl": 40}
                for n, p in (("pass", calls.LOW), ("gap", calls.NORMAL), ("tyres", calls.NORMAL), ("sc", calls.URGENT))]

    def queued(self, level="chatty", topics=None, pushed=()):
        c = Caller(raced(3).st, Hub())
        c.step()  # baseline
        c.level = level
        if topics is not None:
            c.topics = topics
        c.push([{"key": ("team", p), "topic": "team", "prio": p, "text": lambda b: "Box.", "ttl": 60} for p in pushed])
        with patch("engineer.calls.caller.scan", return_value=self.found()):
            sent = c.step()
        return sorted(f'{x["topic"]}{x["prio"]}' for x in c.queue + sent)

    def test_a_switched_off_topic_is_never_said(self):
        self.assertEqual(self.queued(topics={"tyres", "flags", "team"}, pushed=[calls.NORMAL]), ["sc0", "team1", "tyres1"])
        self.assertEqual(self.queued(topics={"gaps"}, pushed=[calls.URGENT]), ["gap1", "pass2"])  # the team's calls too

    def test_the_level_holds_for_the_teams_calls_too(self):
        self.assertEqual(self.queued("quiet", pushed=[calls.URGENT, calls.NORMAL]), ["sc0", "team0"])
        self.assertEqual(self.queued("off", pushed=[calls.URGENT]), [])


def openrouter(*extra):
    data = [{"id": "z/talker", "name": "Talker", "context_length": 128000, "expiration_date": None,
             "pricing": {"prompt": "0.000001", "completion": "0.00001"}},
            {"id": "a/retiring", "name": "Retiring", "expiration_date": "2026-11-01", "pricing": {"prompt": "0", "completion": "0"}},
            {"id": "p/painter", "name": "Painter", "architecture": {"input_modalities": ["text"], "output_modalities": ["image"]}},
            *extra]
    return {"data": data}


class Models(unittest.TestCase):
    def setUp(self):
        models._cache.clear()

    def test_what_a_race_costs_at_the_listed_price(self):
        # engineer: 6 answers of 3900 in, 150 out
        self.assertAlmostEqual(models.per_race({"prompt": "0.000001", "completion": "0.00001"}, "engineer"), 6 * (0.0039 + 0.0015))
        self.assertIsNone(models.per_race(None, "lead"))  # a local server lists no prices

    def test_the_list_keeps_models_that_talk_and_says_which_retire(self):
        with patch.object(llm, "_env", lambda name: None):
            got = models.listing(fetch=lambda url, key: openrouter())
        self.assertFalse(got["local"])
        self.assertEqual([m["id"] for m in got["models"]], ["a/retiring", "z/talker"])
        self.assertEqual(got["models"][0]["expires"], "2026-11-01")
        self.assertAlmostEqual(got["models"][1]["race"]["second"], 6.4 * (0.0026 + 0.0005), places=4)

    def test_asked_again_only_after_an_hour(self):
        asked, now = [], [1000.0]

        def fetch(url, key):
            asked.append((url, key))
            return openrouter()
        with patch.object(llm, "_env", {"OPENROUTER_API_KEY": "sk-or-test"}.get):
            for t in (1000, 1000 + models.KEEP - 1, 1000 + models.KEEP + 1):
                now[0] = t
                models.listing(fetch=fetch, now=lambda: now[0])
        self.assertEqual(asked, [("https://openrouter.ai/api/v1/models", None)] * 2)  # no key to OpenRouter

    def test_a_local_server_lists_its_own(self):
        env = {"RE_LLM_URL": "http://localhost:11434/v1", "RE_LLM_KEY": "local-key"}
        seen = []
        with patch.object(llm, "_env", env.get):
            got = models.listing(fetch=lambda url, key: seen.append((url, key)) or {"data": [{"id": "qwen3:8b"}]})
        self.assertEqual(seen, [("http://localhost:11434/v1/models", "local-key")])
        self.assertTrue(got["local"])
        self.assertEqual(got["models"][0]["race"], {"engineer": None, "lead": None, "second": None})

    def test_the_key_goes_only_to_a_server_that_needs_it(self):
        reply = MagicMock()
        reply.__enter__.return_value.read.return_value = b'{"data": []}'
        with patch("urllib.request.urlopen", return_value=reply) as sent:
            models._fetch("http://localhost:11434/v1/models", "local-key")
            models._fetch("https://openrouter.ai/api/v1/models", None)
        headers = [call.args[0].headers for call in sent.call_args_list]
        self.assertEqual(headers[0]["Authorization"], "Bearer local-key")
        self.assertNotIn("Authorization", headers[1])

    def test_no_list_is_an_error_not_an_empty_one(self):
        def down(url, key):
            raise OSError("no route to host")
        with patch.object(llm, "_env", lambda name: None), self.assertRaisesRegex(llm.LLMError, "no route to host"):
            models.listing(fetch=down)


if __name__ == "__main__":
    unittest.main()
