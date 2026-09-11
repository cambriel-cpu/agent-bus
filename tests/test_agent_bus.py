#!/usr/bin/env python3
"""Tests for the agent-bus reference implementation. Stdlib only (unittest).

Covers the security and concurrency findings from the pre-deployment review:
ID validation / path traversal, remote identity binding, corrupt records,
crash-consistent task transitions, and concurrent claims.
"""
import importlib.machinery
import importlib.util
import io
import json
import os
import shutil
import sys
import tempfile
import threading
import unittest
from contextlib import redirect_stderr
from unittest import mock

BUS_PY = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "agent-bus")


def load_bus():
    loader = importlib.machinery.SourceFileLoader("agent_bus", BUS_PY)
    spec = importlib.util.spec_from_loader("agent_bus", loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


bus = load_bus()


class BusTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="bustest-")
        self.bus_dir = os.path.join(self.tmp, "bus")
        # fresh env without a remote identity unless a test sets one
        self._env = dict(os.environ)
        os.environ.pop("AGENT_BUS_REMOTE_ID", None)
        bus.main(["--bus", self.bus_dir, "init"])

    def tearDown(self):
        os.environ.clear()
        os.environ.update(self._env)
        shutil.rmtree(self.tmp, ignore_errors=True)

    def cli(self, *argv):
        """Run the CLI; return (exit_code, stdout, stderr)."""
        out, err = io.StringIO(), io.StringIO()
        code = 0
        with redirect_stderr(err):
            old = sys.stdout
            sys.stdout = out
            try:
                bus.main(["--bus", self.bus_dir, *argv])
            except SystemExit as e:
                code = e.code or 0
            finally:
                sys.stdout = old
        return code, out.getvalue(), err.getvalue()

    def inbox_files(self, agent, archived=False):
        d = os.path.join(self.bus_dir, "inbox", agent, "archive" if archived else "")
        return sorted(f for f in os.listdir(d) if f.endswith(".json"))

    # --- basic round trip -------------------------------------------------
    def test_send_inbox_read_ack(self):
        code, out, _ = self.cli("send", "--from", "openclaw", "--to", "omni",
                                "--subject", "hi", "--body", "hello")
        self.assertEqual(code, 0)
        mid = json.loads(out)["sent"][0]
        code, out, _ = self.cli("inbox", "omni")
        self.assertEqual(code, 0)
        self.assertIn("hi", out)
        code, out, _ = self.cli("read", "omni", mid)
        self.assertEqual(code, 0)
        self.assertIn("hello", json.loads(out)["body"])
        code, _, _ = self.cli("ack", "omni", mid)
        self.assertEqual(code, 0)
        self.assertEqual(self.inbox_files("omni"), [])
        self.assertEqual(len(self.inbox_files("omni", archived=True)), 1)

    def test_task_lifecycle_with_sidecars(self):
        code, out, _ = self.cli("propose", "--from", "omni", "--subject", "job")
        tid = json.loads(out)["proposed"]
        self.cli("claim", "codex", tid)
        # task file itself is immutable: no claimed_by inside
        with open(os.path.join(self.bus_dir, "tasks", "claimed", tid + ".json")) as f:
            raw = json.load(f)
        self.assertNotIn("claimed_by", raw)
        self.assertTrue(os.path.exists(
            os.path.join(self.bus_dir, "tasks", "claimed", tid + ".claim.json")))
        code, out, _ = self.cli("tasks", "--json")
        view = [t for t in json.loads(out) if t["id"] == tid][0]
        self.assertEqual(view["state"], "claimed")
        self.assertEqual(view["claimed_by"], "codex")
        self.cli("finish", "codex", tid, "--note", "done")
        self.assertTrue(os.path.exists(
            os.path.join(self.bus_dir, "tasks", "done", tid + ".finish.json")))
        code, out, _ = self.cli("tasks", "--state", "done", "--json")
        view = json.loads(out)[0]
        self.assertEqual(view["finish_note"], "done")

    # --- path traversal ----------------------------------------------------
    def test_traversal_rejected(self):
        for bad in ["../../../etc/passwd", "..\\..\\x", "/abs/path",
                    "....//....//x", "a/b"]:
            code, _, err = self.cli("read", "omni", bad)
            self.assertNotEqual(code, 0, bad)
            code, _, _ = self.cli("ack", "omni", bad)
            self.assertNotEqual(code, 0, bad)
            code, _, _ = self.cli("claim", "omni", bad)
            self.assertNotEqual(code, 0, bad)
        # and nothing escaped the bus dir
        self.assertFalse(os.path.exists(os.path.join(self.tmp, "etc")))

    def test_traversal_cannot_read_outside_file(self):
        outside = os.path.join(self.tmp, "secret.json")
        with open(outside, "w") as f:
            json.dump({"s": "shh"}, f)
        code, out, _ = self.cli("read", "omni", "../secret")
        self.assertNotEqual(code, 0)
        self.assertNotIn("shh", out)

    # --- corrupt records ----------------------------------------------------
    def test_corrupt_message_does_not_break_inbox(self):
        self.cli("send", "--from", "openclaw", "--to", "omni", "--subject", "good")
        bad = os.path.join(self.bus_dir, "inbox", "omni", "broken.json")
        with open(bad, "w") as f:
            f.write("{not valid json")
        code, out, err = self.cli("inbox", "omni")
        self.assertEqual(code, 0)
        self.assertIn("good", out)
        self.assertIn("warning", err)

    def test_corrupt_task_does_not_break_listing(self):
        self.cli("propose", "--from", "omni", "--subject", "fine")
        bad = os.path.join(self.bus_dir, "tasks", "open", "broken.json")
        with open(bad, "w") as f:
            f.write("[1,2,")
        code, out, err = self.cli("tasks")
        self.assertEqual(code, 0)
        self.assertIn("fine", out)
        self.assertIn("warning", err)

    # --- concurrency ----------------------------------------------------------
    def test_concurrent_claim_single_winner(self):
        code, out, _ = self.cli("propose", "--from", "omni", "--subject", "race")
        tid = json.loads(out)["proposed"]
        results, errors = [], []
        barrier = threading.Barrier(12)

        def attempt(i):
            agent = bus.AGENTS[i % len(bus.AGENTS)]
            barrier.wait()
            out, err = io.StringIO(), io.StringIO()
            with redirect_stderr(err):
                old = sys.stdout
                sys.stdout = out
                try:
                    bus.main(["--bus", self.bus_dir, "claim", agent, tid])
                    results.append(agent)
                except SystemExit as e:
                    errors.append((e.code, err.getvalue()))
                finally:
                    sys.stdout = old

        threads = [threading.Thread(target=attempt, args=(i,)) for i in range(12)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(len(results), 1, f"expected one winner, got {results}")
        self.assertEqual(len(errors), 11)
        for code, err in errors:
            self.assertNotEqual(code, 0)
            self.assertNotIn("Traceback", err)  # clean failure, no traceback
        # winner's sidecar is consistent
        winner = results[0]
        code, out, _ = self.cli("tasks", "--json")
        view = [t for t in json.loads(out) if t["id"] == tid][0]
        self.assertEqual(view["claimed_by"], winner)

    # --- remote identity -------------------------------------------------------
    def test_remote_identity_binding(self):
        os.environ["AGENT_BUS_REMOTE_ID"] = "omni"
        # cannot send as someone else
        code, _, _ = self.cli("send", "--from", "openclaw", "--to", "omni",
                              "--subject", "x")
        self.assertNotEqual(code, 0)
        # cannot read another agent's inbox
        code, _, _ = self.cli("inbox", "codex")
        self.assertNotEqual(code, 0)
        # cannot use --force remotely
        code, out, _ = self.cli("propose", "--from", "omni", "--subject", "t")
        tid = json.loads(out)["proposed"]
        code, _, _ = self.cli("release", "codex", tid, "--force")
        self.assertNotEqual(code, 0)
        # cannot purge remotely
        code, _, _ = self.cli("purge", "--dry-run")
        self.assertNotEqual(code, 0)
        # own operations still work
        code, _, _ = self.cli("send", "--from", "omni", "--to", "codex",
                              "--subject", "ok")
        self.assertEqual(code, 0)
        code, out, _ = self.cli("inbox", "omni")
        self.assertEqual(code, 0)

    def test_remote_claim_as_self_only(self):
        os.environ["AGENT_BUS_REMOTE_ID"] = "omni"
        code, out, _ = self.cli("propose", "--from", "omni", "--subject", "t")
        tid = json.loads(out)["proposed"]
        code, _, _ = self.cli("claim", "codex", tid)
        self.assertNotEqual(code, 0)
        code, _, _ = self.cli("claim", "omni", tid)
        self.assertEqual(code, 0)

    # --- expiry / purge ---------------------------------------------------------
    def test_purge_removes_only_long_expired(self):
        # craft messages with deterministic expiry timestamps
        ibox = os.path.join(self.bus_dir, "inbox", "omni")
        old = {"id": "old1", "ts": "2026-01-01T00:00:00Z", "from": "omni",
               "to": "omni", "type": "message", "subject": "old",
               "body": "", "thread": None, "expires_at": "2026-01-02T00:00:00Z"}
        fresh = dict(old, id="fresh1", subject="fresh",
                     expires_at="2099-01-01T00:00:00Z")
        for m in (old, fresh):
            with open(os.path.join(ibox, m["id"] + ".json"), "w") as f:
                json.dump(m, f)
        code, out, _ = self.cli("purge", "--grace-days", "0", "--dry-run")
        purged = json.loads(out)["purged"]
        self.assertEqual(purged, ["omni/old1"])
        self.assertEqual(len(self.inbox_files("omni")), 2)  # dry run changed nothing
        self.cli("purge", "--grace-days", "0")
        self.assertEqual(self.inbox_files("omni"), ["fresh1.json"])
        code, out, _ = self.cli("inbox", "omni", "--all")
        self.assertIn("fresh", out)
        self.assertNotIn("old", out)


if __name__ == "__main__":
    unittest.main(verbosity=2)
