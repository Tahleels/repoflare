from repoflare_core.domain.entities import AIContextPackage
from repoflare_core.retrieval.prompt import format_explain_prompt


def _context(**overrides: object) -> AIContextPackage:
    defaults: dict[str, object] = {
        "context_id": "ctx1",
        "change_set_id": "cs1",
        "snippets": {"a.py": "[a.py#L1-L2]\ndef helper():\n    pass"},
        "graph_paths": [],
        "direct_dependents": ["b_entry"],
        "relevant_tests": [],
    }
    defaults.update(overrides)
    return AIContextPackage(**defaults)  # type: ignore[arg-type]


def test_prompt_includes_citation_tag_and_instruction() -> None:
    prompt = format_explain_prompt(_context())

    assert "[a.py#L1-L2]" in prompt
    assert "never invent a tag" in prompt


def test_prompt_lists_direct_dependents() -> None:
    prompt = format_explain_prompt(_context())

    assert "Directly affected symbols: b_entry" in prompt


def test_prompt_handles_no_direct_dependents() -> None:
    prompt = format_explain_prompt(_context(direct_dependents=[]))

    assert "Directly affected symbols: none" in prompt
