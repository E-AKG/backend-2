from sqlalchemy import Column, String, Integer, Date, Enum, ForeignKey, Index, DECIMAL, Text, Boolean
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship
import enum
from .base import Base, TimestampMixin, generate_uuid


class LeaseStatus(str, enum.Enum):
    ACTIVE = "active"
    ENDED = "ended"
    PENDING = "pending"


class LeaseComponentType(str, enum.Enum):
    COLD_RENT = "cold_rent"
    OPERATING_COSTS = "operating_costs"
    HEATING_COSTS = "heating_costs"
    OTHER = "other"


class RentAdjustmentType(str, enum.Enum):
    """Typ der Mietanpassung"""
    FIXED = "fixed"  # Feste Miete
    STAGGERED = "staggered"  # Staffelmiete
    INDEX_LINKED = "index_linked"  # Indexmiete


class Lease(Base, TimestampMixin):
    __tablename__ = "leases"

    id = Column(String, primary_key=True, default=generate_uuid)
    owner_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    client_id = Column(String, ForeignKey("clients.id", ondelete="CASCADE"), nullable=False, index=True)
    fiscal_year_id = Column(String, ForeignKey("fiscal_years.id", ondelete="SET NULL"), nullable=True, index=True)
    unit_id = Column(String, ForeignKey("units.id", ondelete="CASCADE"), nullable=False, index=True)
    tenant_id = Column(String, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    start_date = Column(Date, nullable=False)
    end_date = Column(Date, nullable=True)
    status = Column(Enum(LeaseStatus), default=LeaseStatus.PENDING, nullable=False)
    due_day = Column(Integer, nullable=False)  # 1-28

    # Relationships
    owner = relationship("User", foreign_keys=[owner_id])
    client = relationship("Client", foreign_keys=[client_id])
    fiscal_year = relationship("FiscalYear", foreign_keys=[fiscal_year_id])
    unit = relationship("Unit", back_populates="leases")
    tenant = relationship("Tenant", back_populates="leases")
    components = relationship("LeaseComponent", back_populates="lease", cascade="all, delete-orphan")

    __table_args__ = (
        Index('ix_leases_owner_status', 'owner_id', 'status'),
    )


class LeaseComponent(Base, TimestampMixin):
    __tablename__ = "lease_components"

    id = Column(String, primary_key=True, default=generate_uuid)
    lease_id = Column(String, ForeignKey("leases.id", ondelete="CASCADE"), nullable=False, index=True)
    type = Column(Enum(LeaseComponentType), nullable=False)
    amount = Column(DECIMAL(10, 2), nullable=False)
    description = Column(String(255), nullable=True)
    
    # Mietanpassung
    adjustment_type = Column(Enum(RentAdjustmentType), default=RentAdjustmentType.FIXED, nullable=False)
    
    # Staffelmiete: Liste von {date, amount}
    staggered_schedule = Column(JSONB, nullable=True)  # [{"date": "2024-01-01", "amount": 500.00}, ...]
    
    # Indexmiete
    index_type = Column(String(50), nullable=True)  # z.B. "VPI", "Mietspiegel"
    index_base_value = Column(DECIMAL(10, 2), nullable=True)  # Basiswert des Index
    index_base_date = Column(Date, nullable=True)  # Basis-Datum
    index_adjustment_date = Column(Date, nullable=True)  # Nächstes Anpassungsdatum
    index_adjustment_percentage = Column(DECIMAL(5, 2), nullable=True)  # Anpassungsprozentsatz
    
    # Umlageschlüssel (für Betriebskosten)
    allocation_key = Column(String(50), nullable=True)  # "area", "units", "persons", "custom"
    allocation_factor = Column(DECIMAL(10, 4), nullable=True)  # Individueller Faktor
    allocation_notes = Column(Text, nullable=True)  # Notizen zum Umlageschlüssel

    # Relationships
    lease = relationship("Lease", back_populates="components")
    adjustments = relationship("RentAdjustment", back_populates="component", cascade="all, delete-orphan")
    
    __table_args__ = (
        Index('ix_lease_components_adjustment_type', 'adjustment_type'),
    )


class RentAdjustment(Base, TimestampMixin):
    """
    Mietanpassung (für Staffel- und Indexmieten)
    Historie aller Mietanpassungen
    """
    __tablename__ = "rent_adjustments"

    id = Column(String, primary_key=True, default=generate_uuid)
    component_id = Column(String, ForeignKey("lease_components.id", ondelete="CASCADE"), nullable=False, index=True)
    adjustment_date = Column(Date, nullable=False)  # Datum der Anpassung
    old_amount = Column(DECIMAL(10, 2), nullable=False)  # Alter Betrag
    new_amount = Column(DECIMAL(10, 2), nullable=False)  # Neuer Betrag
    adjustment_reason = Column(String(255), nullable=True)  # Grund (z.B. "Staffelstufe 2", "Indexanpassung")
    index_value = Column(DECIMAL(10, 2), nullable=True)  # Indexwert zum Zeitpunkt der Anpassung
    notes = Column(Text, nullable=True)
    
    # Relationships
    component = relationship("LeaseComponent", back_populates="adjustments")
    
    __table_args__ = (
        Index('ix_rent_adjustments_date', 'adjustment_date'),
        Index('ix_rent_adjustments_component', 'component_id'),
    )

