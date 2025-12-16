from sqlalchemy import Column, String, Integer, Enum, ForeignKey, UniqueConstraint, Index, Boolean, DECIMAL
from sqlalchemy.orm import relationship
import enum
from .base import Base, TimestampMixin, generate_uuid


class UnitStatus(str, enum.Enum):
    VACANT = "vacant"
    OCCUPIED = "occupied"


class UsageType(str, enum.Enum):
    RESIDENTIAL = "residential"  # Wohnen
    COMMERCIAL = "commercial"  # Gewerbe
    PARKING = "parking"  # Stellplatz/Garage
    BASEMENT = "basement"  # Kellerraum
    OTHER = "other"  # Sonstige


class BathroomType(str, enum.Enum):
    BATH = "bath"  # Wanne
    SHOWER = "shower"  # Dusche
    BOTH = "both"  # Wanne und Dusche
    NONE = "none"  # Kein Bad


class Unit(Base, TimestampMixin):
    __tablename__ = "units"

    id = Column(String, primary_key=True, default=generate_uuid)
    owner_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    client_id = Column(String, ForeignKey("clients.id", ondelete="CASCADE"), nullable=True, index=True)
    property_id = Column(String, ForeignKey("properties.id", ondelete="CASCADE"), nullable=False, index=True)
    unit_label = Column(String(100), nullable=False)
    floor = Column(Integer, nullable=True)
    size_sqm = Column(Integer, nullable=True)  # Gesamtfläche (Legacy, bleibt für Kompatibilität)
    status = Column(Enum(UnitStatus), default=UnitStatus.VACANT, nullable=False)
    
    # ========== Basisdaten ==========
    location = Column(String(255), nullable=True)  # Lage (z.B. "EG links", "1. OG")
    unit_number = Column(String(50), nullable=True)  # Einheitsnummer (z.B. "001")
    
    # ========== Flächen & Anteile ==========
    living_area_sqm = Column(DECIMAL(10, 2), nullable=True)  # Wohnfläche in m² (DIN 277 oder WoFlV)
    mea_numerator = Column(Integer, nullable=True)  # MEA Zähler (z.B. 125)
    mea_denominator = Column(Integer, nullable=True)  # MEA Nenner (z.B. 1000)
    
    # ========== Nutzungsart ==========
    usage_type = Column(Enum(UsageType), nullable=True)  # Nutzungsart
    
    # ========== Ausstattung ==========
    rooms = Column(Integer, nullable=True)  # Anzahl Zimmer
    bathroom_type = Column(Enum(BathroomType), nullable=True)  # Bad (Wanne/Dusche)
    has_balcony = Column(Boolean, default=False, nullable=False)  # Balkon
    floor_covering = Column(String(100), nullable=True)  # Bodenbelag (z.B. "Parkett", "Laminat", "Fliesen")

    # Relationships
    property = relationship("Property", back_populates="units")
    owner = relationship("User", foreign_keys=[owner_id])
    client = relationship("Client", foreign_keys=[client_id])
    leases = relationship("Lease", back_populates="unit", cascade="all, delete-orphan")

    __table_args__ = (
        UniqueConstraint('property_id', 'unit_label', name='uq_property_unit_label'),
        Index('ix_units_owner_property', 'owner_id', 'property_id'),
    )

