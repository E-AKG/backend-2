from sqlalchemy import Column, String, Integer, ForeignKey, Index, Enum, DECIMAL, Text, Boolean
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship
from .base import Base, TimestampMixin, generate_uuid
import enum


class AllocationMethod(str, enum.Enum):
    AREA = "area"  # Nach m²
    UNITS = "units"  # Nach Wohneinheiten
    PERSONS = "persons"  # Nach Personen
    CONSUMPTION = "consumption"  # Nach Verbrauch
    CUSTOM = "custom"  # Individuell


class AllocationKey(Base, TimestampMixin):
    """
    Verteilerschlüssel für Nebenkostenabrechnung
    Definiert, wie Kosten auf Einheiten verteilt werden
    """
    __tablename__ = "allocation_keys"

    id = Column(String, primary_key=True, default=generate_uuid)
    property_id = Column(String, ForeignKey("properties.id", ondelete="CASCADE"), nullable=False, index=True)
    owner_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    
    # Name des Verteilerschlüssels
    name = Column(String(255), nullable=False)  # z.B. "Heizung", "Wasser", "Hausmeister"
    
    # Verteilungsmethode
    allocation_method = Column(Enum(AllocationMethod), nullable=False)
    
    # Individuelle Faktoren pro Einheit (für CUSTOM)
    # Format: {"unit_id": factor, ...}
    custom_factors = Column(JSONB, nullable=True)
    
    # Standard-Faktor (für AREA, UNITS, PERSONS)
    default_factor = Column(DECIMAL(10, 4), nullable=True, default=1.0)
    
    # Ist dieser Schlüssel aktiv?
    is_active = Column(Boolean, default=True, nullable=False)
    
    # Notizen
    notes = Column(Text, nullable=True)
    
    # Relationships
    # TODO: Uncomment back_populates after database migration and Property.allocation_keys relationship is enabled
    # property = relationship("Property", back_populates="allocation_keys")
    property = relationship("Property")
    owner = relationship("User", foreign_keys=[owner_id])
    
    __table_args__ = (
        Index('ix_allocation_keys_property', 'property_id'),
        Index('ix_allocation_keys_owner', 'owner_id'),
    )

