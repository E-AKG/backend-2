from sqlalchemy import Column, String, Integer, Date, ForeignKey, Index, Boolean, Numeric
from sqlalchemy.orm import relationship
from datetime import date
from .base import Base, TimestampMixin, generate_uuid


class FiscalYear(Base, TimestampMixin):
    """
    Wirtschaftsjahr (Fiscal Year)
    Pro Mandant können mehrere Geschäftsjahre existieren (z.B. 2023, 2024, 2025)
    """
    __tablename__ = "fiscal_years"

    id = Column(String, primary_key=True, default=generate_uuid)
    client_id = Column(String, ForeignKey("clients.id", ondelete="CASCADE"), nullable=False, index=True)
    
    # Geschäftsjahr
    year = Column(Integer, nullable=False)  # z.B. 2024, 2025
    
    # Zeitraum (optional, falls nicht Kalenderjahr)
    start_date = Column(Date, nullable=False)  # z.B. 2024-01-01
    end_date = Column(Date, nullable=False)    # z.B. 2024-12-31
    
    # Status
    is_active = Column(Boolean, default=True, nullable=False)  # Aktuelles Geschäftsjahr
    is_closed = Column(Boolean, default=False, nullable=False)  # Abgeschlossen
    
    # Eröffnungssalden (optional, für Jahresübertrag)
    opening_balance = Column(Numeric(10, 2), nullable=True, default=0)
    
    # Relationships
    client = relationship("Client", back_populates="fiscal_years")
    
    __table_args__ = (
        Index('ix_fiscal_years_client_year', 'client_id', 'year'),
        Index('ix_fiscal_years_client_active', 'client_id', 'is_active'),
    )

