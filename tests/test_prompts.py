"""Prompt versions: the shipped ones, the driver's edits as new versions, which one is in use, and
every model call saying which it had."""
import json
import shutil
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from engineer import engineer as eng_module, llm, prompts
from engineer.engineer import Engineer, prompt
from engineer.hub import Hub
from engineer.pitwall import triggers, wall as wall_mod
from tests import radio_rows
from tests.test_pitwall import _wall
from tests.test_brief import raced


def fresh(test):
    """An empty custom folder and nothing chosen, for this test only."""
    folder = Path(tempfile.mkdtemp()) / "prompts"
    for p in [mock.patch.object(prompts, "CUSTOM", folder), mock.patch.dict(prompts._using, clear=True),
              mock.patch.dict(prompts._texts, clear=True)]:
        p.start()
        test.addCleanup(p.stop)
    return folder


def ship(test, role, *bodies):
    """The shipped prompts, with the role's v1, v2… replaced by these."""
    folder = Path(tempfile.mkdtemp()) / "shipped"
    shutil.copytree(prompts.SHIPPED, folder, ignore=shutil.ignore_patterns("*.py", "__pycache__"))
    for n, body in enumerate(bodies, 1):
        (folder / role / f"v{n}.md").write_text(f"---\nwhy: number {n}\n---\n{body}", encoding="utf-8")
    p = mock.patch.object(prompts, "SHIPPED", folder)
    p.start()
    test.addCleanup(p.stop)


class Shipped(unittest.TestCase):
    def setUp(self):
        fresh(self)

    def test_every_role_ships_a_first_version_without_its_header(self):
        for role in [*prompts.ROLES, "judge"]:
            self.assertEqual(prompts.latest(role), "v1")
            self.assertFalse(prompts.text(role).startswith("---"), role)
            self.assertIn("You", prompts.text(role)[:40], role)
        self.assertEqual(prompts.versions("lead"), [{"id": "v1", "custom": False, "why": "the first versioned prompt",
                                                      "date": None, "from": None}])

    def test_the_judge_keeps_its_slots(self):
        self.assertIn("{facts}", prompts.text("judge"))


class Saving(unittest.TestCase):
    def setUp(self):
        self.folder = fresh(self)

    def test_an_edit_is_a_new_version_and_never_replaces_one(self):
        self.assertEqual(prompts.save("lead", "Be brief.", "  shorter\n calls ", "v1"), "custom-1")
        self.assertEqual(prompts.save("lead", "Be briefer.", "shorter still", "custom-1"), "custom-2")
        (self.folder / "lead" / "custom-7.md").write_text("mine", encoding="utf-8")  # by hand, no header
        self.assertEqual(prompts.save("lead", "Be briefest.", "again", "v1"), "custom-8")
        self.assertEqual(prompts.text("lead", "custom-1"), "Be brief.\n")
        self.assertEqual(prompts.text("lead", "custom-7"), "mine")
        self.assertEqual(prompts.base("lead", "custom-7"), "v1")
        two = prompts.versions("lead")[2]
        self.assertEqual((two["id"], two["custom"], two["why"], two["from"]), ("custom-2", True, "shorter still", "v1"))
        self.assertEqual(prompts.versions("lead")[1]["why"], "shorter calls")
        with mock.patch.object(prompts, "_ids", lambda role, where, prefix: ["v1"] if prefix == "v" else []):  # listed before others saved
            self.assertEqual(prompts.save("lead", "Be terse.", "race", "v1"), "custom-3")
        self.assertEqual(prompts.text("lead", "custom-1"), "Be brief.\n")

    def test_refuses_what_isnt_an_edit(self):
        same = prompts.text("engineer", "v1")
        for args, said in [(("judge", "x", "why", "v1"), "no prompt role"),
                           (("lead", "  ", "why", "v1"), "empty"),
                           (("lead", "x" * (prompts.MAX_CHARS + 1), "why", "v1"), "over"),
                           (("lead", "x", " ", "v1"), "why"),
                           (("engineer", same + "\n", "why", "v1"), "nothing changed"),
                           (("lead", "x", "why", "custom-3"), "no team lead prompt"),
                           (("lead", None, "why", "v1"), "empty")]:
            with self.assertRaisesRegex(ValueError, said):
                prompts.save(*args)
        self.assertFalse(self.folder.exists())


class InUse(unittest.TestCase):
    def setUp(self):
        fresh(self)

    def test_the_newest_shipped_until_one_is_chosen(self):
        made = prompts.save("engineer", "Talk like a pirate.\n", "fun", "v1")
        self.assertEqual(prompts.pick("engineer"), ("engineer/v1", prompts.text("engineer", "v1")))
        prompts.use(prompts.check({"engineer": made}))
        self.assertEqual(prompts.pick("engineer"), ("engineer/custom-1", "Talk like a pirate.\n"))
        self.assertEqual(prompts.active("lead"), "v1")
        prompts.use({"engineer": "custom-9"})  # deleted by hand since
        self.assertEqual(prompts.active("engineer"), "v1")

    def test_a_choice_must_exist(self):
        for bad, said in [({"judge": "v1"}, "no prompt role"), ({"lead": "v9"}, "no team lead prompt"),
                          ({"lead": "../../x"}, "no team lead prompt"), ({"lead": 1}, "no team lead prompt"), ("v1", "expected")]:
            with self.assertRaisesRegex(ValueError, said):
                prompts.check(bad)

    def test_a_newer_shipped_version_is_offered_with_what_changed(self):
        ship(self, "lead", "Box when told.\nKeep it short.\n", "Box when told.\nKeep it shorter.\n")
        self.assertIsNone(prompts.newer("lead"))
        made = prompts.save("lead", "Box when told.\n", "mine", "v1")
        prompts.use({"lead": made})
        self.assertEqual(prompts.newer("lead"), "v2")
        view = prompts.view()["lead"]
        self.assertEqual((view["active"], view["latest"], view["newer"]), ("custom-1", "v2", "v2"))
        self.assertIn("-Keep it short.", view["changes"])
        self.assertIn("+Keep it shorter.", view["changes"])
        prompts.use({"lead": "v1"})
        self.assertEqual(prompts.newer("lead"), "v2")
        prompts.use({})
        self.assertIsNone(prompts.view()["lead"]["changes"])


