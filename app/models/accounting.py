from sqlalchemy import Column, String, Integer, Date, ForeignKey, Index, Enum, Text, DECIMAL, Boolean
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship
import enum
from datetime import date
from .base import Base, TimestampMixin, generate_uuid


class AccountingType(str, enum.Enum):
    """Abrechnungstyp"""
    OPERATING_COSTS = "operating_costs"  # Betriebskostenabrechnung (für Mieter)
    HOUSING_FUND = "housing_fund"  # Hausgeldabrechnung (für WEG)


class AccountingStatus(str, enum.Enum):
    """Status der Abrechnung"""
    DRAFT = "draft"  # Entwurf
    CALCULATED = "calculated"  # Berechnet
    GENERATED = "generated"  # PDF generiert
    SENT = "sent"  # Versendet
    CLOSED = "closed"  # Abgeschlossen


class Accounting(Base, TimestampMixin):
    """
    Abrechnung (Accounting)
    Betriebskosten- oder Hausgeldabrechnung
    """
    __tablename__ = "accountings"

    id = Column(String, primary_key=True, default=generate_uuid)
    owner_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    client_id = Column(String, ForeignKey("clients.id", ondelete="CASCADE"), nullable=False, index=True)
    fiscal_year_id = Column(String, ForeignKey("fiscal_years.id", ondelete="SET NULL"), nullable=True, index=True)
    
    # Abrechnungstyp
    accounting_type = Column(Enum(AccountingType), nullable=False)
    status = Column(Enum(AccountingStatus), default=AccountingStatus.DRAFT, nullable=False)
    
    # Zeitraum
    period_start = Column(Date, nullable=False)  # z.B. 2024-01-01
    period_end = Column(Date, nullable=False)    # z.B. 2024-12-31
    
    # Beträge
    total_costs = Column(DECIMAL(10, 2), default=0, nullable=False)  # Gesamtkosten
    total_advance_payments = Column(DECIMAL(10, 2), default=0, nullable=False)  # Gesamte Vorauszahlungen
    total_settlement = Column(DECIMAL(10, 2), default=0, nullable=False)  # Gesamte Nachzahlung/Guthaben
    
    # Dokument
    document_path = Column(String(500), nullable=True)  # Pfad zum generierten PDF
    generated_at = Column(Date, nullable=True)  # Wann generiert
    
    # Zusätzliche Daten (JSON für flexible Struktur)
    metadata = Column(JSONB, default=dict)  # Zusätzliche Infos (z.B. Umlageschlüssel)
    notes = Column(Text, nullable=True)
    
    # Relationships
    owner = relationship("User", foreign_keys=[owner_id])
    client = relationship("Client", foreign_keys=[client_id])
    fiscal_year = relationship("FiscalYear", foreign_keys=[fiscal_year_id])
    items = relationship("AccountingItem", back_populates="accounting", cascade="all, delete-orphan")
    unit_settlements = relationship("UnitSettlement", back_populates="accounting", cascade="all, delete-orphan")
    
    __table_args__ = (
        Index('ix_accountings_client_type', 'client_id', 'accounting_type'),
        Index('ix_accountings_period', 'period_start', 'period_end'),
    )


class AccountingItem(Base, TimestampMixin):
    """
    Abrechnungsposten (Accounting Item)
    Einzelne Kostenposition (z.B. Heizung, Müll, Hausmeister)
    """
    __tablename__ = "accounting_items"

    id = Column(String, primary_key=True, default=generate_uuid)
    accounting_id = Column(String, ForeignKey("accountings.id", ondelete="CASCADE"), nullable=False, index=True)
    
    # Kostenart
    cost_type = Column(String(100), nullable=False)  # z.B. "heating", "garbage", "janitor"
    description = Column(String(255), nullable=False)  # Beschreibung
    
    # Betrag
    amount = Column(DECIMAL(10, 2), nullable=False)
    
    # Umlagefähig
    is_allocable = Column(Boolean, default=True, nullable=False)  # Umlagefähig?
    
    # Zusätzliche Infos
    notes = Column(Text, nullable=True)
    
    # Relationships
    accounting = relationship("Accounting", back_populates="items")
    
    __table_args__ = (
        Index('ix_accounting_items_accounting', 'accounting_id'),
    )


class UnitSettlement(Base, TimestampMixin):
    """
    Einzelabrechnung (Unit Settlement)
    Abrechnung für eine einzelne Einheit/Mieter
    """
    __tablename__ = "unit_settlements"

    id = Column(String, primary_key=True, default=generate_uuid)
    accounting_id = Column(String, ForeignKey("accountings.id", ondelete="CASCADE"), nullable=False, index=True)
    unit_id = Column(String, ForeignKey("units.id", ondelete="CASCADE"), nullable=True, index=True)
    lease_id = Column(String, ForeignKey("leases.id", ondelete="SET NULL"), nullable=True, index=True)
    tenant_id = Column(String, ForeignKey("tenants.id", ondelete="SET NULL"), nullable=True, index=True)
    
    # Vorauszahlungen
    advance_payments = Column(DECIMAL(10, 2), default=0, nullable=False)  # Gezahlte Vorauszahlungen
    
    # Anteilige Kosten
    allocated_costs = Column(DECIMAL(10, 2), default=0, nullable=False)  # Zugeordnete Kosten
    
    # Abrechnung
    settlement_amount = Column(DECIMAL(10, 2), nullable=False)  # Nachzahlung (+) oder Guthaben (-)
    
    # Dokument
    document_path = Column(String(500), nullable=True)  # Pfad zum Einzel-PDF
    
    # Status
    is_sent = Column(Boolean, default=False, nullable=False)
    sent_at = Column(Date, nullable=True)
    
    # Relationships
    accounting = relationship("Accounting", back_populates="unit_settlements")
    unit = relationship("Unit", foreign_keys=[unit_id])
    lease = relationship("Lease", foreign_keys=[lease_id])
    tenant = relationship("Tenant", foreign_keys=[tenant_id])
    
    __table_args__ = (
        Index('ix_unit_settlements_accounting', 'accounting_id'),
        Index('ix_unit_settlements_unit', 'unit_id'),
    )

