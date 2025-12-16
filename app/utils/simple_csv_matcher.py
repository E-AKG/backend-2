"""
Einfacher CSV-Matcher: Direkter Vergleich zwischen CSV-Daten und Tool-Daten
Kein komplexes Scoring, einfach: "Passt das zusammen?"
"""
import logging
import re
from typing import Dict, List, Optional, Tuple
from decimal import Decimal
from datetime import date, datetime, timedelta
from sqlalchemy.orm import Session
from ..models.bank import CsvFile, BankTransaction, PaymentMatch
from ..models.billrun import Charge, ChargeStatus
from ..models.lease import Lease
from ..models.tenant import Tenant
from ..models.unit import Unit

logger = logging.getLogger(__name__)


def normalize_iban(iban: Optional[str]) -> str:
    """Normalisiere IBAN (Großbuchstaben, keine Leerzeichen)"""
    if not iban:
        return ""
    return iban.replace(" ", "").upper().strip()


def normalize_text(text: str) -> str:
    """Normalisiere Text für Vergleich (Kleinschreibung, Umlaute)"""
    if not text:
        return ""
    text = text.lower().strip()
    # Normalisiere Umlaute
    replacements = {
        'ü': 'u', 'ö': 'o', 'ä': 'a', 'ß': 'ss',
        'é': 'e', 'è': 'e', 'ê': 'e', 'ë': 'e',
        'á': 'a', 'à': 'a', 'â': 'a', 'ã': 'a',
        'í': 'i', 'ì': 'i', 'î': 'i', 'ï': 'i',
        'ó': 'o', 'ò': 'o', 'ô': 'o', 'õ': 'o',
        'ú': 'u', 'ù': 'u', 'û': 'u'
    }
    for old, new in replacements.items():
        text = text.replace(old, new)
    # Entferne Sonderzeichen für Vergleich
    text = re.sub(r'[^\w\s]', ' ', text)
    text = re.sub(r'\s+', ' ', text)
    return text.strip()


