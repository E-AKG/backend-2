from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from .db import Base, engine
from .routes import (
    auth_routes, client_routes, client_settings_routes, property_routes, unit_routes, tenant_routes, lease_routes,
    billrun_routes, bank_routes, stats_routes, subscription_routes, payment_routes, search_routes,
    meter_routes, key_routes, reminder_routes, accounting_routes, cashbook_routes, ticket_routes, document_routes,
    owner_routes, service_provider_routes
    # FinAPI temporär auskommentiert
    # finapi_webform_routes
)
# from .routes import finapi as finapi_routes
from .config import settings
import logging

# Import models to ensure they are registered with Base
from .models import user, client, client_settings, fiscal_year, property, unit, tenant, lease, billrun, bank, auto_match_log, subscription, payment, meter, key, reminder, accounting, cashbook, ticket, document, owner, service_provider
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

# Create database tables
Base.metadata.create_all(bind=engine)
logger.info("Database tables created successfully")

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
    # Production: Only allow specific domains
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