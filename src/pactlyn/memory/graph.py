from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import UTC, datetime
from email.utils import parseaddr
from enum import StrEnum
from typing import Literal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from pactlyn.email.addresses import email_address, split_address
from pactlyn.storage.models import (
    Commitment,
    CommitmentEvent,
    CommitmentRelationship,
    CommitmentStatus,
    Contact,
    EmailAttachment,
    EmailMessage,
    EmailSendAction,
    EmailState,
    EmailThread,
    MemoryRecord,
    PersonalFact,
    PersonalFactCategory,
    PersonalFactConfirmationState,
)

TERMINAL_STATUSES = frozenset({CommitmentStatus.COMPLETED, CommitmentStatus.CANCELLED})
ACTIVE_STATUSES = frozenset(
    {
        CommitmentStatus.DRAFT,
        CommitmentStatus.NEEDS_CONFIRMATION,
        CommitmentStatus.ACTIVE,
        CommitmentStatus.WAITING,
        CommitmentStatus.RESPONSE_RECEIVED,
        CommitmentStatus.DUE_SOON,
        CommitmentStatus.OVERDUE,
        CommitmentStatus.POSTPONED,
    }
)


class GraphNodeKind(StrEnum):
    PERSON = "person"
    COMMITMENT = "commitment"
    PROJECT = "project"
    EMAIL = "email"
    EVENT = "event"
    DOCUMENT = "document"
    MEMORY = "memory"
    PERSONAL_FACT = "personal_fact"


class GraphEdgeKind(StrEnum):
    BLOCKED_BY = "BLOCKED_BY"
    DEPENDS_ON = "DEPENDS_ON"
    FOLLOWED_BY = "FOLLOWED_BY"
    RESPONSE_REQUIRED_FROM = "RESPONSE_REQUIRED_FROM"
    RELATED_TO = "RELATED_TO"
    SUPERSEDES = "SUPERSEDES"
    PERSON_PERFORMS_ACTION = "PERSON_PERFORMS_ACTION"
    PERSON_RECEIVES_EMAIL = "PERSON_RECEIVES_EMAIL"
    PERSON_SENT_EMAIL = "PERSON_SENT_EMAIL"
    EMAIL_RELATES_TO_COMMITMENT = "EMAIL_RELATES_TO_COMMITMENT"
    CONTACT_ASSOCIATED_WITH_PROJECT = "CONTACT_ASSOCIATED_WITH_PROJECT"
    HAS_EVENT = "HAS_EVENT"
    HAS_ATTACHMENT = "HAS_ATTACHMENT"
    HAS_MEMORY = "HAS_MEMORY"
    # Personal-fact edges
    HAS_BIRTHDAY = "HAS_BIRTHDAY"
    HAS_IDENTITY = "HAS_IDENTITY"
    STUDIES_AT = "STUDIES_AT"
    WORKS_ON = "WORKS_ON"
    PREFERS = "PREFERS"
    HAS_CONTACT_INFO = "HAS_CONTACT_INFO"
    HAS_PERSONAL_FACT = "HAS_PERSONAL_FACT"


EDGE_LABELS: dict[GraphEdgeKind, str] = {
    GraphEdgeKind.BLOCKED_BY: "blocked by",
    GraphEdgeKind.DEPENDS_ON: "depends on",
    GraphEdgeKind.FOLLOWED_BY: "followed by",
    GraphEdgeKind.RESPONSE_REQUIRED_FROM: "response required from",
    GraphEdgeKind.RELATED_TO: "related to",
    GraphEdgeKind.SUPERSEDES: "supersedes",
    GraphEdgeKind.PERSON_PERFORMS_ACTION: "responsible for",
    GraphEdgeKind.PERSON_RECEIVES_EMAIL: "received",
    GraphEdgeKind.PERSON_SENT_EMAIL: "sent",
    GraphEdgeKind.EMAIL_RELATES_TO_COMMITMENT: "relates to",
    GraphEdgeKind.CONTACT_ASSOCIATED_WITH_PROJECT: "associated with project",
    GraphEdgeKind.HAS_EVENT: "event",
    GraphEdgeKind.HAS_ATTACHMENT: "has attachment",
    GraphEdgeKind.HAS_MEMORY: "memory",
    GraphEdgeKind.HAS_BIRTHDAY: "birthday",
    GraphEdgeKind.HAS_IDENTITY: "identity",
    GraphEdgeKind.STUDIES_AT: "studies at",
    GraphEdgeKind.WORKS_ON: "works on",
    GraphEdgeKind.PREFERS: "prefers",
    GraphEdgeKind.HAS_CONTACT_INFO: "contact info",
    GraphEdgeKind.HAS_PERSONAL_FACT: "personal fact",
}

RELATIONSHIP_GROUPS: dict[str, frozenset[GraphEdgeKind]] = {
    "dependencies": frozenset({GraphEdgeKind.BLOCKED_BY, GraphEdgeKind.DEPENDS_ON}),
    "waiting": frozenset(
        {
            GraphEdgeKind.RESPONSE_REQUIRED_FROM,
            GraphEdgeKind.PERSON_PERFORMS_ACTION,
        }
    ),
    "follow_ups": frozenset({GraphEdgeKind.FOLLOWED_BY}),
    "superseded": frozenset({GraphEdgeKind.SUPERSEDES}),
    "personal_facts": frozenset(
        {
            GraphEdgeKind.HAS_BIRTHDAY,
            GraphEdgeKind.HAS_IDENTITY,
            GraphEdgeKind.STUDIES_AT,
            GraphEdgeKind.WORKS_ON,
            GraphEdgeKind.PREFERS,
            GraphEdgeKind.HAS_CONTACT_INFO,
            GraphEdgeKind.HAS_PERSONAL_FACT,
        }
    ),
    "associations": frozenset(
        {
            GraphEdgeKind.RELATED_TO,
            GraphEdgeKind.PERSON_RECEIVES_EMAIL,
            GraphEdgeKind.PERSON_SENT_EMAIL,
            GraphEdgeKind.EMAIL_RELATES_TO_COMMITMENT,
            GraphEdgeKind.CONTACT_ASSOCIATED_WITH_PROJECT,
            GraphEdgeKind.HAS_EVENT,
            GraphEdgeKind.HAS_ATTACHMENT,
            GraphEdgeKind.HAS_MEMORY,
        }
    ),
}

