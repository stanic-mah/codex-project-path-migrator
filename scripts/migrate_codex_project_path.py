#!/usr/bin/env python3
"""Remap a Codex saved project path while preserving chat history.

This script edits Codex metadata only. It does not copy, sync, move, merge,
or delete project files.
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any


REGISTRY_FILES = (".codex-global-state.json", ".codex-global-state.json.bak")
REGISTRY_ARRAY_KEYS = {
    "electron-saved-workspace-roots",
    "project-order",
    "active-workspace-roots",
}
THREAD_WORKSPACE_ROOT_HINTS_KEY = "thread-workspace-root-hints"
PROJECTLESS_THREAD_IDS_KEY = "projectless-thread-ids"
THREAD_PROJECTLESS_OUTPUT_DIRS_KEY = "thread-projectless-output-directories"


def strip_long_prefix(value: str) -> str:
    value = value.strip().replace("/", "\\")
    unc_prefix = "\\\\?\\UNC\\"
    long_prefix = "\\\\?\\"
    if value.startswith(unc_prefix):
        return "\\\\" + value[len(unc_prefix) :]
    if value.startswith(long_prefix):
        return value[len(long_prefix) :]
    return value


def clean_path(value: str) -> str:
    value = os.path.expandvars(strip_long_prefix(value))
    if len(value) > 3:
        value = value.rstrip("\\")
    return value


def path_key(value: str) -> str:
    return clean_path(value).casefold()


def long_path(value: str) -> str:
    value = clean_path(value)
    if value.startswith("\\\\"):
        return "\\\\?\\UNC\\" + value.lstrip("\\")
    return "\\\\?\\" + value


def json_escaped(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)[1:-1]


def replace_path_text(text: str, old_plain: str, new_plain: str) -> str:
    old_plain = clean_path(old_plain)
    new_plain = clean_path(new_plain)
    old_long = long_path(old_plain)
    new_long = long_path(new_plain)
    old_slash = old_plain.replace("\\", "/")
    new_slash = new_plain.replace("\\", "/")
    old_long_slash = old_long.replace("\\", "/")
    new_long_slash = new_long.replace("\\", "/")
    path_pairs = [
        (old_long, new_long),
        (old_plain, new_plain),
        (old_long_slash, new_long_slash),
        (old_slash, new_slash),
    ]
    pairs = [
        pair
        for old, new in path_pairs
        for pair in ((json_escaped(old), json_escaped(new)), (old, new))
    ]
    seen: set[tuple[str, str]] = set()
    for old, new in pairs:
        if old and (old, new) not in seen:
            text = text.replace(old, new)
            seen.add((old, new))
    return text


def replace_path_obj(obj: Any, old_plain: str, new_plain: str) -> Any:
    old_key = path_key(old_plain)
    old_long = long_path(old_plain)
    new_long = long_path(new_plain)
    if isinstance(obj, str):
        if path_key(obj) == old_key or path_key(obj) == path_key(old_long):
            return new_plain
        return replace_path_text(obj, old_plain, new_plain).replace(old_long, new_long)
    if isinstance(obj, list):
        return [replace_path_obj(item, old_plain, new_plain) for item in obj]
    if isinstance(obj, dict):
        return {key: replace_path_obj(value, old_plain, new_plain) for key, value in obj.items()}
    return obj


def dedupe_path_array(items: list[Any]) -> list[Any]:
    out: list[Any] = []
    seen: set[str] = set()
    for item in items:
        if isinstance(item, str):
            key = path_key(item)
        else:
            key = json.dumps(item, sort_keys=True, ensure_ascii=False)
        if key not in seen:
            out.append(item)
            seen.add(key)
    return out


def copy_backup(path: Path, stamp: str, dry_run: bool) -> Path | None:
    if dry_run:
        return None
    backup = path.with_name(path.name + f".codex-path-migrator-backup-{stamp}")
    shutil.copy2(path, backup)
    return backup


def read_text_utf8(path: Path) -> str:
    return path.read_text(encoding="utf-8-sig")


def write_text_utf8_no_bom(path: Path, text: str, dry_run: bool) -> None:
    if not dry_run:
        path.write_bytes(text.encode("utf-8"))


def find_codex_home(value: str | None) -> Path:
    if value:
        return Path(value).expanduser()
    env = os.environ.get("CODEX_HOME")
    if env:
        return Path(env).expanduser()
    return Path.home() / ".codex"


def find_state_db(codex_home: Path, value: str | None) -> Path:
    if value:
        return Path(value)
    preferred = codex_home / "state_5.sqlite"
    if preferred.exists():
        return preferred
    candidates = sorted(codex_home.glob("state_*.sqlite"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not candidates:
        raise FileNotFoundError(f"No state_*.sqlite database found in {codex_home}")
    return candidates[0]


def codex_ui_running() -> bool:
    if os.name != "nt":
        return False
    try:
        result = subprocess.run(
            ["tasklist", "/FI", "IMAGENAME eq Codex.exe", "/FO", "CSV", "/NH"],
            check=False,
            capture_output=True,
            text=True,
        )
    except OSError:
        return False
    if result.returncode != 0:
        return False
    for row in csv.reader(io.StringIO(result.stdout)):
        if row and row[0].strip('"').lower() == "codex.exe":
            return True
    return False


def wait_for_codex_exit(seconds: int, stable_seconds: int = 5, status_stream: Any = None) -> None:
    if seconds <= 0:
        return
    if stable_seconds < 0:
        raise ValueError("--codex-exit-stable-seconds must be zero or greater")
    if stable_seconds >= seconds:
        raise ValueError("--codex-exit-stable-seconds must be less than --wait-for-codex-exit")
    stream = status_stream if status_stream is not None else sys.stdout
    deadline = time.monotonic() + seconds
    closed_since: float | None = None
    print(
        f"Waiting up to {seconds}s for Codex Desktop to remain closed for {stable_seconds}s...",
        file=stream,
        flush=True,
    )
    while time.monotonic() < deadline:
        now = time.monotonic()
        if codex_ui_running():
            closed_since = None
        else:
            if closed_since is None:
                closed_since = now
            if now - closed_since >= stable_seconds:
                print("Codex Desktop is closed; applying migration.", file=stream, flush=True)
                return
        time.sleep(1)
    raise TimeoutError("Timed out waiting for Codex Desktop to close")


def background_command(argv: list[str]) -> list[str]:
    child_args = [arg for arg in argv if arg != "--background"]
    return [sys.executable, str(Path(__file__).resolve()), *child_args]


def launch_background(argv: list[str], log_dir: str | None) -> dict[str, Any]:
    if os.name != "nt":
        raise OSError("--background is currently supported on Windows only")
    root = Path(log_dir).expanduser() if log_dir else Path(tempfile.gettempdir())
    root.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    stem = f"codex-project-path-migrator-{stamp}-{os.getpid()}"
    stdout_suffix = ".json" if "--json" in argv else ".log"
    stdout_path = root / f"{stem}{stdout_suffix}"
    stderr_path = root / f"{stem}.err.log"
    creationflags = 0
    for name in ("DETACHED_PROCESS", "CREATE_NEW_PROCESS_GROUP", "CREATE_NO_WINDOW"):
        creationflags |= int(getattr(subprocess, name, 0))
    command = background_command(argv)
    with stdout_path.open("wb") as stdout_file, stderr_path.open("wb") as stderr_file:
        process = subprocess.Popen(
            command,
            stdin=subprocess.DEVNULL,
            stdout=stdout_file,
            stderr=stderr_file,
            close_fds=True,
            creationflags=creationflags,
        )
    return {
        "status": "queued",
        "pid": process.pid,
        "command": command,
        "output_log": str(stdout_path),
        "error_log": str(stderr_path),
    }


def update_registry(
    codex_home: Path,
    old_plain: str,
    new_plain: str,
    selected_ids: list[str],
    stamp: str,
    dry_run: bool,
) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for name in REGISTRY_FILES:
        path = codex_home / name
        if not path.exists():
            results.append({"file": str(path), "status": "missing"})
            continue
        original = read_text_utf8(path)
        data = json.loads(original)
        data = replace_path_obj(data, old_plain, new_plain)
        for key in REGISTRY_ARRAY_KEYS:
            if isinstance(data, dict) and isinstance(data.get(key), list):
                data[key] = dedupe_path_array(data[key])
        registry_notes: dict[str, Any] = {}
        if isinstance(data, dict) and selected_ids:
            hints = data.setdefault(THREAD_WORKSPACE_ROOT_HINTS_KEY, {})
            if isinstance(hints, dict):
                added_or_updated = []
                for thread_id in selected_ids:
                    if hints.get(thread_id) != new_plain:
                        hints[thread_id] = new_plain
                        added_or_updated.append(thread_id)
                if added_or_updated:
                    registry_notes["workspace_root_hints"] = added_or_updated

            projectless = data.get(PROJECTLESS_THREAD_IDS_KEY)
            if isinstance(projectless, list):
                selected = set(selected_ids)
                kept_projectless = [thread_id for thread_id in projectless if thread_id not in selected]
                if kept_projectless != projectless:
                    registry_notes["removed_projectless_thread_ids"] = [
                        thread_id for thread_id in projectless if thread_id in selected
                    ]
                    data[PROJECTLESS_THREAD_IDS_KEY] = kept_projectless

            output_dirs = data.get(THREAD_PROJECTLESS_OUTPUT_DIRS_KEY)
            if isinstance(output_dirs, dict):
                removed_outputs = []
                for thread_id in selected_ids:
                    if thread_id in output_dirs:
                        removed_outputs.append(thread_id)
                        output_dirs.pop(thread_id, None)
                if removed_outputs:
                    registry_notes["removed_projectless_output_dirs"] = removed_outputs
        updated = json.dumps(data, ensure_ascii=False, indent=2)
        changed = updated != original
        if changed:
            backup = copy_backup(path, stamp, dry_run)
            write_text_utf8_no_bom(path, updated, dry_run)
        else:
            backup = None
        item: dict[str, Any] = {
            "file": str(path),
            "status": "updated" if changed else "unchanged",
            "backup": str(backup) if backup else None,
        }
        if registry_notes:
            item["project_sidebar"] = registry_notes
        results.append(item)
    return results


def select_threads(db_path: Path, old_plain: str, thread_ids: list[str]) -> list[dict[str, Any]]:
    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row
    try:
        if thread_ids:
            placeholders = ",".join("?" for _ in thread_ids)
            rows = con.execute(f"SELECT id, title, cwd, rollout_path FROM threads WHERE id IN ({placeholders})", thread_ids).fetchall()
            return [dict(row) for row in rows]
        rows = con.execute("SELECT id, title, cwd, rollout_path FROM threads").fetchall()
        old_key = path_key(old_plain)
        return [dict(row) for row in rows if path_key(row["cwd"]) == old_key]
    finally:
        con.close()


def update_thread_db(db_path: Path, rows: list[dict[str, Any]], new_plain: str, stamp: str, dry_run: bool) -> dict[str, Any]:
    if not rows:
        return {"file": str(db_path), "status": "no matching threads", "updated_threads": 0}
    backup = copy_backup(db_path, stamp, dry_run)
    if not dry_run:
        con = sqlite3.connect(db_path)
        try:
            new_cwd = long_path(new_plain)
            con.executemany("UPDATE threads SET cwd=? WHERE id=?", [(new_cwd, row["id"]) for row in rows])
            con.commit()
        finally:
            con.close()
    return {
        "file": str(db_path),
        "status": "updated",
        "backup": str(backup) if backup else None,
        "updated_threads": len(rows),
    }


def session_path(value: str) -> Path:
    return Path(strip_long_prefix(value))


def validate_session_file(path: Path) -> None:
    raw = path.read_bytes()
    if raw.startswith(b"\xef\xbb\xbf"):
        raise ValueError(f"{path} starts with a UTF-8 BOM")
    first = raw.splitlines()[0].decode("utf-8")
    data = json.loads(first)
    if data.get("type") != "session_meta":
        raise ValueError(f"{path} does not start with session_meta")


def update_session_files(rows: list[dict[str, Any]], old_plain: str, new_plain: str, stamp: str, dry_run: bool) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in rows:
        raw_path = row.get("rollout_path")
        if not raw_path:
            continue
        path = session_path(raw_path)
        key = str(path).casefold()
        if key in seen:
            continue
        seen.add(key)
        if not path.exists():
            results.append({"file": str(path), "status": "missing"})
            continue
        original = read_text_utf8(path)
        updated = replace_path_text(original, old_plain, new_plain)
        changed = updated != original or path.read_bytes().startswith(b"\xef\xbb\xbf")
        if changed:
            backup = copy_backup(path, stamp, dry_run)
            write_text_utf8_no_bom(path, updated, dry_run)
        else:
            backup = None
        if not dry_run:
            validate_session_file(path)
        results.append({"file": str(path), "status": "updated" if changed else "unchanged", "backup": str(backup) if backup else None})
    return results


def verify_db(db_path: Path, thread_ids: list[str], new_plain: str) -> list[dict[str, Any]]:
    if not thread_ids:
        return []
    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row
    try:
        placeholders = ",".join("?" for _ in thread_ids)
        rows = con.execute(f"SELECT id, title, cwd FROM threads WHERE id IN ({placeholders})", thread_ids).fetchall()
        out = []
        new_key = path_key(new_plain)
        for row in rows:
            item = dict(row)
            item["matches_new_path"] = path_key(row["cwd"]) == new_key
            out.append(item)
        return out
    finally:
        con.close()


def verify_registry(codex_home: Path, thread_ids: list[str], new_plain: str) -> list[dict[str, Any]]:
    if not thread_ids:
        return []
    results: list[dict[str, Any]] = []
    new_key = path_key(new_plain)
    for name in REGISTRY_FILES:
        path = codex_home / name
        if not path.exists():
            results.append({"file": str(path), "status": "missing"})
            continue
        data = json.loads(read_text_utf8(path))
        projectless = data.get(PROJECTLESS_THREAD_IDS_KEY, [])
        output_dirs = data.get(THREAD_PROJECTLESS_OUTPUT_DIRS_KEY, {})
        hints = data.get(THREAD_WORKSPACE_ROOT_HINTS_KEY, {})
        results.append(
            {
                "file": str(path),
                "projectless_remaining": [
                    thread_id for thread_id in thread_ids if isinstance(projectless, list) and thread_id in projectless
                ],
                "projectless_output_dirs_remaining": [
                    thread_id for thread_id in thread_ids if isinstance(output_dirs, dict) and thread_id in output_dirs
                ],
                "workspace_root_hints_match": {
                    thread_id: isinstance(hints, dict) and path_key(str(hints.get(thread_id, ""))) == new_key
                    for thread_id in thread_ids
                },
            }
        )
    return results


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Remap Codex project path metadata without syncing files.")
    parser.add_argument("--old", required=True, help="Old saved Codex project path")
    parser.add_argument("--new", required=True, help="New saved Codex project path")
    parser.add_argument("--thread-id", action="append", default=[], help="Thread ID to remap. Repeat for multiple chats. If omitted, all threads with cwd matching --old are remapped.")
    parser.add_argument("--codex-home", help="Codex home directory. Defaults to CODEX_HOME or %%USERPROFILE%%\\.codex.")
    parser.add_argument("--state-db", help="Path to Codex state sqlite database. Defaults to state_5.sqlite or newest state_*.sqlite.")
    parser.add_argument("--wait-for-codex-exit", type=int, default=0, metavar="SECONDS", help="Wait until Codex.exe closes before applying changes.")
    parser.add_argument("--codex-exit-stable-seconds", type=int, default=5, metavar="SECONDS", help="Require Codex.exe to remain absent for this long before applying. Defaults to 5.")
    parser.add_argument("--background", action="store_true", help="Queue a detached Windows helper and return immediately. Requires --wait-for-codex-exit.")
    parser.add_argument("--log-dir", help="Directory for detached helper output. Defaults to the system temporary directory.")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be changed without writing files.")
    parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON summary.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.background:
        if args.dry_run:
            raise ValueError("--background cannot be combined with --dry-run")
        if args.wait_for_codex_exit <= 0:
            raise ValueError("--background requires --wait-for-codex-exit")
        queued = launch_background(sys.argv[1:], args.log_dir)
        if args.json:
            print(json.dumps(queued, ensure_ascii=False, indent=2))
        else:
            print("Codex project path migration queued")
            print(f"pid: {queued['pid']}")
            print(f"output log: {queued['output_log']}")
            print(f"error log: {queued['error_log']}")
        return 0

    old_plain = clean_path(args.old)
    new_plain = clean_path(args.new)
    codex_home = find_codex_home(args.codex_home)
    db_path = find_state_db(codex_home, args.state_db)
    stamp = time.strftime("%Y%m%d-%H%M%S")

    codex_running_before_wait = codex_ui_running()
    warnings: list[str] = []
    if codex_running_before_wait and args.wait_for_codex_exit <= 0 and not args.dry_run:
        warning = (
            "Codex Desktop is running and may restore projectless sidebar state. "
            "Use --background --wait-for-codex-exit 1200 for a restart-safe repair."
        )
        warnings.append(warning)
        print(f"warning: {warning}", file=sys.stderr, flush=True)

    wait_for_codex_exit(
        args.wait_for_codex_exit,
        args.codex_exit_stable_seconds,
        sys.stderr if args.json else sys.stdout,
    )
    codex_running_at_apply = codex_ui_running()
    if args.wait_for_codex_exit > 0 and codex_running_at_apply:
        raise RuntimeError("Codex Desktop restarted before the migration could be applied")

    rows = select_threads(db_path, old_plain, args.thread_id)
    selected_ids = [row["id"] for row in rows]

    summary = {
        "dry_run": args.dry_run,
        "old_path": old_plain,
        "new_path": new_plain,
        "codex_home": str(codex_home),
        "state_db": str(db_path),
        "codex_ui": {
            "running_before_wait": codex_running_before_wait,
            "running_at_apply": codex_running_at_apply,
        },
        "warnings": warnings,
        "selected_threads": [{"id": row["id"], "title": row["title"], "old_cwd": row["cwd"]} for row in rows],
        "registry": update_registry(codex_home, old_plain, new_plain, selected_ids, stamp, args.dry_run),
        "database": update_thread_db(db_path, rows, new_plain, stamp, args.dry_run),
        "sessions": update_session_files(rows, old_plain, new_plain, stamp, args.dry_run),
    }
    if not args.dry_run:
        summary["verification"] = verify_db(db_path, selected_ids, new_plain)
        summary["registry_verification"] = verify_registry(codex_home, selected_ids, new_plain)

    if args.json:
        print(json.dumps(summary, ensure_ascii=False, indent=2))
    else:
        print(f"Codex project path migration {'dry run' if args.dry_run else 'completed'}")
        print(f"old: {old_plain}")
        print(f"new: {new_plain}")
        print(f"threads selected: {len(rows)}")
        for row in rows:
            print(f"- {row['id']} | {row['title']}")
        print("metadata backups were created for changed files" if not args.dry_run else "no files were changed")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        if "--json" in sys.argv[1:]:
            print(json.dumps({"status": "error", "error": str(exc)}, ensure_ascii=False, indent=2))
        raise SystemExit(1)
