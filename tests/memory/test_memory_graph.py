from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from pactlyn.memory.graph import (
    GraphEdgeKind,
    GraphFilter,
    GraphNodeKind,
    KnowledgeGraphRepository,
)
from pactlyn.storage.models import (
    Commitment,
    CommitmentEvent,
    CommitmentRelationship,
    CommitmentRelationshipType,
    CommitmentStatus,
    Contact,
    EmailAttachment,
    EmailMessage,
    EmailThread,
    MemoryKind,
    MemoryRecord,
)


def _seed_graph(session: Session) -> dict[str, str]:
    rahul = Contact(name="Rahul", email="rahul@example.com")
    professor = Contact(name="Professor", email="prof@example.edu")
    session.add_all([rahul, professor])
    session.flush()

    report = Commitment(
        title="Submit report",
        description="Final report for the course",
        status=CommitmentStatus.ACTIVE,
        person="Professor",
        contact_email="prof@example.edu",
        responsibility="USER_WAITING_FOR",
        evidence="I need the professor to approve my report.",
        source="test",
    )
    approval = Commitment(
        title="Professor approval",
        description="Approval of the final report",
        status=CommitmentStatus.WAITING,
        person="Professor",
        contact_email="prof@example.edu",
        responsibility="OTHER_PARTY_PERFORMS",
        evidence="Waiting for the professor to approve.",
        source="test",
    )
    proposal = Commitment(
        title="Send proposal",
        description="Send the project proposal to Rahul",
        status=CommitmentStatus.ACTIVE,
        person="Rahul",
        contact_email="rahul@example.com",
        responsibility="OTHER_PARTY_PERFORMS",
        evidence="Rahul is expected to send the proposal.",
        source="test",
    )
    session.add_all([report, approval, proposal])
    session.flush()

    session.add_all(
        [
            CommitmentRelationship(
                commitment_id=report.id,
                related_commitment_id=approval.id,
                relationship=CommitmentRelationshipType.BLOCKED_BY,
                confidence=0.92,
                evidence="The report depends on the professor's approval.",
                validation_status="validated",
            ),
            CommitmentRelationship(
                commitment_id=proposal.id,
                related_commitment_id=approval.id,
                relationship=CommitmentRelationshipType.FOLLOWED_BY,
                confidence=0.71,
                evidence="The proposal follows the approval.",
                validation_status="validated",
            ),
        ]
    )
    event = CommitmentEvent(
        commitment_id=report.id,
        event_type="created",
        detail="Captured from a note.",
    )
    session.add(event)

    thread = EmailThread(
        subject="Report questions",
        commitment_id=report.id,
        association_confidence=0.77,
        needs_review=False,
    )
    session.add(thread)
    session.flush()
    message = EmailMessage(
        thread_id=thread.id,
        sender="Rahul <rahul@example.com>",
        recipients=["Professor <prof@example.edu>"],
        subject="Report questions",
        body_text="Can we review the report before Friday?",
        received_at=datetime(2026, 11, 4, 10, 30),
    )
    session.add(message)
    session.flush()
    attachment = EmailAttachment(
        message_id=message.id,
        filename="brief.pdf",
        content_type="application/pdf",
        local_path="/tmp/brief.pdf",
        downloaded=True,
    )
    session.add(attachment)

    linked_memory = MemoryRecord(
        kind=MemoryKind.EPISODIC,
        content="The professor asked for the final report before Friday.",
        source_type="commitment",
        source_id=report.id,
        confidence=0.88,
    )
    email_memory = MemoryRecord(
        kind=MemoryKind.EPISODIC,
        content="Rahul asked about the report.",
        source_type="email",
        source_id=f"{message.id}:chunk:0",
        confidence=0.7,
    )
    orphan_memory = MemoryRecord(
        kind=MemoryKind.SEMANTIC,
        content="A free-standing idea about writing clearly.",
        source_type="note",
        source_id="note-1",
    )
    deleted_memory = MemoryRecord(
        kind=MemoryKind.SEMANTIC,
        content="This memory was deleted and must not appear.",
        source_type="note",
        source_id="note-2",
        deleted_at=datetime(2026, 11, 1),
    )
    session.add_all([linked_memory, email_memory, orphan_memory, deleted_memory])
    session.commit()
    return {
        "rahul": rahul.id,
        "professor": professor.id,
        "report": report.id,
        "approval": approval.id,
        "proposal": proposal.id,
        "thread": thread.id,
        "message": message.id,
        "attachment": attachment.id,
        "orphan_memory": orphan_memory.id,
    }


