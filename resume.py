#!/usr/bin/env python3
"""Recover context from the previous Claude Code chat in the current project folder.

Claude Code stores every chat as a JSONL transcript under
    ~/.claude/projects/<encoded-cwd>/<session-uuid>.jsonl
($CLAUDE_CONFIG_DIR/projects/... when that variable is set), where
<encoded-cwd> is the absolute working directory with every
non-alphanumeric character replaced by '-'
(e.g. C:\\Users\\me\\my-app -> C--Users-me-my-app,
      /home/me/my-app      -> -home-me-my-app).

The live chat that is running this script is identified by the
CLAUDE_CODE_SESSION_ID environment variable and is excluded, so the
"previous chat" is the most recently modified remaining transcript for
this folder.

Usage:
    python resume.py                        # digest of the previous chat (default)
    python resume.py --list                 # list recent chats in this folder + topics
    python resume.py --session <id>         # digest a specific session id
    python resume.py --project-dir <path>   # target a different folder's chats
    python resume.py --full                 # also dump the full plain-text transcript to a file
"""
import argparse
import json
import os
import re
import sys
import time
from datetime import datetime
from pathlib import Path

# Windows consoles default to cp1252; transcripts hold emoji, arrows and CJK text.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

# Without CLAUDE_CODE_SESSION_ID, a transcript written to within this many
# seconds is assumed to be the live chat and skipped.
LIVE_WINDOW_SECONDS = 120


def encode_cwd(path: str) -> str:
    return re.sub(r"[^A-Za-z0-9]", "-", os.path.abspath(path))


def projects_root() -> Path:
    config_dir = os.environ.get("CLAUDE_CONFIG_DIR")
    base = Path(config_dir).expanduser() if config_dir else Path.home() / ".claude"
    return base / "projects"


def find_project_dir(cwd: str) -> Path:
    root = projects_root()
    enc = encode_cwd(cwd)
    exact = root / enc
    if exact.is_dir():
        return exact
    if not root.is_dir():
        raise SystemExit(f"No Claude Code transcripts found: {root} does not exist.")
    # Fallback: case-insensitive match, then longest-prefix match.
    cands = [d for d in root.iterdir() if d.is_dir()]
    for d in cands:
        if d.name.lower() == enc.lower():
            return d
    pref = [
        d for d in cands
        if enc.lower().startswith(d.name.lower()) or d.name.lower().startswith(enc.lower())
    ]
    if pref:
        best = max(pref, key=lambda d: len(d.name))
        print(
            f"note: no exact transcript folder for {os.path.abspath(cwd)}; "
            f"using closest match {best.name}",
            file=sys.stderr,
        )
        return best
    raise SystemExit(
        f"No transcript folder for this project.\n"
        f"  cwd     : {os.path.abspath(cwd)}\n"
        f"  expected: {exact}\n"
        f"Pass --project-dir <path> if you were working in a different folder."
    )


def iso_to_local(ts: str) -> str:
    if not ts:
        return "?"
    try:
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00")).astimezone()
        return dt.strftime("%Y-%m-%d %H:%M")
    except Exception:
        return ts


def text_of(msg) -> str:
    """Extract human/assistant text from a transcript message; '' for tool-only carriers."""
    if not isinstance(msg, dict):
        return ""
    c = msg.get("content")
    if isinstance(c, str):
        return c.strip()
    parts = []
    if isinstance(c, list):
        for b in c:
            if isinstance(b, dict) and b.get("type") == "text" and isinstance(b.get("text"), str):
                parts.append(b["text"])
    return "\n".join(parts).strip()


def is_noise(t: str) -> bool:
    """Skip tool results, hook injections, and system-reminder-only turns."""
    if not t:
        return True
    low = t.lstrip()
    if low.startswith("<system-reminder") or low.startswith("Caveat:"):
        return True
    if low.startswith("[Request interrupted"):
        return True
    return False


def load(path: Path):
    rows = []
    with open(path, encoding="utf-8", errors="replace") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except Exception:
                continue
    return rows


def session_topic(path: Path) -> str:
    for d in load(path):
        if d.get("type") == "user":
            t = text_of(d.get("message", {}))
            if not is_noise(t):
                return t.replace("\n", " ")[:120]
    return "(no user text)"


