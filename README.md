# resume-previous-chat

An agent skill for Claude Code and Codex that picks up where your last chat in the same folder left off.

Both tools write every chat to disk as a JSONL transcript. When a chat ends before the work does (the context fills up, the app crashes, you close the window, or a web chat expires and you move to the CLI), open a new chat in the same folder and say "continue the previous chat". The skill finds the newest chat for that folder in either tool, skips the chat you are in now, and gives the agent a short digest: the original goal, every request you made, the last few exchanges, and the files it touched. The agent then carries on instead of starting over.

Because it reads both tools, a chat you lost in Claude Code can be continued in Codex, and the other way round.

No dependencies beyond Python 3.8+. Works on Windows, macOS and Linux.

## Install

Clone it into the skills folder of the tool you use. Install it in both if you use both.

Claude Code, macOS / Linux:

```bash
git clone https://github.com/vedant-aggarwal/resume-previous-chat ~/.claude/skills/resume-previous-chat
```

Claude Code, Windows (PowerShell):

```powershell
git clone https://github.com/vedant-aggarwal/resume-previous-chat "$env:USERPROFILE\.claude\skills\resume-previous-chat"
```

Codex, macOS / Linux:

```bash
git clone https://github.com/vedant-aggarwal/resume-previous-chat ~/.agents/skills/resume-previous-chat
```

Codex, Windows (PowerShell):

```powershell
git clone https://github.com/vedant-aggarwal/resume-previous-chat "$env:USERPROFILE\.agents\skills\resume-previous-chat"
```

Open a new chat afterwards so the tool picks up the skill.

## Use

In a new chat, in the same folder as the chat you lost, say any of:

- "continue the previous chat"
- "continue where we left off"
- "recover the context from my last chat"

If the lost chat ran in another folder, say which one, and the agent will pass `--project-dir`. If you only want chats from one tool, say so, and it will pass `--source claude` or `--source codex`.

## Run the script yourself

```bash
python resume.py                          # digest of the previous chat, either tool
python resume.py --list                   # recent chats here from both tools, and how each began
python resume.py --source codex           # only Codex chats (or: claude)
python resume.py --session <id>
python resume.py --project-dir "/path/to/folder"
python resume.py --full                   # also write the whole conversation to a .txt
```

Example digest:

```
======================================================================
PREVIOUS CODEX CHAT  (5f3c9e1a-...)
when : 2026-11-18 19:02  ->  2026-11-18 20:01
size : 84 text messages, 6 user turns
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

- **Claude Code** transcripts live in `~/.claude/projects/<encoded-cwd>/<session-id>.jsonl`, or under `$CLAUDE_CONFIG_DIR`. `<encoded-cwd>` is the folder path with every non-alphanumeric character turned into `-` (`/home/me/my-app` becomes `-home-me-my-app`).
- **Codex** rollouts live in `~/.codex/sessions/YYYY/MM/DD/rollout-*.jsonl`, or under `$CODEX_HOME`. The first record of each holds the folder the chat ran in. Rollouts from older Codex versions that don't record a folder are skipped.
- The live chat is excluded using `CLAUDE_CODE_SESSION_ID`, `CODEX_THREAD_ID` or `CODEX_SESSION_ID`. If none is set, a chat written in the last two minutes is assumed to be the live one and skipped, with a note.
- Tool output, system reminders, environment blocks and automation prompts are dropped, so the digest shows only what you and the agent said.
- `--full` writes `<id>.transcript.txt` next to a Claude Code transcript, or to your temp folder for a Codex chat so nothing extra lands in `~/.codex/sessions`.

Transcripts can contain anything you pasted into a chat. The script only reads them locally and prints to your terminal; nothing is sent anywhere.

## Tests

```bash
python -m unittest discover -s tests -v
```

## License

MIT