NODE_KIND_ORDER: dict[GraphNodeKind, int] = {
    GraphNodeKind.PERSON: 0,
    GraphNodeKind.COMMITMENT: 1,
    GraphNodeKind.PERSONAL_FACT: 2,
    GraphNodeKind.PROJECT: 3,
    GraphNodeKind.EMAIL: 4,
    GraphNodeKind.EVENT: 5,
    GraphNodeKind.DOCUMENT: 6,
    GraphNodeKind.MEMORY: 7,
}

_EVENT_TITLES = {
    "created": "Commitment captured",
    "confirmed": "Commitment confirmed",
    "completed": "Commitment completed",
    "cancelled": "Commitment cancelled",
    "updated": "Commitment updated",
    "postponed": "Commitment postponed",
    "incoming_reply": "Reply received",
}


@dataclass(frozen=True)
class GraphNode:
    id: str
    kind: GraphNodeKind
    label: str
    subtitle: str
    entity_id: str | None = None
    status: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    details: tuple[tuple[str, str], ...] = ()
    developer: tuple[tuple[str, str], ...] = ()
    search_text: str = ""
    tags: frozenset[str] = frozenset()
    warning: bool = False
    completed: bool = False


@dataclass(frozen=True)
class GraphEdge:
    id: str
    source_id: str
    target_id: str
    kind: GraphEdgeKind
    label: str
    evidence: str = ""
    confidence: float | None = None
    validation_status: str = ""
    origin: str = ""
    developer: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True)
class GraphRecord:
    id: str
    content: str
    kind: str
    source: str
    created_at: datetime | None
    related_node_id: str | None
    related_label: str
    provenance: str
    source_type: str = ""
    source_id: str = ""
    developer: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True)
class GraphTimelineItem:
    id: str
    timestamp: datetime | None
    title: str
    detail: str
    group: str
    node_id: str | None = None
    commitment_id: str | None = None
    person_node_id: str | None = None
    memory_id: str | None = None
    source: str = ""


@dataclass(frozen=True)
class GraphStats:
    people: int = 0
    active_commitments: int = 0
    waiting_for: int = 0
    blocked_commitments: int = 0
    connected_memories: int = 0
    total_memories: int = 0
    emails: int = 0
    events: int = 0
    documents: int = 0
    edges: int = 0
    personal_facts: int = 0


@dataclass(frozen=True)
class GraphFilter:
    node_kinds: frozenset[GraphNodeKind] = field(default_factory=lambda: frozenset(GraphNodeKind))
    status: str | None = None
    relationship_group: str | None = None

    def allows_node(self, node: GraphNode) -> bool:
        if node.kind not in self.node_kinds:
            return False
        if self.status and node.kind == GraphNodeKind.COMMITMENT:
            return self.status in node.tags
        return True

    def allows_edge(self, edge: GraphEdge) -> bool:
        if not self.relationship_group:
            return True
        return edge.kind in RELATIONSHIP_GROUPS.get(self.relationship_group, frozenset())


@dataclass(frozen=True)
class KnowledgeGraph:
    nodes: tuple[GraphNode, ...] = ()
    edges: tuple[GraphEdge, ...] = ()
    records: tuple[GraphRecord, ...] = ()
    timeline: tuple[GraphTimelineItem, ...] = ()
    stats: GraphStats = field(default_factory=GraphStats)
    limited: bool = False

    @property
    def empty(self) -> bool:
        return not self.nodes

    def node(self, node_id: str) -> GraphNode | None:
        for node in self.nodes:
            if node.id == node_id:
                return node
        return None

    def edges_for(
        self,
        node_id: str,
        *,
        direction: Literal["in", "out", "both"] = "both",
    ) -> tuple[GraphEdge, ...]:
        edges: list[GraphEdge] = []
        for edge in self.edges:
            incoming = edge.target_id == node_id
            outgoing = edge.source_id == node_id
            if direction == "both" and (incoming or outgoing):
                edges.append(edge)
            elif direction == "in" and incoming:
                edges.append(edge)
            elif direction == "out" and outgoing:
                edges.append(edge)
        return tuple(edges)

    def neighbours(self, node_id: str) -> tuple[GraphNode, ...]:
        identifiers = {
            edge.target_id if edge.source_id == node_id else edge.source_id
            for edge in self.edges_for(node_id)
        }
        return tuple(node for node in self.nodes if node.id in identifiers)

    def search(self, query: str) -> tuple[GraphNode, ...]:
        term = query.strip().casefold()
        if not term:
            return ()
        matches: list[tuple[int, int, str, GraphNode]] = []
        for node in self.nodes:
            haystack = (
                f"{node.label} {node.subtitle} {node.search_text} "
                f"{' '.join(node.tags)}"
            ).casefold()
            if term not in haystack:
                continue
            starts = 0 if node.label.casefold().startswith(term) else 1
            matches.append((starts, NODE_KIND_ORDER[node.kind], node.label.casefold(), node))
        matches.sort(key=lambda item: (item[0], item[1], item[2]))
        return tuple(item[3] for item in matches)


@dataclass
class _NodeDraft:
    id: str
    kind: GraphNodeKind
    label: str
    subtitle: str
    entity_id: str | None = None
    status: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    details: list[tuple[str, str]] = field(default_factory=list)
    developer: list[tuple[str, str]] = field(default_factory=list)
    search_parts: list[str] = field(default_factory=list)
    tags: set[str] = field(default_factory=set)
    warning: bool = False
    completed: bool = False

    def to_node(self) -> GraphNode:
        return GraphNode(
            id=self.id,
            kind=self.kind,
            label=self.label,
            subtitle=self.subtitle,
            entity_id=self.entity_id,
            status=self.status,
            created_at=self.created_at,
            updated_at=self.updated_at,
            details=tuple(self.details),
            developer=tuple(self.developer),
            search_text=" ".join(dict.fromkeys(part for part in self.search_parts if part)),
            tags=frozenset(self.tags),
            warning=self.warning,
            completed=self.completed,
        )


def _normalise_name(name: str | None) -> str:
    return " ".join((name or "").split()).casefold()


def _person_key(name: str | None, email: str | None) -> str:
    address = email_address(email)
    if address:
        digest = hashlib.sha1(address.encode("utf-8")).hexdigest()[:16]
        return f"person:email:{digest}"
    normalised = _normalise_name(name)
    digest = hashlib.sha1(normalised.encode("utf-8")).hexdigest()[:16]
    return f"person:name:{digest}"


def _person_display_name(name: str | None, email: str | None) -> str:
    cleaned = " ".join((name or "").split())
    if cleaned:
        return cleaned
    parsed_name, parsed_email = split_address(email)
    return parsed_name or parsed_email or "Unknown person"


