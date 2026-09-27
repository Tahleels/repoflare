"""Entry point for `python -m repoflare_core.api` — the command the Render web service runs.

Reads PORT, which the platform assigns and routes external traffic to; binds 0.0.0.0 rather
than localhost so the instance is reachable from outside its own container.

The env overrides here are deployment settings, not product settings — set them on the
service, not in the repository (see render.yaml, where the defaults are the ones a free
instance needs).
"""

from __future__ import annotations

import logging
import os

from repoflare_core.api.server import ApiConfig, ApiOperations, RepoFlareHttpServer

_DEFAULT_HOST = "0.0.0.0"
_DEFAULT_PORT = 8000

logger = logging.getLogger(__name__)


def _positive_int_from_env(name: str) -> int | None:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return None
    try:
        value = int(raw)
    except ValueError:
        logger.warning("ignoring %s=%r: not a whole number", name, raw)
        return None
    if value <= 0:
        logger.warning("ignoring %s=%r: must be positive", name, raw)
        return None
    return value


def _config_from_env() -> ApiConfig:
    # Read defaults off an instance, not off ApiConfig itself: with slots=True the class
    # attributes are slot descriptors, not the field defaults.
    defaults = ApiConfig()
    return ApiConfig(
        clone_depth=_positive_int_from_env("REPOFLARE_CLONE_DEPTH") or defaults.clone_depth,
        max_files=_positive_int_from_env("REPOFLARE_MAX_FILES") or defaults.max_files,
        max_concurrency=(
            _positive_int_from_env("REPOFLARE_MAX_CONCURRENCY") or defaults.max_concurrency
        ),
    )


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    host = os.environ.get("REPOFLARE_HOST", "").strip() or _DEFAULT_HOST
    port = _positive_int_from_env("PORT") or _DEFAULT_PORT
    server = RepoFlareHttpServer((host, port), ApiOperations(_config_from_env()))

    logger.info("RepoFlare API listening on http://%s:%d", host, port)
    try:
        server.serve_forever()
    except KeyboardInterrupt:  # pragma: no cover — normal Ctrl-C shutdown
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
