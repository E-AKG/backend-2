from sqlalchemy import Column, String, Integer, Enum, ForeignKey, UniqueConstraint, Index
from sqlalchemy.orm import relationship
import enum
from .base import Base, TimestampMixin, generate_uuid


class UnitStatus(str, enum.Enum):
    VACANT = "vacant"
    OCCUPIED = "occupied"


class Unit(Base, TimestampMixin):
    __tablename__ = "units"

    id = Column(String, primary_key=True, default=generate_uuid)
    owner_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    # TODO: Uncomment after database migration adds client_id column
    # client_id = Column(String, ForeignKey("clients.id", ondelete="CASCADE"), nullable=True, index=True)
    property_id = Column(String, ForeignKey("properties.id", ondelete="CASCADE"), nullable=False, index=True)
    unit_label = Column(String(100), nullable=False)
    floor = Column(Integer, nullable=True)
    size_sqm = Column(Integer, nullable=True)
    status = Column(Enum(UnitStatus), default=UnitStatus.VACANT, nullable=False)

    # Relationships
    property = relationship("Property", back_populates="units")
    owner = relationship("User", foreign_keys=[owner_id])
    # TODO: Uncomment after database migration
    # client = relationship("Client", foreign_keys=[client_id])
    leases = relationship("Lease", back_populates="unit", cascade="all, delete-orphan")

    __table_args__ = (
        UniqueConstraint('property_id', 'unit_label', name='uq_property_unit_label'),
        Index('ix_units_owner_property', 'owner_id', 'property_id'),
    )

