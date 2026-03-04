#!/usr/bin/env python3
"""
Migration: Add company_name (Firma/Gewerbe) to tenants
"""
from app.db import engine
from sqlalchemy import text

migration_sql = """
ALTER TABLE tenants 
ADD COLUMN IF NOT EXISTS company_name VARCHAR(255);

-- first_name/last_name nullable für Gewerbe (nur company_name gesetzt)
ALTER TABLE tenants ALTER COLUMN first_name DROP NOT NULL;
ALTER TABLE tenants ALTER COLUMN last_name DROP NOT NULL;
"""

print("🔄 Migration: company_name für Gewerbe (Tenants)...")
try:
    with engine.begin() as conn:
        conn.execute(text(migration_sql))
    print("✅ Migration erfolgreich! (company_name hinzugefügt)")
except Exception as e:
    print(f"❌ Fehler: {str(e)}")
    raise
