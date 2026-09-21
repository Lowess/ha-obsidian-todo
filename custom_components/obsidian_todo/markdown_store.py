"""Read and update Markdown checkbox tasks without an Obsidian runtime."""

from __future__ import annotations

import os
import re
import tempfile
from dataclasses import dataclass
from pathlib import Path
from threading import RLock
from uuid import UUID, uuid4

UID_MARKER = "ha-todo"
TASK_RE = re.compile(
    r"^(?P<prefix>\s*[-*+]\s+)"
    r"\[(?P<status>[ xX])\]\s+"
    r"(?P<summary>.*?)"
    r"(?:\s+<!--\s*ha-todo:(?P<uid>[0-9a-fA-F-]{36})\s*-->)?\s*$"
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


@dataclass(slots=True)
class _Document:
    lines: list[str]
    final_newline: bool


class MarkdownTodoStore:
    """Manage checkbox tasks in one Markdown note."""

    def __init__(self, vault_path: str, note_path: str, title: str) -> None:
        self.vault_path = Path(vault_path).expanduser().resolve()
        relative_note = Path(note_path)
        if relative_note.is_absolute() or ".." in relative_note.parts:
            raise InvalidPathError("The note path must be relative to the vault")

        self.note_path = (self.vault_path / relative_note).resolve()
        if not self.note_path.is_relative_to(self.vault_path):
            raise InvalidPathError("The note path resolves outside the vault")

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
        """Load tasks and assign stable IDs to tasks that do not have one."""
        with self._lock:
            document = self._read_document()
            tasks, changed = self._parse_and_normalize(document)
            if changed:
                self._write_document(document)
            return tasks

    def add(self, summary: str) -> list[MarkdownTask]:
        """Append a new incomplete task."""
        clean_summary = self._validate_summary(summary)
        with self._lock:
            document = self._read_document()
            self._parse_and_normalize(document)
            if document.lines and document.lines[-1].strip():
                document.lines.append("")
            document.lines.append(
                self._render_task("- ", False, clean_summary, str(uuid4()))
            )
            document.final_newline = True
            self._write_document(document)
            return self._parse_and_normalize(document)[0]

    def update(
        self, uid: str, *, summary: str | None = None, completed: bool | None = None
    ) -> list[MarkdownTask]:
        """Update a task by stable UID."""
        with self._lock:
            document = self._read_document()
            tasks, _ = self._parse_and_normalize(document)
            task = self._find(tasks, uid)
            new_summary = (
                task.summary if summary is None else self._validate_summary(summary)
            )
            new_completed = task.completed if completed is None else completed
            document.lines[task.line_index] = self._render_task(
                task.prefix, new_completed, new_summary, task.uid
            )
            self._write_document(document)
            return self._parse_and_normalize(document)[0]

    def delete(self, uids: list[str]) -> list[MarkdownTask]:
        """Delete tasks by stable UID."""
        with self._lock:
            document = self._read_document()
            tasks, normalized = self._parse_and_normalize(document)
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
            if indexes or normalized:
                self._write_document(document)
            return self._parse_and_normalize(document)[0]

    def _read_document(self) -> _Document:
        if not self.note_path.exists():
            return _Document(lines=[f"# {self.title}", ""], final_newline=True)
        text = self.note_path.read_text(encoding="utf-8")
        return _Document(
            lines=text.splitlines(), final_newline=text.endswith(("\n", "\r"))
        )

    def _write_document(self, document: _Document) -> None:
        self.note_path.parent.mkdir(parents=True, exist_ok=True)
        text = "\n".join(document.lines)
        if document.final_newline and (document.lines or text):
            text += "\n"

        existing_mode = (
            self.note_path.stat().st_mode & 0o777 if self.note_path.exists() else None
        )
        temp_name: str | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                newline="\n",
                dir=self.note_path.parent,
                prefix=f".{self.note_path.name}.",
                suffix=".tmp",
                delete=False,
            ) as temporary:
                temp_name = temporary.name
                temporary.write(text)
                temporary.flush()
                os.fsync(temporary.fileno())
            if existing_mode is not None:
                os.chmod(temp_name, existing_mode)
            os.replace(temp_name, self.note_path)
            temp_name = None
        finally:
            if temp_name is not None:
                Path(temp_name).unlink(missing_ok=True)

    def _parse_and_normalize(
        self, document: _Document
    ) -> tuple[list[MarkdownTask], bool]:
        tasks: list[MarkdownTask] = []
        seen: set[str] = set()
        changed = False
        for line_index, line in enumerate(document.lines):
            match = TASK_RE.match(line)
            if not match:
                continue

            uid = match.group("uid")
            try:
                valid_uid = str(UUID(uid)) if uid else None
            except ValueError:
                valid_uid = None
            if valid_uid is None or valid_uid in seen:
                valid_uid = str(uuid4())
                changed = True

            summary = match.group("summary").strip()
            completed = match.group("status").lower() == "x"
            prefix = match.group("prefix")
            normalized_line = self._render_task(
                prefix, completed, summary, valid_uid
            )
            if normalized_line != line:
                document.lines[line_index] = normalized_line
                changed = True

            seen.add(valid_uid)
            tasks.append(
                MarkdownTask(
                    uid=valid_uid,
                    summary=summary,
                    completed=completed,
                    line_index=line_index,
                    prefix=prefix,
                )
            )
        return tasks, changed

    @staticmethod
    def _render_task(prefix: str, completed: bool, summary: str, uid: str) -> str:
        status = "x" if completed else " "
        return f"{prefix}[{status}] {summary} <!-- {UID_MARKER}:{uid} -->"

    @staticmethod
    def _find(tasks: list[MarkdownTask], uid: str) -> MarkdownTask:
        for task in tasks:
            if task.uid == uid:
                return task
        raise ItemNotFoundError(f"Task UID not found: {uid}")

    @staticmethod
    def _validate_summary(summary: str) -> str:
        clean = summary.strip()
        if not clean:
            raise MarkdownStoreError("Task summary cannot be empty")
        if "\n" in clean or "\r" in clean:
            raise MarkdownStoreError("Task summary must be a single line")
        if "<!-- ha-todo:" in clean:
            raise MarkdownStoreError("Task summary contains a reserved marker")
        return clean
