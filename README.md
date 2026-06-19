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

For selected `--thread-id` migrations, the helper now removes those projectless markers and sets a workspace-root hint to the target project.
If Codex is open, it can rewrite `.codex-global-state.json` from memory, so use `--wait-for-codex-exit` and close all Codex windows before expecting the sidebar to update.

## Script Usage

The skill includes a deterministic helper script:

```powershell
python scripts/migrate_codex_project_path.py --old "C:\Old\Project" --new "C:\New\Project"
```

Remap selected chats only:

```powershell
python scripts/migrate_codex_project_path.py --old "C:\Old\Project" --new "C:\New\Project" --thread-id 019e... --thread-id 019e...
```

If Codex Desktop keeps restoring the old sidebar path from memory, close Codex and run:

```powershell
python scripts/migrate_codex_project_path.py --old "C:\Old\Project" --new "C:\New\Project" --wait-for-codex-exit 1200
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
- If the Codex Desktop UI is open, it may rewrite the saved project registry from memory. Close all Codex windows before the final migration if the sidebar still shows the old path.
- This tool intentionally does not touch project contents.

## Repository Layout

```text
.
|-- SKILL.md
|-- agents/
|   `-- openai.yaml
`-- scripts/
    `-- migrate_codex_project_path.py
```
