# Codex Project Path Migrator

A Codex skill for updating a saved Codex Desktop project folder path while keeping the existing chat history attached to that project.

This skill is for path metadata only. It does not copy, sync, merge, move, or delete files between the old and new project folders.

## What It Does

- Updates Codex saved project registry entries.
- Remaps matching chat/thread records to the new project path.
- Updates affected session JSONL path references.
- Preserves chat history format so conversations still load.
- Creates timestamped backups before editing Codex metadata.
- Verifies that remapped chats point to the new path.

## When To Use It

Use this when:

- A Codex project folder was renamed or moved.
- Codex Desktop still shows the old folder path in the sidebar.
- Existing chats disappeared from the project after changing paths.
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
- If the Codex Desktop UI is open, it may rewrite the saved project registry from memory. Close all Codex windows before the final migration if the sidebar still shows the old path.
- This tool intentionally does not touch project contents.

## Repository Layout

```text
.
├── SKILL.md
├── agents/
│   └── openai.yaml
└── scripts/
    └── migrate_codex_project_path.py
```
