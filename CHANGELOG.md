# Changelog

All notable changes follow Keep a Changelog. This project uses Semantic Versioning.

## [Unreleased]

### Added

- Centered diagnostics, create-session, filtering, onboarding, help, and protected management flows
- Inline create validation, duplicate detection, Git project discovery, recent directories, logging
  controls, and exact command previews
- Optional owner-only sanitized tmux logging with bounded log and pane views
- Structured usage-limit activity warnings, advanced details, diagnostics export, and stopped-session
  recovery
- Dark, light, monochrome, `NO_COLOR`, and ASCII presentation modes
- Snapshot coverage for dialogs, validation failures, usage warnings, destructive confirmation, light
  mode, and inventories of 50 and 200 sessions

### Changed

- Rebuilt the inspector into Overview, Status, Activity, Recent Output, and Actions containers
- Made session grouping canonical so a session appears only once; recent activity is now a filter
- Renamed `d More` to `d Manage` and separated ordinary operations from protected operations
- Refined 160, 120, 100, and 80-column layouts, fixed-width tool badges, activity times, and headers
- Restored `--classic` only as a guarded compatibility bridge to an owner-only preserved executable

## [0.2.0] - 2026-07-20

### Added

- Responsive Textual dashboard modes for wide, medium, narrow, and undersized terminals
- Grouped two-line session rows, contextual help, full log view, and explicit task/input metadata
- Protected More Actions and exact-name deletion dialogs with Cancel focused by default
- Deterministic Textual snapshots and before/after screenshots at four terminal sizes
- Temporary tmux socket paths for isolated real-backend integration tests
- Exact-ID session adoption with private plans, sidecar hashes, journals, and batch rollback
- Read-only validation of reviewed plans against current tmux and sidecar state
- Managed-only default inventory with explicit unmanaged diagnostics
- Separately approved SSH-hook migration and seven-day preservation-copy retirement tools

### Changed

- Replaced the permanent search field with `/`-activated search and cancellable filter editing
- Separated tmux runtime health from user-assigned task and input states
- Pane output is now constrained by both line and byte limits after sanitization and redaction
- Metadata writes use schema v2 while schema-v1 task values remain readable
- Session ownership now requires a matching tmux owner marker in addition to metadata and tmux ID
- Sensitive tmux operations retain the verified session ID through the final tmux command
- Migration plans and journals are rejected unless their file permissions are owner-only
- Classic restore and retirement now require an owner-only, checksum-verified preservation copy;
  retirement also requires the new WF command to remain active
- Installer failures after adoption automatically roll back that exact migration until the WF command
  switch succeeds
- Cutover installation is serialized with an owner-only nonblocking process lock
- Install and command rollback replace the WF symlink atomically and never overwrite a command backup
- Classic retirement verifies the archived executable payload before deletion and writes a relocatable
  archive checksum
- Textual filtering clears hidden selections and renders explicit empty or no-match states
- Removed classic actions from the Textual application and normal Typer command surface

## [0.1.0] - 2026-07-19

### Added

- Textual session dashboard and Typer CLI
- tmux-backed Claude, Codex, Hermes, and shell session creation
- Atomic Pydantic-validated state with tmux ID ownership enforcement
- Read-only legacy sidecar discovery
- Notes, tags, task states, pinning, rename, resume, inspect, and guarded delete
- CI, typed tests, real-tmux integration coverage, and security documentation
