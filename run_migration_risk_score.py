#!/usr/bin/env python3
"""
Migration Script: Add risk_score fields to tenants table
"""
import os
from app.db import engine
from sqlalchemy import text

# Lade Migration SQL
migration_sql = """
-- Add risk_score column (0-100)
ALTER TABLE tenants 
ADD COLUMN IF NOT EXISTS risk_score INTEGER;

-- Add risk_level column (low, medium, high)
DO $$ 
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'risklevel') THEN
        CREATE TYPE risklevel AS ENUM ('low', 'medium', 'high');
    END IF;
END $$;

ALTER TABLE tenants 
ADD COLUMN IF NOT EXISTS risk_level risklevel;

-- Add risk_updated_at column
ALTER TABLE tenants 
ADD COLUMN IF NOT EXISTS risk_updated_at TIMESTAMP WITH TIME ZONE;

-- Add index for risk_level for faster queries
CREATE INDEX IF NOT EXISTS ix_tenants_risk_level ON tenants(risk_level) WHERE risk_level IS NOT NULL;

-- Add index for risk_score for sorting
CREATE INDEX IF NOT EXISTS ix_tenants_risk_score ON tenants(risk_score) WHERE risk_score IS NOT NULL;
"""

print("🔄 Führe Migration für risk_score Felder aus...")

try:
    with engine.begin() as conn:
        # Führe Migration aus
        conn.execute(text(migration_sql))
    print("✅ Migration erfolgreich abgeschlossen!")
    print("   - risk_score Spalte hinzugefügt")
    print("   - risk_level Spalte hinzugefügt")
    print("   - risk_updated_at Spalte hinzugefügt")
    print("   - Indizes erstellt")
except Exception as e:
    print(f"❌ Fehler bei Migration: {str(e)}")
    print("   Möglicherweise existieren die Spalten bereits.")

