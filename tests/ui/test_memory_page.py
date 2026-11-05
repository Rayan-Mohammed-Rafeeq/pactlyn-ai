from __future__ import annotations

from datetime import date, datetime
from types import SimpleNamespace
from typing import Any

import pytest
from PySide6.QtCore import QPointF
from PySide6.QtWidgets import QGraphicsView, QPushButton
from sqlalchemy.orm import Session

from pactlyn.memory.graph import GraphEdgeKind, GraphNodeKind
from pactlyn.memory.semantic import SemanticMemoryHit
from pactlyn.storage.database import create_session_factory, init_database, make_engine
from pactlyn.storage.models import (
    Commitment,
    CommitmentEvent,
    CommitmentRelationship,
    CommitmentRelationshipType,
    CommitmentStatus,
    Contact,
    MemoryKind,
    MemoryRecord,
)
from pactlyn.ui.memory_page import NODE_WIDTH, MemoryPage


@pytest.fixture
def page_env(tmp_path: Any, qapp: object):
    engine = make_engine(f"sqlite:///{tmp_path / 'graph.sqlite3'}")
    init_database(engine)
    factory = create_session_factory(engine)
    session = factory()
    try:
        yield session, factory, qapp
    finally:
        session.close()
        engine.dispose()


def _page(factory: Any) -> MemoryPage:
    container = SimpleNamespace(session=factory)
    return MemoryPage(container)  # type: ignore[arg-type]


def _add_contact(session: Session, name: str, email: str) -> Contact:
    contact = Contact(name=name, email=email)
    session.add(contact)
    session.commit()
    return contact


def _seed_relationship(session: Session) -> tuple[Commitment, Commitment, Contact]:
    contact = Contact(name="Rahul", email="rahul@example.com")
    report = Commitment(
        title="Submit report",
        description="The final report",
        status=CommitmentStatus.ACTIVE,
        person="Rahul",
        contact_email="rahul@example.com",
        responsibility="USER_WAITING_FOR",
        evidence="Rahul needs to approve the report.",
        source="test",
    )
    approval = Commitment(
        title="Rahul approval",
        description="Approval of the report",
        status=CommitmentStatus.WAITING,
        person="Rahul",
        contact_email="rahul@example.com",
        responsibility="OTHER_PARTY_PERFORMS",
        evidence="Waiting for Rahul.",
        source="test",
    )
    session.add_all([contact, report, approval])
    session.flush()
    session.add(
        CommitmentRelationship(
            commitment_id=report.id,
            related_commitment_id=approval.id,
            relationship=CommitmentRelationshipType.BLOCKED_BY,
            confidence=0.9,
            evidence="The report is blocked by approval.",
            validation_status="validated",
        )
    )
    session.add(
        CommitmentEvent(
            commitment_id=report.id,
            event_type="created",
            detail="Captured from a note.",
        )
    )
    session.add(
        MemoryRecord(
            kind=MemoryKind.EPISODIC,
            content="Rahul needs to approve the final report.",
            source_type="commitment",
            source_id=report.id,
            confidence=0.8,
        )
    )
    session.add(
        MemoryRecord(
            kind=MemoryKind.SEMANTIC,
            content="A free-standing idea about writing clearly.",
            source_type="note",
            source_id="note-1",
        )
    )
    session.commit()
    return report, approval, contact


def _node_id(report: Commitment) -> str:
    return f"commitment:{report.id}"


def test_empty_state_and_actions(page_env: Any) -> None:
    session, factory, qapp = page_env
    page = _page(factory)
    assert page.graph.empty
    assert page.graph_stack.currentWidget() is page.empty_state
    assert page.graph_summary.text() == "No canonical records yet."

    events: list[object] = []
    page.createCommitmentRequested.connect(lambda: events.append("create"))
    page.navigateRequested.connect(lambda page_name, entity: events.append((page_name, entity)))
    buttons = page.empty_state.findChildren(QPushButton)
    create = next(button for button in buttons if "Create" in button.text())
    create.click()
    assistant = next(button for button in buttons if "Assistant" in button.text())
    assistant.click()
    assert events == ["create", ("assistant", "")]
    page.deleteLater()
    session.close()


def test_single_disconnected_node_and_details(page_env: Any) -> None:
    session, factory, qapp = page_env
    _add_contact(session, "Only Contact", "only@example.com")
    page = _page(factory)
    assert len(page.graph.nodes) == 1
    assert page.graph.nodes[0].kind == GraphNodeKind.PERSON
    assert not page.graph.edges
    assert page.graph_stack.currentWidget() is page.graph_splitter
    node_id = page.graph.nodes[0].id
    assert page.canvas.focus_node(node_id)
    qapp.processEvents()
    assert page.canvas.selected_node_id() == node_id
    text = page.graph_details.browser.toPlainText()
    assert "Only Contact" in text
    assert "only@example.com" in text
    assert page.graph_details.action_button.isHidden()
    page.deleteLater()
    session.close()


