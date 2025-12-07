from sqlalchemy import Column, String, Integer, ForeignKey, Index, DECIMAL, Text
from sqlalchemy.orm import relationship
from .base import Base, TimestampMixin, generate_uuid


class AutoMatchLog(Base, TimestampMixin):
    """
    Log-Tabelle für automatische Zahlungsabgleiche
    Speichert Audit-Trail für alle Auto-Match-Versuche
    """
    __tablename__ = "auto_match_logs"

    id = Column(String, primary_key=True, default=generate_uuid)
    transaction_id = Column(String, ForeignKey("bank_transactions.id", ondelete="CASCADE"), nullable=False, index=True)
    charge_id = Column(String, ForeignKey("charges.id", ondelete="CASCADE"), nullable=True, index=True)
    
    # Match-Ergebnis
    result = Column(String(50), nullable=False)  # "matched", "skipped", "multiple_candidates", "no_match"
    confidence_score = Column(DECIMAL(5, 2), nullable=True)  # 0.00 - 100.00
    
    # Match-Details
    iban_match = Column(Integer, default=0, nullable=False)  # Punkte für IBAN-Match
    name_match = Column(Integer, default=0, nullable=False)  # Punkte für Namen-Match
    amount_match = Column(Integer, default=0, nullable=False)  # Punkte für Betrags-Match
    date_match = Column(Integer, default=0, nullable=False)  # Punkte für Datums-Match
    purpose_match = Column(Integer, default=0, nullable=False)  # Punkte für Verwendungszweck-Match
    
    # Optionale Notizen
    note = Column(Text, nullable=True)
    
    # Relationships
    transaction = relationship("BankTransaction", foreign_keys=[transaction_id])
    charge = relationship("Charge", foreign_keys=[charge_id])

    __table_args__ = (
        Index('ix_auto_match_logs_transaction', 'transaction_id'),
        Index('ix_auto_match_logs_result', 'result'),
        Index('ix_auto_match_logs_created', 'created_at'),
    )