def _person_id(repository: KnowledgeGraphRepository, name: str) -> str:
    graph = repository.build()
    matches = [
        node
        for node in graph.nodes
        if node.kind == GraphNodeKind.PERSON and node.label == name
    ]
    assert len(matches) == 1
    return matches[0].id


def test_graph_construction_uses_canonical_records(session: Session) -> None:
    ids = _seed_graph(session)
    graph = KnowledgeGraphRepository(session).build()

    report = graph.node(f"commitment:{ids['report']}")
    approval = graph.node(f"commitment:{ids['approval']}")
    email = graph.node(f"email_thread:{ids['thread']}")
    document = graph.node(f"document:{ids['attachment']}")
    rahul = next(
        node
        for node in graph.nodes
        if node.kind == GraphNodeKind.PERSON and node.label == "Rahul"
    )
    professor = next(
        node
        for node in graph.nodes
        if node.kind == GraphNodeKind.PERSON and node.label == "Professor"
    )
    assert report is not None and approval is not None
    assert email is not None and document is not None
    assert report.label == "Submit report"
    assert report.status == "active"
    assert "blocked" in report.tags
    assert report.warning is True
    assert email.label == "Report questions"
    assert email.subtitle.startswith("Email · 1 message")
    assert document.subtitle.startswith("Document · application/pdf")
    assert sum(node.kind == GraphNodeKind.PERSON for node in graph.nodes) == 2

    blocked = [
        edge
        for edge in graph.edges_for(report.id, direction="out")
        if edge.kind == GraphEdgeKind.BLOCKED_BY
    ]
    assert len(blocked) == 1
    assert blocked[0].source_id == report.id
    assert blocked[0].target_id == approval.id
    assert blocked[0].evidence == "The report depends on the professor's approval."
    assert blocked[0].confidence == 0.92
    assert blocked[0].validation_status == "validated"

    person_edges = [
        edge
        for edge in graph.edges_for(professor.id, direction="out")
        if edge.kind == GraphEdgeKind.PERSON_PERFORMS_ACTION
    ]
    assert {edge.target_id for edge in person_edges} == {report.id, approval.id}

    email_commitment = [
        edge
        for edge in graph.edges_for(email.id, direction="out")
        if edge.kind == GraphEdgeKind.EMAIL_RELATES_TO_COMMITMENT
    ]
    assert len(email_commitment) == 1
    assert email_commitment[0].target_id == report.id

    sent = [
        edge
        for edge in graph.edges_for(rahul.id, direction="out")
        if edge.kind == GraphEdgeKind.PERSON_SENT_EMAIL
    ]
    assert len(sent) == 1
    assert sent[0].target_id == email.id
    received = [
        edge
        for edge in graph.edges_for(professor.id, direction="out")
        if edge.kind == GraphEdgeKind.PERSON_RECEIVES_EMAIL
    ]
    assert len(received) == 1
    assert received[0].target_id == email.id

    attachments = [
        edge
        for edge in graph.edges_for(email.id, direction="out")
        if edge.kind == GraphEdgeKind.HAS_ATTACHMENT
    ]
    assert len(attachments) == 1
    assert attachments[0].target_id == document.id

    memory_nodes = [node for node in graph.nodes if node.kind == GraphNodeKind.MEMORY]
    assert [node.id for node in memory_nodes] == [f"memory:{ids['orphan_memory']}"]
    assert any(
        label == "Memory evidence"
        for label, _value in report.details
    )
    assert graph.stats.people == 2
    assert graph.stats.active_commitments == 3
    assert graph.stats.waiting_for == 1
    assert graph.stats.blocked_commitments == 1
    assert graph.stats.connected_memories == 2
    assert graph.stats.total_memories == 3
    assert graph.stats.emails == 1
    assert graph.stats.events == 1
    assert graph.stats.documents == 1
    assert len(graph.records) == 3
    assert all("deleted" not in record.content for record in graph.records)
    assert len(graph.timeline) == 4
    assert len(graph.search("final report before Friday")) == 1
    assert graph.search("final report before Friday")[0].id == report.id


