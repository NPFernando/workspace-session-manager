"""Domain-specific errors with safe, user-facing messages."""


class WsError(Exception):
    """Base class for expected application failures."""


class ConfigurationError(WsError):
    """Configuration is missing or invalid."""


class TmuxError(WsError):
    """A tmux operation failed."""


class SessionNotFoundError(WsError):
    """The requested tmux session does not exist."""


class SessionExistsError(WsError):
    """A tmux session already uses the requested name."""


class OwnershipError(WsError):
    """A mutation was rejected because ws does not own the session."""


class ToolUnavailableError(WsError):
    """The configured agent command is unavailable."""


class StateError(WsError):
    """Persisted application state is corrupt or unavailable."""


class MigrationError(WsError):
    """A session adoption plan is invalid, stale, or unsafe to apply."""
