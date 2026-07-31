---
name: codex-project-path-migrator
description: Remap a saved Codex project/workspace path or move selected standalone/global Chats into an existing project while preserving chat history. Use when a project folder moved or was renamed, chats disappeared from a project, a chat has the correct cwd but still appears under general Chats, or Codex restores projectless sidebar state after restart. Update Codex metadata only; never copy, sync, merge, move, or delete project files.
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
2. Resolve exact thread IDs for selected/global-chat migrations. Record each thread's `cwd` and `projectId` from `codex_app.list_threads`.
3. Locate Codex metadata:
   - `CODEX_HOME`, usually `%USERPROFILE%\.codex`.
   - Saved project registry: `.codex-global-state.json` and `.codex-global-state.json.bak`.
   - Thread database: usually `state_5.sqlite`, or the newest `state_*.sqlite`.
   - Session files referenced by `threads.rollout_path`.
4. Prefer the bundled script:
   - `scripts/migrate_codex_project_path.py`
5. Run `--dry-run --json` first and inspect the exact selected threads and files.
6. Back up all edited metadata files with a timestamp.
7. Update saved project registry values such as:
   - `electron-saved-workspace-roots`
   - `project-order`
   - `active-workspace-roots`
   - `thread-workspace-root-hints`
8. For selected migrated threads, also update project/sidebar classification:
   - Set `thread-workspace-root-hints[thread_id]` to the new project path.
   - Remove `thread_id` from `projectless-thread-ids`.
   - Remove `thread_id` from `thread-projectless-output-directories`.
9. Update matching `threads.cwd` rows to the new long Windows path form, for example `\\?\C:\New\Project`.
10. Update affected session JSONL files by replacing backslash, JSON-escaped, and forward-slash path forms.
11. Write session JSONL files as UTF-8 without BOM. The first bytes must remain the first JSON session metadata line, not a UTF-8 marker.
12. For a global-chat migration while Codex is open, queue the restart-safe background repair described below. Do not treat an immediate live-app write as final.
13. After Codex is reopened, verify:
   - The new path appears in saved project roots or already exists as the target saved project.
   - The old path no longer appears in saved project roots when this is a path replacement.
   - The remapped thread rows have the new `cwd`.
   - Each edited session file starts with a `session_meta` JSON line.
   - Selected migrated threads are absent from `projectless-thread-ids`.
   - Selected migrated threads are absent from `thread-projectless-output-directories`.
   - `thread-workspace-root-hints[thread_id]` points to the new project path.
   - `codex_app.list_threads` reports the target project's non-null `projectId` for each migrated thread.

## Restart-Safe Global Chat Repair

A new `cwd` is not proof that the sidebar migration succeeded. A task can report the target path while `projectId` remains null and the conversation stays under global **Chats**.

Inspect both `.codex-global-state.json` and its `.bak`. The usual cause is restored projectless state:

- `projectless-thread-ids` still contained the thread IDs.
- `thread-projectless-output-directories` still mapped those thread IDs to the old disposable chat workspace.
- `thread-workspace-root-hints` reverted to the general Codex output root.

Codex can restore these values from memory during shutdown or the next startup even when an immediate migration and registry verification passed. Apply the final write only after every `Codex.exe` process has remained absent for a stable interval.

Use the script's detached mode from an active Codex task:

```powershell
python scripts/migrate_codex_project_path.py `
  --old "C:\Old\StandaloneChatWorkspace" `
  --new "C:\New\Project" `
  --thread-id 019e... `
  --background `
  --wait-for-codex-exit 1200 `
  --json
```

The parent command returns immediately with a PID and output/error log paths. Ask the user to close all Codex windows, leave Codex closed for at least 10 seconds, and reopen it. The detached helper preserves paths containing spaces, waits for Codex to remain absent for 5 seconds by default, then applies the backed-up migration. Read its logs and run the post-restart verification before claiming completion.

Do not hand-build a `Start-Process -ArgumentList` command for this workflow; unquoted paths containing spaces can be split silently. Use `--background`.

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

For a global **Chats** item, first preview the selected-thread change:

```powershell
python scripts/migrate_codex_project_path.py --old "C:\Old\StandaloneChatWorkspace" --new "C:\New\Project" --thread-id 019e... --dry-run --json
```

Then use `--background --wait-for-codex-exit 1200 --json` as shown above. Use `--log-dir` to choose a log directory and `--codex-exit-stable-seconds` only when the default 5-second stable-close window is unsuitable.

## Important Pitfalls

- PowerShell 5.1 `Set-Content -Encoding UTF8` can write a UTF-8 BOM. Do not use it for session JSONL files.
- Update both `.codex-global-state.json` and `.codex-global-state.json.bak`; otherwise Codex may restore the old path or stale sidebar state.
- A live-app migration can pass its immediate checks and still be undone during shutdown or restart. Use the detached close-wait workflow for global chats.
- A thread can have the correct `threads.cwd` and still show under global **Chats** when `projectless-thread-ids` still contains its ID.
- A `codex_app.list_threads` entry with the target `cwd` but `projectId: null` is not migrated successfully.
- Stale `thread-projectless-output-directories` entries should be removed for selected threads moved into a project.
- Keep `--json` stdout machine-readable; detached wait progress goes to the error log.
- Do not use destructive Git or filesystem commands for this task.
- Do not copy project files unless the user makes a separate explicit request after this path-only migration.
