"""Tests for resume.py against fake Claude Code and Codex transcript folders."""
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "resume.py"
sys.path.insert(0, str(SCRIPT.parent))
import resume  # noqa: E402

LIVE_VARS = ("CLAUDE_CODE_SESSION_ID", "CODEX_THREAD_ID", "CODEX_SESSION_ID")


def write_jsonl(path: Path, records, mtime: float):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        for r in records:
            fh.write(json.dumps(r) + "\n")
    os.utime(path, (mtime, mtime))
    return path


def claude_session(folder: Path, sid: str, turns, mtime: float):
    records = [
        {"type": role, "timestamp": f"2026-01-01T10:{i:02d}:00Z", "message": {"role": role, "content": content}}
        for i, (role, content) in enumerate(turns)
    ]
    return write_jsonl(folder / f"{sid}.jsonl", records, mtime)


def codex_session(home: Path, tid: str, cwd: str, turns, mtime: float, tool_calls=()):
    records = [{"type": "session_meta", "timestamp": "2026-01-02T09:00:00Z",
                "payload": {"id": tid, "cwd": cwd, "timestamp": "2026-01-02T09:00:00Z"}}]
    for i, (role, text) in enumerate(turns):
        kind = "input_text" if role == "user" else "output_text"
        records.append({"type": "response_item", "timestamp": f"2026-01-02T09:{i + 1:02d}:00Z",
                        "payload": {"type": "message", "role": role, "content": [{"type": kind, "text": text}]}})
    for blob in tool_calls:
        records.append({"type": "response_item", "payload": {"type": "custom_tool_call", "name": "apply_patch", "input": blob}})
    path = home / "sessions" / "2026" / "01" / "02" / f"rollout-2026-01-02T09-00-00-{tid}.jsonl"
    return write_jsonl(path, records, mtime)


class ResumeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        base = Path(self.tmp.name).resolve()  # macOS: /var is a symlink to /private/var
        self.claude_config = base / "claude"
        self.codex_home = base / "codex"
        self.project = base / "my-app"
        self.project.mkdir()
        self.pdir = self.claude_config / "projects" / resume.encode_cwd(str(self.project))
        self.pdir.mkdir(parents=True)
        self.now = time.time()
        claude_session(self.pdir, "old", [("user", "old task")], self.now - 7200)
        claude_session(self.pdir, "prev", [
            ("user", "Build the login page"),
            ("assistant", [
                {"type": "text", "text": "Starting on it."},
                {"type": "tool_use", "name": "Write", "input": {"file_path": "/app/login.tsx"}},
            ]),
            ("user", [{"type": "tool_result", "content": "ok"}]),
            ("user", "<system-reminder>noise</system-reminder>"),
            ("user", "Now add a logout button"),
            ("assistant", "Logout button added; tests still to run."),
        ], self.now - 3600)
        claude_session(self.pdir, "live", [("user", "continue the previous chat")], self.now)

    def tearDown(self):
        self.tmp.cleanup()

    def add_codex_chat(self, tid="cdx-1", mtime_offset=-600, cwd=None):
        return codex_session(
            self.codex_home, tid, cwd or str(self.project),
            [
                ("user", "<environment_context>\n  <cwd>x</cwd>\n</environment_context>"),
                ("user", "Fix the flaky payment test"),
                ("assistant", "Found the race in checkout.test.ts and patched it."),
            ],
            self.now + mtime_offset,
            tool_calls=["*** Begin Patch\n*** Update File: src/checkout.ts\n@@\n-a\n+b\n*** End Patch"],
        )

    def run_script(self, *args, live="live", live_var="CLAUDE_CODE_SESSION_ID"):
        env = dict(os.environ, CLAUDE_CONFIG_DIR=str(self.claude_config), CODEX_HOME=str(self.codex_home))
        for var in LIVE_VARS:
            env.pop(var, None)
        if live is not None:
            env[live_var] = live
        return subprocess.run(
            [sys.executable, str(SCRIPT), *args],
            cwd=self.project, env=env, capture_output=True, text=True, encoding="utf-8",
        )

    def test_encode_cwd(self):
        if os.name == "nt":
            self.assertEqual(resume.encode_cwd(r"C:\Users\me\my-app"), "C--Users-me-my-app")
        else:
            self.assertEqual(resume.encode_cwd("/home/me/my-app"), "-home-me-my-app")

    def test_claude_digest_skips_live_chat_and_noise(self):
        r = self.run_script()
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("PREVIOUS CLAUDE CODE CHAT  (prev)", r.stdout)
        self.assertIn("Build the login page", r.stdout)
        self.assertIn("Now add a logout button", r.stdout)
        self.assertIn("/app/login.tsx", r.stdout)
        self.assertIn("2 user turns", r.stdout)
        self.assertNotIn("system-reminder", r.stdout)

    def test_without_live_id_skips_fresh_transcript(self):
        r = self.run_script(live=None)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("PREVIOUS CLAUDE CODE CHAT  (prev)", r.stdout)
        self.assertIn("no live chat id", r.stderr)

    def test_list_marks_live_chat(self):
        self.add_codex_chat()
        r = self.run_script("--list")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("[claude] live  <-- CURRENT (live)", r.stdout)
        self.assertIn("[codex] cdx-1", r.stdout)
        self.assertIn("old task", r.stdout)

    def test_specific_session_and_full_dump(self):
        r = self.run_script("--session", "old", "--full")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("PREVIOUS CLAUDE CODE CHAT  (old)", r.stdout)
        dump = self.pdir / "old.transcript.txt"
        self.assertTrue(dump.exists())
        self.assertIn("old task", dump.read_text(encoding="utf-8"))

    def test_newest_chat_wins_across_tools(self):
        self.add_codex_chat()  # newer than the Claude "prev" chat
        r = self.run_script()
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("PREVIOUS CODEX CHAT  (cdx-1)", r.stdout)
        self.assertIn("Fix the flaky payment test", r.stdout)
        self.assertIn("src/checkout.ts", r.stdout)
        self.assertIn("1 user turns", r.stdout)
        self.assertNotIn("environment_context", r.stdout)

    def test_source_flag_limits_search(self):
        self.add_codex_chat()
        r = self.run_script("--source", "claude")
        self.assertIn("PREVIOUS CLAUDE CODE CHAT  (prev)", r.stdout)

    def test_codex_live_chat_is_skipped(self):
        self.add_codex_chat("cdx-old", mtime_offset=-1800)
        self.add_codex_chat("cdx-live", mtime_offset=0)
        r = self.run_script("--source", "codex", live="cdx-live", live_var="CODEX_THREAD_ID")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("PREVIOUS CODEX CHAT  (cdx-old)", r.stdout)

    def test_codex_chat_from_other_folder_is_ignored(self):
        other = self.project.parent / "other"
        other.mkdir()
        self.add_codex_chat("cdx-elsewhere", cwd=str(other))
        r = self.run_script("--source", "codex")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("No Codex or Claude Code chats found", r.stderr)

    def test_codex_full_dump_goes_to_temp(self):
        self.add_codex_chat()
        r = self.run_script("--source", "codex", "--full")
        self.assertEqual(r.returncode, 0, r.stderr)
        dump = Path(tempfile.gettempdir()) / "cdx-1.transcript.txt"
        try:
            self.assertTrue(dump.exists())
            self.assertFalse(list((self.codex_home / "sessions").rglob("*.txt")))
        finally:
            dump.unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main()
