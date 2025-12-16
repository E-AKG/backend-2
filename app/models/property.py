from sqlalchemy import Column, String, Integer, Text, Index, ForeignKey, Date, DECIMAL, Enum
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import relationship
from .base import Base, TimestampMixin, generate_uuid
import enum


class HeatingType(str, enum.Enum):
    GAS = "gas"
    OIL = "oil"
    ELECTRIC = "electric"
    HEAT_PUMP = "heat_pump"
    DISTRICT_HEATING = "district_heating"
    PELLETS = "pellets"
    OTHER = "other"


class Property(Base, TimestampMixin):
    __tablename__ = "properties"

    id = Column(String, primary_key=True, default=generate_uuid)
    owner_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    client_id = Column(String, ForeignKey("clients.id", ondelete="CASCADE"), nullable=True, index=True)
    name = Column(String(255), nullable=False)
    address = Column(String(500), nullable=False)
    year_built = Column(Integer, nullable=True)
    size_sqm = Column(Integer, nullable=True)
    features = Column(JSONB, default=dict)
    notes = Column(Text, nullable=True)
    
    # ========== Erweiterte Stammdaten ==========
    # Grundsteuer
    unit_value_file_number = Column(String(100), nullable=True)  # Einheitswert-Aktenzeichen
    cadastral_district = Column(String(100), nullable=True)  # Flur
    cadastral_parcel = Column(String(100), nullable=True)  # Flurstück
    
    # ========== Technische Daten ==========
    # Heizung
    heating_type = Column(Enum(HeatingType), nullable=True)  # Heizungsart (für GEG/Energieausweis)
    
    # Energieausweis
    energy_certificate_valid_until = Column(Date, nullable=True)  # Gültigkeit Energieausweis
    energy_rating_value = Column(DECIMAL(10, 2), nullable=True)  # Energiekennwert (kWh/m²a)
    energy_rating_class = Column(String(10), nullable=True)  # Energieklasse (A+, A, B, etc.)
    
    # Gesamtfläche
    total_residential_area = Column(Integer, nullable=True)  # Wohnfläche in m²
    total_commercial_area = Column(Integer, nullable=True)  # Gewerbefläche in m²

    # Relationships
    units = relationship("Unit", back_populates="property", cascade="all, delete-orphan")
    owner = relationship("User", foreign_keys=[owner_id])
    client = relationship("Client", foreign_keys=[client_id])
    # TODO: Uncomment after database migration creates property_insurances, property_bank_accounts, allocation_keys tables
    # insurances = relationship("PropertyInsurance", back_populates="property", cascade="all, delete-orphan")
    # bank_accounts = relationship("PropertyBankAccount", back_populates="property", cascade="all, delete-orphan")
    # allocation_keys = relationship("AllocationKey", back_populates="property", cascade="all, delete-orphan")

    __table_args__ = (
        Index('ix_properties_owner_address', 'owner_id', 'address'),
        Index('ix_properties_client', 'client_id'),
    )

