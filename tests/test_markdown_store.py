"""Tests for the Markdown storage layer without requiring Home Assistant."""

from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
import tempfile
import unittest


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
        self.store = MarkdownTodoStore(
            str(self.vault), "Lists/Shopping.md", "Shopping"
        )

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def test_load_preserves_content_and_adds_stable_ids(self) -> None:
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
        self.assertEqual(2, self.note.read_text(encoding="utf-8").count("ha-todo:"))

    def test_crud(self) -> None:
        added = self.store.add("Milk")
        uid = added[0].uid

        updated = self.store.update(uid, summary="Oat milk", completed=True)
        self.assertEqual("Oat milk", updated[0].summary)
        self.assertTrue(updated[0].completed)

        remaining = self.store.delete([uid])
        self.assertEqual([], remaining)
        self.assertNotIn("Oat milk", self.note.read_text(encoding="utf-8"))

    def test_duplicate_ids_are_repaired(self) -> None:
        uid = "3d64bd38-8c8b-47a5-91be-56df0fdd8cf5"
        self.note.parent.mkdir(parents=True)
        self.note.write_text(
            f"- [ ] One <!-- ha-todo:{uid} -->\n"
            f"- [ ] Two <!-- ha-todo:{uid} -->\n",
            encoding="utf-8",
        )

        tasks = self.store.load()

        self.assertEqual(2, len({task.uid for task in tasks}))


if __name__ == "__main__":
    unittest.main()