def test_graph_updates_after_commitment_changes(session: Session) -> None:
    ids = _seed_graph(session)
    repository = KnowledgeGraphRepository(session)
    first = repository.build()
    node_id = f"commitment:{ids['report']}"
    assert first.node(node_id) is not None

    report = session.get(Commitment, ids["report"])
    assert report is not None
    report.title = "Submit the final report"
    report.status = CommitmentStatus.COMPLETED
    session.commit()
    updated = repository.build()
    node = updated.node(node_id)
    assert node is not None
    assert node.label == "Submit the final report"
    assert node.completed is True
    assert "completed" in node.tags
    assert "active" not in node.tags
    blocked = [
        edge
        for edge in updated.edges_for(node_id, direction="out")
        if edge.kind == GraphEdgeKind.BLOCKED_BY
    ]
    assert len(blocked) == 1
    assert blocked[0].target_id == f"commitment:{ids['approval']}"

    session.delete(report)
    session.commit()
    deleted = repository.build()
    assert deleted.node(node_id) is None
    assert not any(
        edge.source_id == node_id or edge.target_id == node_id
        for edge in deleted.edges
    )


def test_relationship_correction_preserves_direction(session: Session) -> None:
    ids = _seed_graph(session)
    repository = KnowledgeGraphRepository(session)
    first = repository.build()
    report_id = f"commitment:{ids['report']}"
    approval_id = f"commitment:{ids['approval']}"
    original = next(
        edge
        for edge in first.edges_for(report_id, direction="out")
        if edge.kind == GraphEdgeKind.BLOCKED_BY
    )
    assert original.target_id == approval_id

    relationship = session.scalars(
        select(CommitmentRelationship).where(
            CommitmentRelationship.relationship
            == CommitmentRelationshipType.BLOCKED_BY
        )
    ).one()
    relationship.relationship = CommitmentRelationshipType.DEPENDS_ON
    relationship.evidence = "Corrected relationship evidence."
    session.commit()

    corrected = repository.build()
    edge = next(
        edge
        for edge in corrected.edges_for(report_id, direction="out")
        if edge.kind == GraphEdgeKind.DEPENDS_ON
    )
    assert edge.source_id == report_id
    assert edge.target_id == approval_id
    assert edge.evidence == "Corrected relationship evidence."
    assert not any(
        edge.kind == GraphEdgeKind.BLOCKED_BY
        for edge in corrected.edges_for(report_id, direction="out")
    )


def test_missing_related_records_become_independent_memory_nodes(session: Session) -> None:
    memory = MemoryRecord(
        kind=MemoryKind.SEMANTIC,
        content="A memory whose source no longer exists.",
        source_type="commitment",
        source_id="missing-commitment",
    )
    session.add(memory)
    session.commit()

    graph = KnowledgeGraphRepository(session).build()
    node = graph.node(f"memory:{memory.id}")
    assert node is not None
    assert node.kind == GraphNodeKind.MEMORY
    assert not graph.edges
    record = next(record for record in graph.records if record.id == memory.id)
    assert record.related_node_id == node.id
    assert record.related_label == "Independent memory"
    assert graph.stats.connected_memories == 0


