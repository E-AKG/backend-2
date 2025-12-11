from sqlalchemy import Column, String, Integer, Date, Enum, ForeignKey, Index, DECIMAL
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

    # Relationships
    lease = relationship("Lease", back_populates="components")

