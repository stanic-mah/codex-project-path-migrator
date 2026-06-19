---
name: codex-project-path-migrator
description: Use when a user wants to change, remap, migrate, or update a saved Codex project/workspace folder path while keeping existing Codex chat history/conversations attached to the project. This skill updates Codex metadata only, including saved project registry files, thread database cwd values, session JSONL path references, and projectless/global chat sidebar state. It must not copy, sync, merge, move, or delete project files between the old and new paths.
metadata:
  short-description: Remap Codex project paths without syncing files
---

# Codex Project Path Migrator

Use this skill to update Codex Desktop metadata when a project folder moved or was renamed, or when an existing standalone/global chat should be shown under a saved project, while preserving chat history under the new project path.

## Scope

This skill is metadata-only.

- Do update Codex saved project roots, thread database `cwd` values, affected session JSONL path references, and project sidebar metadata.
- Do preserve chat history and session file format.
- Do create backups before editing Codex metadata.
- Do remove selected migrated chats from Codex's projectless/global chat sidebar state.
- Do not copy, sync, merge, move, or delete user project files.
- Do not treat the old folder as the source of truth for project contents.

## Inputs

Collect:

- Old project path or disposable standalone chat workspace path.
- New project path.
- Which chats to remap: either all chats whose `cwd` matches the old path, or specific thread IDs/titles.

If the user asks to move only selected conversations or move a global **Chats** item into a project, resolve the exact thread IDs before changing the database. A global-chat-to-project move should usually be a selected-thread migration, not a broad old-path migration.

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
5. Update saved project registry values such as:
   - `electron-saved-workspace-roots`
   - `project-order`
   - `active-workspace-roots`
   - `thread-workspace-root-hints`
6. For selected migrated threads, also update project/sidebar classification:
   - Set `thread-workspace-root-hints[thread_id]` to the new project path.
   - Remove `thread_id` from `projectless-thread-ids`.
   - Remove `thread_id` from `thread-projectless-output-directories`.
7. Update matching `threads.cwd` rows to the new long Windows path form, for example `\\?\C:\New\Project`.
8. Update affected session JSONL files by replacing the old path with the new path, including JSON-escaped path forms.
9. Write session JSONL files as UTF-8 without BOM. The first bytes must remain the first JSON session metadata line, not a UTF-8 marker.
10. Verify:
   - The new path appears in saved project roots or already exists as the target saved project.
   - The old path no longer appears in saved project roots when this is a path replacement.
   - The remapped thread rows have the new `cwd`.
   - Each edited session file starts with a `session_meta` JSON line.
   - Selected migrated threads are absent from `projectless-thread-ids`.
   - Selected migrated threads are absent from `thread-projectless-output-directories`.
   - `thread-workspace-root-hints[thread_id]` points to the new project path.
   - `codex_app.list_threads` can find the remapped conversations under the new path.

## Experience Notes: Global Chat To Project

In a real migration, changing `threads.cwd`, session JSONL `cwd` values, and `thread-workspace-root-hints` was not enough. The Codex app correctly reported the thread's `cwd` as the project path, but the sidebar still showed the conversation under global **Chats**.

The hidden cause was explicit projectless state in `.codex-global-state.json`:

- `projectless-thread-ids` still contained the thread IDs.
- `thread-projectless-output-directories` still mapped those thread IDs to the old disposable chat workspace.

After removing those projectless entries and keeping `thread-workspace-root-hints` pointed at the project, the chat appeared under the project folder. Because the running Codex Desktop app can rewrite `.codex-global-state.json` from memory, the successful repair had to run after all Codex windows were closed.

Do not keep repeating database edits when `codex_app.list_threads` already reports the correct project `cwd`. At that point, inspect and repair the projectless sidebar keys.

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

For a global **Chats** item that should move under an existing project, use the selected thread ID and close Codex before the final write if the sidebar resists updating:

```powershell
python scripts/migrate_codex_project_path.py --old "C:\Old\StandaloneChatWorkspace" --new "C:\New\Project" --thread-id 019e... --wait-for-codex-exit 1200
```

The wait option applies the migration only after no `Codex.exe` UI process remains, up to the given number of seconds.

## Important Pitfalls

- PowerShell 5.1 `Set-Content -Encoding UTF8` can write a UTF-8 BOM. Do not use it for session JSONL files.
- Update both `.codex-global-state.json` and `.codex-global-state.json.bak`; otherwise Codex may restore the old path or stale sidebar state.
- A running Codex Desktop window can rewrite the saved project registry from memory. If the UI still shows the old tooltip or global **Chats** placement, close all Codex windows and rerun or use the wait option.
- A thread can have the correct `threads.cwd` and still show under global **Chats** when `projectless-thread-ids` still contains its ID.
- Stale `thread-projectless-output-directories` entries should be removed for selected threads moved into a project.
- Do not use destructive Git or filesystem commands for this task.
- Do not copy project files unless the user makes a separate explicit request after this path-only migration.