def list_sessions(pdir: Path, current: str):
    files = sorted(pdir.glob("*.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True)
    print(f"Recent chats in {pdir.name}:\n")
    for p in files[:15]:
        sid = p.stem
        tag = "  <-- CURRENT (live)" if sid == current else ""
        mt = datetime.fromtimestamp(p.stat().st_mtime).strftime("%Y-%m-%d %H:%M")
        print(f"  {mt}  {sid}{tag}")
        print(f"      {session_topic(p)}")


def pick_previous(pdir: Path, current: str) -> Path:
    files = sorted(
        (p for p in pdir.glob("*.jsonl") if p.stem != current),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    if not current and files and time.time() - files[0].stat().st_mtime < LIVE_WINDOW_SECONDS:
        print(
            f"note: CLAUDE_CODE_SESSION_ID is not set; skipping {files[0].stem} "
            f"because it was written in the last {LIVE_WINDOW_SECONDS}s and is likely this chat. "
            f"Use --list and --session to pick another.",
            file=sys.stderr,
        )
        files = files[1:]
    if not files:
        raise SystemExit("No previous chat found in this folder (only the current live session exists).")
    return files[0]


def digest(path: Path, full: bool):
    rows = load(path)
    msgs = [r for r in rows if r.get("type") in ("user", "assistant")]
    first_ts = next((r.get("timestamp") for r in rows if r.get("timestamp")), None)
    last_ts = next((r.get("timestamp") for r in reversed(rows) if r.get("timestamp")), None)

    user_turns = []
    convo = []  # (role, text) real text turns in order
    files_touched = set()
    for r in rows:
        typ = r.get("type")
        msg = r.get("message", {})
        if typ in ("user", "assistant"):
            t = text_of(msg)
            if not is_noise(t):
                convo.append((typ, t))
                if typ == "user":
                    user_turns.append(t)
        if typ == "assistant" and isinstance(msg.get("content"), list):
            for b in msg["content"]:
                if isinstance(b, dict) and b.get("type") == "tool_use":
                    inp = b.get("input") or {}
                    fp = inp.get("file_path")
                    if fp:
                        files_touched.add(fp)

    out = []
    out.append("=" * 70)
    out.append(f"PREVIOUS CHAT  ({path.stem})")
    out.append(f"file : {path}")
    out.append(f"when : {iso_to_local(first_ts)}  ->  {iso_to_local(last_ts)}")
    out.append(f"size : {len(msgs)} messages, {len(user_turns)} user turns")
    out.append("=" * 70)

    out.append("\n## GOAL (first user instruction)")
    out.append((user_turns[0] if user_turns else "(none)")[:900])

    if len(user_turns) > 1:
        out.append("\n## USER TURNS (the arc of what was asked)")
        for i, t in enumerate(user_turns, 1):
            out.append(f"{i:>2}. {t.replace(chr(10), ' ')[:220]}")

    out.append("\n## WHERE WE LEFT OFF (last exchanges)")
    tail = convo[-8:]
    for i, (role, t) in enumerate(tail):
        who = "USER" if role == "user" else "ASSISTANT"
        is_last_reply = role == "assistant" and i == len(tail) - 1
        out.append(f"\n[{who}] {t[:1600 if is_last_reply else 500]}")

    if files_touched:
        out.append("\n## FILES TOUCHED LAST CHAT")
        for f in sorted(files_touched)[:40]:
            out.append(f"  {f}")

    out.append("\n" + "-" * 70)
    if full:
        dump = path.with_name(path.stem + ".transcript.txt")
        with open(dump, "w", encoding="utf-8") as fh:
            for role, t in convo:
                fh.write(f"\n\n===== {'USER' if role == 'user' else 'ASSISTANT'} =====\n{t}")
        out.append(f"FULL transcript written to: {dump}")
    else:
        out.append("For the complete conversation, re-run with --full and read the dumped file.")
    print("\n".join(out))


def main():
    ap = argparse.ArgumentParser(
        description="Recover context from the previous Claude Code chat in this project folder."
    )
    ap.add_argument("--project-dir", default=os.getcwd(), help="folder whose chats to read (default: cwd)")
    ap.add_argument("--session", help="digest this session id instead of the previous chat")
    ap.add_argument("--list", action="store_true", help="list recent chats in the folder")
    ap.add_argument("--full", action="store_true", help="also write the full transcript to a .txt file")
    args = ap.parse_args()

    current = os.environ.get("CLAUDE_CODE_SESSION_ID", "")
    pdir = find_project_dir(args.project_dir)

    if args.list:
        list_sessions(pdir, current)
        return
    if args.session:
        target = pdir / f"{args.session}.jsonl"
        if not target.exists():
            raise SystemExit(f"No transcript {target}")
    else:
        target = pick_previous(pdir, current)
    digest(target, args.full)


if __name__ == "__main__":
    main()
