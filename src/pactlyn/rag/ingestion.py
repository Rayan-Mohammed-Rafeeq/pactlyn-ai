from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from pactlyn.memory.service import MemoryService
from pactlyn.storage.models import MemoryKind, MemoryRecord


@dataclass(frozen=True)
class SourceDocument:
    source_type: str
    source_id: str
    content: str
    metadata: dict[str, object]


class SourceChunker:
    """Chunk by semantic boundaries while retaining source metadata."""

    def __init__(self, max_chars: int = 1600):
        self.max_chars = max_chars

    def chunk(self, document: SourceDocument) -> list[SourceDocument]:
        paragraphs = [paragraph.strip() for paragraph in document.content.split("\n\n") if paragraph.strip()]
        chunks: list[str] = []
        current = ""
        for paragraph in paragraphs or [document.content.strip()]:
            if current and len(current) + len(paragraph) + 2 > self.max_chars:
                chunks.append(current)
                current = ""
            current = f"{current}\n\n{paragraph}".strip()
        if current:
            chunks.append(current)
        return [
            SourceDocument(
                source_type=document.source_type,
                source_id=f"{document.source_id}:chunk:{index}",
                content=chunk,
                metadata={**document.metadata, "parent_source_id": document.source_id, "chunk_index": index},
            )
            for index, chunk in enumerate(chunks)
        ]

    @staticmethod
    def email(
        *,
        source_id: str,
        sender: str,
        recipients: list[str],
        subject: str,
        body: str,
        timestamp: datetime,
        message_id: str | None = None,
        in_reply_to: str | None = None,
        thread_id: str | None = None,
    ) -> SourceDocument:
        header = (
            f"From: {sender}\nTo: {', '.join(recipients)}\nSubject: {subject}\n"
            f"Timestamp: {timestamp.isoformat()}\nMessage-ID: {message_id or ''}\n"
            f"In-Reply-To: {in_reply_to or ''}\nThread-ID: {thread_id or ''}"
        )
        return SourceDocument(
            source_type="email",
            source_id=source_id,
            content=f"{header}\n\n{body}",
            metadata={
                "sender": sender,
                "recipients": recipients,
                "subject": subject,
                "timestamp": timestamp.isoformat(),
                "message_id": message_id,
                "in_reply_to": in_reply_to,
                "thread_id": thread_id,
            },
        )


class IngestionService:
    def __init__(self, memory: MemoryService, chunker: SourceChunker | None = None):
        self.memory = memory
        self.chunker = chunker or SourceChunker()

    async def ingest(self, document: SourceDocument, *, kind: MemoryKind = MemoryKind.SEMANTIC) -> list[MemoryRecord]:
        records: list[MemoryRecord] = []
        for chunk in self.chunker.chunk(document):
            records.append(
                await self.memory.remember(
                    chunk.content,
                    kind=kind,
                    source_type=chunk.source_type,
                    source_id=chunk.source_id,
                )
            )
        self.memory.session.commit()
        return records

    def delete_source(self, source_id: str) -> None:
        records = list(
            self.memory.session.query(MemoryRecord)
            .filter(MemoryRecord.source_id.like(f"{source_id}:chunk:%"))
        )
        for record in records:
            self.memory.delete(record.id)
