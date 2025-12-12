from sqlalchemy import Column, String, Integer, ForeignKey, Index, Text, DECIMAL, Integer as IntColumn
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship
from .base import Base, TimestampMixin, generate_uuid


class ClientSettings(Base, TimestampMixin):
    """
    Mandanten-Einstellungen
    Pro-Mandant-Konfigurationen für Konten, Mahnstufen, Textbausteine, Logo
    """
    __tablename__ = "client_settings"

    id = Column(String, primary_key=True, default=generate_uuid)
    client_id = Column(String, ForeignKey("clients.id", ondelete="CASCADE"), nullable=False, unique=True, index=True)
    owner_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    
    # Bankkonten (für CSV-Import)
    default_bank_account_id = Column(String, nullable=True)  # Standard-Konto für CSV-Import
    
    # Mahnstufen-Konfiguration
    reminder_fees = Column(JSONB, default=dict)  # {"payment_reminder": 0, "first_reminder": 5.0, ...}
    reminder_days = Column(JSONB, default=dict)  # {"payment_reminder": 14, "first_reminder": 30, ...}
    reminder_enabled = Column(JSONB, default=dict)  # {"payment_reminder": true, ...}
    
    # Textbausteine
    text_templates = Column(JSONB, default=dict)  # {"reminder_1": "...", "reminder_2": "...", ...}
    
    # Logo & Branding
    logo_path = Column(String(500), nullable=True)  # Pfad zum Logo
    company_name = Column(String(255), nullable=True)  # Firmenname für Dokumente
    company_address = Column(Text, nullable=True)  # Firmenadresse
    company_tax_id = Column(String(50), nullable=True)  # Steuernummer
    company_iban = Column(String(34), nullable=True)  # IBAN für Rechnungen
    
    # Zusätzliche Einstellungen
    settings = Column(JSONB, default=dict)  # Flexible Einstellungen
    
    # Relationships
    client = relationship("Client", foreign_keys=[client_id])
    owner = relationship("User", foreign_keys=[owner_id])
    
    __table_args__ = (
        Index('ix_client_settings_client', 'client_id'),
    )

