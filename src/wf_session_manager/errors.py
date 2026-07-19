"""Domain-specific errors with safe, user-facing messages."""


class WFError(Exception):
    """Base class for expected application failures."""


class ConfigurationError(WFError):
    """Configuration is missing or invalid."""


class TmuxError(WFError):
    """A tmux operation failed."""


class SessionNotFoundError(WFError):
    """The requested tmux session does not exist."""


class SessionExistsError(WFError):
    """A tmux session already uses the requested name."""


class OwnershipError(WFError):
    """A mutation was rejected because WF does not own the session."""


class ToolUnavailableError(WFError):
    """The configured agent command is unavailable."""


class StateError(WFError):
    """Persisted application state is corrupt or unavailable."""
