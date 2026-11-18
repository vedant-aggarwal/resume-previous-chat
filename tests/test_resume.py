"""Tests for resume.py against a fake Claude Code transcript folder."""
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


def write_session(folder: Path, sid: str, turns, mtime: float):
    path = folder / f"{sid}.jsonl"
    with open(path, "w", encoding="utf-8") as fh:
        for i, (role, content) in enumerate(turns):
            fh.write(json.dumps({
                "type": role,
                "timestamp": f"2026-01-01T10:{i:02d}:00Z",
                "message": {"role": role, "content": content},
            }) + "\n")
    os.utime(path, (mtime, mtime))
    return path


class ResumeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        base = Path(self.tmp.name).resolve()  # macOS: /var is a symlink to /private/var
        self.config = base / "config"
        self.project = base / "my-app"
        self.project.mkdir()
        self.pdir = self.config / "projects" / resume.encode_cwd(str(self.project))
        self.pdir.mkdir(parents=True)
        now = time.time()
        write_session(self.pdir, "old", [("user", "old task")], now - 7200)
        write_session(self.pdir, "prev", [
            ("user", "Build the login page"),
            ("assistant", [
                {"type": "text", "text": "Starting on it."},
                {"type": "tool_use", "name": "Write", "input": {"file_path": "/app/login.tsx"}},
            ]),
            ("user", [{"type": "tool_result", "content": "ok"}]),
            ("user", "<system-reminder>noise</system-reminder>"),
            ("user", "Now add a logout button"),
            ("assistant", "Logout button added; tests still to run."),
        ], now - 3600)
        write_session(self.pdir, "live", [("user", "continue the previous chat")], now)

    def tearDown(self):
        self.tmp.cleanup()

    def run_script(self, *args, session_id="live"):
        env = dict(os.environ, CLAUDE_CONFIG_DIR=str(self.config))
        env.pop("CLAUDE_CODE_SESSION_ID", None)
        if session_id is not None:
            env["CLAUDE_CODE_SESSION_ID"] = session_id
        return subprocess.run(
            [sys.executable, str(SCRIPT), *args],
            cwd=self.project, env=env, capture_output=True, text=True, encoding="utf-8",
        )

    def test_encode_cwd(self):
        if os.name == "nt":
            self.assertEqual(resume.encode_cwd(r"C:\Users\me\my-app"), "C--Users-me-my-app")
        else:
            self.assertEqual(resume.encode_cwd("/home/me/my-app"), "-home-me-my-app")

    def test_digest_skips_live_chat_and_noise(self):
        r = self.run_script()
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("PREVIOUS CHAT  (prev)", r.stdout)
        self.assertIn("Build the login page", r.stdout)
        self.assertIn("Now add a logout button", r.stdout)
        self.assertIn("/app/login.tsx", r.stdout)
        self.assertIn("2 user turns", r.stdout)
        self.assertNotIn("system-reminder", r.stdout)

    def test_without_session_id_skips_fresh_transcript(self):
        r = self.run_script(session_id=None)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("PREVIOUS CHAT  (prev)", r.stdout)
        self.assertIn("CLAUDE_CODE_SESSION_ID is not set", r.stderr)

    def test_list_marks_live_chat(self):
        r = self.run_script("--list")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("live  <-- CURRENT (live)", r.stdout)
        self.assertIn("old task", r.stdout)

    def test_specific_session_and_full_dump(self):
        r = self.run_script("--session", "old", "--full")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("PREVIOUS CHAT  (old)", r.stdout)
        dump = self.pdir / "old.transcript.txt"
        self.assertTrue(dump.exists())
        self.assertIn("old task", dump.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
