# PRESETS — project preset groups for /docs-fetch

`/docs-fetch preset:<group>` expands a group to its alias list; each alias is then resolved
against the `docs-fetch` skill's alias tables (the single source of truth). Combine groups
with `+` (`/docs-fetch preset:web-frontend+python-api`); aliases are deduped before fetching.

**Every alias used below must exist in `SKILL.md`'s alias tables — add new aliases there,
not here.**

## Example groups

These are starter examples — edit them or add your own for the stacks you actually use.

| Group | Aliases |
|-------|---------|
| `web-frontend` | react-native, tailwind, typescript, zod |
| `python-api` | fastapi, pydantic, httpx, pytest |

## Add your own

1. Ensure each alias exists in `SKILL.md`'s alias tables (add the row if missing).
2. Add a row above mapping `<group>` → comma-separated alias list.

Tip: keep a group per project/stack you work on, so one `/docs-fetch preset:<group>` refreshes
all of that stack's docs in one command.
