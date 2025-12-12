from sqlalchemy import Column, String, Integer, Date, ForeignKey, Index, DECIMAL, Boolean, Text
from sqlalchemy.orm import relationship
from .base import Base, TimestampMixin, generate_uuid


class CashBookEntry(Base, TimestampMixin):
    """
    Kassenbuch-Eintrag (Barzahlungen)
    Für Barzahlungen im Büro
    """
    __tablename__ = "cashbook_entries"

    id = Column(String, primary_key=True, default=generate_uuid)
    owner_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    client_id = Column(String, ForeignKey("clients.id", ondelete="CASCADE"), nullable=False, index=True)
    fiscal_year_id = Column(String, ForeignKey("fiscal_years.id", ondelete="SET NULL"), nullable=True, index=True)
    
    # Buchungsdatum
    entry_date = Column(Date, nullable=False)
    
    # Art der Buchung
    entry_type = Column(String(50), nullable=False)  # "income" (Einzahlung) oder "expense" (Auszahlung)
    
    # Betrag
    amount = Column(DECIMAL(10, 2), nullable=False)
    
    # Verwendungszweck
    purpose = Column(Text, nullable=True)
    
    # Verknüpfung (optional)
    lease_id = Column(String, ForeignKey("leases.id", ondelete="SET NULL"), nullable=True, index=True)
    tenant_id = Column(String, ForeignKey("tenants.id", ondelete="SET NULL"), nullable=True, index=True)
    charge_id = Column(String, ForeignKey("charges.id", ondelete="SET NULL"), nullable=True, index=True)
    
    # Beleg (optional)
    receipt_path = Column(String(500), nullable=True)  # Pfad zum Beleg
    
    # Relationships
    owner = relationship("User", foreign_keys=[owner_id])
    client = relationship("Client", foreign_keys=[client_id])
    fiscal_year = relationship("FiscalYear", foreign_keys=[fiscal_year_id])
    lease = relationship("Lease", foreign_keys=[lease_id])
    tenant = relationship("Tenant", foreign_keys=[tenant_id])
    charge = relationship("Charge", foreign_keys=[charge_id])
    
    __table_args__ = (
        Index('ix_cashbook_owner_date', 'owner_id', 'entry_date'),
        Index('ix_cashbook_client_fiscal', 'client_id', 'fiscal_year_id'),
    )

