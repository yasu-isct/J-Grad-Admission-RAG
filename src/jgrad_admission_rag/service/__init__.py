"""Optional local HTTP service. Install with ``.[service]`` before importing."""

try:
    from .app import create_app
except ModuleNotFoundError as error:
    if error.name and (error.name == "fastapi" or error.name.startswith("starlette")):
        raise ImportError(
            'J-Grad HTTP service dependencies are optional; install with ".[service]"'
        ) from None
    raise

from .runtime import ServiceDependencies, ServiceSettings
from .contracts import ApplicantReportRequest, ApplicantReportResponse

__all__ = [
    "ApplicantReportRequest",
    "ApplicantReportResponse",
    "ServiceDependencies",
    "ServiceSettings",
    "create_app",
]
