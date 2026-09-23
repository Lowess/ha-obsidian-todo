"""Read and update Markdown checkbox tasks without an Obsidian runtime."""

from __future__ import annotations

import json
import os
import re
import tempfile
from dataclasses import dataclass
from pathlib import Path
from threading import RLock
from uuid import UUID, uuid4

LEGACY_TASK_RE = re.compile(
    r"^(?P<prefix>\s*[-*+]\s+)"
    r"\[(?P<status>[ xX])\]\s+"
    r"(?P<summary>.*?)"
    r"(?:\s+\\?<!--\s*ha-todo:(?P<uid>[0-9a-fA-F-]{36})\s*-->)?\s*$"
)


class MarkdownStoreError(Exception):
    """Base error for Markdown storage operations."""


class InvalidPathError(MarkdownStoreError):
    """Raised when a note resolves outside the configured vault."""


class ItemNotFoundError(MarkdownStoreError):
    """Raised when a requested task UID does not exist."""


@dataclass(frozen=True, slots=True)
class MarkdownTask:
    """A Markdown task parsed from a note."""

    uid: str
    summary: str
    completed: bool
    line_index: int
    prefix: str = "- "


@dataclass(frozen=True, slots=True)
class _ParsedTask:
    summary: str
    completed: bool
    line_index: int
    prefix: str
    legacy_uid: str | None


@dataclass(frozen=True, slots=True)
class _RegistryItem:
    uid: str
    summary: str


@dataclass(slots=True)
class _Document:
    lines: list[str]
    final_newline: bool


