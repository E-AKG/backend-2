from sqlalchemy import Column, String, Integer, ForeignKey, Index, Enum, Text
from sqlalchemy.orm import relationship
from .base import Base, TimestampMixin, generate_uuid
import enum


class PropertyAccountType(str, enum.Enum):
    RENT = "rent"  # Mietkonto (für Mieteingänge)
    RESERVES = "reserves"  # Rücklagenkonto (für Instandhaltungsrücklagen - WEG)
    DEPOSIT = "deposit"  # Kautionskonto (Treuhandkonten)
    OTHER = "other"  # Sonstiges


class PropertyBankAccount(Base, TimestampMixin):
    """
    Bankkonten, die einem Objekt zugeordnet sind
    Mietkonto, Rücklagenkonto, Kautionskonto
    """
    __tablename__ = "property_bank_accounts"

    id = Column(String, primary_key=True, default=generate_uuid)
    property_id = Column(String, ForeignKey("properties.id", ondelete="CASCADE"), nullable=False, index=True)
    owner_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    
    # Kontotyp
    account_type = Column(Enum(PropertyAccountType), nullable=False)
    
    # Kontodetails
    account_name = Column(String(255), nullable=False)  # Name des Kontos
    iban = Column(String(34), nullable=True)
    bank_name = Column(String(255), nullable=True)
    account_holder = Column(String(255), nullable=True)  # Kontoinhaber
    
    # Notizen
    notes = Column(Text, nullable=True)
    
    # Relationships
    # TODO: Uncomment back_populates after database migration and Property.bank_accounts relationship is enabled
    # property = relationship("Property", back_populates="bank_accounts")
    property = relationship("Property")
    owner = relationship("User", foreign_keys=[owner_id])
    
    __table_args__ = (
        Index('ix_property_bank_accounts_property', 'property_id'),
        Index('ix_property_bank_accounts_owner', 'owner_id'),
    )