def check_match(
    csv_row: Dict,
    charge: Charge,
    tenant: Tenant,
    unit: Optional[Unit],
    csv_data: Dict  # Enthält: amount, date, iban, name, purpose
) -> Tuple[bool, List[str]]:
    """
    Einfacher Check: Passt CSV-Zeile zu Charge?
    
    Returns:
        (passt: bool, gründe: List[str])
    """
    reasons = []
    matches = 0
    
    # 1. IBAN-Check
    tenant_iban = normalize_iban(tenant.iban)
    csv_iban = normalize_iban(csv_data.get('iban'))
    
    if tenant_iban and csv_iban:
        if tenant_iban == csv_iban:
            matches += 1
            reasons.append(f"✅ IBAN passt: {csv_iban}")
        else:
            reasons.append(f"❌ IBAN passt nicht: {csv_iban} vs {tenant_iban}")
    elif not tenant_iban:
        reasons.append(f"⚠️ Keine IBAN beim Mieter hinterlegt")
    elif not csv_iban:
        reasons.append(f"⚠️ Keine IBAN in CSV")
    
    # 2. Betrag-Check (mit Toleranz ±0.01€)
    csv_amount = csv_data.get('amount', Decimal('0'))
    charge_amount = charge.amount - charge.paid_amount  # Offener Betrag
    
    if abs(csv_amount - charge_amount) <= Decimal('0.01'):
        matches += 1
        reasons.append(f"✅ Betrag passt: {csv_amount}€ = {charge_amount}€")
    else:
        reasons.append(f"❌ Betrag passt nicht: {csv_amount}€ vs {charge_amount}€ (offen)")
    
    # 3. Name-Check
    tenant_name = f"{tenant.first_name} {tenant.last_name}"
    tenant_last_normalized = normalize_text(tenant.last_name)
    tenant_first_normalized = normalize_text(tenant.first_name)
    
    csv_name = csv_data.get('name', '')
    csv_name_normalized = normalize_text(csv_name)
    
    if csv_name_normalized:
        if tenant_last_normalized in csv_name_normalized or tenant_first_normalized in csv_name_normalized:
            matches += 1
            reasons.append(f"✅ Name passt: '{csv_name}' enthält '{tenant.last_name}' oder '{tenant.first_name}'")
        else:
            reasons.append(f"❌ Name passt nicht: '{csv_name}' vs '{tenant_name}'")
    else:
        reasons.append(f"⚠️ Kein Name in CSV")
    
    # 4. Datum-Check (±30 Tage Toleranz)
    csv_date = csv_data.get('date')
    charge_due_date = charge.due_date
    
    if csv_date and charge_due_date:
        days_diff = abs((csv_date - charge_due_date).days)
        if days_diff <= 30:
            matches += 1
            reasons.append(f"✅ Datum passt: {csv_date} (Fällig: {charge_due_date}, {days_diff} Tage Differenz)")
        else:
            reasons.append(f"❌ Datum passt nicht: {csv_date} vs {charge_due_date} ({days_diff} Tage Differenz)")
    elif not csv_date:
        reasons.append(f"⚠️ Kein Datum in CSV")
    
    # 5. Verwendungszweck-Check (Einheit oder Name)
    csv_purpose = csv_data.get('purpose', '')
    csv_purpose_normalized = normalize_text(csv_purpose)
    
    if csv_purpose_normalized and unit and unit.unit_label:
        unit_label_normalized = normalize_text(unit.unit_label)
        # Entferne generische Wörter
        unit_parts = [p for p in unit_label_normalized.split() if p not in ['wohnung', 'apartment', 'unit', 'einheit', 'nr', 'no']]
        
        found_unit = False
        for part in unit_parts:
            if len(part) > 1 and part in csv_purpose_normalized:
                found_unit = True
                break
        
        if found_unit or unit_label_normalized in csv_purpose_normalized:
            matches += 1
            reasons.append(f"✅ Verwendungszweck passt: '{csv_purpose[:50]}...' enthält Einheit '{unit.unit_label}'")
        elif tenant_last_normalized in csv_purpose_normalized:
            matches += 1
            reasons.append(f"✅ Verwendungszweck passt: '{csv_purpose[:50]}...' enthält Name '{tenant.last_name}'")
        else:
            reasons.append(f"❌ Verwendungszweck passt nicht: '{csv_purpose[:50]}...' vs Einheit '{unit.unit_label}'")
    elif csv_purpose_normalized and tenant_last_normalized in csv_purpose_normalized:
        matches += 1
        reasons.append(f"✅ Verwendungszweck passt: '{csv_purpose[:50]}...' enthält Name '{tenant.last_name}'")
    
    # Entscheidung: Mindestens 3 von 5 Checks müssen passen
    passt = matches >= 3
    
    if passt:
        reasons.insert(0, f"✅ PASST ({matches}/5 Checks)")
    else:
        reasons.insert(0, f"❌ PASST NICHT ({matches}/5 Checks)")
    
    return passt, reasons


