# Changelog

All notable changes follow Keep a Changelog. This project uses Semantic Versioning.

## [Unreleased]

### Added

- Exact-ID session adoption with private plans, sidecar hashes, journals, and batch rollback
- Managed-only default inventory with explicit unmanaged diagnostics
- Separately approved SSH-hook migration and seven-day preservation-copy retirement tools

### Changed

- Session ownership now requires a matching tmux owner marker in addition to metadata and tmux ID
- Removed the user-facing classic bridge from the Textual application and Typer CLI

## [0.1.0] - 2026-07-19

### Added

- Textual session dashboard and Typer CLI
- tmux-backed Claude, Codex, Hermes, and shell session creation
- Atomic Pydantic-validated state with tmux ID ownership enforcement
- Read-only legacy sidecar discovery
- Notes, tags, task states, pinning, rename, resume, inspect, and guarded delete
- CI, typed tests, real-tmux integration coverage, and security documentation
