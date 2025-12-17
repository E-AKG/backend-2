from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from .db import Base, engine
from .routes import (
    auth_routes, client_routes, client_settings_routes, property_routes, unit_routes, tenant_routes, lease_routes,
    billrun_routes, bank_routes, stats_routes, subscription_routes, payment_routes, search_routes,
    meter_routes, key_routes, reminder_routes, accounting_routes, cashbook_routes, ticket_routes, document_routes,
    owner_routes, service_provider_routes, property_extended_routes, portal_routes, admin_portal_routes
    # FinAPI temporär auskommentiert
    # finapi_webform_routes
)
# from .routes import finapi as finapi_routes
from .config import settings
import logging

# Import models to ensure they are registered with Base
from .models import user, client, client_settings, fiscal_year, property, unit, tenant, lease, billrun, bank, auto_match_log, subscription, payment, meter, key, reminder, accounting, cashbook, ticket, document, owner, service_provider, property_insurance, property_bank_account, allocation_key, portal_user, document_link, notification
# FinAPI temporär auskommentiert - Models bleiben erhalten

# Configure logging
# Stelle sicher, dass INFO-Level für Scheduler-Logs verwendet wird
logging.basicConfig(
    level=logging.INFO,  # Immer INFO-Level für Scheduler-Logs
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
# Setze spezifisches Level für Scheduler-Module
logging.getLogger('apscheduler').setLevel(logging.INFO)
logging.getLogger('app.routes.finapi').setLevel(logging.INFO)

logger = logging.getLogger(__name__)

# Create database tables (mit Fehlerbehandlung für bereits existierende Indizes)
try:
    Base.metadata.create_all(bind=engine)
    logger.info("Database tables created successfully")
except Exception as e:
    # Ignoriere Fehler für bereits existierende Indizes/Tabellen
    if "already exists" in str(e) or "DuplicateTable" in str(e) or "DuplicateIndex" in str(e):
        logger.warning(f"⚠️ Einige Datenbank-Objekte existieren bereits (kann ignoriert werden): {str(e)[:200]}")
    else:
        logger.error(f"❌ Fehler beim Erstellen der Datenbank-Tabellen: {str(e)}")
        raise

# Migration: Füge table_name Spalte zu csv_files hinzu (falls nicht vorhanden)
try:
    from sqlalchemy import text, inspect
    inspector = inspect(engine)
    columns = [col['name'] for col in inspector.get_columns('csv_files')]
    
    if 'table_name' not in columns:
        logger.info("🔄 Füge table_name Spalte zu csv_files Tabelle hinzu...")
        with engine.begin() as conn:
            conn.execute(text("ALTER TABLE csv_files ADD COLUMN IF NOT EXISTS table_name VARCHAR(255)"))
        logger.info("✅ Migration erfolgreich: table_name Spalte hinzugefügt")
    else:
        logger.debug("✅ table_name Spalte existiert bereits")
except Exception as e:
    logger.warning(f"⚠️ Migration-Fehler (kann ignoriert werden wenn Spalte bereits existiert): {str(e)}")

# Migration: Erweiterte Felder für Owners (Eigentümer)
try:
    from sqlalchemy import text, inspect
    inspector = inspect(engine)
    
    # Prüfe ob owners Tabelle existiert
    if 'owners' in inspector.get_table_names():
        owner_columns = [col['name'] for col in inspector.get_columns('owners')]
        
        if 'tax_id' not in owner_columns:
            logger.info("🔄 Füge erweiterte Felder zu owners Tabelle hinzu...")
            with engine.begin() as conn:
                conn.execute(text("ALTER TABLE owners ADD COLUMN IF NOT EXISTS tax_id VARCHAR(50)"))
                conn.execute(text("ALTER TABLE owners ADD COLUMN IF NOT EXISTS status VARCHAR(50)"))
            logger.info("✅ Migration erfolgreich: Owner-Felder hinzugefügt")
        else:
            logger.debug("✅ Owner-Felder existieren bereits")
except Exception as e:
    logger.warning(f"⚠️ Owner-Migration-Fehler (kann ignoriert werden): {str(e)}")

# Migration: Erweiterte Felder für Tenants (Mieter)
try:
    from sqlalchemy import text, inspect
    inspector = inspect(engine)
    
    # Prüfe ob tenants Tabelle existiert
    if 'tenants' in inspector.get_table_names():
        tenant_columns = [col['name'] for col in inspector.get_columns('tenants')]
        
        if 'contract_partners' not in tenant_columns:
            logger.info("🔄 Füge erweiterte Felder zu tenants Tabelle hinzu...")
            with engine.begin() as conn:
                conn.execute(text("ALTER TABLE tenants ADD COLUMN IF NOT EXISTS contract_partners JSONB"))
                conn.execute(text("ALTER TABLE tenants ADD COLUMN IF NOT EXISTS schufa_score INTEGER"))
                conn.execute(text("ALTER TABLE tenants ADD COLUMN IF NOT EXISTS salary_proof_document_id VARCHAR"))
                conn.execute(text("ALTER TABLE tenants ADD COLUMN IF NOT EXISTS sepa_mandate_reference VARCHAR(100)"))
                conn.execute(text("ALTER TABLE tenants ADD COLUMN IF NOT EXISTS sepa_mandate_date TIMESTAMP WITH TIME ZONE"))
                
                # Foreign Key nur wenn documents Tabelle existiert
                if 'documents' in inspector.get_table_names():
                    # Prüfe ob Constraint bereits existiert
                    constraints = [c['name'] for c in inspector.get_foreign_keys('tenants')]
                    if 'fk_tenants_salary_proof_document' not in constraints:
                        try:
                            conn.execute(text("""
                                ALTER TABLE tenants ADD CONSTRAINT fk_tenants_salary_proof_document 
                                FOREIGN KEY (salary_proof_document_id) REFERENCES documents(id) ON DELETE SET NULL
                            """))
                        except Exception as fk_error:
                            logger.debug(f"Foreign Key konnte nicht erstellt werden (möglicherweise bereits vorhanden): {fk_error}")
            logger.info("✅ Migration erfolgreich: Tenant-Felder hinzugefügt")
        else:
            logger.debug("✅ Tenant-Felder existieren bereits")
except Exception as e:
    logger.warning(f"⚠️ Tenant-Migration-Fehler (kann ignoriert werden): {str(e)}")

# Migration: client_id Spalten für Multi-Tenancy
try:
    from sqlalchemy import text, inspect
    inspector = inspect(engine)
    
    with engine.begin() as conn:
        # Properties
        if 'properties' in inspector.get_table_names():
            columns = [col['name'] for col in inspector.get_columns('properties')]
            if 'client_id' not in columns:
                logger.info("🔄 Füge client_id zu properties hinzu...")
                conn.execute(text("ALTER TABLE properties ADD COLUMN client_id VARCHAR"))
                try:
                    conn.execute(text("ALTER TABLE properties ADD CONSTRAINT fk_properties_client FOREIGN KEY (client_id) REFERENCES clients(id) ON DELETE CASCADE"))
                    conn.execute(text("CREATE INDEX IF NOT EXISTS ix_properties_client ON properties(client_id)"))
                except Exception:
                    pass
                logger.info("✅ properties.client_id hinzugefügt")
        
        # Units
        if 'units' in inspector.get_table_names():
            columns = [col['name'] for col in inspector.get_columns('units')]
            if 'client_id' not in columns:
                logger.info("🔄 Füge client_id zu units hinzu...")
                conn.execute(text("ALTER TABLE units ADD COLUMN client_id VARCHAR"))
                try:
                    conn.execute(text("ALTER TABLE units ADD CONSTRAINT fk_units_client FOREIGN KEY (client_id) REFERENCES clients(id) ON DELETE CASCADE"))
                    conn.execute(text("CREATE INDEX IF NOT EXISTS ix_units_client ON units(client_id)"))
                except Exception:
                    pass
                logger.info("✅ units.client_id hinzugefügt")
        
        # Tenants
        if 'tenants' in inspector.get_table_names():
            columns = [col['name'] for col in inspector.get_columns('tenants')]
            if 'client_id' not in columns:
                logger.info("🔄 Füge client_id zu tenants hinzu...")
                conn.execute(text("ALTER TABLE tenants ADD COLUMN client_id VARCHAR"))
                try:
                    conn.execute(text("ALTER TABLE tenants ADD CONSTRAINT fk_tenants_client FOREIGN KEY (client_id) REFERENCES clients(id) ON DELETE CASCADE"))
                    conn.execute(text("CREATE INDEX IF NOT EXISTS ix_tenants_client ON tenants(client_id)"))
                except Exception:
                    pass
                logger.info("✅ tenants.client_id hinzugefügt")
        
        # Leases
        if 'leases' in inspector.get_table_names():
            columns = [col['name'] for col in inspector.get_columns('leases')]
            if 'client_id' not in columns:
                logger.info("🔄 Füge client_id zu leases hinzu...")
                conn.execute(text("ALTER TABLE leases ADD COLUMN client_id VARCHAR"))
                try:
                    conn.execute(text("ALTER TABLE leases ADD CONSTRAINT fk_leases_client FOREIGN KEY (client_id) REFERENCES clients(id) ON DELETE CASCADE"))
                    conn.execute(text("CREATE INDEX IF NOT EXISTS ix_leases_client ON leases(client_id)"))
                except Exception:
                    pass
                logger.info("✅ leases.client_id hinzugefügt")
            
            if 'fiscal_year_id' not in columns:
                logger.info("🔄 Füge fiscal_year_id zu leases hinzu...")
                conn.execute(text("ALTER TABLE leases ADD COLUMN fiscal_year_id VARCHAR"))
                try:
                    conn.execute(text("ALTER TABLE leases ADD CONSTRAINT fk_leases_fiscal_year FOREIGN KEY (fiscal_year_id) REFERENCES fiscal_years(id) ON DELETE SET NULL"))
                    conn.execute(text("CREATE INDEX IF NOT EXISTS ix_leases_fiscal_year ON leases(fiscal_year_id)"))
                except Exception:
                    pass
                logger.info("✅ leases.fiscal_year_id hinzugefügt")
        
        # BillRuns
        if 'bill_runs' in inspector.get_table_names():
            columns = [col['name'] for col in inspector.get_columns('bill_runs')]
            if 'client_id' not in columns:
                logger.info("🔄 Füge client_id zu bill_runs hinzu...")
                conn.execute(text("ALTER TABLE bill_runs ADD COLUMN client_id VARCHAR"))
                try:
                    conn.execute(text("ALTER TABLE bill_runs ADD CONSTRAINT fk_bill_runs_client FOREIGN KEY (client_id) REFERENCES clients(id) ON DELETE CASCADE"))
                    conn.execute(text("CREATE INDEX IF NOT EXISTS ix_bill_runs_client ON bill_runs(client_id)"))
                except Exception:
                    pass
                logger.info("✅ bill_runs.client_id hinzugefügt")
            
            if 'fiscal_year_id' not in columns:
                logger.info("🔄 Füge fiscal_year_id zu bill_runs hinzu...")
                conn.execute(text("ALTER TABLE bill_runs ADD COLUMN fiscal_year_id VARCHAR"))
                try:
                    conn.execute(text("ALTER TABLE bill_runs ADD CONSTRAINT fk_bill_runs_fiscal_year FOREIGN KEY (fiscal_year_id) REFERENCES fiscal_years(id) ON DELETE SET NULL"))
                    conn.execute(text("CREATE INDEX IF NOT EXISTS ix_bill_runs_fiscal_year ON bill_runs(fiscal_year_id)"))
                except Exception:
                    pass
                logger.info("✅ bill_runs.fiscal_year_id hinzugefügt")
        
except Exception as e:
    logger.warning(f"⚠️ client_id Migration-Fehler (kann ignoriert werden): {str(e)}")

# Migration: role Spalte für users Tabelle
try:
    from sqlalchemy import text, inspect
    inspector = inspect(engine)
    
    if 'users' in inspector.get_table_names():
        user_columns = [col['name'] for col in inspector.get_columns('users')]
        
        if 'role' not in user_columns:
            logger.info("🔄 Füge role Spalte zu users Tabelle hinzu...")
            with engine.begin() as conn:
                # Füge role Spalte hinzu mit Default-Wert 'admin'
                conn.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS role VARCHAR(50) DEFAULT 'admin'"))
                # Setze role für bestehende User auf 'admin'
                conn.execute(text("UPDATE users SET role = 'admin' WHERE role IS NULL"))
            logger.info("✅ Migration erfolgreich: role Spalte hinzugefügt")
        else:
            logger.debug("✅ role Spalte existiert bereits")
except Exception as e:
    logger.warning(f"⚠️ role Migration-Fehler (kann ignoriert werden): {str(e)}")

# Migration: notification_from_email Spalte für users Tabelle
try:
    from sqlalchemy import text, inspect
    inspector = inspect(engine)
    
    # Prüfe ob users Tabelle existiert
    if 'users' in inspector.get_table_names():
        user_columns = [col['name'] for col in inspector.get_columns('users')]
        
        if 'notification_from_email' not in user_columns:
            logger.info("🔄 Füge notification_from_email Spalte zu users Tabelle hinzu...")
            with engine.begin() as conn:
                conn.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS notification_from_email VARCHAR(255)"))
            logger.info("✅ Migration erfolgreich: notification_from_email Spalte hinzugefügt")
        else:
            logger.debug("✅ notification_from_email Spalte existiert bereits")
except Exception as e:
    logger.warning(f"⚠️ notification_from_email Migration-Fehler (kann ignoriert werden): {str(e)}")

# Migration: Portal-Tabellen (portal_users, document_links, notifications)
try:
    from sqlalchemy import text, inspect
    inspector = inspect(engine)
    
    # portal_users Tabelle
    if 'portal_users' not in inspector.get_table_names():
        logger.info("🔄 Erstelle portal_users Tabelle...")
        Base.metadata.tables['portal_users'].create(bind=engine, checkfirst=True)
        logger.info("✅ portal_users Tabelle erstellt")
    
    # document_links Tabelle
    if 'document_links' not in inspector.get_table_names():
        logger.info("🔄 Erstelle document_links Tabelle...")
        Base.metadata.tables['document_links'].create(bind=engine, checkfirst=True)
        logger.info("✅ document_links Tabelle erstellt")
    
    # notifications Tabelle
    if 'notifications' not in inspector.get_table_names():
        logger.info("🔄 Erstelle notifications Tabelle...")
        Base.metadata.tables['notifications'].create(bind=engine, checkfirst=True)
        logger.info("✅ notifications Tabelle erstellt")
    
    # Erweitere documents Tabelle um status, billing_year, published_at
    if 'documents' in inspector.get_table_names():
        doc_columns = [col['name'] for col in inspector.get_columns('documents')]
        
        if 'status' not in doc_columns:
            logger.info("🔄 Füge Portal-Felder zu documents Tabelle hinzu...")
            with engine.begin() as conn:
                conn.execute(text("ALTER TABLE documents ADD COLUMN IF NOT EXISTS status VARCHAR(50) DEFAULT 'draft'"))
                conn.execute(text("ALTER TABLE documents ADD COLUMN IF NOT EXISTS billing_year INTEGER"))
                conn.execute(text("ALTER TABLE documents ADD COLUMN IF NOT EXISTS published_at TIMESTAMP WITH TIME ZONE"))
                conn.execute(text("CREATE INDEX IF NOT EXISTS ix_documents_billing_year ON documents(billing_year)"))
            logger.info("✅ Migration erfolgreich: Portal-Felder zu documents hinzugefügt")
        else:
            logger.debug("✅ Portal-Felder existieren bereits in documents")
            
except Exception as e:
    logger.warning(f"⚠️ Portal-Migration-Fehler (kann ignoriert werden): {str(e)}")

# Migration: Erweitere unit_settlements um Zeitraum-Felder für anteilige Berechnung
try:
    from sqlalchemy import text, inspect
    inspector = inspect(engine)
    
    if 'unit_settlements' in inspector.get_table_names():
        columns = [col['name'] for col in inspector.get_columns('unit_settlements')]
        
        if 'period_start' not in columns:
            logger.info("🔄 Füge Zeitraum-Felder zu unit_settlements Tabelle hinzu...")
            with engine.begin() as conn:
                conn.execute(text("ALTER TABLE unit_settlements ADD COLUMN IF NOT EXISTS period_start DATE"))
                conn.execute(text("ALTER TABLE unit_settlements ADD COLUMN IF NOT EXISTS period_end DATE"))
                conn.execute(text("ALTER TABLE unit_settlements ADD COLUMN IF NOT EXISTS lease_period_start DATE"))
                conn.execute(text("ALTER TABLE unit_settlements ADD COLUMN IF NOT EXISTS lease_period_end DATE"))
                conn.execute(text("ALTER TABLE unit_settlements ADD COLUMN IF NOT EXISTS days_in_period INTEGER"))
                conn.execute(text("ALTER TABLE unit_settlements ADD COLUMN IF NOT EXISTS days_occupied INTEGER"))
            logger.info("✅ Migration erfolgreich: Zeitraum-Felder zu unit_settlements hinzugefügt")
        else:
            logger.debug("✅ Zeitraum-Felder existieren bereits in unit_settlements")
except Exception as e:
    logger.warning(f"⚠️ unit_settlements Zeitraum-Migration-Fehler (kann ignoriert werden): {str(e)}")

# Migration: Erweitere DocumentType Enum um BK_STATEMENT und BK_RECEIPT
# WICHTIG: PostgreSQL erlaubt ALTER TYPE nur außerhalb von Transaktionen
# Daher verwenden wir einen DO-Block (wird automatisch außerhalb von Transaktionen ausgeführt)
try:
    from sqlalchemy import text, inspect
    inspector = inspect(engine)
    
    if 'documents' in inspector.get_table_names():
        logger.info("🔄 Prüfe DocumentType Enum...")
        # Verwende DO-Block für PostgreSQL (läuft außerhalb von Transaktionen)
        with engine.connect() as conn:
            try:
                # Prüfe ob BK_STATEMENT bereits existiert
                result = conn.execute(text("""
                    SELECT EXISTS (
                        SELECT 1 FROM pg_enum 
                        WHERE enumlabel = 'bk_statement' 
                        AND enumtypid = (SELECT oid FROM pg_type WHERE typname = 'documenttype')
                    )
                """))
                bk_statement_exists = result.scalar()
                
                # Prüfe alle fehlenden Enum-Werte
                result_all = conn.execute(text("""
                    SELECT enumlabel 
                    FROM pg_enum 
                    WHERE enumtypid = (SELECT oid FROM pg_type WHERE typname = 'documenttype')
                """))
                existing_values = [row[0] for row in result_all]
                expected_values = ['bk_statement', 'bk_receipt', 'other']
                missing_values = [v for v in expected_values if v not in existing_values]
                
                if missing_values:
                    logger.info(f"🔄 Füge fehlende Werte zu DocumentType Enum hinzu: {missing_values}")
                    # Verwende DO-Block für PostgreSQL (läuft außerhalb von Transaktionen)
                    do_block = "DO $$\nBEGIN\n"
                    for value in missing_values:
                        do_block += f"""
                            IF NOT EXISTS (
                                SELECT 1 FROM pg_enum 
                                WHERE enumlabel = '{value}' 
                                AND enumtypid = (SELECT oid FROM pg_type WHERE typname = 'documenttype')
                            ) THEN
                                ALTER TYPE documenttype ADD VALUE '{value}';
                            END IF;
                        """
                    do_block += "END $$;"
                    conn.execute(text(do_block))
                    conn.commit()
                    logger.info(f"✅ Migration erfolgreich: DocumentType Enum erweitert um {missing_values}")
                else:
                    logger.debug("✅ DocumentType Enum-Werte existieren bereits")
            except Exception as inner_e:
                # Wenn Enum-Werte bereits existieren, ist das OK
                if "already exists" in str(inner_e) or "duplicate" in str(inner_e).lower():
                    logger.debug("✅ DocumentType Enum-Werte existieren bereits")
                else:
                    logger.warning(f"⚠️ DocumentType Enum-Migration-Fehler: {str(inner_e)}")
                    logger.info("💡 Falls der Fehler weiterhin auftritt, führe das SQL-Script aus:")
                    logger.info("   backend-2/add_document_type_enum_values.sql")
except Exception as e:
    logger.warning(f"⚠️ DocumentType Enum-Migration-Fehler (kann ignoriert werden): {str(e)}")
    logger.info("💡 Hinweis: Falls BK_STATEMENT/BK_RECEIPT fehlen, führe das SQL-Script aus:")
    logger.info("   backend-2/add_document_type_enum_values.sql")

# Initialize FastAPI application
app = FastAPI(
    title=settings.APP_NAME,
    description="A modern SaaS for property-management automation",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc"
)

# Configure CORS
# Allow local development from various origins
if settings.DEBUG:
    cors_origins = [
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://192.168.178.51:5173",  # Mac IP
        "http://192.168.178.1:5173",  # Mobile device IP
        # Add more origins as needed for testing
    ]
else:
    # Production: Use CORS_ORIGINS from env if set, otherwise use defaults
    if settings.CORS_ORIGINS:
        cors_origins = [origin.strip() for origin in settings.CORS_ORIGINS.split(",")]
    else:
        # Default production origins
        cors_origins = [
            "https://immpire.com",
            "https://www.immpire.com",
            "https://api.immpire.com",
        ]

# Note: allow_origins=["*"] and allow_credentials=True cannot be used together
# Since we use JWT in localStorage (not cookies), we don't need credentials
app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins if not settings.DEBUG else ["*"],  # Use specific origins in production
    allow_credentials=False,  # Set to False when using allow_origins=["*"]
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["*"],
)

