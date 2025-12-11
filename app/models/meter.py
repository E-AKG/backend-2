from sqlalchemy import Column, String, Integer, Date, ForeignKey, Index, Enum, Text
from datetime import date
from sqlalchemy.orm import relationship
import enum
from datetime import date
from .base import Base, TimestampMixin, generate_uuid


class MeterType(str, enum.Enum):
    """Zählerart"""
    WATER = "water"  # Wasser
    HEATING = "heating"  # Heizung/Wärme
    ELECTRICITY = "electricity"  # Strom
    GAS = "gas"  # Gas
    OTHER = "other"  # Sonstiges


class Meter(Base, TimestampMixin):
    """
    Zähler (Meter)
    Verwaltung von Wasser-, Heizungs-, Stromzählern etc.
    """
    __tablename__ = "meters"

    id = Column(String, primary_key=True, default=generate_uuid)
    owner_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    client_id = Column(String, ForeignKey("clients.id", ondelete="CASCADE"), nullable=False, index=True)
    property_id = Column(String, ForeignKey("properties.id", ondelete="CASCADE"), nullable=True, index=True)
    unit_id = Column(String, ForeignKey("units.id", ondelete="CASCADE"), nullable=True, index=True)
    
    # Zählerdaten
    meter_type = Column(Enum(MeterType), nullable=False)
    meter_number = Column(String(100), nullable=False)  # Zählernummer
    location = Column(String(255), nullable=True)  # Einbauort (z.B. "Keller", "Wohnung 3")
    
    # Eichfrist
    calibration_date = Column(Date, nullable=True)  # Letzte Eichung
    calibration_due_date = Column(Date, nullable=True)  # Nächste Eichung fällig
    
    # Zusätzliche Infos
    manufacturer = Column(String(255), nullable=True)
    model = Column(String(255), nullable=True)
    notes = Column(Text, nullable=True)
    
    # Relationships
    owner = relationship("User", foreign_keys=[owner_id])
    client = relationship("Client", foreign_keys=[client_id])
    property = relationship("Property", foreign_keys=[property_id])
    unit = relationship("Unit", foreign_keys=[unit_id])
    readings = relationship("MeterReading", back_populates="meter", cascade="all, delete-orphan")
    
    __table_args__ = (
        Index('ix_meters_property', 'property_id'),
        Index('ix_meters_unit', 'unit_id'),
        Index('ix_meters_calibration_due', 'calibration_due_date'),
    )


class MeterReading(Base, TimestampMixin):
    """
    Zählerstand (Meter Reading)
    Historie von Zählerständen für Abrechnungen
    """
    __tablename__ = "meter_readings"

    id = Column(String, primary_key=True, default=generate_uuid)
    meter_id = Column(String, ForeignKey("meters.id", ondelete="CASCADE"), nullable=False, index=True)
    owner_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    
    # Zählerstand
    reading_value = Column(Integer, nullable=False)  # Zählerstand
    reading_date = Column(Date, nullable=False)  # Ablesedatum
    
    # Kontext
    reading_type = Column(String(50), nullable=True)  # "manual", "estimated", "billing"
    reader_name = Column(String(255), nullable=True)  # Wer hat abgelesen?
    
    # Verknüpfung mit Abrechnung (optional)
    billrun_id = Column(String, ForeignKey("bill_runs.id", ondelete="SET NULL"), nullable=True, index=True)
    
    # Relationships
    meter = relationship("Meter", back_populates="readings")
    owner = relationship("User", foreign_keys=[owner_id])
    
    __table_args__ = (
        Index('ix_meter_readings_date', 'reading_date'),
        Index('ix_meter_readings_meter_date', 'meter_id', 'reading_date'),
    )

