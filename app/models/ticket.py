from sqlalchemy import Column, String, Integer, Date, ForeignKey, Index, Enum, Boolean, Text
from sqlalchemy.orm import relationship
import enum
from .base import Base, TimestampMixin, generate_uuid


class TicketCategory(str, enum.Enum):
    """Kategorie des Tickets"""
    DAMAGE = "damage"  # Schaden
    MAINTENANCE = "maintenance"  # Wartung
    REPAIR = "repair"  # Reparatur
    INQUIRY = "inquiry"  # Anfrage
    OTHER = "other"  # Sonstiges


class TicketPriority(str, enum.Enum):
    """Priorität des Tickets"""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    URGENT = "urgent"


class TicketStatus(str, enum.Enum):
    """Status des Tickets"""
    NEW = "new"  # Neu
    IN_PROGRESS = "in_progress"  # In Bearbeitung
    ASSIGNED = "assigned"  # Handwerker beauftragt
    WAITING = "waiting"  # Wartend
    RESOLVED = "resolved"  # Erledigt
    CLOSED = "closed"  # Geschlossen
    CANCELLED = "cancelled"  # Storniert


class Ticket(Base, TimestampMixin):
    """
    Ticket / Vorgang
    Für Schäden, Reparaturen, Aufgaben
    """
    __tablename__ = "tickets"

    id = Column(String, primary_key=True, default=generate_uuid)
    owner_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    client_id = Column(String, ForeignKey("clients.id", ondelete="CASCADE"), nullable=False, index=True)
    
    # Titel & Beschreibung
    title = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    
    # Kategorisierung
    category = Column(Enum(TicketCategory), default=TicketCategory.OTHER, nullable=False)
    priority = Column(Enum(TicketPriority), default=TicketPriority.MEDIUM, nullable=False)
    status = Column(Enum(TicketStatus), default=TicketStatus.NEW, nullable=False)
    
    # Verknüpfungen
    property_id = Column(String, ForeignKey("properties.id", ondelete="SET NULL"), nullable=True, index=True)
    unit_id = Column(String, ForeignKey("units.id", ondelete="SET NULL"), nullable=True, index=True)
    tenant_id = Column(String, ForeignKey("tenants.id", ondelete="SET NULL"), nullable=True, index=True)
    
    # Handwerker / Dienstleister (optional)
    service_provider_id = Column(String, ForeignKey("tenants.id", ondelete="SET NULL"), nullable=True, index=True)
    
    # Termine
    due_date = Column(Date, nullable=True)  # Fälligkeitsdatum
    resolved_at = Column(Date, nullable=True)  # Wann erledigt
    
    # Kosten (optional, für spätere Zuordnung zu Betriebskosten)
    estimated_cost = Column(String, nullable=True)  # Geschätzte Kosten
    actual_cost = Column(String, nullable=True)  # Tatsächliche Kosten
    
    # Relationships
    owner = relationship("User", foreign_keys=[owner_id])
    client = relationship("Client", foreign_keys=[client_id])
    property = relationship("Property", foreign_keys=[property_id])
    unit = relationship("Unit", foreign_keys=[unit_id])
    tenant = relationship("Tenant", foreign_keys=[tenant_id])
    service_provider = relationship("Tenant", foreign_keys=[service_provider_id])
    comments = relationship("TicketComment", back_populates="ticket", cascade="all, delete-orphan")
    attachments = relationship("TicketAttachment", back_populates="ticket", cascade="all, delete-orphan")
    
    __table_args__ = (
        Index('ix_tickets_status', 'status'),
        Index('ix_tickets_priority', 'priority'),
        Index('ix_tickets_property', 'property_id'),
    )


class TicketComment(Base, TimestampMixin):
    """
    Kommentar zu einem Ticket
    """
    __tablename__ = "ticket_comments"

    id = Column(String, primary_key=True, default=generate_uuid)
    ticket_id = Column(String, ForeignKey("tickets.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    
    # Kommentar
    comment = Column(Text, nullable=False)
    
    # Relationships
    ticket = relationship("Ticket", back_populates="comments")
    user = relationship("User", foreign_keys=[user_id])


class TicketAttachment(Base, TimestampMixin):
    """
    Anhang zu einem Ticket (Fotos, PDFs, etc.)
    """
    __tablename__ = "ticket_attachments"

    id = Column(String, primary_key=True, default=generate_uuid)
    ticket_id = Column(String, ForeignKey("tickets.id", ondelete="CASCADE"), nullable=False, index=True)
    
    # Datei
    filename = Column(String(255), nullable=False)
    file_path = Column(String(500), nullable=False)
    file_size = Column(Integer, nullable=True)  # Größe in Bytes
    mime_type = Column(String(100), nullable=True)
    
    # Relationships
    ticket = relationship("Ticket", back_populates="attachments")

