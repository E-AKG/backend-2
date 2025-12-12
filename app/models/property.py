from sqlalchemy import Column, String, Integer, Text, Index, ForeignKey
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import relationship
from .base import Base, TimestampMixin, generate_uuid


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

    # Relationships
    units = relationship("Unit", back_populates="property", cascade="all, delete-orphan")
    owner = relationship("User", foreign_keys=[owner_id])
    client = relationship("Client", foreign_keys=[client_id])

    __table_args__ = (
        Index('ix_properties_owner_address', 'owner_id', 'address'),
        Index('ix_properties_client', 'client_id'),
    )

