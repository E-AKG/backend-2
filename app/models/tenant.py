from sqlalchemy import Column, String, Integer, Text, ForeignKey, Index, Enum, DateTime
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from .base import Base, TimestampMixin, generate_uuid
import enum


class RiskLevel(str, enum.Enum):
    """Risiko-Level für Mieter basierend auf Zahlungsverhalten"""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class Tenant(Base, TimestampMixin):
    __tablename__ = "tenants"

    id = Column(String, primary_key=True, default=generate_uuid)
    owner_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    client_id = Column(String, ForeignKey("clients.id", ondelete="CASCADE"), nullable=True, index=True)
    first_name = Column(String(100), nullable=False)
    last_name = Column(String(100), nullable=False)
    email = Column(String(255), nullable=True)  # E-Mail für Mieterportal-Zugang
    phone = Column(String(50), nullable=True)  # Telefon
    address = Column(String(500), nullable=True)
    notes = Column(Text, nullable=True)
    
    # Alle Vertragspartner (z.B. Eheleute)
    contract_partners = Column(JSONB, nullable=True)  # Liste von Partnern: [{"first_name": "Maria", "last_name": "Mustermann"}]
    
    # Bonität
    schufa_score = Column(Integer, nullable=True)  # Schufa-Score (z.B. 0-100)
    salary_proof_document_id = Column(String, ForeignKey("documents.id", ondelete="SET NULL"), nullable=True)  # Gehaltsnachweis als Dokument
    
    # Bankverbindung für SEPA-Lastschriftmandate
    iban = Column(String(34), nullable=True)  # IBAN für SEPA-Lastschriftmandate (Mieteinzug)
    sepa_mandate_reference = Column(String(100), nullable=True)  # SEPA-Mandatsreferenz
    sepa_mandate_date = Column(DateTime(timezone=True), nullable=True)  # Datum des SEPA-Mandats
    
    # Risk Score Fields (nullable - können fehlen wenn Migration noch nicht ausgeführt wurde)
    risk_score = Column(Integer, nullable=True, default=None)  # 0-100
    risk_level = Column(Enum(RiskLevel, name='risklevel', create_type=False), nullable=True, default=None)
    risk_updated_at = Column(DateTime(timezone=True), nullable=True, server_default=None, onupdate=func.now())

    # Relationships
    owner = relationship("User", foreign_keys=[owner_id])
    client = relationship("Client", foreign_keys=[client_id])
    leases = relationship("Lease", back_populates="tenant", cascade="all, delete-orphan")

    __table_args__ = (
        Index('ix_tenants_owner_lastname', 'owner_id', 'last_name'),
    )

