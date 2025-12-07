"""
CSV-Matcher: Führt Abgleich direkt mit CSV-Tabellen durch
"""
import logging
from typing import List, Dict, Optional
from decimal import Decimal
from datetime import date, datetime
from sqlalchemy import text
from sqlalchemy.orm import Session
from ..models.bank import CsvFile, BankTransaction, PaymentMatch
from ..models.billrun import Charge, ChargeStatus
from ..models.lease import Lease
from ..models.tenant import Tenant
from ..models.unit import Unit
from .auto_matcher import calculate_match_score

logger = logging.getLogger(__name__)


def match_csv_table_transactions(
    db: Session,
    csv_file: CsvFile,
    owner_id: int,
    min_confidence: float = 80.0
) -> Dict:
    """
    Führe Abgleich direkt mit CSV-Tabellen-Daten durch
    
    Args:
        db: Database Session
        csv_file: CsvFile Objekt mit table_name
        owner_id: Benutzer ID
        min_confidence: Minimaler Confidence Score
    
    Returns:
        Dict mit Statistiken
    """
    if not csv_file.table_name:
        logger.warning(f"⚠️ CSV-Datei {csv_file.id} hat keine PostgreSQL-Tabelle")
        return {"matched": 0, "processed": 0, "errors": 0}
    
    stats = {
        "matched": 0,
        "processed": 0,
        "errors": 0,
        "no_match": 0
    }
    
    try:
        # Hole offene Sollbuchungen
        open_charges = db.query(Charge).join(
            Charge.bill_run
        ).filter(
            Charge.bill_run.has(owner_id=owner_id),
            Charge.status.in_([ChargeStatus.OPEN, ChargeStatus.PARTIALLY_PAID])
        ).all()
        
        logger.info(f"📊 {len(open_charges)} offene Sollbuchungen gefunden")
        
        # Lese alle Zeilen aus CSV-Tabelle
        from .csv_table_manager import query_csv_table
        
        csv_rows = query_csv_table(db, csv_file.table_name, csv_file.id)
        logger.info(f"📊 {len(csv_rows)} Zeilen aus CSV-Tabelle {csv_file.table_name} gelesen")
        
        if not csv_rows:
            logger.warning(f"⚠️ Keine Daten in Tabelle {csv_file.table_name}")
            return stats
        
        # Hole Spalten-Namen aus der ersten Zeile (Tabelle hat sanitized Namen)
        # Die Spalten sind: id, csv_file_id, row_index, dann die CSV-Spalten
        table_columns = [k for k in csv_rows[0].keys() if k not in ['id', 'csv_file_id', 'row_index']]
        
        # Parse Original-Header aus column_mapping
        import json
        column_mapping = json.loads(csv_file.column_mapping) if csv_file.column_mapping else {}
        original_headers = column_mapping.get("headers", [])
        
        # Erstelle Mapping: Original-Header → Sanitized Spaltenname
        import re
        header_to_column = {}
        for orig_header in original_headers:
            safe_name = re.sub(r'[^a-zA-Z0-9_]', '_', orig_header).lower()
            if not safe_name or safe_name[0].isdigit():
                safe_name = 'col_' + safe_name
            safe_name = safe_name[:63]
            # Finde passende Spalte in Tabelle
            for col in table_columns:
                if col.lower() == safe_name.lower() or col.lower().replace('"', '') == safe_name:
                    header_to_column[orig_header] = col
                    break
        
        logger.info(f"📋 {len(header_to_column)} Spalten-Mappings erstellt")
        
        # Erkenne Spalten automatisch (verwende Original-Header)
        # WICHTIG: Exakte Matches haben Priorität!
        date_col = None
        amount_col = None
        iban_col = None
        name_col = None
        purpose_col = None
        
        # Zuerst: Suche nach exakten/priorisierten Matches
        for header in original_headers:
            header_lower = header.lower().strip()
            
            # DATUM: Priorität für exakte Matches
            if not date_col:
                if header_lower in ['buchungstag', 'valutadatum', 'datum', 'date', 'buchungsdatum']:
                    date_col = header
                elif any(x in header_lower for x in ['buchungstag', 'valutadatum']):
                    date_col = header
            
            # BETRAG: "Betrag" hat höchste Priorität (nicht "Lastschrift Ursprungsbetrag"!)
            if not amount_col:
                if header_lower == 'betrag' or header_lower == 'amount':
                    amount_col = header
                elif 'betrag' in header_lower and 'lastschrift' not in header_lower and 'ursprungsbetrag' not in header_lower:
                    amount_col = header
            
            # IBAN: Priorität für exakte Matches
            if not iban_col:
                if header_lower in ['iban', 'kontonummer/iban', 'kontonummer_iban']:
                    iban_col = header
                elif 'iban' in header_lower and 'kontonummer' in header_lower:
                    iban_col = header
            
            # NAME: Priorität für exakte Matches
            if not name_col:
                if header_lower in ['beguenstigter/zahlungspflichtiger', 'beguenstigter', 'name', 'empfaenger']:
                    name_col = header
                elif 'beguenstigter' in header_lower or 'zahlungspflichtig' in header_lower:
                    name_col = header
            
            # ZWECK: "Verwendungszweck" hat höchste Priorität (nicht "Buchungstext"!)
            if not purpose_col:
                if header_lower == 'verwendungszweck' or header_lower == 'purpose':
                    purpose_col = header
                elif 'verwendungszweck' in header_lower:
                    purpose_col = header
        
        # Zweiter Durchlauf: Fallback für nicht gefundene Spalten
        if not date_col:
            for header in original_headers:
                header_lower = header.lower()
                if any(x in header_lower for x in ['datum', 'date']):
                    date_col = header
                    break
        
        if not amount_col:
            for header in original_headers:
                header_lower = header.lower()
                if any(x in header_lower for x in ['betrag', 'amount', 'summe']):
                    amount_col = header
                    break
        
        if not iban_col:
            for header in original_headers:
                header_lower = header.lower()
                if any(x in header_lower for x in ['iban', 'kontonummer', 'account']):
                    iban_col = header
                    break
        
        if not name_col:
            for header in original_headers:
                header_lower = header.lower()
                if any(x in header_lower for x in ['name', 'empfaenger', 'sender', 'absender']):
                    name_col = header
                    break
        
        if not purpose_col:
            for header in original_headers:
                header_lower = header.lower()
                if any(x in header_lower for x in ['buchungstext', 'zweck', 'info', 'text', 'memo']):
                    purpose_col = header
                    break
        
        logger.info(f"🔍 Erkannte Spalten: Datum={date_col}, Betrag={amount_col}, IBAN={iban_col}, Name={name_col}, Zweck={purpose_col}")
        
        if not date_col or not amount_col:
            logger.warning(f"⚠️ WICHTIGE Spalten fehlen! Datum={date_col}, Betrag={amount_col}")
            logger.warning(f"   Verfügbare Original-Header: {original_headers}")
            logger.warning(f"   Verfügbare Tabellen-Spalten: {table_columns[:10]}...")
        
        # Debug: Zeige alle verfügbaren Header für Betrag
        if amount_col:
            logger.info(f"✅ Betrag-Spalte: '{amount_col}' (Mapping: {header_to_column.get(amount_col, 'NICHT GEFUNDEN')})")
        else:
            betrag_candidates = [h for h in original_headers if 'betrag' in h.lower()]
            logger.warning(f"⚠️ Keine Betrag-Spalte gefunden! Kandidaten: {betrag_candidates}")
        
        # Debug: Zeige alle verfügbaren Header für Zweck
        if purpose_col:
            logger.info(f"✅ Zweck-Spalte: '{purpose_col}' (Mapping: {header_to_column.get(purpose_col, 'NICHT GEFUNDEN')})")
        else:
            zweck_candidates = [h for h in original_headers if any(x in h.lower() for x in ['zweck', 'text', 'purpose'])]
            logger.warning(f"⚠️ Keine Zweck-Spalte gefunden! Kandidaten: {zweck_candidates}")
        
        # Für jede CSV-Zeile
        logger.info(f"🔄 Starte Verarbeitung von {len(csv_rows)} CSV-Zeilen...")
        for csv_row in csv_rows:
            try:
                stats["processed"] += 1
                row_idx = csv_row.get('row_index', stats["processed"] - 1)
                
                if stats["processed"] <= 3:  # Log nur erste 3 Zeilen
                    logger.info(f"📄 Verarbeite Zeile {row_idx} (Zeile {stats['processed']}/{len(csv_rows)})")
                
                # Extrahiere Daten aus CSV-Zeile (direkt aus Tabelle)
                # Verwende header_to_column Mapping um richtige Spalte zu finden
                
                def get_value(original_header):
                    """Hole Wert aus Tabelle basierend auf Original-Header"""
                    if original_header not in header_to_column:
                        return None
                    table_col = header_to_column[original_header]
                    return csv_row.get(table_col)
                
                # Parse Datum
                transaction_date = date.today()
                if date_col:
                    date_value = get_value(date_col)
                    if date_value:
                        date_str = str(date_value).strip()
                        if date_str:
                            date_formats = [
                                '%d.%m.%Y', '%d.%m.%y', '%Y-%m-%d',
                                '%d/%m/%Y', '%d-%m-%Y'
                            ]
                            for fmt in date_formats:
                                try:
                                    transaction_date = datetime.strptime(date_str, fmt).date()
                                    break
                                except:
                                    continue
                
                # Parse Betrag
                amount = Decimal('0')
                if amount_col:
                    amount_value = get_value(amount_col)
                    if stats["processed"] <= 3:
                        logger.info(f"   🔍 Betrag-Rohwert aus Spalte '{amount_col}': {amount_value} (Typ: {type(amount_value).__name__})")
                    if amount_value:
                        try:
                            amount_str = str(amount_value).replace(',', '.').replace(' ', '').replace('€', '').strip()
                            if amount_str:
                                amount = Decimal(amount_str)
                                if stats["processed"] <= 3:
                                    logger.info(f"   ✅ Betrag geparst: {amount}€")
                        except Exception as e:
                            if stats["processed"] <= 3:
                                logger.warning(f"   ⚠️ Fehler beim Parsen von Betrag '{amount_value}': {str(e)}")
                else:
                    if stats["processed"] <= 3:
                        logger.warning(f"   ⚠️ Keine Betrag-Spalte erkannt!")
                
                # Nur Eingänge (positive Beträge)
                if amount <= 0:
                    if stats["processed"] <= 3:
                        logger.info(f"   ⏭️ Überspringe: Betrag {amount} <= 0 (Ausgang)")
                    continue
                
                if stats["processed"] <= 3:
                    logger.info(f"   ✅ Zeile {row_idx}: {amount}€, {transaction_date}")
                    logger.info(f"      IBAN: {counterpart_iban or 'N/A'}")
                    logger.info(f"      Name: {counterpart_name or 'N/A'}")
                    logger.info(f"      Zweck: {purpose[:80] if purpose else 'N/A'}")
                
                # Extrahiere weitere Felder
                counterpart_iban = None
                counterpart_name = None
                purpose = None
                
                if iban_col:
                    iban_value = get_value(iban_col)
                    if iban_value:
                        counterpart_iban = str(iban_value).strip() or None
                
                if name_col:
                    name_value = get_value(name_col)
                    if name_value:
                        counterpart_name = str(name_value).strip() or None
                
                if purpose_col:
                    purpose_value = get_value(purpose_col)
                    if purpose_value:
                        purpose = str(purpose_value).strip() or None
                
                # Erstelle temporäres BankTransaction-Objekt für Matching
                from ..models.bank import BankTransaction
                temp_transaction = type('obj', (object,), {
                    'amount': amount,
                    'transaction_date': transaction_date,
                    'counterpart_iban': counterpart_iban,
                    'counterpart_name': counterpart_name,
                    'purpose': purpose,
                    'id': f"csv_{csv_file.id}_{csv_row.get('row_index', 0)}"
                })()
                
                # Finde beste Übereinstimmung
                best_match = None
                best_score = 0.0
                
                for charge in open_charges:
                    # Hole Mieter und Einheit
                    lease = db.query(Lease).filter(Lease.id == charge.lease_id).first()
                    if not lease:
                        continue
                    
                    tenant = db.query(Tenant).filter(Tenant.id == lease.tenant_id).first()
                    if not tenant:
                        continue
                    
                    unit = db.query(Unit).filter(Unit.id == lease.unit_id).first()
                    unit_label = unit.unit_label if unit else None
                    
                    # Berechne Score
                    score_result = calculate_match_score(
                        temp_transaction, charge, tenant, unit_label
                    )
                    
                    # Debug-Logging für erste 3 Zeilen
                    if stats["processed"] <= 3:
                        logger.info(f"   🔍 Charge {charge.id}: {charge.amount}€, Mieter: {tenant.first_name} {tenant.last_name}, Einheit: {unit_label}")
                        logger.info(f"      Score: {score_result['total']:.0f}% (IBAN:{score_result['iban']}, Name:{score_result['name']}, Amount:{score_result['amount']}, Date:{score_result['date']}, Purpose:{score_result['purpose']})")
                        logger.info(f"      Details: {', '.join(score_result['details'][:3])}")
                    
                    if score_result["total"] > best_score and score_result["total"] >= min_confidence:
                        best_score = score_result["total"]
                        best_match = {
                            "charge": charge,
                            "score": score_result["total"],
                            "score_details": score_result
                        }
                
                # Wenn Match gefunden, erstelle BankTransaction und PaymentMatch
                if best_match:
                    charge = best_match["charge"]
                    remaining = charge.amount - charge.paid_amount
                    matched_amount = min(amount, remaining)
                    
                    # Erstelle BankTransaction
                    transaction = BankTransaction(
                        bank_account_id=csv_file.bank_account_id,
                        transaction_date=transaction_date,
                        amount=amount,
                        counterpart_iban=counterpart_iban,
                        counterpart_name=counterpart_name,
                        purpose=purpose,
                        is_matched=False
                    )
                    db.add(transaction)
                    db.flush()
                    
                    # Erstelle PaymentMatch
                    payment_match = PaymentMatch(
                        transaction_id=transaction.id,
                        charge_id=charge.id,
                        matched_amount=matched_amount,
                        is_automatic=True,
                        note=f"Auto-Match aus CSV (Score: {best_score:.0f}%) - {csv_file.filename}"
                    )
                    db.add(payment_match)
                    
                    # Update Charge
                    charge.paid_amount += matched_amount
                    if charge.paid_amount >= charge.amount:
                        charge.status = ChargeStatus.PAID
                    else:
                        charge.status = ChargeStatus.PARTIALLY_PAID
                    
                    # Update Transaction
                    transaction.matched_amount = matched_amount
                    if transaction.matched_amount >= transaction.amount:
                        transaction.is_matched = True
                    
                    stats["matched"] += 1
                    logger.info(f"✅ Match: CSV-Zeile {csv_row.get('row_index')} → Charge {charge.id} (Score: {best_score:.0f}%)")
                    logger.info(f"   Details: {', '.join(best_match['score_details']['details'][:5])}")
                else:
                    stats["no_match"] += 1
                    if stats["processed"] <= 3:
                        logger.warning(f"   ❌ Kein Match gefunden (bester Score: {best_score:.0f}% < {min_confidence}%)")
                    
            except Exception as row_error:
                logger.error(f"❌ Fehler bei CSV-Zeile {csv_row.get('row_index', '?')}: {str(row_error)}")
                stats["errors"] += 1
                continue
        
        if stats["matched"] > 0:
            db.commit()
            logger.info(f"✅ CSV-Abgleich abgeschlossen: {stats['matched']} von {stats['processed']} Zeilen zugeordnet")
        else:
            logger.info(f"ℹ️ CSV-Abgleich abgeschlossen: {stats['processed']} Zeilen verarbeitet, {stats['matched']} zugeordnet, {stats['no_match']} ohne Match, {stats['errors']} Fehler")
            if stats["processed"] == 0:
                logger.warning(f"⚠️ KEINE Zeilen verarbeitet! Mögliche Ursachen:")
                logger.warning(f"   - CSV-Tabelle {csv_file.table_name} ist leer?")
                logger.warning(f"   - Spalten nicht erkannt? (Datum={date_col}, Betrag={amount_col})")
                logger.warning(f"   - Alle Beträge <= 0?")
        
        return stats
        
    except Exception as e:
        logger.error(f"❌ Fehler beim CSV-Abgleich: {str(e)}")
        import traceback
        logger.error(traceback.format_exc())
        db.rollback()
        return stats

