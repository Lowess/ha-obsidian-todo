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

Each checkbox gets an invisible stable identifier:

```markdown
- [ ] Milk <!-- ha-todo:3d64bd38-8c8b-47a5-91be-56df0fdd8cf5 -->
```

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

Back up the note before first use. On the first read, the integration adds an
HTML comment containing a UUID to every checkbox that does not already have one.

## Development

Run the storage tests without a Home Assistant installation:

```bash
python3 -m unittest discover -s tests -v
```
