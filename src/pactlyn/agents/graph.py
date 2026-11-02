from __future__ import annotations

from collections.abc import Callable
from typing import Any

from langgraph.graph import END, START, StateGraph

from pactlyn.agents.state import PactlynState
from pactlyn.core.commitments import CommitmentExtractor


def build_capture_graph(
    *, extractor: CommitmentExtractor | None = None, persist: Callable[[PactlynState], str] | None = None
) -> Any:
    """Build the single stateful capture workflow.

    External effects are supplied as ``persist`` and therefore remain outside
    model execution. The graph stops with ``awaiting_confirmation`` when an
    extraction contains an uncertain field; the UI can resume it with
    ``confirmation=True`` in a later invocation.
    """

    extraction = extractor or CommitmentExtractor()

    def normalise(state: PactlynState) -> dict[str, object]:
        return {"input_text": state["input_text"].strip(), "status": "normalised", "errors": []}

    def extract(state: PactlynState) -> dict[str, object]:
        result = extraction.extract(state["input_text"], timezone_name=state.get("timezone", "UTC"))
        return {"candidates": result.candidates, "explanation": result.explanation, "status": "extracted"}

    def validate(state: PactlynState) -> dict[str, object]:
        candidates = state.get("candidates", [])
        if not candidates:
            return {"status": "invalid", "errors": ["No commitment was found"]}
        candidate = candidates[0]
        return {"selected_candidate": candidate, "needs_confirmation": candidate.needs_confirmation, "status": "validated"}

    def route(state: PactlynState) -> str:
        return "persist" if state.get("confirmation") or not state.get("needs_confirmation", True) else "approval"

    def approval(state: PactlynState) -> dict[str, object]:
        return {"status": "awaiting_confirmation"}

    def persist_node(state: PactlynState) -> dict[str, object]:
        if not persist:
            return {"status": "ready_to_persist"}
        identifier = persist(state)
        return {"status": "persisted", "run_id": identifier}

    workflow = StateGraph(PactlynState)
    workflow.add_node("normalise", normalise)
    workflow.add_node("extract", extract)
    workflow.add_node("validate", validate)
    workflow.add_node("approval", approval)
    workflow.add_node("persist", persist_node)
    workflow.add_edge(START, "normalise")
    workflow.add_edge("normalise", "extract")
    workflow.add_edge("extract", "validate")
    workflow.add_conditional_edges("validate", route, {"approval": "approval", "persist": "persist"})
    workflow.add_edge("approval", END)
    workflow.add_edge("persist", END)
    return workflow.compile()