class MarkdownTodoStore:
    """Manage checkbox tasks in one Markdown note."""

    def __init__(
        self,
        vault_path: str,
        note_path: str,
        title: str,
        metadata_path: str | None = None,
    ) -> None:
        self.vault_path = Path(vault_path).expanduser().resolve()
        relative_note = Path(note_path)
        if relative_note.is_absolute() or ".." in relative_note.parts:
            raise InvalidPathError("The note path must be relative to the vault")

        self.note_path = (self.vault_path / relative_note).resolve()
        if not self.note_path.is_relative_to(self.vault_path):
            raise InvalidPathError("The note path resolves outside the vault")

        self.metadata_path = (
            Path(metadata_path).expanduser().resolve() if metadata_path else None
        )
        self.title = title.strip() or "To-do"
        self._lock = RLock()

    def validate_access(self) -> None:
        """Validate that the vault and target note are accessible."""
        if not self.vault_path.is_dir():
            raise OSError(f"Vault directory does not exist: {self.vault_path}")

        target = (
            self.note_path if self.note_path.exists() else self.note_path.parent
        )
        while not target.exists() and target != self.vault_path:
            target = target.parent
        if not os.access(target, os.R_OK | os.W_OK):
            raise OSError(f"Vault path is not readable and writable: {target}")

    def load(self) -> list[MarkdownTask]:
        """Load tasks and reconcile stable IDs in HA-owned metadata."""
        with self._lock:
            document = self._read_document()
            tasks, document_changed = self._reconcile(document)
            if document_changed:
                self._write_document(document)
            self._write_registry_if_changed(tasks)
            return tasks

    def add(self, summary: str) -> list[MarkdownTask]:
        """Append a new incomplete task."""
        clean_summary = self._validate_summary(summary)
        with self._lock:
            document = self._read_document()
            tasks, _ = self._reconcile(document)
            if (
                document.lines
                and document.lines[-1].strip()
                and LEGACY_TASK_RE.match(document.lines[-1]) is None
            ):
                document.lines.append("")
            line_index = len(document.lines)
            document.lines.append(self._render_task("- ", False, clean_summary))
            document.final_newline = True
            tasks.append(
                MarkdownTask(
                    uid=str(uuid4()),
                    summary=clean_summary,
                    completed=False,
                    line_index=line_index,
                )
            )
            self._write_document(document)
            self._write_registry(tasks)
            return tasks

    def update(
        self, uid: str, *, summary: str | None = None, completed: bool | None = None
    ) -> list[MarkdownTask]:
        """Update a task by stable UID."""
        with self._lock:
            document = self._read_document()
            tasks, _ = self._reconcile(document)
            task = self._find(tasks, uid)
            new_summary = (
                task.summary if summary is None else self._validate_summary(summary)
            )
            new_completed = task.completed if completed is None else completed
            document.lines[task.line_index] = self._render_task(
                task.prefix, new_completed, new_summary
            )
            updated_tasks = [
                MarkdownTask(
                    uid=current.uid,
                    summary=new_summary if current.uid == uid else current.summary,
                    completed=(
                        new_completed if current.uid == uid else current.completed
                    ),
                    line_index=current.line_index,
                    prefix=current.prefix,
                )
                for current in tasks
            ]
            self._write_document(document)
            self._write_registry(updated_tasks)
            return updated_tasks

    def delete(self, uids: list[str]) -> list[MarkdownTask]:
        """Delete tasks by stable UID."""
        with self._lock:
            document = self._read_document()
            tasks, _ = self._reconcile(document)
            requested = set(uids)
            existing = {task.uid for task in tasks}
            missing = requested - existing
            if missing:
                raise ItemNotFoundError(
                    f"Task UID not found: {', '.join(sorted(missing))}"
                )
            indexes = {task.line_index for task in tasks if task.uid in requested}
            document.lines = [
                line
                for index, line in enumerate(document.lines)
                if index not in indexes
            ]
            self._write_document(document)
            remaining, _ = self._reconcile(document, previous=tasks)
            self._write_registry(remaining)
            return remaining

    def _reconcile(
        self,
        document: _Document,
        previous: list[MarkdownTask] | None = None,
    ) -> tuple[list[MarkdownTask], bool]:
        parsed, document_changed = self._parse_document(document)
        registry = (
            [_RegistryItem(task.uid, task.summary) for task in previous]
            if previous is not None
            else self._read_registry()
        )
        assigned: dict[int, str] = {}
        used_uids: set[str] = set()

        # Preserve IDs from v0.1 HTML markers during automatic migration.
        for index, task in enumerate(parsed):
            if task.legacy_uid and task.legacy_uid not in used_uids:
                assigned[index] = task.legacy_uid
                used_uids.add(task.legacy_uid)

        # Exact text matches survive status changes, insertions, and reordering.
        for index, task in enumerate(parsed):
            if index in assigned:
                continue
            match = next(
                (
                    item
                    for item in registry
                    if item.uid not in used_uids and item.summary == task.summary
                ),
                None,
            )
            if match:
                assigned[index] = match.uid
                used_uids.add(match.uid)

        # If the unmatched counts agree, treat positional changes as renames.
        unmatched_indexes = [
            index for index in range(len(parsed)) if index not in assigned
        ]
        unmatched_registry = [
            item for item in registry if item.uid not in used_uids
        ]
        if len(unmatched_indexes) == len(unmatched_registry):
            for index, item in zip(
                unmatched_indexes, unmatched_registry, strict=True
            ):
                assigned[index] = item.uid
                used_uids.add(item.uid)

        for index in unmatched_indexes:
            if index not in assigned:
                assigned[index] = str(uuid4())

        return (
            [
                MarkdownTask(
                    uid=assigned[index],
                    summary=task.summary,
                    completed=task.completed,
                    line_index=task.line_index,
                    prefix=task.prefix,
                )
                for index, task in enumerate(parsed)
            ],
            document_changed,
        )

    def _parse_document(
        self, document: _Document
    ) -> tuple[list[_ParsedTask], bool]:
        tasks: list[_ParsedTask] = []
        changed = False
        for line_index, line in enumerate(document.lines):
            match = LEGACY_TASK_RE.match(line)
            if not match:
                continue

            legacy_uid = self._valid_uid(match.group("uid"))
            summary = match.group("summary").strip()
            completed = match.group("status").lower() == "x"
            prefix = match.group("prefix")
            normalized_line = self._render_task(prefix, completed, summary)
            if normalized_line != line:
                document.lines[line_index] = normalized_line
                changed = True
            tasks.append(
                _ParsedTask(
                    summary=summary,
                    completed=completed,
                    line_index=line_index,
                    prefix=prefix,
                    legacy_uid=legacy_uid,
                )
            )
        return tasks, changed

    def _read_document(self) -> _Document:
        if not self.note_path.exists():
            return _Document(lines=[f"# {self.title}", ""], final_newline=True)
        text = self.note_path.read_text(encoding="utf-8")
        return _Document(
            lines=text.splitlines(), final_newline=text.endswith(("\n", "\r"))
        )

    def _read_registry(self) -> list[_RegistryItem]:
        if self.metadata_path is None or not self.metadata_path.exists():
            return []
        try:
            payload = json.loads(self.metadata_path.read_text(encoding="utf-8"))
            items = [
                _RegistryItem(
                    uid=self._valid_uid(item["uid"], required=True),
                    summary=str(item["summary"]),
                )
                for item in payload["items"]
            ]
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as err:
            raise MarkdownStoreError(
                f"Invalid task metadata: {self.metadata_path}"
            ) from err
        if len({item.uid for item in items}) != len(items):
            raise MarkdownStoreError(
                f"Duplicate IDs in task metadata: {self.metadata_path}"
            )
        return items

    def _write_document(self, document: _Document) -> None:
        text = "\n".join(document.lines)
        if document.final_newline and (document.lines or text):
            text += "\n"
        self._atomic_write(self.note_path, text)

    def _write_registry_if_changed(self, tasks: list[MarkdownTask]) -> None:
        registry = self._read_registry()
        desired = [_RegistryItem(task.uid, task.summary) for task in tasks]
        if registry != desired:
            self._write_registry(tasks)

    def _write_registry(self, tasks: list[MarkdownTask]) -> None:
        if self.metadata_path is None:
            return
        payload = {
            "version": 1,
            "note": str(self.note_path),
            "items": [
                {"uid": task.uid, "summary": task.summary} for task in tasks
            ],
        }
        self._atomic_write(
            self.metadata_path,
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        )

    @staticmethod
    def _atomic_write(path: Path, text: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        existing_stat = path.stat() if path.exists() else None
        temp_name: str | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                newline="\n",
                dir=path.parent,
                prefix=f".{path.name}.",
                suffix=".tmp",
                delete=False,
            ) as temporary:
                temp_name = temporary.name
                temporary.write(text)
                temporary.flush()
                os.fsync(temporary.fileno())
            if existing_stat is not None:
                os.chmod(temp_name, existing_stat.st_mode & 0o777)
                os.chown(temp_name, existing_stat.st_uid, existing_stat.st_gid)
            os.replace(temp_name, path)
            temp_name = None
        finally:
            if temp_name is not None:
                Path(temp_name).unlink(missing_ok=True)

    @staticmethod
    def _render_task(prefix: str, completed: bool, summary: str) -> str:
        status = "x" if completed else " "
        return f"{prefix}[{status}] {summary}"

    @staticmethod
    def _find(tasks: list[MarkdownTask], uid: str) -> MarkdownTask:
        for task in tasks:
            if task.uid == uid:
                return task
        raise ItemNotFoundError(f"Task UID not found: {uid}")

    @staticmethod
    def _valid_uid(uid: str | None, *, required: bool = False) -> str | None:
        if uid is None:
            if required:
                raise ValueError("Missing UID")
            return None
        try:
            return str(UUID(uid))
        except (AttributeError, TypeError, ValueError):
            if required:
                raise
            return None

    @staticmethod
    def _validate_summary(summary: str) -> str:
        clean = summary.strip()
        if not clean:
            raise MarkdownStoreError("Task summary cannot be empty")
        if "\n" in clean or "\r" in clean:
            raise MarkdownStoreError("Task summary must be a single line")
        if "<!-- ha-todo:" in clean:
            raise MarkdownStoreError("Task summary contains a legacy marker")
        return clean
