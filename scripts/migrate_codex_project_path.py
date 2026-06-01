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
import time
from pathlib import Path
from typing import Any


REGISTRY_FILES = (".codex-global-state.json", ".codex-global-state.json.bak")
REGISTRY_ARRAY_KEYS = {
    "electron-saved-workspace-roots",
    "project-order",
    "active-workspace-roots",
}


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
    old_long = long_path(old_plain)
    new_long = long_path(new_plain)
    pairs = [
        (json_escaped(old_long), json_escaped(new_long)),
        (json_escaped(old_plain), json_escaped(new_plain)),
        (old_long, new_long),
        (old_plain, new_plain),
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


def wait_for_codex_exit(seconds: int) -> None:
    if seconds <= 0:
        return
    deadline = time.time() + seconds
    print(f"Waiting up to {seconds}s for Codex Desktop to close...")
    while time.time() < deadline:
        if not codex_ui_running():
            time.sleep(2)
            print("Codex Desktop is closed; applying migration.")
            return
        time.sleep(2)
    raise TimeoutError("Timed out waiting for Codex Desktop to close")


def update_registry(codex_home: Path, old_plain: str, new_plain: str, stamp: str, dry_run: bool) -> list[dict[str, Any]]:
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
        updated = json.dumps(data, ensure_ascii=False, indent=2)
        changed = updated != original
        if changed:
            backup = copy_backup(path, stamp, dry_run)
            write_text_utf8_no_bom(path, updated, dry_run)
        else:
            backup = None
        results.append({"file": str(path), "status": "updated" if changed else "unchanged", "backup": str(backup) if backup else None})
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


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Remap Codex project path metadata without syncing files.")
    parser.add_argument("--old", required=True, help="Old saved Codex project path")
    parser.add_argument("--new", required=True, help="New saved Codex project path")
    parser.add_argument("--thread-id", action="append", default=[], help="Thread ID to remap. Repeat for multiple chats. If omitted, all threads with cwd matching --old are remapped.")
    parser.add_argument("--codex-home", help="Codex home directory. Defaults to CODEX_HOME or %%USERPROFILE%%\\.codex.")
    parser.add_argument("--state-db", help="Path to Codex state sqlite database. Defaults to state_5.sqlite or newest state_*.sqlite.")
    parser.add_argument("--wait-for-codex-exit", type=int, default=0, metavar="SECONDS", help="Wait until Codex.exe closes before applying changes.")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be changed without writing files.")
    parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON summary.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    old_plain = clean_path(args.old)
    new_plain = clean_path(args.new)
    codex_home = find_codex_home(args.codex_home)
    db_path = find_state_db(codex_home, args.state_db)
    stamp = time.strftime("%Y%m%d-%H%M%S")

    wait_for_codex_exit(args.wait_for_codex_exit)

    rows = select_threads(db_path, old_plain, args.thread_id)
    selected_ids = [row["id"] for row in rows]

    summary = {
        "dry_run": args.dry_run,
        "old_path": old_plain,
        "new_path": new_plain,
        "codex_home": str(codex_home),
        "state_db": str(db_path),
        "selected_threads": [{"id": row["id"], "title": row["title"], "old_cwd": row["cwd"]} for row in rows],
        "registry": update_registry(codex_home, old_plain, new_plain, stamp, args.dry_run),
        "database": update_thread_db(db_path, rows, new_plain, stamp, args.dry_run),
        "sessions": update_session_files(rows, old_plain, new_plain, stamp, args.dry_run),
    }
    if not args.dry_run:
        summary["verification"] = verify_db(db_path, selected_ids, new_plain)

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
        raise SystemExit(1)
