from sqlalchemy import Column, String, Integer, Date, ForeignKey, Index, Enum, Text
from sqlalchemy.orm import relationship
import enum
from datetime import date
from .base import Base, TimestampMixin, generate_uuid


class KeyType(str, enum.Enum):
    """Schlüsseltyp"""
    APARTMENT = "apartment"  # Wohnungstür
    BUILDING = "building"  # Haustür
    MAILBOX = "mailbox"  # Briefkasten
    BASEMENT = "basement"  # Keller
    GARAGE = "garage"  # Garage
    OTHER = "other"  # Sonstiges


class KeyStatus(str, enum.Enum):
    """Schlüsselstatus"""
    AVAILABLE = "available"  # Verfügbar
    OUT = "out"  # Ausgegeben
    LOST = "lost"  # Verloren
    REPLACED = "replaced"  # Ersetzt


class Key(Base, TimestampMixin):
    """
    Schlüssel (Key)
    Verwaltung von Schlüsseln für Objekte/Einheiten
    """
    __tablename__ = "keys"

    id = Column(String, primary_key=True, default=generate_uuid)
    owner_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    client_id = Column(String, ForeignKey("clients.id", ondelete="CASCADE"), nullable=False, index=True)
    property_id = Column(String, ForeignKey("properties.id", ondelete="CASCADE"), nullable=True, index=True)
    unit_id = Column(String, ForeignKey("units.id", ondelete="CASCADE"), nullable=True, index=True)
    
    # Schlüsseldaten
    key_type = Column(Enum(KeyType), nullable=False)
    key_number = Column(String(100), nullable=True)  # Schlüsselnummer (optional)
    description = Column(String(255), nullable=True)  # Beschreibung (z.B. "Hauptschlüssel")
    
    # Status
    status = Column(Enum(KeyStatus), default=KeyStatus.AVAILABLE, nullable=False)
    
    # Aktuelle Zuordnung
    assigned_to_type = Column(String(50), nullable=True)  # "tenant", "contractor", "manager", "other"
    assigned_to_id = Column(String, nullable=True)  # ID der zugeordneten Person
    assigned_to_name = Column(String(255), nullable=True)  # Name (für schnelle Anzeige)
    
    # Historie
    notes = Column(Text, nullable=True)
    
    # Relationships
    owner = relationship("User", foreign_keys=[owner_id])
    client = relationship("Client", foreign_keys=[client_id])
    property = relationship("Property", foreign_keys=[property_id])
    unit = relationship("Unit", foreign_keys=[unit_id])
    history = relationship("KeyHistory", back_populates="key", cascade="all, delete-orphan")
    
    __table_args__ = (
        Index('ix_keys_property', 'property_id'),
        Index('ix_keys_unit', 'unit_id'),
        Index('ix_keys_status', 'status'),
    )


class KeyHistory(Base, TimestampMixin):
    """
    Schlüssel-Historie
    Protokolliert Ausgabe und Rückgabe von Schlüsseln
    """
    __tablename__ = "key_history"

    id = Column(String, primary_key=True, default=generate_uuid)
    key_id = Column(String, ForeignKey("keys.id", ondelete="CASCADE"), nullable=False, index=True)
    owner_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    
    # Aktion
    action = Column(String(50), nullable=False)  # "out", "return", "lost", "replaced"
    action_date = Column(Date, nullable=False, default=date.today)
    
    # Zuordnung
    assigned_to_type = Column(String(50), nullable=True)
    assigned_to_id = Column(String, nullable=True)
    assigned_to_name = Column(String(255), nullable=True)
    
    # Notizen
    notes = Column(Text, nullable=True)
    
    # Relationships
    key = relationship("Key", back_populates="history")
    owner = relationship("User", foreign_keys=[owner_id])
    
    __table_args__ = (
        Index('ix_key_history_date', 'action_date'),
        Index('ix_key_history_key_date', 'key_id', 'action_date'),
    )