class Recorded(unittest.TestCase):
    def setUp(self):
        fresh(self)
        self.rows = radio_rows(self)

    def test_the_engineer_answers_with_the_prompt_in_use_and_says_which(self):
        prompts.use({"engineer": prompts.save("engineer", "Only say 'copy'.\n", "test", "v1")})
        sent = []

        def stream(model, messages, on_text, **kw):
            sent.append((messages[0]["content"], kw["prompt"]))
            on_text("Copy. ")
            return {"firstMs": 1}
        eng = Engineer(Hub(), SimpleNamespace(lock=threading.Lock(), session_uid=1, latest={}), model="m", at=lambda: ("s", 0))
        with mock.patch.object(eng_module, "api_key", lambda: "key"), mock.patch.object(eng_module, "stream", stream), \
                mock.patch.object(eng_module, "brief", SimpleNamespace(build=lambda st: "BRIEF")):
            eng.error = None
            eng._answer({"id": "1", "text": "gap?"})
        self.assertEqual(sent, [("Only say 'copy'.\nBRIEF", "engineer/custom-1")])
        self.assertEqual(self.rows("reply")[0]["prompt"], "engineer/custom-1")
        self.assertTrue(prompt("B", "q")[0]["content"].startswith("Only say"))

    def test_each_team_run_says_which_prompts_it_had(self):
        prompts.use({"second": prompts.save("second", "Always AGREE.\n", "test", "v1")})
        sent = []

        def stream(model, messages, on_text, **kw):
            sent.append((messages[0]["content"][:13], kw["prompt"]))
            on_text("CALL: No change\nSAY: nothing\nWHY: x" if "lead" in kw["prompt"] else "AGREE: fine")
            return {"firstMs": 1}
        st = raced(3).st
        w = _wall(st)
        with mock.patch.object(wall_mod, "stream", stream):
            note = w.run([triggers.reason(("tyres",), "rear-left reaches 70% in 5 laps")], 10, 600.0, 0, wait=True)
        self.assertEqual(sent[1], ("Always AGREE.", "second/custom-1"))
        self.assertEqual((sent[0][1], note["prompt"], w.notes[-1]["prompt"]), ("lead/v1", "lead/v1", "second/custom-1"))

    def test_race_prep_says_which_prompts_it_had(self):
        sent = []

        def stream(model, messages, on_text, **kw):
            sent.append(kw["prompt"])
            on_text("FUEL: +1.0\nSTART: Medium new\nCALL: Medium to L12, Hard to the flag\nSAY: nothing\nWHY: x" if "prep" in kw["prompt"]
                    else "AGREE: fine")
            return {"firstMs": 1}
        w = _wall(raced(3).st)
        info = {"track": "Austria", "sets": [], "sprint": False}
        with mock.patch.object(wall_mod, "stream", stream), mock.patch.object(wall_mod.prep, "facts", lambda: ("FACTS", info)), \
                mock.patch.object(wall_mod.prep, "check", lambda lead, info: None if len(sent) > 2 else "starts and boxes on the Medium"), mock.patch.object(wall_mod.prep, "save", lambda p: None), \
                mock.patch.object(wall_mod.notes, "read_brief", lambda: None):
            w._prepare()
        self.assertEqual(sent, ["prep/v1", "prep/v1", "second/v1"])  # the retry, told what was wrong, has it too
        self.assertEqual((w.prep["note"]["prompt"], w.prep["review"]["prompt"]), ("prep/v1", "second/v1"))

    def test_the_trace_keeps_the_prompt_version(self):
        folder = Path(tempfile.mkdtemp())

        class Reply:
            def __init__(self, lines):
                self.lines = lines

            def __enter__(self):
                return iter(self.lines)

            def __exit__(self, *a):
                return False
        lines = [b'data: {"choices": [{"delta": {"content": "Copy."}}]}\n', b"data: [DONE]\n"]
        with mock.patch.object(llm, "TRACE", folder), mock.patch.object(llm, "api_key", lambda: "key"), \
                mock.patch("urllib.request.urlopen", lambda req, timeout: Reply(lines)):
            llm.stream("some/model", [{"role": "user", "content": "q"}], lambda t: None, prompt="engineer/v1")
        [row] = [json.loads(line) for f in folder.glob("*.jsonl") for line in f.read_text().splitlines()]
        self.assertEqual(row["prompt"], "engineer/v1")


if __name__ == "__main__":
    unittest.main()
