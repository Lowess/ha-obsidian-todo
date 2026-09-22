"""Tests for the Markdown storage layer without requiring Home Assistant."""

from __future__ import annotations

import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

MODULE_PATH = (
    Path(__file__).parents[1]
    / "custom_components"
    / "obsidian_todo"
    / "markdown_store.py"
)
SPEC = importlib.util.spec_from_file_location("markdown_store", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
markdown_store = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = markdown_store
SPEC.loader.exec_module(markdown_store)
MarkdownTodoStore = markdown_store.MarkdownTodoStore


class MarkdownTodoStoreTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.vault = Path(self.temporary_directory.name)
        self.note = self.vault / "Lists" / "Shopping.md"
        self.metadata = self.vault / ".ha-metadata" / "shopping.json"
        self.store = MarkdownTodoStore(
            str(self.vault),
            "Lists/Shopping.md",
            "Shopping",
            str(self.metadata),
        )

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def test_load_preserves_content_and_keeps_ids_out_of_note(self) -> None:
        self.note.parent.mkdir(parents=True)
        self.note.write_text(
            "# Shopping\n\nKeep this paragraph.\n\n- [ ] Milk\n  - [x] Coffee\n",
            encoding="utf-8",
        )

        first = self.store.load()
        second = self.store.load()

        self.assertEqual(["Milk", "Coffee"], [task.summary for task in first])
        self.assertEqual([task.uid for task in first], [task.uid for task in second])
        self.assertIn("Keep this paragraph.", self.note.read_text(encoding="utf-8"))
        self.assertNotIn("ha-todo:", self.note.read_text(encoding="utf-8"))
        self.assertTrue(self.metadata.exists())

    def test_crud(self) -> None:
        added = self.store.add("Milk")
        uid = added[0].uid

        updated = self.store.update(uid, summary="Oat milk", completed=True)
        self.assertEqual("Oat milk", updated[0].summary)
        self.assertTrue(updated[0].completed)

        remaining = self.store.delete([uid])
        self.assertEqual([], remaining)
        self.assertNotIn("Oat milk", self.note.read_text(encoding="utf-8"))

    def test_legacy_markers_are_migrated_out_of_note(self) -> None:
        uid = "3d64bd38-8c8b-47a5-91be-56df0fdd8cf5"
        self.note.parent.mkdir(parents=True)
        self.note.write_text(
            f"- [ ] One <!-- ha-todo:{uid} -->\n"
            f"- [ ] Two <!-- ha-todo:{uid} -->\n",
            encoding="utf-8",
        )

        tasks = self.store.load()

        self.assertEqual(2, len({task.uid for task in tasks}))
        self.assertEqual(uid, tasks[0].uid)
        self.assertNotIn("ha-todo:", self.note.read_text(encoding="utf-8"))

    def test_escaped_legacy_markers_are_migrated_out_of_note(self) -> None:
        uid = "b5196f6c-45de-4ea7-97f1-fe365c08c48a"
        self.note.parent.mkdir(parents=True)
        self.note.write_text(
            f"- [x] Bibi \\<!-- ha-todo:{uid} -->\n",
            encoding="utf-8",
        )

        tasks = self.store.load()

        self.assertEqual(uid, tasks[0].uid)
        self.assertEqual("Bibi", tasks[0].summary)
        self.assertTrue(tasks[0].completed)
        self.assertEqual("- [x] Bibi\n", self.note.read_text(encoding="utf-8"))

    def test_atomic_write_preserves_existing_owner(self) -> None:
        self.note.parent.mkdir(parents=True)
        self.note.write_text("before\n", encoding="utf-8")
        existing_stat = self.note.stat()

        with patch.object(markdown_store.os, "chown") as chown:
            MarkdownTodoStore._atomic_write(self.note, "after\n")

        chown.assert_called_once()
        _, uid, gid = chown.call_args.args
        self.assertEqual(existing_stat.st_uid, uid)
        self.assertEqual(existing_stat.st_gid, gid)
        self.assertEqual("after\n", self.note.read_text(encoding="utf-8"))

    def test_external_rename_retains_id(self) -> None:
        self.note.parent.mkdir(parents=True)
        self.note.write_text("- [ ] Milk\n- [ ] Bread\n", encoding="utf-8")
        original = self.store.load()

        self.note.write_text("- [ ] Oat milk\n- [ ] Bread\n", encoding="utf-8")
        renamed = self.store.load()

        self.assertEqual(original[0].uid, renamed[0].uid)
        self.assertEqual(original[1].uid, renamed[1].uid)

    def test_external_add_delete_reorder_and_status_retain_ids(self) -> None:
        self.note.parent.mkdir(parents=True)
        self.note.write_text(
            "- [ ] Milk\n- [ ] Bread\n- [ ] Coffee\n", encoding="utf-8"
        )
        original = {task.summary: task.uid for task in self.store.load()}

        self.note.write_text(
            "- [x] Coffee\n- [ ] Apples\n- [ ] Milk\n", encoding="utf-8"
        )
        changed = {task.summary: task for task in self.store.load()}

        self.assertEqual(original["Coffee"], changed["Coffee"].uid)
        self.assertTrue(changed["Coffee"].completed)
        self.assertEqual(original["Milk"], changed["Milk"].uid)
        self.assertNotIn("Bread", changed)
        self.assertNotIn(
            changed["Apples"].uid,
            {original["Coffee"], original["Milk"]},
        )


if __name__ == "__main__":
    unittest.main()
