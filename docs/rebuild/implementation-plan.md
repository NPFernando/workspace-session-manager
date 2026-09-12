# Incremental implementation plan

Each phase must build, test, and remain usable.

1. **Baseline and contracts** — this assessment, branch, architecture, UX, compatibility, and agent
   guidance. No lifecycle behavior changes.
2. **Foundation** — typed app context seam, semantic errors at boundaries, theme package/provider
   interfaces, and package-resource tests.
3. **Theme subsystem** — built-ins, custom data-only palettes, optional Omarchy detection, terminal
   capability fallback, and `ws theme` commands.
4. **TUI shell** — extracted header/action/help/palette state while the existing screens remain
   available behind the same service façade.
5. **Sessions UX** — session list/row/details/empty-state widgets and contextual actions.
6. **Create/edit UX** — short wizard, review, advanced disclosure, actionable validation.
7. **Activity and health** — workspace navigation and unified warnings without duplicating workers.
8. **Grouped CLI** — `session`, `logs`, `config`, `theme`, `health`, `migration`, and `federation`
   namespaces as compatibility aliases.
9. **Cohesive extraction** — move service, CLI, and TUI workflows one at a time; retain old imports.
10. **Hardening/release** — clean install, package resource, security, migration, SSH, ASCII, no-color,
    isolated tmux, documentation, and release checks.

The first implementation slice in this branch is phase 2/3 foundation: data-only theme models,
provider selection, explicit context composition, theme CLI commands, and tests. The existing TUI
palette remains the compatibility fallback until the theme bridge is verified against all snapshots.
