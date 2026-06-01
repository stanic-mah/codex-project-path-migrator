---
name: codex-project-path-migrator
description: Use when a user wants to change, remap, migrate, or update a saved Codex project/workspace folder path while keeping existing Codex chat history/conversations attached to the project. This skill updates Codex metadata only, including saved project registry files, thread database cwd values, and session JSONL path references. It must not copy, sync, merge, move, or delete project files between the old and new paths.
metadata:
  short-description: Remap Codex project paths without syncing files
---

# Codex Project Path Migrator

Use this skill to update Codex Desktop metadata when a project folder moved or was renamed, while preserving chat history under the new saved project path.

## Scope

This skill is metadata-only.

- Do update Codex saved project roots, thread database `cwd` values, and affected session JSONL path references.
- Do preserve chat history and session file format.
- Do create backups before editing Codex metadata.
- Do not copy, sync, merge, move, or delete user project files.
- Do not treat the old folder as the source of truth for project contents.

## Inputs

Collect:

- Old project path.
- New project path.
- Which chats to remap: either all chats whose `cwd` matches the old path, or specific thread IDs/titles.

If the user asks to move only selected conversations, resolve their exact thread IDs before changing the database.

## Main Workflow

1. Verify the new path is the intended saved project path. Do not sync files even if the folder contents differ.
2. Locate Codex metadata:
   - `CODEX_HOME`, usually `%USERPROFILE%\.codex`.
   - Saved project registry: `.codex-global-state.json` and `.codex-global-state.json.bak`.
   - Thread database: usually `state_5.sqlite`, or the newest `state_*.sqlite`.
   - Session files referenced by `threads.rollout_path`.
3. Prefer the bundled script:
   - `scripts/migrate_codex_project_path.py`
4. Back up all edited metadata files with a timestamp.
5. Update saved project registry arrays such as:
   - `electron-saved-workspace-roots`
   - `project-order`
   - `active-workspace-roots`
   - `thread-workspace-root-hints`
6. Update matching `threads.cwd` rows to the new long Windows path form, for example `\\?\C:\New\Project`.
7. Update affected session JSONL files by replacing the old path with the new path, including JSON-escaped path forms.
8. Write session JSONL files as UTF-8 without BOM. The first bytes must remain the first JSON session metadata line, not a UTF-8 marker.
9. Verify:
   - The new path appears in saved project roots.
   - The old path no longer appears in saved project roots.
   - The remapped thread rows have the new `cwd`.
   - Each edited session file starts with a `session_meta` JSON line.
   - `codex_app.list_threads` can find the remapped conversations under the new path.

## Running The Script

Use a Python runtime available in the current environment. In Codex Desktop, `codex_app.load_workspace_dependencies` can reveal the bundled Python executable.

Example for all chats under the old path:

```powershell
python scripts/migrate_codex_project_path.py --old "C:\Old\Project" --new "C:\New\Project"
```

Example for selected chats only:

```powershell
python scripts/migrate_codex_project_path.py --old "C:\Old\Project" --new "C:\New\Project" --thread-id 019e... --thread-id 019e...
```

If Codex Desktop keeps restoring the old project path in the sidebar, run the script after Codex is fully closed, or launch it with a wait period:

```powershell
python scripts/migrate_codex_project_path.py --old "C:\Old\Project" --new "C:\New\Project" --wait-for-codex-exit 1200
```

The wait option applies the migration only after no `Codex.exe` UI process remains, up to the given number of seconds.

## Important Pitfalls

- PowerShell 5.1 `Set-Content -Encoding UTF8` can write a UTF-8 BOM. Do not use it for session JSONL files.
- Update both `.codex-global-state.json` and `.codex-global-state.json.bak`; otherwise Codex may restore the old path.
- A running Codex Desktop window can rewrite the saved project registry from memory. If the UI still shows the old tooltip, close all Codex windows and rerun or use the wait option.
- Do not use destructive Git or filesystem commands for this task.
- Do not copy project files unless the user makes a separate explicit request after this path-only migration.
