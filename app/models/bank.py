from sqlalchemy import Column, String, Integer, Date, ForeignKey, Index, DECIMAL, Boolean, Text
from sqlalchemy.orm import relationship
from .base import Base, TimestampMixin, generate_uuid


class BankAccount(Base, TimestampMixin):
    """
    Bankkonto des Benutzers
    Verknüpft mit FinAPI für automatischen Abruf von Transaktionen
    """
    __tablename__ = "bank_accounts"

    id = Column(String, primary_key=True, default=generate_uuid)
    owner_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    
    # Kontodetails
    account_name = Column(String(255), nullable=False)
    iban = Column(String(34), nullable=True)
    bank_name = Column(String(255), nullable=True)
    
    # FinAPI-Verknüpfung
    finapi_account_id = Column(String(255), nullable=True, unique=True)  # Externe ID von FinAPI
    finapi_connection_id = Column(String(255), nullable=True)  # FinAPI Bank Connection ID für Updates
    finapi_access_token = Column(Text, nullable=True)  # Verschlüsselt in Produktion!
    finapi_user_id = Column(String(255), nullable=True)  # FinAPI User ID
    finapi_user_password = Column(String(255), nullable=True)  # FinAPI User Password (verschlüsseln!)
    finapi_webform_id = Column(String(255), nullable=True)  # FinAPI WebForm ID
    
    # Status
    is_active = Column(Boolean, default=True, nullable=False)
    last_sync = Column(Date, nullable=True)  # Letzter Sync mit FinAPI
    
    # Aktueller Kontostand (optional, wird von FinAPI aktualisiert)
    balance = Column(DECIMAL(10, 2), nullable=True)
    
    # Relationships
    owner = relationship("User", foreign_keys=[owner_id])
    transactions = relationship("BankTransaction", back_populates="bank_account", cascade="all, delete-orphan")

    __table_args__ = (
        Index('ix_bank_accounts_owner', 'owner_id'),
    )


class BankTransaction(Base, TimestampMixin):
    """
    Einzelne Banktransaktion (von FinAPI importiert)
    Wird mit Sollbuchungen (Charges) abgeglichen
    """
    __tablename__ = "bank_transactions"

    id = Column(String, primary_key=True, default=generate_uuid)
    bank_account_id = Column(String, ForeignKey("bank_accounts.id", ondelete="CASCADE"), nullable=False, index=True)
    
    # Transaktionsdetails
    transaction_date = Column(Date, nullable=False)
    booking_date = Column(Date, nullable=True)
    amount = Column(DECIMAL(10, 2), nullable=False)
    
    # Transaktionsinformationen
    purpose = Column(Text, nullable=True)  # Verwendungszweck
    counterpart_name = Column(String(255), nullable=True)  # Name Gegenkonto
    counterpart_iban = Column(String(34), nullable=True)  # IBAN Gegenkonto
    
    # FinAPI-Daten
    finapi_transaction_id = Column(String(255), nullable=True, unique=True)  # Externe ID
    
    # Matching-Status
    is_matched = Column(Boolean, default=False, nullable=False)  # Wurde zugeordnet?
    matched_amount = Column(DECIMAL(10, 2), default=0, nullable=False)  # Bereits zugeordneter Betrag
    
    # Relationships
    bank_account = relationship("BankAccount", back_populates="transactions")
    payment_matches = relationship("PaymentMatch", back_populates="transaction", cascade="all, delete-orphan")

    __table_args__ = (
        Index('ix_bank_transactions_date', 'transaction_date'),
        Index('ix_bank_transactions_matched', 'is_matched'),
    )


class PaymentMatch(Base, TimestampMixin):
    """
    Zuordnung von Banktransaktion zu Sollbuchung
    Ermöglicht Teilzahlungen (eine Transaktion kann mehrere Charges bedienen)
    """
    __tablename__ = "payment_matches"

    id = Column(String, primary_key=True, default=generate_uuid)
    transaction_id = Column(String, ForeignKey("bank_transactions.id", ondelete="CASCADE"), nullable=False, index=True)
    charge_id = Column(String, ForeignKey("charges.id", ondelete="CASCADE"), nullable=False, index=True)
    
    # Zugeordneter Betrag (kann kleiner sein als Transaktions- oder Charge-Betrag)
    matched_amount = Column(DECIMAL(10, 2), nullable=False)
    
    # Automatisch oder manuell zugeordnet?
    is_automatic = Column(Boolean, default=False, nullable=False)
    
    # Optionale Notiz
    note = Column(String(500), nullable=True)
    
    # Relationships
    transaction = relationship("BankTransaction", back_populates="payment_matches")
    charge = relationship("Charge", back_populates="payment_matches")

    __table_args__ = (
        Index('ix_payment_matches_transaction', 'transaction_id'),
        Index('ix_payment_matches_charge', 'charge_id'),
    )


class CsvFile(Base, TimestampMixin):
    """
    Gespeicherte CSV-Dateien
    """
    __tablename__ = "csv_files"

    id = Column(String, primary_key=True, default=generate_uuid)
    owner_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    bank_account_id = Column(String, ForeignKey("bank_accounts.id", ondelete="CASCADE"), nullable=True, index=True)
    
    # Datei-Informationen
    filename = Column(String(255), nullable=False)
    file_size = Column(Integer, nullable=False)  # Größe in Bytes
    row_count = Column(Integer, nullable=False)  # Anzahl der Zeilen (ohne Header)
    
    # CSV-Daten als JSON gespeichert (für Anzeige im Frontend)
    csv_data = Column(Text, nullable=False)  # JSON-Array mit allen Zeilen
    
    # Spalten-Mapping (welche Spalten wurden erkannt)
    column_mapping = Column(Text, nullable=True)  # JSON mit Spalten-Mapping
    
    # PostgreSQL-Tabellen-Name (wenn als Tabelle gespeichert)
    table_name = Column(String(255), nullable=True)  # z.B. "csv_data_konto1_abc12345"
    
    # Relationships
    owner = relationship("User", foreign_keys=[owner_id])
    bank_account = relationship("BankAccount", foreign_keys=[bank_account_id])

    __table_args__ = (
        Index('ix_csv_files_owner', 'owner_id'),
        Index('ix_csv_files_account', 'bank_account_id'),
    )

