from sqlalchemy import Column, String, Integer, Text, ForeignKey, Index, DECIMAL, Enum
from sqlalchemy.orm import relationship
from .base import Base, TimestampMixin, generate_uuid
import enum


class OwnerStatus(str, enum.Enum):
    """Status des Eigentümers"""
    SELF_OCCUPIED = "self_occupied"  # Selbstnutzer
    INVESTOR = "investor"  # Kapitalanleger (vermietet weiter)


class Owner(Base, TimestampMixin):
    """
    Eigentümer
    Repräsentiert einen Eigentümer (z.B. bei WEG-Verwaltung)
    """
    __tablename__ = "owners"

    id = Column(String, primary_key=True, default=generate_uuid)
    owner_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    client_id = Column(String, ForeignKey("clients.id", ondelete="CASCADE"), nullable=False, index=True)
    
    # Stammdaten
    first_name = Column(String(100), nullable=False)
    last_name = Column(String(100), nullable=False)
    email = Column(String(255), nullable=True)
    phone = Column(String(50), nullable=True)
    address = Column(String(500), nullable=True)
    
    # Steuerliche Daten
    tax_id = Column(String(50), nullable=True)  # Steuer-ID (für Bescheinigungen)
    
    # Eigentumsanteile (für WEG)
    ownership_percentage = Column(DECIMAL(5, 2), nullable=True)  # z.B. 12.5 für 12,5%
    
    # Zahlungsverkehr
    iban = Column(String(34), nullable=True)  # IBAN für Ausschüttungen (Mieteinnahmen) oder Lastschrift (Hausgeld)
    bank_name = Column(String(255), nullable=True)
    
    # Status
    status = Column(Enum(OwnerStatus), nullable=True)  # Selbstnutzer oder Kapitalanleger
    
    # Zusätzliche Infos
    notes = Column(Text, nullable=True)
    
    # Relationships
    owner = relationship("User", foreign_keys=[owner_id])
    client = relationship("Client", foreign_keys=[client_id])
    
    __table_args__ = (
        Index('ix_owners_owner_client', 'owner_id', 'client_id'),
        Index('ix_owners_client', 'client_id'),
    )

