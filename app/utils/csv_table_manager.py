"""
CSV-Tabellen-Manager: Speichert CSV-Daten als PostgreSQL-Tabellen
EINFACH: CSV → PostgreSQL-Tabelle
"""
import logging
import re
from typing import List, Dict, Optional
from sqlalchemy import text, inspect
from sqlalchemy.orm import Session
from sqlalchemy.exc import SQLAlchemyError

logger = logging.getLogger(__name__)


def sanitize_table_name(name: str) -> str:
    """Erstelle einen sicheren Tabellennamen"""
    name = name.rsplit('.', 1)[0] if '.' in name else name
    name = re.sub(r'[^a-zA-Z0-9_]', '_', name)
    if name and name[0].isdigit():
        name = 'csv_' + name
    name = name[:50]  # Kürzer für bessere Lesbarkeit
    if not name:
        name = 'csv_table'
    return name.lower()


def create_and_fill_csv_table(
    db: Session,
    csv_file_id: str,
    filename: str,
    headers: List[str],
    rows: List[Dict]
) -> Optional[str]:
    """
    EINFACH: Erstelle Tabelle und füge ALLE CSV-Daten ein
    
    Args:
        db: Database Session
        csv_file_id: ID der CSV-Datei
        filename: Dateiname
        headers: Liste von Spalten-Namen
        rows: Liste von Zeilen (jede Zeile ist ein Dict mit "raw_data")
    
    Returns:
        Tabellenname bei Erfolg, None bei Fehler
    """
    try:
        # 1. Erstelle Tabellenname
        safe_name = sanitize_table_name(filename)
        table_name = f"csv_data_{safe_name}_{csv_file_id[:8]}"
        
        logger.info(f"📊 Erstelle Tabelle: {table_name}")
        logger.info(f"   {len(headers)} Spalten, {len(rows)} Zeilen")
        
        # 2. Prüfe ob Tabelle existiert (lösche alte falls vorhanden)
        inspector = inspect(db.bind)
        if table_name in inspector.get_table_names():
            logger.warning(f"⚠️ Tabelle {table_name} existiert bereits - lösche sie")
            db.execute(text(f"DROP TABLE IF EXISTS {table_name} CASCADE"))
            db.commit()
        
        # 3. Erstelle Spalten-Definitionen
        column_defs = [
            "id SERIAL PRIMARY KEY",
            "csv_file_id VARCHAR NOT NULL",
            "row_index INTEGER NOT NULL"
        ]
        
        # Sanitize Spalten-Namen
        safe_headers = []
        for header in headers:
            safe_header = re.sub(r'[^a-zA-Z0-9_]', '_', header).lower()
            if not safe_header or safe_header[0].isdigit():
                safe_header = 'col_' + safe_header
            safe_header = safe_header[:63]
            safe_headers.append(safe_header)
            column_defs.append(f'"{safe_header}" TEXT')
        
        # 4. Erstelle Tabelle
        create_sql = f"""
        CREATE TABLE {table_name} (
            {', '.join(column_defs)}
        );
        """
        
        db.execute(text(create_sql))
        db.commit()
        logger.info(f"✅ Tabelle {table_name} erstellt")
        
        # 5. Füge ALLE Daten ein
        inserted = 0
        for row_index, row in enumerate(rows):
            try:
                if "error" in row:
                    continue
                
                raw_data = row.get("raw_data", {})
                
                # Erstelle Spalten und Werte
                col_names = ["csv_file_id", "row_index"] + [f'"{h}"' for h in safe_headers]
                values = [csv_file_id, row_index]
                
                # Füge Werte für jede Spalte hinzu
                for header in headers:
                    value = raw_data.get(header, "")
                    if value is None:
                        value = ""
                    values.append(str(value))
                
                # Erstelle INSERT
                placeholders = [f":val_{i}" for i in range(len(col_names))]
                insert_sql = f"""
                INSERT INTO {table_name} ({', '.join(col_names)})
                VALUES ({', '.join(placeholders)})
                """
                
                params = {f"val_{i}": val for i, val in enumerate(values)}
                db.execute(text(insert_sql), params)
                inserted += 1
                
            except Exception as row_error:
                logger.warning(f"⚠️ Fehler bei Zeile {row_index}: {str(row_error)}")
                continue
        
        # 6. Commit alle Inserts
        db.commit()
        logger.info(f"✅ {inserted} Zeilen in {table_name} eingefügt")
        
        return table_name
        
    except Exception as e:
        logger.error(f"❌ Fehler beim Erstellen/Füllen der Tabelle: {str(e)}")
        import traceback
        logger.error(traceback.format_exc())
        db.rollback()
        return None


def query_csv_table(
    db: Session,
    table_name: str,
    csv_file_id: Optional[str] = None,
    limit: Optional[int] = None
) -> List[Dict]:
    """Lese Daten aus CSV-Tabelle"""
    try:
        # Prüfe ob Tabelle existiert
        from sqlalchemy import inspect
        inspector = inspect(db.bind)
        if table_name not in inspector.get_table_names():
            logger.error(f"❌ Tabelle {table_name} existiert nicht!")
            return []
        
        where_clause = ""
        params = {}
        
        if csv_file_id:
            where_clause = "WHERE csv_file_id = :csv_file_id"
            params["csv_file_id"] = csv_file_id
        
        limit_clause = f"LIMIT {limit}" if limit else ""
        
        query_sql = f"""
        SELECT * FROM {table_name} 
        {where_clause} 
        ORDER BY row_index 
        {limit_clause}
        """
        
        logger.debug(f"🔍 SQL Query: {query_sql}")
        logger.debug(f"   Params: {params}")
        
        result = db.execute(text(query_sql), params)
        rows = []
        
        for row in result:
            row_dict = dict(row._mapping)
            rows.append(row_dict)
        
        logger.info(f"📊 {len(rows)} Zeilen aus {table_name} gelesen")
        if rows and len(rows) > 0:
            logger.debug(f"   Erste Zeile Spalten: {list(rows[0].keys())[:5]}...")
        
        return rows
        
    except Exception as e:
        logger.error(f"❌ Fehler beim Lesen der Tabelle {table_name}: {str(e)}")
        import traceback
        logger.error(traceback.format_exc())
        return []


def drop_csv_table(db: Session, table_name: str) -> bool:
    """Lösche CSV-Tabelle"""
    try:
        db.execute(text(f"DROP TABLE IF EXISTS {table_name} CASCADE"))
        db.commit()
        logger.info(f"✅ Tabelle {table_name} gelöscht")
        return True
    except Exception as e:
        logger.error(f"❌ Fehler beim Löschen: {str(e)}")
        db.rollback()
        return False
