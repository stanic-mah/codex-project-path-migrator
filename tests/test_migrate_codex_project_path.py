from __future__ import annotations

import importlib.util
import io
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "migrate_codex_project_path.py"
SPEC = importlib.util.spec_from_file_location("migrate_codex_project_path", SCRIPT_PATH)
assert SPEC is not None and SPEC.loader is not None
migrator = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(migrator)


class PathReplacementTests(unittest.TestCase):
    def test_replaces_backslash_json_and_forward_slash_forms(self) -> None:
        old = r"C:\Users\USER\Documents\Codex\2026-07-16\wo"
        new = r"C:\Users\USER\OneDrive\Documents\Phuket 攻略"
        old_slash = old.replace("\\", "/")
        new_slash = new.replace("\\", "/")
        text = "\n".join(
            [
                old,
                json.dumps({"cwd": old}, ensure_ascii=False),
                f"[output](/{old_slash}/outputs/guide.md)",
                migrator.long_path(old),
            ]
        )

        updated = migrator.replace_path_text(text, old, new)

        self.assertNotIn(old, updated)
        self.assertNotIn(old_slash, updated)
        self.assertIn(new, updated)
        self.assertIn(new_slash, updated)
        self.assertIn(migrator.long_path(new), updated)


class RegistryTests(unittest.TestCase):
    def test_selected_thread_is_removed_from_projectless_state(self) -> None:
        thread_id = "019f69c1-8cec-7173-9499-ec0a839625c6"
        old = r"C:\Users\USER\Documents\Codex\2026-07-16\wo"
        new = r"C:\Users\USER\OneDrive\Documents\Phuket 攻略"
        original = {
            "projectless-thread-ids": ["keep", thread_id],
            "thread-projectless-output-directories": {
                "keep": r"C:\Keep\outputs",
                thread_id: old + r"\outputs",
            },
            "thread-workspace-root-hints": {
                "keep": r"C:\Keep",
                thread_id: r"C:\Users\USER\Documents\Codex",
            },
        }

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for name in migrator.REGISTRY_FILES:
                (root / name).write_text(json.dumps(original), encoding="utf-8")

            results = migrator.update_registry(
                root,
                old,
                new,
                [thread_id],
                "20260731-000000",
                dry_run=False,
            )

            self.assertEqual({item["status"] for item in results}, {"updated"})
            for name in migrator.REGISTRY_FILES:
                path = root / name
                data = json.loads(path.read_text(encoding="utf-8"))
                self.assertNotIn(thread_id, data["projectless-thread-ids"])
                self.assertNotIn(thread_id, data["thread-projectless-output-directories"])
                self.assertEqual(data["thread-workspace-root-hints"][thread_id], new)
                self.assertTrue(
                    path.with_name(path.name + ".codex-path-migrator-backup-20260731-000000").exists()
                )


class SessionTests(unittest.TestCase):
    def test_session_update_preserves_format_and_updates_links(self) -> None:
        old = r"C:\Users\USER\Documents\Codex\2026-07-16\wo"
        new = r"C:\Users\USER\OneDrive\Documents\Phuket 攻略"
        old_slash = old.replace("\\", "/")
        new_slash = new.replace("\\", "/")
        first = json.dumps({"type": "session_meta", "payload": {"cwd": old}}, ensure_ascii=False)
        second = json.dumps(
            {"type": "response_item", "payload": {"text": f"[guide](/{old_slash}/outputs/guide.md)"}},
            ensure_ascii=False,
        )

        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "rollout.jsonl"
            path.write_text(first + "\n" + second + "\n", encoding="utf-8")
            rows = [{"rollout_path": str(path)}]

            results = migrator.update_session_files(
                rows,
                old,
                new,
                "20260731-000000",
                dry_run=False,
            )

            self.assertEqual(results[0]["status"], "updated")
            raw = path.read_bytes()
            self.assertFalse(raw.startswith(b"\xef\xbb\xbf"))
            text = raw.decode("utf-8")
            self.assertNotIn(old_slash, text)
            self.assertIn(new_slash, text)
            migrator.validate_session_file(path)


class BackgroundTests(unittest.TestCase):
    def test_background_command_preserves_space_path_as_one_argument(self) -> None:
        new = r"C:\Users\USER\OneDrive\Documents\Phuket 攻略"
        argv = [
            "--old",
            r"C:\Old",
            "--new",
            new,
            "--background",
            "--wait-for-codex-exit",
            "1200",
            "--json",
        ]

        command = migrator.background_command(argv)

        self.assertNotIn("--background", command)
        self.assertIn(new, command)
        self.assertEqual(command.count(new), 1)

    def test_launch_background_returns_pid_and_logs(self) -> None:
        new = r"C:\Users\USER\OneDrive\Documents\Phuket 攻略"
        argv = [
            "--old",
            r"C:\Old",
            "--new",
            new,
            "--background",
            "--wait-for-codex-exit",
            "1200",
            "--json",
        ]
        process = mock.Mock(pid=12345)

        with tempfile.TemporaryDirectory() as temporary:
            with mock.patch.object(migrator.os, "name", "nt"):
                with mock.patch.object(migrator.subprocess, "Popen", return_value=process) as popen:
                    result = migrator.launch_background(argv, temporary)

            command = popen.call_args.args[0]
            self.assertEqual(result["status"], "queued")
            self.assertEqual(result["pid"], 12345)
            self.assertIn(new, command)
            self.assertNotIn("--background", command)
            self.assertTrue(result["output_log"].endswith(".json"))
            self.assertTrue(Path(result["output_log"]).exists())
            self.assertTrue(Path(result["error_log"]).exists())

    def test_wait_requires_stable_window_shorter_than_timeout(self) -> None:
        with self.assertRaises(ValueError):
            migrator.wait_for_codex_exit(5, stable_seconds=5, status_stream=io.StringIO())

    def test_json_runtime_errors_are_structured(self) -> None:
        result = subprocess.run(
            [
                sys.executable,
                str(SCRIPT_PATH),
                "--old",
                r"C:\Old",
                "--new",
                r"C:\New",
                "--background",
                "--wait-for-codex-exit",
                "10",
                "--dry-run",
                "--json",
            ],
            check=False,
            capture_output=True,
            text=True,
        )

        self.assertEqual(result.returncode, 1)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["status"], "error")
        self.assertIn("--background cannot be combined with --dry-run", payload["error"])


if __name__ == "__main__":
    unittest.main()
