# Themes

Workspace Session Manager owns its theme system and does not require Omarchy. Themes are data-only
semantic palettes; `colors.toml` files are parsed with Python's TOML reader and never imported or
executed.

## Commands

```bash
ws theme list
ws theme current
ws theme set auto
ws theme set omarchy
ws theme preview omarchy
ws theme doctor
```

`ws theme set` stores the selection in the owner-only interface-preferences file. It does not change
session state, tmux, or the main configuration file.

## Resolution

Effective selection follows this order:

1. `NO_COLOR=1` selects monochrome.
2. An explicit TUI/CLI theme request wins.
3. `WS_THEME` is used when the request is `auto`.
4. `interface.theme` in TOML is used when set.
5. `auto` reads the active Omarchy palette if available.
6. The built-in standalone fallback is used.

The current Omarchy palette is read from the data file under
`$XDG_STATE_HOME/omarchy/current/theme/colors.toml`, with the legacy
`~/.config/omarchy/current/theme/colors.toml` location as fallback. No graphical session, Wayland,
Hyprland, or Omarchy executable is required.

## Custom themes

Create:

```text
~/.config/workspace-session-manager/themes/<name>/colors.toml
```

Theme names use lowercase letters, digits, `_`, and `-`. At minimum, provide `background`,
`foreground`, and `accent`; missing semantic colors receive safe defaults.

```toml
mode = "dark"
background = "#101218"
foreground = "#e6edf3"
accent = "#f2a65a"
selection = "#2b3440"
muted = "#82909d"
red = "#ef6b73"
yellow = "#e9b44c"
green = "#72c78e"
cyan = "#8bd5ca"
blue = "#66aaff"
magenta = "#c792ea"
```

Symlinked theme directories/files and malformed palettes are ignored and reported through fallback
diagnostics. A theme cannot run code or provide subprocess commands.