def simple_match_csv(
    db: Session,
    csv_file: CsvFile,
    owner_id: int
) -> Dict:
    """
    Einfacher CSV-Abgleich: Direkter Vergleich CSV ↔ Tool-Daten
    
    Args:
        db: Database Session
        csv_file: CsvFile mit table_name
        owner_id: Benutzer ID
    
    Returns:
        Dict mit Statistiken
    """
    if not csv_file.table_name:
        logger.warning(f"⚠️ CSV-Datei {csv_file.id} hat keine PostgreSQL-Tabelle")
        return {"matched": 0, "processed": 0, "errors": 0, "details": []}
    
    stats = {
        "matched": 0,
        "processed": 0,
        "errors": 0,
        "no_match": 0,
        "details": []  # Liste mit Match-Details
    }
    
    try:
        # 1. HOLE TOOL-DATEN: Alle offenen Sollbuchungen
        open_charges = db.query(Charge).join(Lease).filter(
            Lease.owner_id == owner_id,
            Charge.status.in_([ChargeStatus.OPEN, ChargeStatus.PARTIALLY_PAID])
        ).all()
        
        logger.info(f"📊 {len(open_charges)} offene Sollbuchungen gefunden")
        
        if not open_charges:
            logger.warning("⚠️ Keine offenen Sollbuchungen gefunden")
            return stats
        
        # 2. HOLE CSV-DATEN: Aus PostgreSQL-Tabelle
        from .csv_table_manager import query_csv_table
        
        csv_rows = query_csv_table(db, csv_file.table_name, csv_file.id)
        logger.info(f"📊 {len(csv_rows)} Zeilen aus CSV-Tabelle {csv_file.table_name} gelesen")
        
        if not csv_rows:
            logger.warning(f"⚠️ Keine Daten in Tabelle {csv_file.table_name}")
            return stats
        
        # 3. ERKENNE SPALTEN
        import json
        column_mapping = json.loads(csv_file.column_mapping) if csv_file.column_mapping else {}
        original_headers = column_mapping.get("headers", [])
        
        # Erstelle Mapping: Original-Header → Tabellen-Spalte
        import re
        table_columns = [k for k in csv_rows[0].keys() if k not in ['id', 'csv_file_id', 'row_index']]
        header_to_column = {}
        for orig_header in original_headers:
            safe_name = re.sub(r'[^a-zA-Z0-9_]', '_', orig_header).lower()
            if not safe_name or safe_name[0].isdigit():
                safe_name = 'col_' + safe_name
            safe_name = safe_name[:63]
            for col in table_columns:
                if col.lower() == safe_name.lower():
                    header_to_column[orig_header] = col
                    break
        
        # Erkenne wichtige Spalten (Priorität für exakte Matches)
        date_col = None
        amount_col = None
        iban_col = None
        name_col = None
        purpose_col = None
        
        for header in original_headers:
            header_lower = header.lower().strip()
            if not date_col and header_lower in ['buchungstag', 'valutadatum', 'datum']:
                date_col = header
            if not amount_col and header_lower == 'betrag':
                amount_col = header
            if not iban_col and 'iban' in header_lower:
                iban_col = header
            if not name_col and ('beguenstigter' in header_lower or 'zahlungspflichtig' in header_lower):
                name_col = header
            if not purpose_col and header_lower == 'verwendungszweck':
                purpose_col = header
        
        logger.info(f"🔍 Spalten: Datum={date_col}, Betrag={amount_col}, IBAN={iban_col}, Name={name_col}, Zweck={purpose_col}")
        
        # 4. VERGLEICHE JEDE CSV-ZEILE MIT JEDER CHARGE
        for csv_row in csv_rows:
            try:
                stats["processed"] += 1
                row_idx = csv_row.get('row_index', stats["processed"] - 1)
                
                # Extrahiere CSV-Daten
                def get_csv_value(header):
                    """Hole Wert aus CSV-Zeile basierend auf Original-Header"""
                    if not header or header not in header_to_column:
                        return None
                    col = header_to_column[header]
                    return csv_row.get(col)
                
                # Parse Datum
                csv_date = None
                if date_col:
                    date_val = get_csv_value(date_col)
                    if date_val:
                        date_str = str(date_val).strip()
                        for fmt in ['%d.%m.%Y', '%d.%m.%y', '%Y-%m-%d', '%d/%m/%Y']:
                            try:
                                csv_date = datetime.strptime(date_str, fmt).date()
                                break
                            except:
                                continue
                
                # Parse Betrag
                csv_amount = Decimal('0')
                if amount_col:
                    amount_val = get_csv_value(amount_col)
                    if amount_val:
                        try:
                            amount_str = str(amount_val).replace(',', '.').replace(' ', '').replace('€', '').strip()
                            if amount_str:
                                csv_amount = Decimal(amount_str)
                        except:
                            pass
                
                # Nur Eingänge (positive Beträge)
                if csv_amount <= 0:
                    continue
                
                # Extrahiere weitere Felder
                csv_iban = None
                if iban_col:
                    iban_val = get_csv_value(iban_col)
                    if iban_val:
                        csv_iban = str(iban_val).strip()
                
                csv_name = None
                if name_col:
                    name_val = get_csv_value(name_col)
                    if name_val:
                        csv_name = str(name_val).strip()
                
                csv_purpose = None
                if purpose_col:
                    purpose_val = get_csv_value(purpose_col)
                    if purpose_val:
                        csv_purpose = str(purpose_val).strip()
                
                csv_data = {
                    'amount': csv_amount,
                    'date': csv_date,
                    'iban': csv_iban,
                    'name': csv_name,
                    'purpose': csv_purpose
                }
                
                # Log erste 3 Zeilen
                if stats["processed"] <= 3:
                    logger.info(f"📄 CSV-Zeile {row_idx}: {csv_amount}€, {csv_date}, IBAN: {csv_iban}, Name: {csv_name}, Zweck: {csv_purpose[:50] if csv_purpose else 'N/A'}...")
                
                # Vergleiche mit allen offenen Charges
                best_match = None
                best_reasons = []
                
                for charge in open_charges:
                    # Hole Mieter und Einheit
                    lease = db.query(Lease).filter(Lease.id == charge.lease_id).first()
                    if not lease:
                        continue
                    
                    tenant = db.query(Tenant).filter(Tenant.id == lease.tenant_id).first()
                    if not tenant:
                        continue
                    
                    unit = db.query(Unit).filter(Unit.id == lease.unit_id).first()
                    
                    # Einfacher Check: Passt das?
                    passt, reasons = check_match(csv_row, charge, tenant, unit, csv_data)
                    
                    if passt:
                        if not best_match or len(reasons) > len(best_reasons):
                            best_match = charge
                            best_reasons = reasons
                
                # Wenn Match gefunden → Zuordnung
                if best_match:
                    charge = best_match
                    remaining = charge.amount - charge.paid_amount
                    matched_amount = min(csv_amount, remaining)
                    
                    # Erstelle BankTransaction
                    transaction = BankTransaction(
                        bank_account_id=csv_file.bank_account_id,
                        transaction_date=csv_date or date.today(),
                        amount=csv_amount,
                        counterpart_iban=csv_iban,
                        counterpart_name=csv_name,
                        purpose=csv_purpose,
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
                        note=f"Auto-Match aus CSV - {csv_file.filename}"
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
                    
                    # Aktualisiere BillRun (Sollstellung) automatisch
                    try:
                        from ..routes.billrun_routes import update_bill_run_totals
                        update_bill_run_totals(db, charge.bill_run_id)
                    except Exception as e:
                        logger.error(f"Fehler beim Aktualisieren der BillRun: {str(e)}")
                        # Nicht kritisch - Charge wurde bereits aktualisiert
                    
                    stats["matched"] += 1
                    
                    # Hole Details für Log
                    lease = db.query(Lease).filter(Lease.id == charge.lease_id).first()
                    tenant = db.query(Tenant).filter(Tenant.id == lease.tenant_id).first() if lease else None
                    unit = db.query(Unit).filter(Unit.id == lease.unit_id).first() if lease else None
                    
                    match_detail = {
                        "csv_row": row_idx,
                        "csv_amount": str(csv_amount),
                        "csv_date": str(csv_date) if csv_date else None,
                        "charge_id": charge.id,
                        "charge_amount": str(charge.amount),
                        "tenant": f"{tenant.first_name} {tenant.last_name}" if tenant else None,
                        "unit": unit.unit_label if unit else None,
                        "reasons": best_reasons
                    }
                    stats["details"].append(match_detail)
                    
                    logger.info(f"✅ ZUGEORDNET: CSV-Zeile {row_idx} → Charge {charge.id} ({tenant.first_name} {tenant.last_name if tenant else ''}, {unit.unit_label if unit else ''})")
                    for reason in best_reasons[:3]:
                        logger.info(f"   {reason}")
                else:
                    stats["no_match"] += 1
                    if stats["processed"] <= 3:
                        logger.info(f"   ❌ Kein Match gefunden für diese Zeile")
                
            except Exception as row_error:
                logger.error(f"❌ Fehler bei CSV-Zeile {csv_row.get('row_index', '?')}: {str(row_error)}")
                import traceback
                logger.error(traceback.format_exc())
                stats["errors"] += 1
                continue
        
        if stats["matched"] > 0:
            db.commit()
            logger.info(f"✅ Abgleich abgeschlossen: {stats['matched']} von {stats['processed']} Zeilen zugeordnet")
        else:
            logger.info(f"ℹ️ Abgleich abgeschlossen: {stats['processed']} Zeilen verarbeitet, {stats['matched']} zugeordnet")
        
        return stats
        
    except Exception as e:
        db.rollback()
        logger.error(f"❌ Fehler beim CSV-Abgleich: {str(e)}")
        import traceback
        logger.error(traceback.format_exc())
        raise