def test_duplicate_associations_are_deduplicated(session: Session) -> None:
    contact = Contact(name="Rahul", email="rahul@example.com")
    commitment = Commitment(
        title="Send proposal",
        status=CommitmentStatus.ACTIVE,
        person="Rahul",
        contact_email="rahul@example.com",
        responsibility="OTHER_PARTY_PERFORMS",
    )
    session.add_all([contact, commitment])
    session.flush()
    thread = EmailThread(subject="Proposal", needs_review=False)
    session.add(thread)
    session.flush()
    session.add_all(
        [
            EmailMessage(
                thread_id=thread.id,
                sender="Rahul <rahul@example.com>",
                recipients=["me@example.com"],
                subject="Proposal",
                body_text="First message",
            ),
            EmailMessage(
                thread_id=thread.id,
                sender="Rahul <rahul@example.com>",
                recipients=["me@example.com"],
                subject="Re: Proposal",
                body_text="Second message",
            ),
        ]
    )
    related = Commitment(
        title="Review proposal",
        status=CommitmentStatus.ACTIVE,
        person="Rahul",
        contact_email="rahul@example.com",
        responsibility="USER_PERFORMS",
    )
    session.add(related)
    session.flush()
    session.add_all(
        [
            CommitmentRelationship(
                commitment_id=commitment.id,
                related_commitment_id=related.id,
                relationship=CommitmentRelationshipType.BLOCKED_BY,
            ),
            CommitmentRelationship(
                commitment_id=commitment.id,
                related_commitment_id=related.id,
                relationship=CommitmentRelationshipType.BLOCKED_BY,
            ),
        ]
    )
    session.commit()

    graph = KnowledgeGraphRepository(session).build()
    rahul = next(
        node
        for node in graph.nodes
        if node.kind == GraphNodeKind.PERSON and node.label == "Rahul"
    )
    assert sum(node.kind == GraphNodeKind.PERSON for node in graph.nodes) == 1
    sent_edges = [
        edge
        for edge in graph.edges
        if edge.kind == GraphEdgeKind.PERSON_SENT_EMAIL
        and edge.source_id == rahul.id
    ]
    assert len(sent_edges) == 1
    blocked_edges = [
        edge for edge in graph.edges if edge.kind == GraphEdgeKind.BLOCKED_BY
    ]
    assert len(blocked_edges) == 1
    assert blocked_edges[0].source_id == f"commitment:{commitment.id}"
    assert blocked_edges[0].target_id == f"commitment:{related.id}"
    assert not any(edge.source_id == edge.target_id for edge in graph.edges)


def test_graph_filter_and_search_semantics(session: Session) -> None:
    ids = _seed_graph(session)
    graph = KnowledgeGraphRepository(session).build()
    report = graph.node(f"commitment:{ids['report']}")
    approval = graph.node(f"commitment:{ids['approval']}")
    assert report is not None and approval is not None

    blocked_filter = GraphFilter(status="blocked")
    assert blocked_filter.allows_node(report)
    assert not blocked_filter.allows_node(approval)

    commitments_only = GraphFilter(
        node_kinds=frozenset({GraphNodeKind.COMMITMENT})
    )
    assert commitments_only.allows_node(report)
    assert not commitments_only.allows_node(
        next(node for node in graph.nodes if node.kind == GraphNodeKind.PERSON)
    )

    dependencies = GraphFilter(relationship_group="dependencies")
    assert any(
        dependencies.allows_edge(edge)
        for edge in graph.edges
        if edge.kind == GraphEdgeKind.BLOCKED_BY
    )
    assert not any(
        dependencies.allows_edge(edge)
        for edge in graph.edges
        if edge.kind == GraphEdgeKind.PERSON_SENT_EMAIL
    )
    assert any(
        node.kind == GraphNodeKind.MEMORY for node in graph.search("free-standing idea")
    )


def test_graph_enforces_a_total_node_limit_without_dangling_edges(
    session: Session,
) -> None:
    _seed_graph(session)
    graph = KnowledgeGraphRepository(session).build(max_nodes=3)
    assert len(graph.nodes) == 3
    assert graph.limited
    node_ids = {node.id for node in graph.nodes}
    assert all(
        edge.source_id in node_ids and edge.target_id in node_ids
        for edge in graph.edges
    )


def test_commitment_without_contact_does_not_fabricate_a_person(
    session: Session,
) -> None:
    session.add(
        Commitment(
            title="Book conference flights",
            status=CommitmentStatus.DUE_SOON,
            evidence="No contact is involved.",
        )
    )
    session.commit()
    graph = KnowledgeGraphRepository(session).build()
    assert [node for node in graph.nodes if node.kind == GraphNodeKind.PERSON] == []
    assert [node for node in graph.nodes if node.kind == GraphNodeKind.COMMITMENT]
    assert graph.stats.people == 0
