import warnings

warnings.warn(
    "The `fdc3` package is a migration shim that re-exports the existing"
    " packages `fdc3_client` and `fdc3_desktop_agent`. Import from the new"
    " `fdc3` namespace when available. This shim will be removed in a"
    " future release.",
    DeprecationWarning,
)

__all__ = []
