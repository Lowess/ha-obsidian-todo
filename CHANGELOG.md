# Changelog

## 0.2.0

- Keep stable task IDs in Home Assistant metadata instead of Markdown comments.
- Automatically remove and migrate identifiers written by version 0.1.
- Reconcile external Obsidian additions, status changes, renames, deletions,
  and reordering without adding visible metadata to the note.

## 0.1.0

- Expose one Markdown note as a native Home Assistant to-do entity.
- Add, rename, complete, reopen, and delete checkbox tasks.
- Preserve unrelated Markdown and add invisible UUID markers for stable IDs.
- Poll for external vault edits every 10 seconds.
- Support configuration from the Home Assistant UI.