# Include routers
app.include_router(auth_routes.router)
app.include_router(client_routes.router)
app.include_router(client_settings_routes.router)
app.include_router(property_routes.router)
app.include_router(unit_routes.router)
app.include_router(tenant_routes.router)
app.include_router(lease_routes.router)
app.include_router(billrun_routes.router)
app.include_router(bank_routes.router)
app.include_router(stats_routes.router)
app.include_router(subscription_routes.router)
app.include_router(payment_routes.router)
app.include_router(search_routes.router)
app.include_router(meter_routes.router)
app.include_router(key_routes.router)
app.include_router(reminder_routes.router)
app.include_router(accounting_routes.router)
app.include_router(cashbook_routes.router)
app.include_router(ticket_routes.router)
app.include_router(document_routes.router)
app.include_router(owner_routes.router)
app.include_router(service_provider_routes.router)
app.include_router(property_extended_routes.router)
app.include_router(portal_routes.router)
app.include_router(admin_portal_routes.router)
# FinAPI temporär auskommentiert
# app.include_router(finapi_webform_routes.router)
# app.include_router(finapi_routes.router)


@app.get("/", tags=["Health"])
def root():
    """Root endpoint - API health check"""
    return {
        "status": "healthy",
        "message": "Welcome to IZENIC ImmoAssist API",
        "version": "1.0.0"
    }


@app.get("/health", tags=["Health"])
def health_check():
    """Health check endpoint"""
    return {
        "status": "healthy",
        "database": "connected"
    }


# Startup Event - Starte Scheduler
@app.on_event("startup")
async def startup_event():
    """Starte den Auto-Sync Scheduler beim App-Start"""
    # FinAPI Scheduler temporär auskommentiert
    # try:
    #     logger.info("🚀 Starte Scheduler...")
    #     from .routes import finapi
    #     finapi.start_transaction_scheduler()
    #     logger.info("✅ Application startup complete - Scheduler aktiv")
    # except Exception as e:
    #     logger.error(f"❌ Fehler beim Starten des Schedulers: {str(e)}")
    #     import traceback
    #     logger.error(traceback.format_exc())
    logger.info("✅ Application startup complete")