# TUI Screenshots

`before/` preserves the prior reviewed dashboard at `160x45`, `120x35`, `100x30`, and `80x24`.
`after/` contains the current deterministic frames at the same terminal sizes. `states/` contains
focused review frames for the normal dashboard, usage-limit warning, create validation success and
failure, expanded Create advanced options, diagnostics running and completed, and reduced-motion
mode. It also includes Filter, session-aware Command Palette, responsive and filtered Manage states,
disabled action reasons, identity and status forms, and protected Confirmation workflows.
`logs/` contains the reviewed Logs workspace at `160x45`, `120x35`, `100x30`, and `80x24`.
The focused state set also includes Saved output, find mode, a structured usage warning, and an inline
read failure with retry guidance.
`details/` contains the reviewed in-place narrow inspector at `80x24` and `99x30`, plus warning,
failure, and long-content states.
`attention/` contains reviewed scan-progress, warning-only, responsive, and completed-clear states.

All current frames use the fake backend and synthetic values. The SVGs do not connect to tmux or
contain operational session data.
