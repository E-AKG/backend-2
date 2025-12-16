from sqlalchemy import Column, String, Integer, Date, ForeignKey, Index, Enum, Boolean, Text, DateTime, TypeDecorator
from sqlalchemy.orm import relationship
import enum
from .base import Base, TimestampMixin, generate_uuid


class DocumentType(str, enum.Enum):
    """Typ des Dokuments"""
    CONTRACT = "contract"  # Mietvertrag
    INVOICE = "invoice"  # Rechnung
    RECEIPT = "receipt"  # Quittung
    STATEMENT = "statement"  # Abrechnung
    CERTIFICATE = "certificate"  # Energieausweis, etc.
    PROTOCOL = "protocol"  # Protokoll (Eigentümerversammlung)
    BK_STATEMENT = "bk_statement"  # Betriebskostenabrechnung (Statement)
    BK_RECEIPT = "bk_receipt"  # Betriebskosten-Beleg
    OTHER = "other"  # Sonstiges


class DocumentStatus(str, enum.Enum):
    """Status des Dokuments (für Portal-Veröffentlichung)"""
    DRAFT = "draft"  # Entwurf (nicht sichtbar für Mieter)
    PUBLISHED = "published"  # Veröffentlicht (sichtbar für Mieter)


class EnumValueType(TypeDecorator):
    """
    TypeDecorator für Enums, der sicherstellt, dass der Enum-Wert (nicht der Name) verwendet wird.
    Wichtig für PostgreSQL Enums mit create_type=False.
    """
    impl = String
    cache_ok = True
    
    def __init__(self, enum_class, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.enum_class = enum_class
    
    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        # Wenn es ein Enum-Objekt ist, verwende den Wert
        if isinstance(value, self.enum_class):
            return value.value
        # Wenn es ein String ist, prüfe ob es ein Enum-Wert oder Enum-Name ist
        if isinstance(value, str):
            # Prüfe zuerst, ob es ein gültiger Enum-Wert ist (lowercase)
            try:
                enum_val = self.enum_class(value.lower())
                return enum_val.value
            except ValueError:
                # Falls nicht, könnte es ein Enum-Name sein (z.B. "BK_STATEMENT")
                # Versuche es als Enum-Name zu interpretieren
                try:
                    # Suche nach einem Enum-Member mit diesem Namen
                    for enum_member in self.enum_class:
                        if enum_member.name == value:
                            return enum_member.value
                except:
                    pass
                # Falls nichts funktioniert, gib den Wert zurück (könnte ein Fehler sein)
                return value.lower() if value else value
        return value
    
    def process_result_value(self, value, dialect):
        if value is None:
            return None
        try:
            return self.enum_class(value)
        except ValueError:
            return value


class Document(Base, TimestampMixin):
    """
    Dokument (DMS)
    Zentrale Dokumentenverwaltung
    """
    __tablename__ = "documents"

    id = Column(String, primary_key=True, default=generate_uuid)
    owner_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    client_id = Column(String, ForeignKey("clients.id", ondelete="CASCADE"), nullable=False, index=True)
    
    # Datei-Informationen
    filename = Column(String(255), nullable=False)
    file_path = Column(String(500), nullable=False)  # Pfad zur Datei
    file_size = Column(Integer, nullable=True)  # Größe in Bytes
    mime_type = Column(String(100), nullable=True)  # MIME-Type
    
    # Metadaten
    # Verwende EnumValueType, um sicherzustellen, dass der Enum-Wert (lowercase String) verwendet wird
    # statt des Enum-Namens (wichtig für PostgreSQL Enums mit create_type=False)
    document_type = Column(EnumValueType(DocumentType), default=DocumentType.OTHER.value, nullable=False)
    title = Column(String(255), nullable=True)  # Anzeigename
    description = Column(Text, nullable=True)
    
    # Portal-Veröffentlichung
    status = Column(EnumValueType(DocumentStatus), default=DocumentStatus.DRAFT.value, nullable=False)
    billing_year = Column(Integer, nullable=True, index=True)  # Abrechnungsjahr (z.B. 2025)
    published_at = Column(DateTime(timezone=True), nullable=True)  # Veröffentlichungsdatum
    
    # Datum (falls relevant)
    document_date = Column(Date, nullable=True)  # Datum des Dokuments (z.B. Rechnungsdatum)
    
    # Verknüpfungen (optional, mehrere möglich)
    property_id = Column(String, ForeignKey("properties.id", ondelete="SET NULL"), nullable=True, index=True)
    unit_id = Column(String, ForeignKey("units.id", ondelete="SET NULL"), nullable=True, index=True)
    tenant_id = Column(String, ForeignKey("tenants.id", ondelete="SET NULL"), nullable=True, index=True)
    lease_id = Column(String, ForeignKey("leases.id", ondelete="SET NULL"), nullable=True, index=True)
    ticket_id = Column(String, ForeignKey("tickets.id", ondelete="SET NULL"), nullable=True, index=True)
    accounting_id = Column(String, ForeignKey("accountings.id", ondelete="SET NULL"), nullable=True, index=True)
    charge_id = Column(String, ForeignKey("charges.id", ondelete="SET NULL"), nullable=True, index=True)
    
    # Tags (für Suche)
    tags = Column(Text, nullable=True)  # Komma-getrennte Tags
    
    # Relationships
    owner = relationship("User", foreign_keys=[owner_id])
    client = relationship("Client", foreign_keys=[client_id])
    property = relationship("Property", foreign_keys=[property_id])
    unit = relationship("Unit", foreign_keys=[unit_id])
    tenant = relationship("Tenant", foreign_keys=[tenant_id])
    lease = relationship("Lease", foreign_keys=[lease_id])
    ticket = relationship("Ticket", foreign_keys=[ticket_id])
    accounting = relationship("Accounting", foreign_keys=[accounting_id])
    charge = relationship("Charge", foreign_keys=[charge_id])
    
    __table_args__ = (
        Index('ix_documents_type', 'document_type'),
        Index('ix_documents_property', 'property_id'),
        Index('ix_documents_tenant', 'tenant_id'),
    )

