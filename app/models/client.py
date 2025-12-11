from sqlalchemy import Column, String, Integer, Text, ForeignKey, Index, Enum, Boolean
from sqlalchemy.orm import relationship
import enum
from .base import Base, TimestampMixin, generate_uuid


class ClientType(str, enum.Enum):
    """Typ des Mandanten"""
    PRIVATE_LANDLORD = "private_landlord"  # Privater Vermieter
    WEG = "weg"  # Wohnungseigentümergemeinschaft
    COMPANY = "company"  # Firma / Eigenbestand
    FUND = "fund"  # Fonds
    OTHER = "other"  # Sonstiges


class Client(Base, TimestampMixin):
    """
    Mandant (Client)
    Repräsentiert einen Verwaltungsmandanten (z.B. WEG, privater Vermieter, Firma)
    """
    __tablename__ = "clients"

    id = Column(String, primary_key=True, default=generate_uuid)
    owner_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    
    # Stammdaten
    name = Column(String(255), nullable=False)  # z.B. "WEG Müllerstraße", "GbR Schmidt"
    client_type = Column(Enum(ClientType), default=ClientType.PRIVATE_LANDLORD, nullable=False)
    
    # Kontaktdaten (optional)
    contact_name = Column(String(255), nullable=True)
    email = Column(String(255), nullable=True)
    phone = Column(String(50), nullable=True)
    address = Column(String(500), nullable=True)
    
    # Zusätzliche Infos
    notes = Column(Text, nullable=True)
    
    # Aktiv/Inaktiv
    is_active = Column(Boolean, default=True, nullable=False)
    
    # Relationships
    owner = relationship("User", foreign_keys=[owner_id])
    fiscal_years = relationship("FiscalYear", back_populates="client", cascade="all, delete-orphan")
    properties = relationship("Property", back_populates="client", cascade="all, delete-orphan")
    
    __table_args__ = (
        Index('ix_clients_owner_name', 'owner_id', 'name'),
    )

