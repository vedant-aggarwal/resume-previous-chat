# resume-previous-chat

A Claude Code skill that picks up where your last chat in the same folder left off.

Claude Code writes every chat to disk as a JSONL transcript. When a chat ends before the work does (the context fills up, the app crashes, you close the window, or a web chat expires and you move to the CLI), open a new chat in the same folder and say "continue the previous chat". The skill finds the last transcript for that folder, skips the chat you are in now, and gives Claude a short digest: the original goal, every request you made, the last few exchanges, and the files it touched. Claude then carries on instead of starting over.

No dependencies beyond Python 3.8+. Works on Windows, macOS and Linux.

## Install

Clone it into your personal skills folder.

macOS / Linux:

```bash
git clone https://github.com/vedant-aggarwal/resume-previous-chat ~/.claude/skills/resume-previous-chat
```

Windows (PowerShell):

```powershell
git clone https://github.com/vedant-aggarwal/resume-previous-chat "$env:USERPROFILE\.claude\skills\resume-previous-chat"
```

To share it with everyone on a project instead, clone it into that project's `.claude/skills/` folder. Restart Claude Code or open a new chat so it picks up the skill.

## Use

In a new chat, in the same folder as the chat you lost, say any of:

- "continue the previous chat"
- "continue where we left off"
- "recover the context from my last chat"

If the lost chat ran in another folder, say which one, and Claude will pass `--project-dir`.

## Run the script yourself

```bash
python ~/.claude/skills/resume-previous-chat/resume.py            # digest of the previous chat
python ~/.claude/skills/resume-previous-chat/resume.py --list     # recent chats here and how each began
python ~/.claude/skills/resume-previous-chat/resume.py --session <uuid>
python ~/.claude/skills/resume-previous-chat/resume.py --project-dir "/path/to/folder"
python ~/.claude/skills/resume-previous-chat/resume.py --full     # also write the whole conversation to a .txt
```

Example digest:

```
======================================================================
PREVIOUS CHAT  (5f3c9e1a-...)
when : 2026-11-18 19:02  ->  2026-11-18 20:01
size : 84 messages, 6 user turns
======================================================================

## GOAL (first user instruction)
Build the login page for the dashboard...

## USER TURNS (the arc of what was asked)
 1. Build the login page for the dashboard...
 2. Now add a logout button
 ...

## WHERE WE LEFT OFF (last exchanges)
[USER] run the tests
[ASSISTANT] 2 of 14 tests fail in auth.test.ts...

## FILES TOUCHED LAST CHAT
  src/pages/login.tsx
  ...
```

## How it works

- Transcripts live in `~/.claude/projects/<encoded-cwd>/<session-id>.jsonl`, or under `$CLAUDE_CONFIG_DIR` if you set it. `<encoded-cwd>` is the folder path with every non-alphanumeric character turned into `-` (`/home/me/my-app` becomes `-home-me-my-app`).
- The live chat is excluded using `CLAUDE_CODE_SESSION_ID`. If that variable is missing, a transcript written in the last two minutes is assumed to be the live chat and skipped, with a note.
- Tool results, system reminders and interrupted-request markers are dropped, so the digest shows only what you and Claude said.
- `--full` writes `<session-id>.transcript.txt` next to the transcript, inside your Claude config folder.

Transcripts can contain anything you pasted into a chat. The script only reads them locally and prints to your terminal; nothing is sent anywhere.

## Tests

```bash
python -m unittest discover -s tests -v
```

## License

MIT
