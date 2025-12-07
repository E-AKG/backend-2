#!/usr/bin/env python3
"""
Migration: Füge table_name Spalte zu csv_files Tabelle hinzu
"""
from app.db import engine
from sqlalchemy import text

print("🔄 Füge table_name Spalte zu csv_files Tabelle hinzu...")

try:
    with engine.begin() as conn:
        # Prüfe ob Spalte bereits existiert
        check_sql = """
        SELECT column_name 
        FROM information_schema.columns 
        WHERE table_name = 'csv_files' AND column_name = 'table_name';
        """
        result = conn.execute(text(check_sql))
        exists = result.fetchone() is not None
        
        if exists:
            print("✅ Spalte table_name existiert bereits")
        else:
            # Füge Spalte hinzu
            alter_sql = """
            ALTER TABLE csv_files 
            ADD COLUMN table_name VARCHAR(255);
            """
            conn.execute(text(alter_sql))
            print("✅ Spalte table_name erfolgreich hinzugefügt")
    
    print("\n✨ Migration abgeschlossen!")
    
except Exception as e:
    print(f"❌ Fehler: {str(e)}")
    import traceback
    traceback.print_exc()

