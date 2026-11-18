---
name: resume-previous-chat
description: Use when the user says "continue the previous chat", "continue where we left off", "recover the context", "my chat expired", "I lost that conversation", "reuse that skill from last time", or opens a fresh chat to keep working on something started in a chat that is now gone. Recovers the previous Claude Code or Codex chat for the current project folder from their on-disk transcripts so work picks up where it stopped.
---

# Resume Previous Chat

## Overview

Chats end: a context window fills up, a session crashes, a web chat expires, or a message gets lost. Claude Code and Codex both save every chat to disk, so the previous chat's context can be recovered, even when the lost chat ran in the other tool. This skill loads it and continues the work.

**Core rule:** the chat to recover is the most recent one **in the project folder you are in now**, from either tool. If the user was working in a different folder, they will say so. Then target that folder or chat explicitly.

## Where the chats are stored

- **Claude Code:** `~/.claude/projects/<encoded-cwd>/<session-id>.jsonl` (`$CLAUDE_CONFIG_DIR` overrides `~/.claude`). `<encoded-cwd>` is the absolute folder path with every non-alphanumeric character replaced by `-`: `C:\Users\me\my-app` → `C--Users-me-my-app`, `/home/me/my-app` → `-home-me-my-app`.
- **Codex:** `~/.codex/sessions/YYYY/MM/DD/rollout-<time>-<thread-id>.jsonl` (`$CODEX_HOME` overrides `~/.codex`). The first record is `session_meta`, whose `payload.cwd` is the chat's folder. Conversation text is in `response_item` records with `payload.type == "message"`. User messages that start with `<` (environment blocks, automation prompts) or `# AGENTS.md instructions` are injected context, not the user.
- **The live chat** (the one running this skill) is excluded by id: `CLAUDE_CODE_SESSION_ID` in Claude Code, `CODEX_THREAD_ID` or `CODEX_SESSION_ID` in Codex. If none is set, a chat written in the last 2 minutes is treated as live and skipped.

The helper script `resume.py` in this skill folder handles all of this. Do not rebuild it by hand.

## Procedure

1. Run the digest from the current project folder, using the folder this skill is installed in:
   ```
   python ~/.claude/skills/resume-previous-chat/resume.py     # Claude Code install
   python ~/.agents/skills/resume-previous-chat/resume.py     # Codex install
   ```
2. Read the digest: which tool the chat ran in, the GOAL, the arc of user turns, WHERE WE LEFT OFF, and the files touched.
3. If you need the whole conversation rather than the tail, re-run with `--full` and read the dumped `.transcript.txt`.
4. Tell the user in one short message what the previous chat was doing, how far it got, and the next step. Then continue that work. Do not restart from zero.

## Different folder, tool or chat

- User names a different folder → `--project-dir "<absolute path>"`.
- Only one tool's chats → `--source claude` or `--source codex`. The default searches both and the newest wins.
- Unsure which chat, or the user wants a specific one → `--list` shows recent chats from both tools and their opening request, then `--session <id>`.

## Quick reference

| Need | Arguments after `python resume.py` |
| --- | --- |
| Digest of the previous chat (default) | *(none)* |
| List recent chats here, both tools | `--list` |
| Only Claude Code / only Codex | `--source claude` / `--source codex` |
| A specific chat | `--session <id>` |
| Another folder's chats | `--project-dir "/path/to/folder"` |
| Dump the full transcript to a file | `--full` |

## Common mistakes

- **Recovering the live chat itself.** The script skips it by id. Don't hand-pick the newest file.
- **Passing an MSYS `/c/...` path to native Windows Python.** The script works out its own paths. Run it from the project folder.
- **Reading the raw JSONL.** Transcripts often run to tens of megabytes. Use the digest, and `--full` only when you need the whole thread.
- **Assuming the last-discussed project.** Recovery is keyed to the current folder, not to conversational memory.