def _format_datetime(value: datetime | None) -> str:
    if value is None:
        return "Not recorded"
    if value.tzinfo is not None:
        value = value.astimezone()
    return value.strftime("%d %b %Y, %H:%M")


def _format_date(value: datetime | None) -> str:
    if value is None:
        return "No date"
    if value.tzinfo is not None:
        value = value.astimezone()
    return value.strftime("%d %b %Y")


def _status_label(value: CommitmentStatus) -> str:
    return value.value.replace("_", " ").title()


def _recency_key(value: datetime | None) -> str:
    return value.strftime("%Y%m%d%H%M%S") if value is not None else ""


def _source_label(source_type: str) -> str:
    labels = {
        "commitment": "Commitment evidence",
        "email": "Email message",
        "note": "Personal note",
        "contact": "Contact record",
        "document": "Document",
    }
    return labels.get(source_type, source_type.replace("_", " ").title() or "Memory")


def _event_title(event_type: str) -> str:
    return _EVENT_TITLES.get(event_type, event_type.replace("_", " ").title())


def _edge_id(kind: GraphEdgeKind, source_id: str, target_id: str) -> str:
    digest = hashlib.sha1(f"{source_id}|{kind.value}|{target_id}".encode()).hexdigest()
    return f"edge:{digest[:20]}"


def _truncate(value: str, limit: int = 160) -> str:
    text = " ".join(value.split())
    if len(text) <= limit:
        return text
    return f"{text[: limit - 1].rstrip()}…"


