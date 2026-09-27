"""RepoFlare Governance Audit subsystem.

Exposes the GovernanceEngine and the public finding/report types.  Everything in this
package is intentionally separate from the code-intelligence core (scanning, graph, impact)
so the governance subsystem can be used standalone or composed — depending on how much
local repository context is available.
"""

from repoflare_core.governance.engine import GovernanceEngine, GovernanceEngineConfig

__all__ = ["GovernanceEngine", "GovernanceEngineConfig"]
