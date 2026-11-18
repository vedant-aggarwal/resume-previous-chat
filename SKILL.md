---
name: resume-previous-chat
description: Use when the user says "continue the previous chat", "continue where we left off", "recover the context", "my chat expired", "I lost that conversation", "reuse that skill from last time", or opens a fresh Claude Code chat to keep working on something started in a chat that is now gone. Recovers the prior session's context from Claude Code's on-disk transcripts for the current project folder so work continues without starting over.
---

# Resume Previous Chat

## Overview

Chats end: a context window fills up, a session crashes, a web chat expires, or a message gets lost. Claude Code saves every chat in a project folder to disk as a transcript, so the previous chat's context can be recovered. This skill loads it and continues the work.

**Core rule:** the chat to recover is the most recent one **in the project folder you are in now**. If the user was working in a different folder, they will say so. Then target that folder or session explicitly.

## Where the chats are stored

- Path: `~/.claude/projects/<encoded-cwd>/<session-uuid>.jsonl` (or `$CLAUDE_CONFIG_DIR/projects/...` when that variable is set).
- `<encoded-cwd>` is the absolute working directory with every non-alphanumeric character replaced by `-`.
  - `C:\Users\me\my-app` → `C--Users-me-my-app`
  - `/home/me/my-app` → `-home-me-my-app`
- The **live chat** (the one running this skill) is the file named `$CLAUDE_CODE_SESSION_ID.jsonl`. Exclude it: the "previous chat" is the newest transcript that is not the current session.
- Each `.jsonl` holds one record per line. `type: user` and `type: assistant` records carry the conversation (`message.content` is a string or a list of `{type: "text" | "tool_use", ...}` blocks). `type: user` records that hold only `tool_result` blocks are tool output, not user turns.

The helper script `resume.py` in this skill folder handles all of this. Do not rebuild it by hand.

## Procedure

1. Run the digest from the current project folder:
   ```
   python ~/.claude/skills/resume-previous-chat/resume.py
   ```
   (Use the path where this skill is installed if it differs.)
2. Read the digest: the GOAL, the arc of user turns, WHERE WE LEFT OFF, and the files touched.
3. If you need the whole conversation rather than the tail, re-run with `--full` and read the dumped `.transcript.txt`.
4. Tell the user in one short message what the previous chat was doing, how far it got, and the next step. Then continue that work. Do not restart from zero.

## Different folder or wrong chat

- User names a different folder → `--project-dir "<absolute path>"`.
- Unsure which chat, or the user wants a specific one → `--list` shows recent chats and their opening request, then `--session <uuid>`.
- The current-folder assumption is the default. Override it only when the user corrects it.

## Quick reference

| Need | Arguments after `python resume.py` |
| --- | --- |
| Digest of the previous chat (default) | *(none)* |
| List recent chats and topics here | `--list` |
| A specific chat | `--session <uuid>` |
| Another folder's chats | `--project-dir "/path/to/folder"` |
| Dump the full transcript to a file | `--full` |

## Common mistakes

- **Recovering the live chat itself.** Always exclude `$CLAUDE_CODE_SESSION_ID`. The script does this, so don't hand-pick the newest file.
- **Passing an MSYS `/c/...` path to native Windows Python.** The script works out its own paths. Run it from the project folder and it finds the right transcript folder.
- **Reading the raw JSONL.** Transcripts often run to tens of megabytes. Use the digest, and `--full` only when you need the whole thread.
- **Assuming the last-discussed project.** Recovery is keyed to the current folder, not to conversational memory.
