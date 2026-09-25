"""Assembles a bounded AIContextPackage from ImpactResults — the targeted slice of the
repository handed to a BobProvider, never the whole repo."""

from repoflare_core.retrieval.context_retriever import ContextRetriever
from repoflare_core.retrieval.prompt import format_explain_prompt

__all__ = ["ContextRetriever", "format_explain_prompt"]
