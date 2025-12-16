from sqlalchemy import Column, String, Integer, Date, ForeignKey, Index, Text, Enum
from sqlalchemy.orm import relationship
from .base import Base, TimestampMixin, generate_uuid
import enum


class InsuranceType(str, enum.Enum):
    BUILDING = "building"  # Gebäudeversicherung
    LIABILITY = "liability"  # Haftpflichtversicherung
    OTHER = "other"  # Sonstige


class PropertyInsurance(Base, TimestampMixin):
    """
    Versicherungen für ein Objekt
    Gebäudeversicherung, Haftpflicht, etc.
    """
    __tablename__ = "property_insurances"

    id = Column(String, primary_key=True, default=generate_uuid)
    property_id = Column(String, ForeignKey("properties.id", ondelete="CASCADE"), nullable=False, index=True)
    owner_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    
    # Versicherungstyp
    insurance_type = Column(Enum(InsuranceType), nullable=False)
    
    # Versicherungsdetails
    insurer_name = Column(String(255), nullable=False)  # Versicherer
    policy_number = Column(String(100), nullable=True)  # Police-Nr.
    coverage_description = Column(Text, nullable=True)  # Was ist abgedeckt?
    
    # Laufzeit
    start_date = Column(Date, nullable=True)
    end_date = Column(Date, nullable=True)
    
    # Jahresprämie
    annual_premium = Column(String(50), nullable=True)  # Als String, da Beträge variieren können
    
    # Notizen
    notes = Column(Text, nullable=True)
    
    # Relationships
    # TODO: Uncomment back_populates after database migration and Property.insurances relationship is enabled
    # property = relationship("Property", back_populates="insurances")
    property = relationship("Property")
    owner = relationship("User", foreign_keys=[owner_id])
    
    __table_args__ = (
        Index('ix_property_insurances_property', 'property_id'),
        Index('ix_property_insurances_owner', 'owner_id'),
    )

