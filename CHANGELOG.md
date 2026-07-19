# Changelog

All notable changes follow Keep a Changelog. This project uses Semantic Versioning.

## [Unreleased]

### Added

- Exact-ID session adoption with private plans, sidecar hashes, journals, and batch rollback
- Read-only validation of reviewed plans against current tmux and sidecar state
- Managed-only default inventory with explicit unmanaged diagnostics
- Separately approved SSH-hook migration and seven-day preservation-copy retirement tools

### Changed

- Session ownership now requires a matching tmux owner marker in addition to metadata and tmux ID
- Sensitive tmux operations retain the verified session ID through the final tmux command
- Migration plans and journals are rejected unless their file permissions are owner-only
- Classic restore and retirement now require an owner-only, checksum-verified preservation copy;
  retirement also requires the new WF command to remain active
- Installer failures after adoption automatically roll back that exact migration until the WF command
  switch succeeds
- Cutover installation is serialized with an owner-only nonblocking process lock
- Removed the user-facing classic bridge from the Textual application and Typer CLI

## [0.1.0] - 2026-07-19

### Added

- Textual session dashboard and Typer CLI
- tmux-backed Claude, Codex, Hermes, and shell session creation
- Atomic Pydantic-validated state with tmux ID ownership enforcement
- Read-only legacy sidecar discovery
- Notes, tags, task states, pinning, rename, resume, inspect, and guarded delete
- CI, typed tests, real-tmux integration coverage, and security documentation
