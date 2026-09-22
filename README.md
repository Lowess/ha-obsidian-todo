# Obsidian Markdown To-do for Home Assistant

[![Validate](https://github.com/Lowess/ha-obsidian-todo/actions/workflows/validate.yml/badge.svg)](https://github.com/Lowess/ha-obsidian-todo/actions/workflows/validate.yml)
[![GitHub release](https://img.shields.io/github/v/release/Lowess/ha-obsidian-todo)](https://github.com/Lowess/ha-obsidian-todo/releases)

This custom integration exposes Markdown checkbox tasks from one Obsidian note
as a native Home Assistant `todo` entity. It reads and writes the vault directly;
Obsidian, `obscli`, and a REST service are not required on the Home Assistant host.

## Current scope

- Add tasks.
- Rename tasks.
- Mark tasks complete or incomplete.
- Delete tasks.
- Detect external edits on a 10-second polling interval.
- Preserve non-task Markdown content.
- Keep HA task IDs outside the Obsidian vault note.

The Markdown remains clean and can be edited normally in Obsidian:

```markdown
- [ ] Milk
- [x] Coffee
```

Home Assistant keeps stable IDs in `/config/.obsidian_todo/`, not in the
vault. Existing `<!-- ha-todo:... -->` markers created by version 0.1 are
removed automatically and their IDs are preserved during migration.

## Install with HACS

1. Open HACS in Home Assistant.
2. Select **Integrations**.
3. Open the three-dot menu and select **Custom repositories**.
4. Add `https://github.com/Lowess/ha-obsidian-todo` with category
   **Integration**.
5. Search for **Obsidian Markdown To-do** and install it.
6. Restart Home Assistant.

## Configure

1. Mount the vault read/write inside the Home Assistant container. Example:

   ```yaml
   volumes:
     - /mnt/user/appdata/obsidian/vault:/vault
   ```

2. Open **Settings → Devices & services → Add integration**.
3. Search for **Obsidian Markdown To-do**.
4. Enter `/vault` as the vault directory and, for example,
   `Lists/Shopping.md` as the note path.
5. Add the resulting `todo` entity to a To-do List dashboard card.

## Manual installation

Copy `custom_components/obsidian_todo` into Home Assistant's
`/config/custom_components/` directory and restart Home Assistant.

## Backup

Back up the note before first use. The integration updates checkbox lines when
tasks are changed from Home Assistant.

## Development

Run the storage tests without a Home Assistant installation:

```bash
python3 -m unittest discover -s tests -v
```
