# UX v2 specification

## Primary navigation

The default workspace exposes four understandable destinations without removing advanced operations:

```text
Sessions  Activity  Health  Settings
```

Sessions remains the operational home. Activity, Health, and Settings become discoverable actions
first and dedicated workspaces as screens are extracted.

## Default action rail

Always-visible actions are limited to:

```text
Enter Attach/Open   C Create   / Search   F Filter   P Commands   ? Help   Esc Back
```

The existing advanced bindings remain available through help and the palette. They do not disappear;
they leave the first-time path.

## Contextual session actions

The selected-session action set is capability and state aware. Common actions are Attach, Details,
Logs, Edit, task-state changes, Pin, Restart, Stop, Archive, and Delete. Unavailable actions are
omitted or disabled with a reason before execution.

## Create flow

The default flow is Essentials → Task → Review. Essentials contains Tool, Project/Directory, and
Name. Task is optional. Review shows the exact tool command, directory, logging, and final action
before creation. Tags, presets, profiles, and startup controls remain under Advanced.

## Status language

The UI renders separate rows for Runtime, Task, Agent, Input, and Warnings. Icons are supplementary;
text and ASCII alternatives remain sufficient. Color is never the only status signal.

## Help and palette

`?` is contextual and searchable. `P` searches semantic command aliases such as `new`, `create`, and
`start session`, which all resolve to Session: Create. The palette is the home for rare federation,
migration, backup, and policy operations.

It also accepts normal workspace language: `activity` finds attention activity, `health` finds
system health, and `settings` finds interface settings.

## Responsive behavior

- Wide: list and inspector side by side.
- Medium: list and inspector share the viewport with reduced secondary detail.
- Narrow: list first; Enter opens an in-place detail view; Esc returns to the list.
- Very narrow: concise empty/fallback guidance, no clipped destructive controls.
