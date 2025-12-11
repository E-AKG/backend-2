from sqlalchemy import Column, String, Integer, Text, ForeignKey, Index, Enum, DateTime
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
    client_id = Column(String, ForeignKey("clients.id", ondelete="CASCADE"), nullable=False, index=True)
    first_name = Column(String(100), nullable=False)
    last_name = Column(String(100), nullable=False)
    email = Column(String(255), nullable=True)
    phone = Column(String(50), nullable=True)
    iban = Column(String(34), nullable=True)  # NEU: IBAN des Mieters
    address = Column(String(500), nullable=True)
    notes = Column(Text, nullable=True)
    
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

