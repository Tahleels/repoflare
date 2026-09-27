"""HTTP API layer: repoflare_core.service exposed to a hosted environment — see server.py's
module docstring for the endpoint list and the status-code contract."""

from repoflare_core.api.page import render_demo_page
from repoflare_core.api.server import (
    ApiConfig,
    ApiOperations,
    RemoteAnalysisOperations,
    RepoFlareHttpServer,
    RepoFlareRequestHandler,
)

__all__ = [
    "ApiConfig",
    "ApiOperations",
    "RemoteAnalysisOperations",
    "RepoFlareHttpServer",
    "RepoFlareRequestHandler",
    "render_demo_page",
]
