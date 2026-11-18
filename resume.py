#!/usr/bin/env python3
"""Recover context from the previous Codex or Claude Code chat in the current folder.

Codex stores every chat as a JSONL rollout under
    $CODEX_HOME/sessions/YYYY/MM/DD/rollout-<time>-<thread-id>.jsonl   (default ~/.codex)
whose first record (session_meta) holds the chat's working folder (cwd).

Claude Code stores every chat as
    $CLAUDE_CONFIG_DIR/projects/<encoded-cwd>/<session-id>.jsonl      (default ~/.claude)
where <encoded-cwd> is the folder path with every non-alphanumeric
character replaced by '-'.

By default both are searched and the newest chat for this folder wins,
so a chat lost in one tool can be continued in the other. The live chat
is skipped using CODEX_THREAD_ID / CODEX_SESSION_ID / CLAUDE_CODE_SESSION_ID.

Usage:
    python resume.py                        # digest of the previous chat (default)
    python resume.py --list                 # recent chats in this folder, both tools
    python resume.py --source codex         # only Codex chats (or: claude)
    python resume.py --session <id>         # digest a specific chat id
    python resume.py --project-dir <path>   # target a different folder's chats
    python resume.py --full                 # also dump the full plain-text transcript to a file
"""
import argparse
import json
import os
import re
import sys
import tempfile
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

# With no live-chat id in the environment, a chat written to within this
# many seconds is assumed to be the live one and skipped.
LIVE_WINDOW_SECONDS = 120
# apply_patch headers, either raw or inside an escaped string ("\\n" line ends, "\\\\" separators).
PATCH_FILE_RE = re.compile(r"\*\*\* (?:Add|Update|Delete) File: (.+?)(?:\\n|\\r|[\n\r\"]|$)")


@dataclass
class Chat:
    source: str  # "codex" or "claude"
    id: str
    path: Path

    @property
    def mtime(self) -> float:
        return self.path.stat().st_mtime


# ---------------------------------------------------------------- locations

def claude_projects_root() -> Path:
    base = os.environ.get("CLAUDE_CONFIG_DIR")
    return (Path(base).expanduser() if base else Path.home() / ".claude") / "projects"


def codex_home() -> Path:
    base = os.environ.get("CODEX_HOME")
    return Path(base).expanduser() if base else Path.home() / ".codex"


def live_ids() -> set:
    names = ("CODEX_THREAD_ID", "CODEX_SESSION_ID", "CLAUDE_CODE_SESSION_ID")
    return {os.environ[n] for n in names if os.environ.get(n)}


def norm(path: str) -> set:
    """Comparable forms of a folder path (as given and with symlinks resolved)."""
    return {
        os.path.normcase(os.path.abspath(path)).rstrip("\\/"),
        os.path.normcase(os.path.realpath(path)).rstrip("\\/"),
    }


def encode_cwd(path: str) -> str:
    return re.sub(r"[^A-Za-z0-9]", "-", os.path.abspath(path))


# ---------------------------------------------------------------- discovery

def claude_chats(project_dir: str) -> list:
    root = claude_projects_root()
    if not root.is_dir():
        return []
    wanted = {encode_cwd(project_dir).lower(), encode_cwd(os.path.realpath(project_dir)).lower()}
    folders = [d for d in root.iterdir() if d.is_dir() and d.name.lower() in wanted]
    return [Chat("claude", p.stem, p) for d in folders for p in d.glob("*.jsonl")]


def codex_meta(path: Path) -> dict:
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            first = json.loads(fh.readline())
        if first.get("type") == "session_meta":
            return first.get("payload") or {}
    except Exception:
        pass
    return {}


def codex_rollouts(include_archived: bool):
    home = codex_home()
    dirs = [home / "sessions"] + ([home / "archived_sessions"] if include_archived else [])
    for d in dirs:
        if d.is_dir():
            yield from d.rglob("rollout-*.jsonl")


def codex_chats(project_dir: str) -> list:
    wanted = norm(project_dir)
    chats = []
    for p in codex_rollouts(include_archived=False):
        meta = codex_meta(p)
        cwd = meta.get("cwd")
        if cwd and norm(cwd) & wanted:
            chats.append(Chat("codex", meta.get("id") or p.stem[-36:], p))
    return chats


