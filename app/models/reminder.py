from sqlalchemy import Column, String, Integer, Date, ForeignKey, Index, Enum, Text, DECIMAL
from sqlalchemy.orm import relationship
import enum
from datetime import date
from .base import Base, TimestampMixin, generate_uuid


class ReminderType(str, enum.Enum):
    """Mahnstufe"""
    PAYMENT_REMINDER = "payment_reminder"  # Zahlungserinnerung
    FIRST_REMINDER = "first_reminder"  # 1. Mahnung
    SECOND_REMINDER = "second_reminder"  # 2. Mahnung
    FINAL_REMINDER = "final_reminder"  # Letzte Mahnung
    LEGAL_ACTION = "legal_action"  # Rechtsweg


class ReminderStatus(str, enum.Enum):
    """Status der Mahnung"""
    DRAFT = "draft"  # Entwurf
    SENT = "sent"  # Versendet
    PAID = "paid"  # Bezahlt
    CANCELLED = "cancelled"  # Storniert


class Reminder(Base, TimestampMixin):
    """
    Mahnung (Reminder)
    Verwaltung von Mahnungen für offene Posten
    """
    __tablename__ = "reminders"

    id = Column(String, primary_key=True, default=generate_uuid)
    owner_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    client_id = Column(String, ForeignKey("clients.id", ondelete="CASCADE"), nullable=False, index=True)
    charge_id = Column(String, ForeignKey("charges.id", ondelete="CASCADE"), nullable=False, index=True)
    tenant_id = Column(String, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    
    # Mahndaten
    reminder_type = Column(Enum(ReminderType), nullable=False)
    status = Column(Enum(ReminderStatus), default=ReminderStatus.DRAFT, nullable=False)
    
    # Betrag
    amount = Column(DECIMAL(10, 2), nullable=False)  # Mahnbetrag
    reminder_fee = Column(DECIMAL(10, 2), default=0, nullable=False)  # Mahngebühr
    
    # Datum
    reminder_date = Column(Date, nullable=False, default=date.today)  # Mahndatum
    due_date = Column(Date, nullable=True)  # Neue Fälligkeit
    
    # Dokument
    document_path = Column(String(500), nullable=True)  # Pfad zum generierten PDF
    document_sent_at = Column(Date, nullable=True)  # Wann versendet
    
    # Notizen
    notes = Column(Text, nullable=True)
    
    # Relationships
    owner = relationship("User", foreign_keys=[owner_id])
    client = relationship("Client", foreign_keys=[client_id])
    charge = relationship("Charge", foreign_keys=[charge_id])
    tenant = relationship("Tenant", foreign_keys=[tenant_id])
    
    __table_args__ = (
        Index('ix_reminders_charge', 'charge_id'),
        Index('ix_reminders_tenant', 'tenant_id'),
        Index('ix_reminders_status', 'status'),
        Index('ix_reminders_date', 'reminder_date'),
    )

