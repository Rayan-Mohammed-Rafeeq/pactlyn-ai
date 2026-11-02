from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from pactlyn.storage.models import Contact


class ContactService:
    def __init__(self, session: Session):
        self.session = session

    def upsert(self, name: str, email: str | None = None, notes: str = "") -> Contact:
        contact = None
        if email:
            contact = self.session.scalar(select(Contact).where(func.lower(Contact.email) == email.lower()))
        if not contact:
            contact = self.session.scalar(select(Contact).where(func.lower(Contact.name) == name.lower()))
        if contact:
            contact.email = email or contact.email
            if notes:
                contact.notes = notes
            return contact
        contact = Contact(name=name, email=email, notes=notes)
        self.session.add(contact)
        self.session.flush()
        return contact

    def find(self, name: str | None = None, email: str | None = None) -> list[Contact]:
        query = select(Contact)
        if email:
            query = query.where(func.lower(Contact.email) == email.lower())
        elif name:
            query = query.where(func.lower(Contact.name).contains(name.lower()))
        else:
            return list(self.session.scalars(query.order_by(Contact.name)))
        return list(self.session.scalars(query.order_by(Contact.name)))