def test_edge_selection_and_search_focus(page_env: Any) -> None:
    session, factory, qapp = page_env
    report, approval, _contact = _seed_relationship(session)
    page = _page(factory)
    blocked = next(
        edge for edge in page.graph.edges if edge.kind == GraphEdgeKind.BLOCKED_BY
    )
    assert page.canvas.focus_edge(blocked.id)
    qapp.processEvents()
    assert page.canvas.selected_edge_id() == blocked.id
    text = page.graph_details.browser.toPlainText()
    assert "Blocked By" in text
    assert "The report is blocked by approval." in text
    assert "Supporting statement" in text

    page.search_input.setText("Rahul approval")
    page._focus_first_search_result()
    qapp.processEvents()
    assert page.canvas.selected_node_id() == _node_id(approval)
    assert page.tabs.currentWidget() is page.graph_tab
    page.deleteLater()
    session.close()


def test_filters_expand_and_collapse(page_env: Any) -> None:
    session, factory, qapp = page_env
    report, approval, _contact = _seed_relationship(session)
    page = _page(factory)
    report_id = _node_id(report)
    approval_id = _node_id(approval)
    assert page.canvas.focus_node(report_id)
    qapp.processEvents()
    assert page.canvas._node_items[approval_id].isVisible()
    assert page.canvas.collapse_selected()
    qapp.processEvents()
    assert not page.canvas._node_items[approval_id].isVisible()
    assert page.canvas.expand_selected()
    qapp.processEvents()
    assert page.canvas._node_items[approval_id].isVisible()

    page.node_filter_checks[GraphNodeKind.COMMITMENT].setChecked(False)
    qapp.processEvents()
    assert not page.canvas._node_items[report_id].isVisible()
    assert page.canvas.visible_node_count >= 1
    page.node_filter_checks[GraphNodeKind.COMMITMENT].setChecked(True)
    qapp.processEvents()

    blocked_index = page.status_combo.findData("blocked")
    page.status_combo.setCurrentIndex(blocked_index)
    qapp.processEvents()
    assert page.canvas._node_items[report_id].isVisible()
    assert not page.canvas._node_items[approval_id].isVisible()
    page.status_combo.setCurrentIndex(0)
    qapp.processEvents()

    dependency_index = page.relationship_combo.findData("dependencies")
    page.relationship_combo.setCurrentIndex(dependency_index)
    qapp.processEvents()
    visible_edge_kinds = {
        edge.kind
        for edge in page.graph.edges
        if page.canvas._edge_items[edge.id].isVisible()
    }
    assert GraphEdgeKind.BLOCKED_BY in visible_edge_kinds
    assert GraphEdgeKind.PERSON_PERFORMS_ACTION not in visible_edge_kinds
    page.deleteLater()
    session.close()


def test_records_and_timeline_filters(page_env: Any) -> None:
    session, factory, qapp = page_env
    _seed_relationship(session)
    page = _page(factory)
    assert page.records_list.count() == 2
    page.record_search.setText("free-standing")
    assert page.records_list.count() == 1
    item = page.records_list.item(0)
    assert item is not None
    page.records_list.setCurrentItem(item)
    qapp.processEvents()
    text = page.record_details.browser.toPlainText()
    assert "free-standing idea" in text
    assert "Provenance" in text

    page.record_search.clear()
    assert page.timeline_tree.topLevelItemCount() >= 1
    contact_index = page.timeline_contact.findData(page.graph.nodes[0].id)
    if contact_index < 0:
        contact_node = next(
            node for node in page.graph.nodes if node.kind == GraphNodeKind.PERSON
        )
        contact_index = page.timeline_contact.findData(contact_node.id)
    page.timeline_contact.setCurrentIndex(contact_index)
    qapp.processEvents()
    assert page.timeline_tree.topLevelItemCount() >= 1
    page._clear_timeline_filters()
    qapp.processEvents()
    assert page.timeline_tree.topLevelItemCount() >= 1

    memory_child = None
    for index in range(page.timeline_tree.topLevelItemCount()):
        group = page.timeline_tree.topLevelItem(index)
        for child_index in range(group.childCount()):
            child = group.child(child_index)
            if child.data(2, 0):
                memory_child = child
                break
        if memory_child is not None:
            break
    assert memory_child is not None
    page._timeline_item_activated(memory_child, 0)
    selected_record = page._selected_record_id()
    assert selected_record is not None
    assert page.tabs.currentWidget() is page.records_tab
    page.deleteLater()
    session.close()


def test_timeline_full_range_expands_after_older_record_is_added(
    page_env: Any,
) -> None:
    session, factory, qapp = page_env
    _seed_relationship(session)
    page = _page(factory)
    assert page.timeline_from.date().toPython() == date.today()

    session.add(
        MemoryRecord(
            kind=MemoryKind.SEMANTIC,
            content="An older memory added after the page was opened.",
            source_type="note",
            source_id="older-note",
            created_at=datetime(2025, 1, 2, 3, 4),
        )
    )
    session.commit()
    page.refresh()
    qapp.processEvents()

    assert page.timeline_from.date().toPython() == date(2025, 1, 2)
    assert page.timeline_to.date().toPython() == date.today()
    page.deleteLater()
    session.close()