class KnowledgeGraphRepository:
    """Build a typed presentation graph from canonical SQLite records.

    The graph is deliberately derived only from stored records and foreign
    keys. Semantic vector similarity never becomes an edge here.
    """

    def __init__(self, session: Session):
        self.session = session

    def build(self, *, max_nodes: int = 600) -> KnowledgeGraph:
        now = datetime.now(UTC).replace(tzinfo=None)
        people: dict[str, _NodeDraft] = {}
        people_by_email: dict[str, str] = {}
        people_by_name: dict[str, str] = {}
        people_by_contact_id: dict[str, str] = {}
        commitments: dict[str, _NodeDraft] = {}
        emails: dict[str, _NodeDraft] = {}
        events: dict[str, _NodeDraft] = {}
        documents: dict[str, _NodeDraft] = {}
        memories: dict[str, _NodeDraft] = {}
        personal_facts_nodes: dict[str, _NodeDraft] = {}
        edges: dict[str, GraphEdge] = {}
        records: list[GraphRecord] = []
        timeline: list[GraphTimelineItem] = []

        def add_edge(edge: GraphEdge) -> None:
            if edge.source_id == edge.target_id:
                return
            if edge.source_id not in all_node_ids() or edge.target_id not in all_node_ids():
                return
            edges.setdefault(edge.id, edge)

        def all_node_ids() -> set[str]:
            return {
                *people,
                *commitments,
                *emails,
                *events,
                *documents,
                *memories,
                *personal_facts_nodes,
            }

        def person_key_for(name: str | None, email: str | None) -> str | None:
            address = email_address(email)
            if address and address in people_by_email:
                return people_by_email[address]
            normalised = _normalise_name(name)
            if normalised and normalised in people_by_name:
                return people_by_name[normalised]
            return None

        def ensure_person(
            name: str | None,
            email: str | None,
            *,
            contact_id: str | None = None,
            notes: str = "",
            created_at: datetime | None = None,
        ) -> str:
            address = email_address(email)
            normalised_name = _normalise_name(name)
            email_key = _person_key(name, address) if address else None
            name_key = people_by_name.get(normalised_name) if normalised_name else None
            if email_key and email_key in people:
                key = email_key
            elif name_key and name_key in people:
                key = name_key
            elif email_key:
                key = email_key
            elif name_key:
                key = name_key
            else:
                key = _person_key(name, address)
            draft = people.get(key)
            if draft is None:
                label = _person_display_name(name, address)
                draft = _NodeDraft(
                    id=key,
                    kind=GraphNodeKind.PERSON,
                    label=label,
                    subtitle=address or "Person",
                    entity_id=contact_id,
                    created_at=created_at,
                    details=[],
                    developer=[],
                    search_parts=[label, address],
                )
                people[key] = draft
            elif address and draft.subtitle in {"", "Person"}:
                draft.subtitle = address
            if address:
                people_by_email.setdefault(address, key)
            if normalised_name:
                people_by_name.setdefault(normalised_name, key)
            if contact_id:
                people_by_contact_id[contact_id] = key
                draft.entity_id = contact_id

            def add_detail(label: str, value: str) -> None:
                if value and not any(existing == label for existing, _item in draft.details):
                    draft.details.append((label, value))

            if address:
                draft.search_parts.append(address)
                add_detail("Email", address)
            if name:
                draft.search_parts.append(name)
            if contact_id:
                add_detail("Notes", notes or "No notes.")
                add_detail("Added", _format_datetime(created_at))
                draft.developer.append(("Contact ID", contact_id))
            if created_at:
                draft.created_at = draft.created_at or created_at
            return key

        contacts = list(
            self.session.scalars(select(Contact).order_by(Contact.name).limit(max_nodes))
        )
        for contact in contacts:
            if contact.name or contact.email:
                ensure_person(
                    contact.name,
                    contact.email,
                    contact_id=contact.id,
                    notes=contact.notes,
                    created_at=contact.created_at,
                )

        commitments_query = (
            select(Commitment)
            .order_by(Commitment.created_at.desc())
            .limit(max_nodes)
        )
        commitment_rows = list(self.session.scalars(commitments_query))
        commitment_by_id = {commitment.id: commitment for commitment in commitment_rows}
        for commitment in commitment_rows:
            status_label = _status_label(commitment.status)
            subtitle_parts = [status_label]
            if commitment.due_at:
                subtitle_parts.append(f"due {_format_date(commitment.due_at)}")
            if commitment.person:
                subtitle_parts.append(commitment.person)
            tags = {commitment.status.value}
            active = commitment.status not in TERMINAL_STATUSES
            if active:
                tags.add("active")
            if commitment.status == CommitmentStatus.WAITING:
                tags.add("waiting")
            if commitment.status == CommitmentStatus.OVERDUE or (
                active and commitment.due_at is not None and commitment.due_at < now
            ):
                tags.add("overdue")
            if commitment.status == CommitmentStatus.COMPLETED:
                tags.add("completed")
            if commitment.status == CommitmentStatus.CANCELLED:
                tags.add("cancelled")
            draft = _NodeDraft(
                id=f"commitment:{commitment.id}",
                kind=GraphNodeKind.COMMITMENT,
                label=commitment.title,
                subtitle=" · ".join(part for part in subtitle_parts if part),
                entity_id=commitment.id,
                status=commitment.status.value,
                created_at=commitment.created_at,
                updated_at=commitment.updated_at,
                details=[
                    ("Description", commitment.description or "No description."),
                    ("Status", status_label),
                    (
                        "Review",
                        "Needs confirmation"
                        if commitment.needs_confirmation
                        else "Confirmed",
                    ),
                    ("Type", commitment.type.value.replace("_", " ").title()),
                    ("Due", _format_datetime(commitment.due_at)),
                    ("Responsible", commitment.person or "You"),
                    ("Recipient", commitment.contact_email or "Not set"),
                    ("Responsibility", commitment.responsibility.replace("_", " ").title()),
                    ("Condition", commitment.condition or "None"),
                    ("Evidence", commitment.evidence or commitment.source_span or "No supporting statement recorded."),
                    ("Created", _format_datetime(commitment.created_at)),
                ],
                developer=[
                    ("Commitment ID", commitment.id),
                    ("Event ID", commitment.event_id or ""),
                    ("Source", commitment.source),
                    ("Source span", commitment.source_span),
                    ("Confidence", f"{commitment.confidence:.2f}"),
                    ("Needs confirmation", "yes" if commitment.needs_confirmation else "no"),
                ],
                search_parts=[
                    commitment.title,
                    commitment.description,
                    commitment.person or "",
                    commitment.contact_email or "",
                    commitment.evidence,
                    commitment.object or "",
                    commitment.actor or "",
                    commitment.condition or "",
                ],
                tags=tags,
                warning="overdue" in tags,
                completed=commitment.status == CommitmentStatus.COMPLETED,
            )
            commitments[draft.id] = draft
            person_key = (
                ensure_person(
                    commitment.person,
                    commitment.contact_email,
                    created_at=commitment.created_at,
                )
                if commitment.person or commitment.contact_email
                else None
            )
            if person_key:
                if commitment.responsibility in {
                    "OTHER_PARTY_PERFORMS",
                    "USER_WAITING_FOR",
                } or (
                    commitment.type.value == "waiting_for"
                    and commitment.responsibility == "UNKNOWN"
                ):
                    add_edge(
                        GraphEdge(
                            id=_edge_id(
                                GraphEdgeKind.PERSON_PERFORMS_ACTION,
                                person_key,
                                draft.id,
                            ),
                            source_id=person_key,
                            target_id=draft.id,
                            kind=GraphEdgeKind.PERSON_PERFORMS_ACTION,
                            label=EDGE_LABELS[GraphEdgeKind.PERSON_PERFORMS_ACTION],
                            origin="person_commitment",
                            developer=(
                                ("Origin", "Commitment person and responsibility"),
                                ("Responsibility", commitment.responsibility),
                            ),
                        )
                    )
                elif commitment.responsibility == "USER_CONTACTS":
                    add_edge(
                        GraphEdge(
                            id=_edge_id(
                                GraphEdgeKind.PERSON_PERFORMS_ACTION,
                                person_key,
                                draft.id,
                            ),
                            source_id=person_key,
                            target_id=draft.id,
                            kind=GraphEdgeKind.PERSON_PERFORMS_ACTION,
                            label="needs contact",
                            origin="person_commitment",
                            developer=(
                                ("Origin", "Commitment person and responsibility"),
                                ("Responsibility", commitment.responsibility),
                            ),
                        )
                    )
                else:
                    add_edge(
                        GraphEdge(
                            id=_edge_id(GraphEdgeKind.RELATED_TO, draft.id, person_key),
                            source_id=draft.id,
                            target_id=person_key,
                            kind=GraphEdgeKind.RELATED_TO,
                            label="involves",
                            origin="person_commitment",
                            developer=(
                                ("Origin", "Commitment person association"),
                                ("Responsibility", commitment.responsibility),
                            ),
                        )
                    )

        relationships = list(
            self.session.scalars(
                select(CommitmentRelationship)
                .where(CommitmentRelationship.validation_status != "rejected")
                .limit(max_nodes * 5)
            )
        )
        for relationship in relationships:
            source_id = f"commitment:{relationship.commitment_id}"
            target_id = f"commitment:{relationship.related_commitment_id}"
            if source_id not in commitments or target_id not in commitments:
                continue
            kind = GraphEdgeKind(relationship.relationship.value)
            add_edge(
                GraphEdge(
                    id=_edge_id(kind, source_id, target_id),
                    source_id=source_id,
                    target_id=target_id,
                    kind=kind,
                    label=EDGE_LABELS[kind],
                    evidence=relationship.evidence,
                    confidence=relationship.confidence,
                    validation_status=relationship.validation_status,
                    origin="commitment_relationship",
                    developer=(
                        ("Relationship ID", relationship.id),
                        ("Validation", relationship.validation_status),
                        ("Confidence", f"{relationship.confidence:.2f}"),
                    ),
                )
            )
            if kind in {GraphEdgeKind.BLOCKED_BY, GraphEdgeKind.DEPENDS_ON}:
                target = commitment_by_id.get(relationship.related_commitment_id)
                if target and target.status not in TERMINAL_STATUSES:
                    commitments[source_id].tags.add("blocked")
                    commitments[source_id].warning = True

        thread_rows = list(
            self.session.scalars(
                select(EmailThread).order_by(EmailThread.created_at.desc()).limit(max_nodes)
            )
        )
        thread_ids = [thread.id for thread in thread_rows]
        messages: list[EmailMessage] = []
        if thread_ids:
            messages = list(
                self.session.scalars(
                    select(EmailMessage)
                    .where(EmailMessage.thread_id.in_(thread_ids))
                    .order_by(EmailMessage.received_at)
                    .limit(max_nodes * 6)
                )
            )
        messages_by_thread: dict[str, list[EmailMessage]] = {}
        for message in messages:
            messages_by_thread.setdefault(message.thread_id, []).append(message)

        actions: list[EmailSendAction] = []
        if thread_ids:
            actions = list(
                self.session.scalars(
                    select(EmailSendAction)
                    .where(EmailSendAction.thread_id.in_(thread_ids))
                    .order_by(EmailSendAction.updated_at.desc())
                    .limit(max_nodes)
                )
            )
        actions_by_thread: dict[str, EmailSendAction] = {}
        for action in actions:
            if action.thread_id and action.thread_id not in actions_by_thread:
                actions_by_thread[action.thread_id] = action

        email_node_by_message: dict[str, str] = {}
        for thread in thread_rows:
            thread_messages = messages_by_thread.get(thread.id, [])
            latest_action = actions_by_thread.get(thread.id)
            if not thread_messages and latest_action is None:
                continue
            node_id = f"email_thread:{thread.id}"
            participants: list[str] = []
            search_parts = [thread.subject]
            participant_edges: list[GraphEdge] = []
            for message in thread_messages:
                sender_name, sender_email = parseaddr(message.sender)
                sender_key = person_key_for(sender_name, sender_email)
                if sender_key:
                    participant_edges.append(
                        GraphEdge(
                            id=_edge_id(GraphEdgeKind.PERSON_SENT_EMAIL, sender_key, node_id),
                            source_id=sender_key,
                            target_id=node_id,
                            kind=GraphEdgeKind.PERSON_SENT_EMAIL,
                            label=EDGE_LABELS[GraphEdgeKind.PERSON_SENT_EMAIL],
                            origin="email_participant",
                        )
                    )
                for recipient in message.recipients:
                    recipient_name, recipient_email = parseaddr(recipient)
                    recipient_key = person_key_for(recipient_name, recipient_email)
                    if recipient_key:
                        participant_edges.append(
                            GraphEdge(
                                id=_edge_id(
                                    GraphEdgeKind.PERSON_RECEIVES_EMAIL,
                                    recipient_key,
                                    node_id,
                                ),
                                source_id=recipient_key,
                                target_id=node_id,
                                kind=GraphEdgeKind.PERSON_RECEIVES_EMAIL,
                                label=EDGE_LABELS[GraphEdgeKind.PERSON_RECEIVES_EMAIL],
                                origin="email_participant",
                            )
                        )
                sender_label = _person_display_name(sender_name, sender_email)
                if sender_label and sender_label not in participants:
                    participants.append(sender_label)
                for recipient in message.recipients:
                    name, address = parseaddr(recipient)
                    label = _person_display_name(name, address)
                    if label and label not in participants:
                        participants.append(label)
                search_parts.extend([message.sender, *message.recipients, message.subject, message.body_text])
                email_node_by_message[message.id] = node_id
            latest = thread_messages[-1] if thread_messages else None
            status = (
                latest_action.state.value
                if latest_action is not None
                else "thread"
            )
            subtitle_parts = [
                f"Email · {len(thread_messages)} message"
                + ("" if len(thread_messages) == 1 else "s")
            ]
            if thread.needs_review:
                subtitle_parts.append("needs review")
            elif latest_action is not None:
                subtitle_parts.append(latest_action.state.value.replace("_", " ").title())
            related_commitment = (
                thread.commitment_id
                or (latest_action.commitment_id if latest_action is not None else None)
            )
            senders = list(
                dict.fromkeys(
                    _person_display_name(*parseaddr(message.sender))
                    for message in thread_messages
                )
            )
            recipients = list(
                dict.fromkeys(
                    _person_display_name(*parseaddr(recipient))
                    for message in thread_messages
                    for recipient in message.recipients
                )
            )
            details: list[tuple[str, str]] = [
                ("Subject", thread.subject or "(no subject)"),
                ("Messages", str(len(thread_messages))),
                ("Senders", ", ".join(senders) or "No senders recorded"),
                ("Recipients", ", ".join(recipients) or "No recipients recorded"),
                ("Participants", ", ".join(participants) or "No participants recorded"),
                ("Latest", _format_datetime(latest.received_at if latest else thread.created_at)),
                ("Review", "Needs review" if thread.needs_review else "Reviewed"),
            ]
            if latest_action is not None:
                details.extend(
                    [
                        ("Delivery status", latest_action.state.value.replace("_", " ").title()),
                        ("Approved", "yes" if latest_action.approval_hash else "no"),
                    ]
                )
                if latest_action.last_error:
                    details.append(("Last error", latest_action.last_error))
            if latest and latest.body_text:
                details.append(("Latest message", _truncate(latest.body_text, 360)))
            draft = _NodeDraft(
                id=node_id,
                kind=GraphNodeKind.EMAIL,
                label=thread.subject or "(no subject)",
                subtitle=" · ".join(subtitle_parts),
                entity_id=thread.id,
                status=status,
                created_at=thread.created_at,
                updated_at=latest.received_at if latest else thread.created_at,
                details=details,
                developer=[
                    ("Thread ID", thread.id),
                    ("Provider thread ID", thread.provider_thread_id or ""),
                    ("Association confidence", f"{thread.association_confidence:.2f}"),
                ],
                search_parts=search_parts,
                warning=thread.needs_review,
            )
            if isinstance(status, str) and status == EmailState.CANCELLED.value:
                draft.tags.add("cancelled")
            emails[node_id] = draft
            for participant_edge in participant_edges:
                add_edge(participant_edge)
            if related_commitment:
                commitment_node_id = f"commitment:{related_commitment}"
                if commitment_node_id in commitments:
                    add_edge(
                        GraphEdge(
                            id=_edge_id(
                                GraphEdgeKind.EMAIL_RELATES_TO_COMMITMENT,
                                node_id,
                                commitment_node_id,
                            ),
                            source_id=node_id,
                            target_id=commitment_node_id,
                            kind=GraphEdgeKind.EMAIL_RELATES_TO_COMMITMENT,
                            label=EDGE_LABELS[GraphEdgeKind.EMAIL_RELATES_TO_COMMITMENT],
                            evidence=thread.subject,
                            confidence=thread.association_confidence,
                            validation_status="reviewed"
                            if not thread.needs_review
                            else "needs_review",
                            origin="email_thread_commitment",
                            developer=(
                                ("Origin", "Email thread commitment association"),
                                ("Needs review", "yes" if thread.needs_review else "no"),
                            ),
                        )
                    )
                    draft.details.append(
                        (
                            "Related commitment",
                            commitments[commitment_node_id].label,
                        )
                    )

        message_ids = [message.id for message in messages]
        attachment_rows: list[EmailAttachment] = []
        if message_ids:
            attachment_rows = list(
                self.session.scalars(
                    select(EmailAttachment)
                    .where(EmailAttachment.message_id.in_(message_ids))
                    .order_by(EmailAttachment.filename)
                    .limit(max_nodes * 2)
                )
            )
        message_thread = {message.id: message.thread_id for message in messages}
        for attachment in attachment_rows:
            thread_id = message_thread.get(attachment.message_id)
            if not thread_id:
                continue
            node_id = f"document:{attachment.id}"
            email_node_id = f"email_thread:{thread_id}"
            if email_node_id not in emails:
                continue
            documents[node_id] = _NodeDraft(
                id=node_id,
                kind=GraphNodeKind.DOCUMENT,
                label=attachment.filename or "Attachment",
                subtitle=(
                    f"Document · {attachment.content_type}"
                    + (" · downloaded" if attachment.downloaded else "")
                ),
                entity_id=attachment.id,
                details=[
                    ("Filename", attachment.filename or "Attachment"),
                    ("Content type", attachment.content_type),
                    ("Downloaded", "yes" if attachment.downloaded else "no"),
                    ("Attached to", emails[email_node_id].label),
                ],
                developer=[
                    ("Attachment ID", attachment.id),
                    ("Local path", attachment.local_path or ""),
                ],
                search_parts=[attachment.filename, attachment.content_type],
            )
            add_edge(
                GraphEdge(
                    id=_edge_id(GraphEdgeKind.HAS_ATTACHMENT, email_node_id, node_id),
                    source_id=email_node_id,
                    target_id=node_id,
                    kind=GraphEdgeKind.HAS_ATTACHMENT,
                    label=EDGE_LABELS[GraphEdgeKind.HAS_ATTACHMENT],
                    origin="email_attachment",
                )
            )

        event_rows = list(
            self.session.scalars(
                select(CommitmentEvent)
                .order_by(CommitmentEvent.created_at.desc())
                .limit(max_nodes * 8)
            )
        )
        event_count_by_commitment: dict[str, int] = {}
        # Audit-only event types are recorded in the timeline but must NOT
        # appear as standalone graph nodes.  Only meaningful state-change
        # events (confirmed, completed, cancelled, postponed, incoming_reply)
        # produce visual nodes so the graph represents knowledge, not activity.
        _GRAPH_EVENT_TYPES = frozenset(
            {"confirmed", "completed", "cancelled", "postponed", "incoming_reply"}
        )
        for event in event_rows:
            commitment_node_id = f"commitment:{event.commitment_id}"
            if commitment_node_id not in commitments:
                continue
            event_count_by_commitment[event.commitment_id] = (
                event_count_by_commitment.get(event.commitment_id, 0) + 1
            )
            # Only materialise meaningful events as graph nodes; skip audit events.
            if (
                event.event_type in _GRAPH_EVENT_TYPES
                and event_count_by_commitment[event.commitment_id] <= 3
            ):
                node_id = f"event:{event.id}"
                events[node_id] = _NodeDraft(
                    id=node_id,
                    kind=GraphNodeKind.EVENT,
                    label=_event_title(event.event_type),
                    subtitle=f"Event · {_format_datetime(event.created_at)}",
                    entity_id=event.id,
                    status=event.event_type,
                    created_at=event.created_at,
                    details=[
                        ("Event", _event_title(event.event_type)),
                        ("When", _format_datetime(event.created_at)),
                        ("Commitment", commitments[commitment_node_id].label),
                        ("Detail", event.detail or "No additional detail."),
                    ],
                    developer=[
                        ("Event ID", event.id),
                        ("Commitment ID", event.commitment_id),
                        ("Event type", event.event_type),
                    ],
                    search_parts=[event.event_type, event.detail, commitments[commitment_node_id].label],
                    tags={"event"},
                )
                add_edge(
                    GraphEdge(
                        id=_edge_id(GraphEdgeKind.HAS_EVENT, commitment_node_id, node_id),
                        source_id=commitment_node_id,
                        target_id=node_id,
                        kind=GraphEdgeKind.HAS_EVENT,
                        label=EDGE_LABELS[GraphEdgeKind.HAS_EVENT],
                        evidence=event.detail,
                        origin="commitment_event",
                        developer=(
                            ("Event ID", event.id),
                            ("Event type", event.event_type),
                        ),
                    )
                )
            event_commitment = commitment_by_id.get(event.commitment_id)
            if event_commitment is None:
                continue
            event_person_key: str | None = (
                people_by_email.get(email_address(event_commitment.contact_email))
                if event_commitment.contact_email
                else None
            )
            if event_person_key is None and event_commitment.person:
                event_person_key = people_by_name.get(_normalise_name(event_commitment.person))
            timeline.append(
                GraphTimelineItem(
                    id=f"event:{event.id}",
                    timestamp=event.created_at,
                    title=f"{_event_title(event.event_type)} · {event_commitment.title}",
                    detail=event.detail or "No additional detail.",
                    group="Commitment event",
                    node_id=commitment_node_id,
                    commitment_id=event_commitment.id,
                    person_node_id=event_person_key,
                    source="Commitment",
                )
            )

        memory_rows = list(
            self.session.scalars(
                select(MemoryRecord)
                .where(MemoryRecord.deleted_at.is_(None))
                .order_by(MemoryRecord.created_at.desc())
                .limit(max_nodes * 5)
            )
        )
        linked_memory_count = 0
        for record in memory_rows:
            related_node_id = self._related_memory_node(
                record,
                commitments=commitments,
                emails=emails,
                email_node_by_message=email_node_by_message,
                documents=documents,
                people_by_contact_id=people_by_contact_id,
            )
            related_label = ""
            linked_memory = related_node_id is not None
            if related_node_id:
                related_draft = (
                    people.get(related_node_id)
                    or commitments.get(related_node_id)
                    or emails.get(related_node_id)
                    or events.get(related_node_id)
                    or documents.get(related_node_id)
                    or memories.get(related_node_id)
                )
                if related_draft is not None:
                    related_label = related_draft.label
                    related_draft.search_parts.append(record.content)
                    if len(record.content) <= 500:
                        related_draft.details.append(
                            ("Memory evidence", _truncate(record.content, 360))
                        )
            else:
                node_id = f"memory:{record.id}"
                memories[node_id] = _NodeDraft(
                    id=node_id,
                    kind=GraphNodeKind.MEMORY,
                    label=_truncate(record.content, 90) or "(empty memory)",
                    subtitle=f"Memory · {_source_label(record.source_type)}",
                    entity_id=record.id,
                    status=record.kind.value,
                    created_at=record.created_at,
                    details=[
                        ("Content", record.content),
                        ("Kind", record.kind.value.title()),
                        ("Source", _source_label(record.source_type)),
                        ("Created", _format_datetime(record.created_at)),
                        ("Verified", "yes" if record.user_verified else "no"),
                    ],
                    developer=[
                        ("Memory ID", record.id),
                        ("Source type", record.source_type),
                        ("Source ID", record.source_id),
                        ("Confidence", f"{record.confidence:.2f}"),
                        ("Indexed", "yes" if record.indexed else "no"),
                    ],
                    search_parts=[record.content, record.source_type],
                    tags={"memory"},
                )
                related_node_id = node_id
                related_label = "Independent memory"
            records.append(
                GraphRecord(
                    id=record.id,
                    content=record.content,
                    kind=record.kind.value,
                    source=_source_label(record.source_type),
                    created_at=record.created_at,
                    related_node_id=related_node_id,
                    related_label=related_label,
                    provenance=(
                        f"{_source_label(record.source_type)} · "
                        f"{'user verified' if record.user_verified else 'unverified'}"
                    ),
                    source_type=record.source_type,
                    source_id=record.source_id,
                    developer=tuple(
                        [
                            ("Memory ID", record.id),
                            ("Kind", record.kind.value),
                            ("Source type", record.source_type),
                            ("Source ID", record.source_id),
                            ("Confidence", f"{record.confidence:.2f}"),
                            ("User verified", "yes" if record.user_verified else "no"),
                            ("Indexed", "yes" if record.indexed else "no"),
                            ("Created", _format_datetime(record.created_at)),
                        ]
                    ),
                )
            )
            timeline.append(
                GraphTimelineItem(
                    id=f"memory:{record.id}",
                    timestamp=record.created_at,
                    title=_truncate(record.content, 110) or "(empty memory)",
                    detail=f"{record.kind.value.title()} · {_source_label(record.source_type)}",
                    group="Memory",
                    node_id=related_node_id,
                    commitment_id=self._memory_commitment_id(record, commitments),
                    person_node_id=self._memory_person_node(
                        record,
                        commitment_by_id,
                        people_by_email,
                        people_by_name,
                        people_by_contact_id,
                    ),
                    memory_id=record.id,
                    source=_source_label(record.source_type),
                )
            )
            if linked_memory:
                linked_memory_count += 1

        # ----------------------------------------------------------------
        # Personal facts
        # ----------------------------------------------------------------
        _CAT_EDGE: dict[str, GraphEdgeKind] = {
            PersonalFactCategory.BIRTHDAY.value: GraphEdgeKind.HAS_BIRTHDAY,
            PersonalFactCategory.IDENTITY.value: GraphEdgeKind.HAS_IDENTITY,
            PersonalFactCategory.EDUCATION.value: GraphEdgeKind.STUDIES_AT,
            PersonalFactCategory.CAREER.value: GraphEdgeKind.WORKS_ON,
            PersonalFactCategory.PREFERENCE.value: GraphEdgeKind.PREFERS,
            PersonalFactCategory.CONTACT_INFORMATION.value: GraphEdgeKind.HAS_CONTACT_INFO,
            PersonalFactCategory.PERSONAL_RELATIONSHIP.value: GraphEdgeKind.HAS_PERSONAL_FACT,
            PersonalFactCategory.OTHER.value: GraphEdgeKind.HAS_PERSONAL_FACT,
        }

        pf_rows = list(
            self.session.scalars(
                select(PersonalFact)
                .where(PersonalFact.deleted_at.is_(None))
                .order_by(PersonalFact.category, PersonalFact.attribute)
                .limit(max_nodes)
            )
        )

        # We anchor all personal-fact nodes to a single "User" person node.
        user_node_key: str | None = None
        for key, draft in people.items():
            if not draft.entity_id:  # no contact_id means it was auto-created from context
                pass
            # Use the first person node as the user proxy, or create one.
            user_node_key = key
            break

        if pf_rows and user_node_key is None:
            user_node_key = "person:user"
            people[user_node_key] = _NodeDraft(
                id=user_node_key,
                kind=GraphNodeKind.PERSON,
                label="You",
                subtitle="Your profile",
                search_parts=["user", "me", "my profile"],
            )

        for pf in pf_rows:
            node_id = f"personal_fact:{pf.id}"
            cat_label = pf.category.value.replace("_", " ").title()
            attr_label = pf.attribute.replace("_", " ").title()
            confirmed = pf.confirmation_state == PersonalFactConfirmationState.CONFIRMED
            tags: set[str] = {"personal_fact", pf.category.value}
            if confirmed:
                tags.add("confirmed")
            else:
                tags.add("needs_confirmation")
            personal_facts_nodes[node_id] = _NodeDraft(
                id=node_id,
                kind=GraphNodeKind.PERSONAL_FACT,
                label=pf.display_value or pf.value,
                subtitle=f"{cat_label} · {'Confirmed' if confirmed else 'Needs confirmation'}",
                entity_id=pf.id,
                status="confirmed" if confirmed else "needs_confirmation",
                created_at=pf.created_at,
                updated_at=pf.updated_at,
                details=[
                    ("Category", cat_label),
                    ("Attribute", attr_label),
                    ("Value", pf.display_value or pf.value),
                    ("Confirmed", "Yes" if confirmed else "No"),
                    ("Recurrence", pf.recurrence or "None"),
                    ("Source", pf.source_text or "Your own statement."),
                ],
                developer=[
                    ("Fact ID", pf.id),
                    ("Category", pf.category.value),
                    ("Attribute", pf.attribute),
                    ("Raw value", pf.value),
                    ("Confidence", f"{pf.confidence:.2f}"),
                    ("Indexed", "yes" if pf.indexed else "no"),
                ],
                search_parts=[
                    pf.attribute,
                    pf.display_value,
                    pf.value,
                    pf.source_text,
                    cat_label,
                ],
                tags=tags,
            )
            # Edge from user node → personal fact node
            if user_node_key is not None:
                edge_kind = _CAT_EDGE.get(pf.category.value, GraphEdgeKind.HAS_PERSONAL_FACT)
                add_edge(
                    GraphEdge(
                        id=_edge_id(edge_kind, user_node_key, node_id),
                        source_id=user_node_key,
                        target_id=node_id,
                        kind=edge_kind,
                        label=EDGE_LABELS[edge_kind],
                        evidence=pf.source_text,
                        confidence=pf.confidence,
                        validation_status="confirmed" if confirmed else "needs_review",
                        origin="personal_fact",
                        developer=(
                            ("Fact ID", pf.id),
                            ("Category", pf.category.value),
                        ),
                    )
                )
            # Timeline entry
            timeline.append(
                GraphTimelineItem(
                    id=f"personal_fact:{pf.id}",
                    timestamp=pf.created_at,
                    title=f"{attr_label} remembered · {pf.display_value or pf.value}",
                    detail=f"Personal profile · {cat_label}",
                    group="Personal fact",
                    node_id=node_id,
                    source="Personal profile",
                )
            )
            # Records entry
            records.append(
                GraphRecord(
                    id=pf.id,
                    content=f"{attr_label}: {pf.display_value or pf.value}",
                    kind="personal_fact",
                    source=f"Personal profile · {cat_label}",
                    created_at=pf.created_at,
                    related_node_id=node_id,
                    related_label=pf.display_value or pf.value,
                    provenance=f"Personal profile · {'confirmed' if confirmed else 'unconfirmed'}",
                    source_type="personal_fact",
                    source_id=pf.id,
                    developer=(
                        ("Fact ID", pf.id),
                        ("Category", pf.category.value),
                        ("Attribute", pf.attribute),
                        ("Raw value", pf.value),
                        ("Confidence", f"{pf.confidence:.2f}"),
                        ("Confirmation state", pf.confirmation_state.value),
                        ("Indexed", "yes" if pf.indexed else "no"),
                        ("Created", _format_datetime(pf.created_at)),
                    ),
                )
            )

        for draft in people.values():
            incident = sum(
                1
                for edge in edges.values()
                if edge.source_id == draft.id or edge.target_id == draft.id
            )
            if incident:
                draft.subtitle = (
                    f"{draft.subtitle} · {incident} connection"
                    + ("" if incident == 1 else "s")
                )

        total_memories = (
            self.session.scalar(
                select(func.count(MemoryRecord.id)).where(MemoryRecord.deleted_at.is_(None))
            )
            or 0
        )
        active_commitments = (
            self.session.scalar(
                select(func.count(Commitment.id)).where(
                    Commitment.status.notin_(tuple(TERMINAL_STATUSES))
                )
            )
            or 0
        )
        waiting_commitments = (
            self.session.scalar(
                select(func.count(Commitment.id)).where(
                    Commitment.status == CommitmentStatus.WAITING
                )
            )
            or 0
        )
        email_count = self.session.scalar(select(func.count(EmailThread.id))) or 0
        event_count = self.session.scalar(select(func.count(CommitmentEvent.id))) or 0
        document_count = self.session.scalar(select(func.count(EmailAttachment.id))) or 0
        blocked = len(
            {
                commitment_id
                for commitment_id, draft in commitments.items()
                if "blocked" in draft.tags
            }
        )
        node_values = [
            *people.values(),
            *commitments.values(),
            *emails.values(),
            *events.values(),
            *documents.values(),
            *memories.values(),
            *personal_facts_nodes.values(),
        ]
        limited = len(node_values) > max_nodes
        if limited:
            degree: dict[str, int] = {}
            for edge in edges.values():
                degree[edge.source_id] = degree.get(edge.source_id, 0) + 1
                degree[edge.target_id] = degree.get(edge.target_id, 0) + 1
            node_values = sorted(
                node_values,
                key=lambda node: (
                    degree.get(node.id, 0),
                    -NODE_KIND_ORDER[node.kind],
                    _recency_key(node.updated_at or node.created_at),
                ),
                reverse=True,
            )[:max_nodes]
            kept = {node.id for node in node_values}
            edges = {
                edge_id: edge
                for edge_id, edge in edges.items()
                if edge.source_id in kept and edge.target_id in kept
            }
        return KnowledgeGraph(
            nodes=tuple(node.to_node() for node in node_values),
            edges=tuple(edges.values()),
            records=tuple(records),
            timeline=tuple(
                sorted(
                    timeline,
                    key=lambda item: item.timestamp or datetime.min,
                    reverse=True,
                )
            ),
            stats=GraphStats(
                people=len(people),
                active_commitments=int(active_commitments),
                waiting_for=int(waiting_commitments),
                blocked_commitments=blocked,
                connected_memories=linked_memory_count,
                total_memories=int(total_memories),
                emails=int(email_count),
                events=int(event_count),
                documents=int(document_count),
                edges=len(edges),
                personal_facts=len(personal_facts_nodes),
            ),
            limited=limited,
        )

    @staticmethod
    def _related_memory_node(
        record: MemoryRecord,
        *,
        commitments: dict[str, _NodeDraft],
        emails: dict[str, _NodeDraft],
        email_node_by_message: dict[str, str],
        documents: dict[str, _NodeDraft],
        people_by_contact_id: dict[str, str],
    ) -> str | None:
        source_id = record.source_id.split(":chunk:", 1)[0]
        if record.source_type == "commitment":
            candidate = f"commitment:{source_id}"
            return candidate if candidate in commitments else None
        if record.source_type == "email":
            email_candidate = email_node_by_message.get(source_id)
            if email_candidate and email_candidate in emails:
                return email_candidate
            thread_candidate = f"email_thread:{source_id}"
            return thread_candidate if thread_candidate in emails else None
        if record.source_type == "contact":
            return people_by_contact_id.get(source_id)
        if record.source_type == "document":
            candidate = f"document:{source_id}"
            return candidate if candidate in documents else None
        return None

    @staticmethod
    def _memory_commitment_id(
        record: MemoryRecord,
        commitments: dict[str, _NodeDraft],
    ) -> str | None:
        if record.source_type != "commitment":
            return None
        source_id = record.source_id.split(":chunk:", 1)[0]
        candidate = f"commitment:{source_id}"
        return source_id if candidate in commitments else None

    @staticmethod
    def _memory_person_node(
        record: MemoryRecord,
        commitments: dict[str, Commitment],
        people_by_email: dict[str, str],
        people_by_name: dict[str, str],
        people_by_contact_id: dict[str, str],
    ) -> str | None:
        if record.source_type == "contact":
            return people_by_contact_id.get(record.source_id)
        if record.source_type != "commitment":
            return None
        source_id = record.source_id.split(":chunk:", 1)[0]
        commitment = commitments.get(source_id)
        if commitment is None:
            return None
        if commitment.contact_email:
            key = people_by_email.get(email_address(commitment.contact_email))
            if key:
                return key
        if commitment.person:
            return people_by_name.get(_normalise_name(commitment.person))
        return None
