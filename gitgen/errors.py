class GitError(RuntimeError):
    """Raised when a Git command cannot be completed."""


APP_ERRORS = (GitError, RuntimeError, ValueError, TypeError)