def gather(project_dir: str, source: str) -> list:
    chats = []
    if source in ("auto", "codex"):
        chats += codex_chats(project_dir)
    if source in ("auto", "claude"):
        chats += claude_chats(project_dir)
    return sorted(chats, key=lambda c: c.mtime, reverse=True)


def find_session(session_id: str, project_dir: str) -> Chat:
    for c in claude_chats(project_dir):
        if c.id == session_id:
            return c
    root = claude_projects_root()
    if root.is_dir():
        for p in root.glob(f"*/{session_id}.jsonl"):
            return Chat("claude", session_id, p)
    for p in codex_rollouts(include_archived=True):
        if p.stem.endswith(session_id):
            return Chat("codex", session_id, p)
    raise SystemExit(f"No Codex or Claude Code chat with id {session_id}")


def pick_previous(chats: list) -> Chat:
    live = live_ids()
    rest = [c for c in chats if c.id not in live]
    if not live and rest and time.time() - rest[0].mtime < LIVE_WINDOW_SECONDS:
        print(
            f"note: no live chat id in the environment; skipping {rest[0].source} chat {rest[0].id} "
            f"because it was written in the last {LIVE_WINDOW_SECONDS}s and is likely this chat. "
            f"Use --list and --session to pick another.",
            file=sys.stderr,
        )
        rest = rest[1:]
    if not rest:
        raise SystemExit("No previous chat found for this folder (only the live chat exists).")
    return rest[0]


# ---------------------------------------------------------------- parsing

def load(path: Path):
    with open(path, encoding="utf-8", errors="replace") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except Exception:
                continue


def is_noise(t: str) -> bool:
    low = t.lstrip()
    return (
        not low
        or low.startswith("<")  # <system-reminder>, <environment_context>, <user_instructions> ...
        or low.startswith("Caveat:")
        or low.startswith("[Request interrupted")
        or low.startswith("# AGENTS.md instructions")
    )


def parse_claude(path: Path):
    turns, files, stamps = [], set(), []
    for r in load(path):
        if r.get("timestamp"):
            stamps.append(r["timestamp"])
        typ, msg = r.get("type"), r.get("message") or {}
        if typ not in ("user", "assistant") or not isinstance(msg, dict):
            continue
        c = msg.get("content")
        if isinstance(c, str):
            text = c.strip()
        elif isinstance(c, list):
            text = "\n".join(
                b["text"] for b in c
                if isinstance(b, dict) and b.get("type") == "text" and isinstance(b.get("text"), str)
            ).strip()
            if typ == "assistant":
                for b in c:
                    if isinstance(b, dict) and b.get("type") == "tool_use":
                        fp = (b.get("input") or {}).get("file_path")
                        if fp:
                            files.add(fp)
        else:
            text = ""
        if not is_noise(text):
            turns.append((typ, text))
    return turns, files, stamps


def parse_codex(path: Path):
    turns, files, stamps = [], set(), []
    for r in load(path):
        if r.get("timestamp"):
            stamps.append(r["timestamp"])
        if r.get("type") != "response_item":
            continue
        p = r.get("payload") or {}
        kind = p.get("type")
        if kind == "message" and p.get("role") in ("user", "assistant"):
            parts = [
                b.get("text", "") for b in p.get("content") or []
                if isinstance(b, dict) and b.get("type") in ("input_text", "output_text")
            ]
            text = "\n".join(t for t in parts if not is_noise(t)).strip()
            if text:
                turns.append((p["role"], text))
        elif kind in ("custom_tool_call", "function_call"):
            blob = p.get("input") or p.get("arguments") or ""
            if isinstance(blob, str):
                files.update(m.replace("\\\\", "\\").strip() for m in PATCH_FILE_RE.findall(blob))
    return turns, files, stamps


# ---------------------------------------------------------------- output

def iso_to_local(ts) -> str:
    if not ts:
        return "?"
    try:
        return datetime.fromisoformat(str(ts).replace("Z", "+00:00")).astimezone().strftime("%Y-%m-%d %H:%M")
    except Exception:
        return str(ts)