def test_semantic_results_are_rendered_as_discovery_only(page_env: Any) -> None:
    session, factory, qapp = page_env
    report, _approval, _contact = _seed_relationship(session)
    page = _page(factory)
    page.search_input.setText("approval")
    page.semantic_check.setChecked(True)
    hit = SemanticMemoryHit(
        memory_id="memory-1",
        content="Rahul approved the report in a phone call.",
        source="Personal note",
        score=0.81,
        node_id=_node_id(report),
        related_label=report.title,
    )
    page._semantic_results("approval", (hit,))
    qapp.processEvents()
    assert not page.semantic_status.isHidden()
    texts = [
        page.search_results.item(index).text()
        for index in range(page.search_results.count())
    ]
    assert any("Related memories" in text for text in texts)
    assert any("phone call" in text for text in texts)
    assert page.graph.edges
    assert not any(
        edge.kind == GraphEdgeKind.HAS_MEMORY
        for edge in page.graph.edges
    )
    page.deleteLater()
    session.close()


def test_zoom_fit_reset_resize_and_theme(page_env: Any) -> None:
    session, factory, qapp = page_env
    _seed_relationship(session)
    page = _page(factory)
    page.resize(900, 700)
    qapp.processEvents()
    initial = {
        node_id: (item.pos().x(), item.pos().y())
        for node_id, item in page.canvas._node_items.items()
    }
    assert page.canvas.dragMode() == QGraphicsView.DragMode.ScrollHandDrag
    page.canvas.zoom_in()
    assert page.canvas.transform().m11() != 1.0
    page.canvas.zoom_out()
    page.canvas.fit_graph()
    assert page.canvas.transform().m11() > 0
    page.graph_canvas_reset()
    after_reset = {
        node_id: (item.pos().x(), item.pos().y())
        for node_id, item in page.canvas._node_items.items()
    }
    assert after_reset == initial
    page.resize(500, 420)
    qapp.processEvents()
    page.set_theme("dark")
    qapp.processEvents()
    assert all(item.mode == "dark" for item in page.canvas._node_items.values())
    page.deleteLater()
    session.close()


def test_long_labels_and_refresh_after_update(page_env: Any) -> None:
    session, factory, qapp = page_env
    long_name = "A Very Long Contact Name " * 6
    _add_contact(session, long_name.strip(), "long@example.com")
    report, approval, _contact = _seed_relationship(session)
    page = _page(factory)
    person = next(
        node for node in page.graph.nodes if node.kind == GraphNodeKind.PERSON
    )
    item = page.canvas._node_items[person.id]
    assert item.boundingRect().width() == NODE_WIDTH
    assert person.label in item.toolTip()
    moved = item.pos() + QPointF(24.0, 18.0)
    item.setPos(moved)

    report.title = "A corrected commitment title"
    report.status = CommitmentStatus.COMPLETED
    session.commit()
    page.refresh()
    qapp.processEvents()
    updated = page.graph.node(_node_id(report))
    assert updated is not None
    assert updated.label == "A corrected commitment title"
    assert updated.completed
    assert page.graph.node(_node_id(approval)) is not None
    assert page.canvas._node_items[person.id].pos() == moved
    page.deleteLater()
    session.close()


def test_node_action_navigation_signal(page_env: Any) -> None:
    session, factory, qapp = page_env
    report, _approval, _contact = _seed_relationship(session)
    page = _page(factory)
    requested: list[tuple[str, str]] = []
    page.navigateRequested.connect(lambda name, entity: requested.append((name, entity)))
    node_id = _node_id(report)
    assert page.canvas.focus_node(node_id)
    qapp.processEvents()
    assert not page.graph_details.action_button.isHidden()
    page.graph_details.action_button.click()
    assert requested == [("commitments", report.id)]
    page.deleteLater()
    session.close()


def test_memory_page_renders_visual_graph(page_env: Any, tmp_path: Any) -> None:
    session, factory, qapp = page_env
    report, _approval, _contact = _seed_relationship(session)
    page = _page(factory)
    page.resize(1100, 760)
    page.show()
    qapp.processEvents()
    assert page.canvas.focus_node(_node_id(report))
    qapp.processEvents()
    image = page.grab().toImage()
    assert not image.isNull()
    colors = {
        image.pixelColor(x, y).name()
        for x in range(0, image.width(), 17)
        for y in range(0, image.height(), 17)
    }
    assert len(colors) >= 12
    screenshot = tmp_path / "memory-page.png"
    assert image.save(str(screenshot))
    assert screenshot.stat().st_size > 10_000
    page.hide()
    page.deleteLater()
    session.close()
