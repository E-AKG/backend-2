from sqlalchemy import Column, String, Integer, Date, Enum, ForeignKey, Index, DECIMAL, Boolean
from sqlalchemy.orm import relationship
import enum
from datetime import date
from .base import Base, TimestampMixin, generate_uuid


class BillRunStatus(str, enum.Enum):
    DRAFT = "draft"
    FINALIZED = "finalized"
    SENT = "sent"
    CLOSED = "closed"


class ChargeStatus(str, enum.Enum):
    OPEN = "open"
    PAID = "paid"
    PARTIALLY_PAID = "partially_paid"
    CANCELLED = "cancelled"
    OVERDUE = "overdue"


class BillRun(Base, TimestampMixin):
    """
    Monatliche Sollstellung (Abrechnungsmonat)
    Erzeugt automatisch Sollbuchungen für alle aktiven Verträge
    """
    __tablename__ = "bill_runs"

    id = Column(String, primary_key=True, default=generate_uuid)
    owner_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    client_id = Column(String, ForeignKey("clients.id", ondelete="CASCADE"), nullable=False, index=True)
    fiscal_year_id = Column(String, ForeignKey("fiscal_years.id", ondelete="SET NULL"), nullable=True, index=True)
    
    # Abrechnungszeitraum
    period_month = Column(Integer, nullable=False)  # 1-12
    period_year = Column(Integer, nullable=False)   # z.B. 2025
    
    # Status
    status = Column(Enum(BillRunStatus), default=BillRunStatus.DRAFT, nullable=False)
    
    # Datum der Erstellung
    run_date = Column(Date, nullable=False, default=date.today)
    
    # Optionale Beschreibung
    description = Column(String(500), nullable=True)
    
    # Beträge (werden beim Finalisieren berechnet)
    total_amount = Column(DECIMAL(10, 2), nullable=True)  # Gesamtsumme aller Charges
    paid_amount = Column(DECIMAL(10, 2), default=0, nullable=False)  # Bereits bezahlt
    
    # Relationships
    owner = relationship("User", foreign_keys=[owner_id])
    client = relationship("Client", foreign_keys=[client_id])
    fiscal_year = relationship("FiscalYear", foreign_keys=[fiscal_year_id])
    charges = relationship("Charge", back_populates="bill_run", cascade="all, delete-orphan")

    __table_args__ = (
        Index('ix_billruns_owner_period', 'owner_id', 'period_year', 'period_month'),
    )


class Charge(Base, TimestampMixin):
    """
    Einzelne Sollbuchung innerhalb einer Sollstellung
    Verknüpft mit einem Mietvertrag (Lease)
    """
    __tablename__ = "charges"

    id = Column(String, primary_key=True, default=generate_uuid)
    bill_run_id = Column(String, ForeignKey("bill_runs.id", ondelete="CASCADE"), nullable=False, index=True)
    lease_id = Column(String, ForeignKey("leases.id", ondelete="CASCADE"), nullable=False, index=True)
    
    # Sollbetrag
    amount = Column(DECIMAL(10, 2), nullable=False)
    
    # Fälligkeitsdatum
    due_date = Column(Date, nullable=False)
    
    # Status
    status = Column(Enum(ChargeStatus), default=ChargeStatus.OPEN, nullable=False)
    
    # Bereits gezahlter Betrag (für Teilzahlungen)
    paid_amount = Column(DECIMAL(10, 2), default=0, nullable=False)
    
    # Optionale Beschreibung
    description = Column(String(500), nullable=True)
    
    # Relationships
    bill_run = relationship("BillRun", back_populates="charges")
    lease = relationship("Lease", foreign_keys=[lease_id])
    payment_matches = relationship("PaymentMatch", back_populates="charge", cascade="all, delete-orphan")

    __table_args__ = (
        Index('ix_charges_status', 'status'),
        Index('ix_charges_due_date', 'due_date'),
    )

