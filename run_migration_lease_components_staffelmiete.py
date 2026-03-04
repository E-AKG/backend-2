#!/usr/bin/env python3
"""
Migration Script: Add adjustment_type and staggered_schedule to lease_components
Für Staffelmiete (Mieterhöhungen).
"""
import os
from app.db import engine
from sqlalchemy import text

migration_sql = """
-- Enum-Typ für Mietanpassung (falls nicht existiert)
DO $$ 
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'rentadjustmenttype') THEN
        CREATE TYPE rentadjustmenttype AS ENUM ('fixed', 'staggered', 'index_linked');
    END IF;
END $$;

-- adjustment_type Spalte (DEFAULT setzt Wert für bestehende Zeilen)
ALTER TABLE lease_components 
ADD COLUMN IF NOT EXISTS adjustment_type rentadjustmenttype DEFAULT 'fixed';

-- Fallback: bestehende NULLs auf 'fixed' setzen
UPDATE lease_components SET adjustment_type = 'fixed' WHERE adjustment_type IS NULL;

-- Default und NOT NULL
ALTER TABLE lease_components ALTER COLUMN adjustment_type SET DEFAULT 'fixed';
ALTER TABLE lease_components ALTER COLUMN adjustment_type SET NOT NULL;

-- staggered_schedule Spalte (JSONB)
ALTER TABLE lease_components 
ADD COLUMN IF NOT EXISTS staggered_schedule JSONB;

-- Index für schnellere Abfragen
CREATE INDEX IF NOT EXISTS ix_lease_components_adjustment_type 
ON lease_components(adjustment_type) WHERE adjustment_type != 'fixed';
"""

print("🔄 Migration: adjustment_type und staggered_schedule für lease_components...")

try:
    with engine.begin() as conn:
        conn.execute(text(migration_sql))
    print("✅ Migration erfolgreich!")
    print("   - adjustment_type Spalte hinzugefügt (fixed/staggered/index_linked)")
    print("   - staggered_schedule Spalte hinzugefügt (JSONB)")
except Exception as e:
    print(f"❌ Fehler: {str(e)}")
    if "already exists" in str(e).lower() or "duplicate" in str(e).lower():
        print("   Die Spalten existieren möglicherweise bereits.")
    raise
