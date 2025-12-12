from sqlalchemy import Column, String, Integer, Text, ForeignKey, Index, Enum
from sqlalchemy.orm import relationship
from .base import Base, TimestampMixin, generate_uuid
import enum


class ServiceProviderType(str, enum.Enum):
    """Typ des Dienstleisters"""
    ELECTRICIAN = "electrician"  # Elektriker
    PLUMBER = "plumber"  # Klempner
    HEATING = "heating"  # Heizungstechniker
    CLEANING = "cleaning"  # Reinigung
    GARDENING = "gardening"  # Gartenpflege
    LOCKSMITH = "locksmith"  # Schlüsseldienst
    PAINTER = "painter"  # Maler
    ROOFER = "roofer"  # Dachdecker
    OTHER = "other"  # Sonstiges


class ServiceProvider(Base, TimestampMixin):
    """
    Dienstleister
    Repräsentiert einen Handwerker/Dienstleister
    """
    __tablename__ = "service_providers"

    id = Column(String, primary_key=True, default=generate_uuid)
    owner_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    client_id = Column(String, ForeignKey("clients.id", ondelete="CASCADE"), nullable=False, index=True)
    
    # Stammdaten
    company_name = Column(String(255), nullable=True)  # Firma (optional)
    first_name = Column(String(100), nullable=False)
    last_name = Column(String(100), nullable=False)
    service_type = Column(Enum(ServiceProviderType), nullable=False)
    
    # Kontaktdaten
    email = Column(String(255), nullable=True)
    phone = Column(String(50), nullable=True)
    mobile = Column(String(50), nullable=True)
    address = Column(String(500), nullable=True)
    
    # Geschäftsdaten
    tax_id = Column(String(50), nullable=True)  # Steuernummer/USt-IdNr
    iban = Column(String(34), nullable=True)
    bank_name = Column(String(255), nullable=True)
    
    # Bewertung
    rating = Column(Integer, nullable=True)  # 1-5 Sterne
    notes = Column(Text, nullable=True)
    
    # Relationships
    owner = relationship("User", foreign_keys=[owner_id])
    client = relationship("Client", foreign_keys=[client_id])
    
    __table_args__ = (
        Index('ix_service_providers_owner_client', 'owner_id', 'client_id'),
        Index('ix_service_providers_client_type', 'client_id', 'service_type'),
    )

