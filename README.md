# Codex Project Path Migrator

A Codex skill and helper script for moving Codex Desktop chat history between project folders, including moving standalone/global **Chats** into a saved project folder.

This is a metadata repair tool. It updates Codex's saved project registry, thread database rows, session JSONL path references, and sidebar classification state. It does not copy, sync, merge, move, or delete project files.

Use it when Codex shows a conversation in the wrong place, for example:

- A project folder was renamed or moved.
- Existing project chats disappeared after changing paths.
- A chat still appears under global **Chats** when it should live under a project.

## What It Does

- Updates Codex saved project registry entries.
- Remaps matching chat/thread records to the new project path.
- Updates affected session JSONL path references.
- Moves selected chats out of Codex's projectless/global chat sidebar state.
- Preserves chat history format so conversations still load.
- Creates timestamped backups before editing Codex metadata.
- Verifies that remapped chats point to the new path.
- Queues a detached, restart-safe repair when Codex must be closed before the final write.

## When To Use It

Use this when:

- A Codex project folder was renamed or moved.
- Codex Desktop still shows the old folder path in the sidebar.
- Existing chats disappeared from the project after changing paths.
- A chat still appears under global **Chats** even after its `cwd` points to the project.
- You want to keep chat history but only update paths.

Do not use this to synchronize project files. File copying is intentionally out of scope.

## Install

From Codex, you can ask:

```text
install skill: stanic-mah/codex-project-path-migrator
```

Or manually copy this repository folder to:

```text
%USERPROFILE%\.codex\skills\codex-project-path-migrator
```

## Usage In Codex

Example prompt:

```text
Use $codex-project-path-migrator to update my Codex project path from
C:\Old\Project
to
C:\New\Project
while keeping the existing chat history.
Do not sync files.
```

For selected conversations, include the chat titles or thread IDs:

```text
Use $codex-project-path-migrator to remap only these thread IDs from C:\Old\Project to C:\New\Project:
019e...
019e...
Do not copy files.
```

## Global Chat To Project Notes

Moving a standalone Codex chat into a project needs more than changing the thread database `cwd`.
In a real migration, the thread still appeared under global **Chats** after these fields were already correct:

- `threads.cwd` in `state_5.sqlite`
- `session_meta.cwd` and `turn_context.cwd` in the session JSONL
- `thread-workspace-root-hints` in `.codex-global-state.json`

The missing sidebar state was:

- `projectless-thread-ids`, which explicitly keeps a thread under global **Chats**
- `thread-projectless-output-directories`, which can keep stale output-folder metadata tied to the old disposable chat workspace

For selected `--thread-id` migrations, the helper removes those projectless markers and sets a workspace-root hint to the target project.

There is a second failure mode: an immediate migration can pass verification, then Codex can restore the projectless values during shutdown or the next startup. A correct `cwd` is not enough—after restart, the thread must also have the target project's non-null `projectId`.

Use the built-in detached mode from an active Codex task:

```powershell
python scripts/migrate_codex_project_path.py `
  --old "C:\Old\StandaloneChatWorkspace" `
  --new "C:\New\Project" `
  --thread-id 019e... `
  --background `
  --wait-for-codex-exit 1200 `
  --json
```

The command returns immediately with a PID and log paths. Close all Codex windows, leave the app closed for at least 10 seconds, and reopen it. The helper waits until `Codex.exe` has remained absent for 5 seconds before writing. It launches with a real argument vector, so project paths containing spaces are preserved without hand-written `Start-Process` quoting.

## Script Usage

The skill includes a deterministic helper script:

```powershell
python scripts/migrate_codex_project_path.py --old "C:\Old\Project" --new "C:\New\Project"
```

Remap selected chats only:

```powershell
python scripts/migrate_codex_project_path.py --old "C:\Old\Project" --new "C:\New\Project" --thread-id 019e... --thread-id 019e...
```

If Codex Desktop keeps restoring the old sidebar path from memory, queue the repair while Codex is open:

```powershell
python scripts/migrate_codex_project_path.py --old "C:\Old\Project" --new "C:\New\Project" --thread-id 019e... --background --wait-for-codex-exit 1200 --json
```

Optional controls:

```text
--log-dir PATH                     detached helper log directory
--codex-exit-stable-seconds N      stable-close interval; default 5
```

Preview changes without writing:

```powershell
python scripts/migrate_codex_project_path.py --old "C:\Old\Project" --new "C:\New\Project" --dry-run
```

## Safety Notes

- The script edits Codex metadata under `%USERPROFILE%\.codex`.
- It backs up changed metadata files before writing.
- It writes session JSONL files as UTF-8 without BOM, because Codex expects the first byte to be the JSON session metadata line.
- It removes selected migrated threads from `projectless-thread-ids` and `thread-projectless-output-directories` so they can appear under the target project.
- If Codex Desktop is open, a foreground write emits a warning because the app may restore projectless state.
- For global-chat repairs, use `--background --wait-for-codex-exit`; do not rely on an immediate live-app verification.
- Detached `--json` output stays machine-readable in the output log; waiting progress is written to the error log.
- The helper updates Windows backslash, JSON-escaped, and forward-slash path references in session history.
- This tool intentionally does not touch project contents.

## Repository Layout

```text
.
|-- SKILL.md
|-- agents/
|   `-- openai.yaml
|-- tests/
|   `-- test_migrate_codex_project_path.py
`-- scripts/
    `-- migrate_codex_project_path.py
```
