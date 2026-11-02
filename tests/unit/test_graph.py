from pactlyn.agents.graph import build_capture_graph


def test_langgraph_stops_for_ambiguous_capture():
    graph = build_capture_graph()
    result = graph.invoke({"input_text": "I should deal with the project", "timezone": "UTC"})
    assert result["status"] == "awaiting_confirmation"


def test_langgraph_persists_after_confirmation():
    persisted: list[str] = []
    graph = build_capture_graph(persist=lambda state: persisted.append(state["selected_candidate"].title) or "run-1")
    result = graph.invoke({"input_text": "Finish the report tomorrow", "timezone": "UTC", "confirmation": True})
    assert result["status"] == "persisted"
    assert persisted