def topic(chat: Chat) -> str:
    parse = parse_codex if chat.source == "codex" else parse_claude
    turns, _, _ = parse(chat.path)
    first = next((t for role, t in turns if role == "user"), "(no user text)")
    return first.replace("\n", " ")[:120]


def list_chats(chats: list, project_dir: str):
    live = live_ids()
    print(f"Recent chats for {os.path.abspath(project_dir)}:\n")
    if not chats:
        print("  (none)")
    for c in chats[:15]:
        tag = "  <-- CURRENT (live)" if c.id in live else ""
        mt = datetime.fromtimestamp(c.mtime).strftime("%Y-%m-%d %H:%M")
        print(f"  {mt}  [{c.source}] {c.id}{tag}")
        print(f"      {topic(c)}")


def digest(chat: Chat, full: bool):
    parse = parse_codex if chat.source == "codex" else parse_claude
    turns, files, stamps = parse(chat.path)
    user_turns = [t for role, t in turns if role == "user"]
    tool = "CODEX" if chat.source == "codex" else "CLAUDE CODE"

    out = ["=" * 70, f"PREVIOUS {tool} CHAT  ({chat.id})", f"file : {chat.path}"]
    out.append(f"when : {iso_to_local(stamps[0] if stamps else None)}  ->  {iso_to_local(stamps[-1] if stamps else None)}")
    out.append(f"size : {len(turns)} text messages, {len(user_turns)} user turns")
    out.append("=" * 70)

    out.append("\n## GOAL (first user instruction)")
    out.append((user_turns[0] if user_turns else "(none)")[:900])

    if len(user_turns) > 1:
        out.append("\n## USER TURNS (the arc of what was asked)")
        for i, t in enumerate(user_turns, 1):
            out.append(f"{i:>2}. {t.replace(chr(10), ' ')[:220]}")

    out.append("\n## WHERE WE LEFT OFF (last exchanges)")
    tail = turns[-8:]
    for i, (role, t) in enumerate(tail):
        who = "USER" if role == "user" else "ASSISTANT"
        last_reply = role == "assistant" and i == len(tail) - 1
        out.append(f"\n[{who}] {t[:1600 if last_reply else 500]}")

    if files:
        out.append("\n## FILES TOUCHED LAST CHAT")
        out.extend(f"  {f}" for f in sorted(files)[:40])

    out.append("\n" + "-" * 70)
    if full:
        # Codex scans its sessions folder, so keep dumps out of it.
        folder = Path(tempfile.gettempdir()) if chat.source == "codex" else chat.path.parent
        dump = folder / f"{chat.id}.transcript.txt"
        with open(dump, "w", encoding="utf-8") as fh:
            for role, t in turns:
                fh.write(f"\n\n===== {'USER' if role == 'user' else 'ASSISTANT'} =====\n{t}")
        out.append(f"FULL transcript written to: {dump}")
    else:
        out.append("For the complete conversation, re-run with --full and read the dumped file.")
    print("\n".join(out))


def main():
    ap = argparse.ArgumentParser(description="Recover the previous Codex or Claude Code chat in this folder.")
    ap.add_argument("--project-dir", default=os.getcwd(), help="folder whose chats to read (default: cwd)")
    ap.add_argument("--source", choices=("auto", "codex", "claude"), default="auto",
                    help="which tool's chats to search (default: both, newest wins)")
    ap.add_argument("--session", help="digest this chat id instead of the previous chat")
    ap.add_argument("--list", action="store_true", help="list recent chats for the folder")
    ap.add_argument("--full", action="store_true", help="also write the full transcript to a .txt file")
    args = ap.parse_args()

    if args.session:
        digest(find_session(args.session, args.project_dir), args.full)
        return
    chats = gather(args.project_dir, args.source)
    if args.list:
        list_chats(chats, args.project_dir)
        return
    if not chats:
        raise SystemExit(
            f"No Codex or Claude Code chats found for {os.path.abspath(args.project_dir)}.\n"
            f"Pass --project-dir <path> if you were working in a different folder, or --list to check."
        )
    digest(pick_previous(chats), args.full)


if __name__ == "__main__":
    main()
