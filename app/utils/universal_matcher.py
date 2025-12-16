"""
Universeller Abgleich: Unterstützt CSV, Kassenbuch und manuelle Transaktionen
Gleicht alle Zahlungsquellen mit offenen Sollbuchungen ab
"""
import logging
import re
from typing import Dict, List, Optional, Tuple
from decimal import Decimal
from datetime import date, datetime, timedelta
from sqlalchemy.orm import Session
from ..models.bank import BankTransaction, PaymentMatch, BankAccount, CsvFile
from ..models.cashbook import CashBookEntry
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


def extract_name_parts(name: str) -> List[str]:
    """
    Extrahiert alle möglichen Namens-Teile aus einem Namen
    z.B. "Oßmann-Cavrar" → ["oßmann-cavrar", "oßmann", "cavrar"]
    z.B. "Max Mustermann" → ["max mustermann", "max", "mustermann"]
    """
    if not name:
        return []
    
    normalized = normalize_text(name)
    parts = []
    
    # Vollständiger Name
    parts.append(normalized)
    
    # Teile bei Bindestrich, Leerzeichen, etc.
    # Split bei Bindestrich
    if '-' in normalized:
        for part in normalized.split('-'):
            part = part.strip()
            if part and len(part) >= 3:  # Mindestens 3 Zeichen
                parts.append(part)
    
    # Split bei Leerzeichen
    if ' ' in normalized:
        for part in normalized.split(' '):
            part = part.strip()
            if part and len(part) >= 3:  # Mindestens 3 Zeichen
                parts.append(part)
    
    # Entferne Duplikate, behalte Reihenfolge
    seen = set()
    unique_parts = []
    for part in parts:
        if part not in seen:
            seen.add(part)
            unique_parts.append(part)
    
    return unique_parts


def calculate_match_score(
    payment_data: Dict,  # Enthält: amount, date, iban, name, purpose
    charge: Charge,
    tenant: Tenant,
    unit: Optional[Unit] = None
) -> Dict:
    """
    Berechnet Match-Score zwischen Zahlung und Charge
    
    Args:
        payment_data: Dict mit amount, date, iban, name, purpose
        charge: Charge-Objekt
        tenant: Tenant-Objekt
        unit: Optional Unit-Objekt
    
    Returns:
        Dict mit score (0-100), reasons (List[str]), confidence (float)
    """
    score = 0
    max_score = 100
    reasons = []
    
    # 1. IBAN-Match (40 Punkte) - Höchste Priorität
    tenant_iban = normalize_iban(tenant.iban)
    payment_iban = normalize_iban(payment_data.get('iban'))
    
    if tenant_iban and payment_iban:
        if tenant_iban == payment_iban:
            score += 40
            reasons.append(f"✅ IBAN exakt: {payment_iban[:10]}...")
        else:
            reasons.append(f"❌ IBAN passt nicht: {payment_iban[:10]}... vs {tenant_iban[:10]}...")
    elif not tenant_iban:
        reasons.append("⚠️ Keine IBAN beim Mieter hinterlegt")
    elif not payment_iban:
        reasons.append("⚠️ Keine IBAN in Zahlung")
    
    # 2. Betrag-Match (30 Punkte)
    payment_amount = Decimal(str(payment_data.get('amount', 0)))
    remaining_amount = charge.amount - charge.paid_amount
    
    if remaining_amount > 0:
        # Prüfe ob Zahlung <= offener Betrag (Teilzahlung möglich)
        if payment_amount <= remaining_amount:
            amount_diff = abs(payment_amount - remaining_amount)
            amount_diff_percent = float(amount_diff) / float(remaining_amount) if remaining_amount > 0 else 1.0
            
            if amount_diff == 0:
                score += 30
                reasons.append(f"✅ Betrag exakt: {payment_amount}€")
            elif amount_diff_percent < 0.01:  # ±1%
                score += 25
                reasons.append(f"✅ Betrag sehr nah: {payment_amount}€ (±1%)")
            elif amount_diff_percent < 0.05:  # ±5%
                score += 20
                reasons.append(f"⚠️ Betrag ähnlich: {payment_amount}€ (±5%)")
            elif amount_diff_percent < 0.10:  # ±10%
                score += 10
                reasons.append(f"⚠️ Betrag abweichend: {payment_amount}€ (±10%)")
            elif amount_diff_percent < 0.50:  # ±50% (Teilzahlung)
                # Teilzahlungen sollten mehr Punkte geben, da sie legitim sind
                if amount_diff_percent < 0.20:  # Bis 20% Abweichung (z.B. 2€ von 2.50€)
                    score += 15
                    reasons.append(f"✅ Teilzahlung: {payment_amount}€ von {remaining_amount}€ offen (noch {remaining_amount - payment_amount}€ ausstehend)")
                elif amount_diff_percent < 0.35:  # Bis 35% Abweichung (z.B. 2€ von 3€)
                    score += 12
                    reasons.append(f"⚠️ Teilzahlung: {payment_amount}€ von {remaining_amount}€ offen (noch {remaining_amount - payment_amount}€ ausstehend)")
                else:  # 35-50% Abweichung
                    score += 8
                    reasons.append(f"⚠️ Teilzahlung: {payment_amount}€ von {remaining_amount}€ offen (noch {remaining_amount - payment_amount}€ ausstehend)")
            elif amount_diff_percent < 0.80:  # 50-80% Abweichung (z.B. 1€ von 3€ = 66%)
                # Auch sehr kleine Teilzahlungen akzeptieren (wenn Name passt)
                score += 10  # Mehr Punkte für kleine Teilzahlungen, damit sie durchkommen
                reasons.append(f"⚠️ Kleine Teilzahlung: {payment_amount}€ von {remaining_amount}€ offen (noch {remaining_amount - payment_amount}€ ausstehend)")
            else:
                # Nur bei extremen Abweichungen (>80%) ablehnen
                reasons.append(f"❌ Betrag passt nicht: {payment_amount}€ vs {remaining_amount}€ (offen, Abweichung: {amount_diff_percent:.0%})")
        else:
            # Zahlung ist größer als offener Betrag (Überzahlung)
            amount_diff = payment_amount - remaining_amount
            amount_diff_percent = float(amount_diff) / float(remaining_amount) if remaining_amount > 0 else 1.0
            
            # Überzahlungen akzeptieren (flexibel, aber mit Warnung)
            # Akzeptiere bis zu 200% Überzahlung (z.B. 3€ bei 1€ Sollbetrag) oder max. 100€
            max_overpayment = min(remaining_amount * Decimal('2'), Decimal('100'))
            
            if amount_diff <= max_overpayment:
                # Überzahlung akzeptieren, aber mit Warnung
                if amount_diff_percent < 0.20:  # Bis 20% Überzahlung
                    score += 20
                    reasons.append(f"✅ Betrag etwas höher: {payment_amount}€ (offen: {remaining_amount}€)")
                elif amount_diff_percent < 0.50:  # Bis 50% Überzahlung
                    score += 15
                    reasons.append(f"⚠️ Betrag deutlich höher: {payment_amount}€ (offen: {remaining_amount}€)")
                elif amount_diff_percent < 1.0:  # Bis 100% Überzahlung
                    score += 10
                    reasons.append(f"⚠️ Betrag viel höher: {payment_amount}€ (offen: {remaining_amount}€)")
                else:  # Über 100% Überzahlung
                    score += 5
                    reasons.append(f"⚠️ Betrag sehr viel höher: {payment_amount}€ (offen: {remaining_amount}€)")
                
                # Warnung wird später in calculate_match_score hinzugefügt
            else:
                reasons.append(f"❌ Zahlung viel zu hoch: {payment_amount}€ vs {remaining_amount}€ (offen, Differenz: {amount_diff}€)")
    else:
        reasons.append("⚠️ Charge bereits vollständig bezahlt")
    
    # 3. Name-Match (20 Punkte) - FLEXIBEL: Akzeptiert Teilnamen, Tippfehler, etc.
    tenant_name = f"{tenant.first_name} {tenant.last_name}"
    tenant_last_normalized = normalize_text(tenant.last_name)
    tenant_first_normalized = normalize_text(tenant.first_name)
    
    # Extrahiere Namens-Teile (z.B. "Oßmann-Cavrar" → ["oßmann-cavrar", "oßmann", "cavrar"])
    tenant_last_parts = extract_name_parts(tenant.last_name)
    tenant_first_parts = extract_name_parts(tenant.first_name)
    
    payment_name = payment_data.get('name', '')
    payment_name_normalized = normalize_text(payment_name)
    
    # Prüfe auch Verwendungszweck für Name (wichtig für Kassenbuch und manuelle Buchungen!)
    payment_purpose = normalize_text(payment_data.get('purpose', ''))
    
    # Kombiniere payment_name und payment_purpose für Suche
    search_text = f"{payment_name_normalized} {payment_purpose}".strip()
    
    name_match_found = False
    name_match_score = 0
    name_match_reason = ""
    
    # Mindestlänge für Namens-Teile (reduziert von 3 auf 2 für flexibleres Matching)
    min_name_length = 2
    
    if payment_name_normalized:
        # Wenn Name exakt übereinstimmt
        if payment_name_normalized == normalize_text(tenant_name):
            name_match_score = 20
            name_match_reason = f"✅ Name exakt: {tenant_name}"
            name_match_found = True
        else:
            # Prüfe alle Teile des Nachnamens (auch kurze Teile)
            for part in tenant_last_parts:
                if part in payment_name_normalized and len(part) >= min_name_length:
                    if part == tenant_last_normalized:
                        name_match_score = max(name_match_score, 18)
                        name_match_reason = f"✅ Nachname gefunden: {tenant.last_name}"
                    else:
                        # Teilname gefunden (z.B. "Oßmann" in "Oßmann-Cavrar")
                        name_match_score = max(name_match_score, 15)
                        name_match_reason = f"✅ Nachname-Teil gefunden: {part}"
                    name_match_found = True
                    break
            
            # Prüfe Vorname (auch wenn Nachname nicht gefunden)
            for part in tenant_first_parts:
                if part in payment_name_normalized and len(part) >= min_name_length:
                    if not name_match_found:
                        name_match_score = max(name_match_score, 15)
                        name_match_reason = f"✅ Vorname gefunden: {tenant.first_name}"
                        name_match_found = True
                    elif name_match_score < 18:  # Wenn bereits Nachname gefunden, erhöhe Score
                        name_match_score = max(name_match_score, 18)
                        name_match_reason = f"✅ Vorname und Nachname gefunden: {tenant.first_name} {tenant.last_name}"
                    break
    
    # Wenn kein Match im Namen, suche im Verwendungszweck (WICHTIG für manuelle Buchungen!)
    if not name_match_found and payment_purpose:
        # Prüfe alle Teile des Nachnamens im Verwendungszweck
        for part in tenant_last_parts:
            if part in payment_purpose and len(part) >= min_name_length:
                if part == tenant_last_normalized:
                    name_match_score = max(name_match_score, 15)
                    name_match_reason = f"✅ Nachname im Verwendungszweck: {tenant.last_name}"
                else:
                    # Teilname gefunden (z.B. "Oßmann" in "Miete Oßmann" für "Oßmann-Cavrar")
                    name_match_score = max(name_match_score, 12)
                    name_match_reason = f"✅ Nachname-Teil im Verwendungszweck: {part}"
                name_match_found = True
                break
        
        # Prüfe Vorname im Verwendungszweck
        if not name_match_found:
            for part in tenant_first_parts:
                if part in payment_purpose and len(part) >= min_name_length:
                    name_match_score = max(name_match_score, 12)
                    name_match_reason = f"✅ Vorname im Verwendungszweck: {tenant.first_name}"
                    name_match_found = True
                    break
    
    # Auch wenn kein exakter Match, geben wir Punkte wenn ähnlich (für Tippfehler)
    if not name_match_found:
        # Prüfe auf ähnliche Namen (Fuzzy-Matching für Tippfehler)
        # Einfache Levenshtein-ähnliche Prüfung: Wenn ein großer Teil des Namens übereinstimmt
        if payment_name_normalized or payment_purpose:
            search_in = payment_name_normalized or payment_purpose
            # Wenn mindestens 60% des Nachnamens im Zahlungstext vorkommt
            if tenant_last_normalized and len(tenant_last_normalized) >= 4:
                # Prüfe ob große Teile des Nachnamens enthalten sind
                for i in range(len(tenant_last_normalized) - 2):
                    substring = tenant_last_normalized[i:i+3]
                    if substring in search_in:
                        name_match_score = max(name_match_score, 10)
                        name_match_reason = f"⚠️ Ähnlicher Name gefunden (möglicher Tippfehler): {substring}"
                        name_match_found = True
                        break
    
    if name_match_found:
        score += name_match_score
        reasons.append(name_match_reason)
    else:
        # Auch ohne Match geben wir minimale Punkte, wenn Betrag passt
        # (Name könnte falsch geschrieben sein oder fehlen)
        if score >= 20:  # Wenn Betrag gut passt, geben wir trotzdem Punkte
            score += 5
            reasons.append(f"⚠️ Name nicht gefunden, aber Betrag passt: {payment_name or payment_purpose or 'N/A'} vs {tenant_name}")
        else:
            reasons.append(f"⚠️ Name passt nicht: {payment_name or payment_purpose or 'N/A'} vs {tenant_name}")
    
    # 4. Verwendungszweck-Match (10 Punkte) - nur wenn Name nicht bereits gefunden wurde
    # payment_purpose wurde bereits oben definiert
    if payment_purpose:
        # Prüfe ob Name bereits im Zahlungsnamen gefunden wurde
        name_found_in_payment = False
        if payment_name_normalized:
            if tenant_last_normalized in payment_name_normalized or tenant_first_normalized in payment_name_normalized:
                name_found_in_payment = True
        
        # Wenn Name noch nicht gefunden wurde, suche im Verwendungszweck
        if not name_found_in_payment:
            # Verwende extract_name_parts für flexibleres Matching
            tenant_last_parts = extract_name_parts(tenant.last_name)
            tenant_first_parts = extract_name_parts(tenant.first_name)
            
            for part in tenant_last_parts:
                if part in payment_purpose and len(part) >= 3:
                    if part == tenant_last_normalized:
                        score += 8  # Erhöht von 5 auf 8, da Verwendungszweck wichtig für Kassenbuch ist
                        reasons.append("✅ Nachname im Verwendungszweck")
                    else:
                        score += 6  # Teilname gefunden
                        reasons.append(f"✅ Nachname-Teil im Verwendungszweck: {part}")
                    name_found_in_payment = True
                    break
            
            if not name_found_in_payment:
                for part in tenant_first_parts:
                    if part in payment_purpose and len(part) >= 3:
                        score += 6  # Erhöht von 3 auf 6, wichtig für "Max" statt "Max Mustermann"
                        reasons.append("✅ Vorname im Verwendungszweck")
                        name_found_in_payment = True
                        break
        
        # Suche nach Einheit/Objekt im Verwendungszweck
        if unit:
            unit_label_normalized = normalize_text(unit.unit_label)
            if unit_label_normalized and unit_label_normalized in payment_purpose:
                score += 2
                reasons.append(f"✅ Einheit im Verwendungszweck: {unit.unit_label}")
    
    # 5. Datum-Match (optional, 0-10 Punkte)
    payment_date = payment_data.get('date')
    if payment_date and charge.due_date:
        if isinstance(payment_date, str):
            try:
                payment_date = datetime.strptime(payment_date, '%Y-%m-%d').date()
            except:
                pass
        
        if isinstance(payment_date, date) and isinstance(charge.due_date, date):
            days_diff = abs((payment_date - charge.due_date).days)
            if days_diff == 0:
                score += 10
                reasons.append("✅ Datum exakt")
            elif days_diff <= 7:
                score += 7
                reasons.append(f"✅ Datum nah: ±{days_diff} Tage")
            elif days_diff <= 30:
                score += 3
                reasons.append(f"⚠️ Datum abweichend: ±{days_diff} Tage")
    
    # Berechne Confidence (0.0 - 1.0)
    confidence = min(1.0, float(score) / float(max_score))
    
    # Erstelle Warnungen bei Abweichungen (IMMER wenn Betrag nicht exakt)
    warnings = []
    
    # Warnung bei Teilzahlung (Unterzahlung) - IMMER wenn bezahlt < sollbetrag
    if remaining_amount > 0 and payment_amount < remaining_amount:
        diff = remaining_amount - payment_amount
        # Runde auf 2 Dezimalstellen für bessere Lesbarkeit
        diff_rounded = float(Decimal(str(diff)).quantize(Decimal('0.01')))
        payment_rounded = float(Decimal(str(payment_amount)).quantize(Decimal('0.01')))
        remaining_rounded = float(Decimal(str(remaining_amount)).quantize(Decimal('0.01')))
        warnings.append(f"⚠️ Unterzahlung: {payment_rounded:.2f}€ bezahlt, {diff_rounded:.2f}€ noch ausstehend (Sollbetrag: {remaining_rounded:.2f}€)")
    
    # Warnung bei Überzahlung - IMMER wenn bezahlt > sollbetrag
    if remaining_amount > 0 and payment_amount > remaining_amount:
        diff = payment_amount - remaining_amount
        # Runde auf 2 Dezimalstellen für bessere Lesbarkeit
        diff_rounded = float(Decimal(str(diff)).quantize(Decimal('0.01')))
        payment_rounded = float(Decimal(str(payment_amount)).quantize(Decimal('0.01')))
        remaining_rounded = float(Decimal(str(remaining_amount)).quantize(Decimal('0.01')))
        warnings.append(f"⚠️ Überzahlung: {payment_rounded:.2f}€ bezahlt, {diff_rounded:.2f}€ zu viel (Sollbetrag: {remaining_rounded:.2f}€)")
    
    # Warnung bei unvollständigem Namen
    if payment_name_normalized:
        if tenant_first_normalized in payment_name_normalized and tenant_last_normalized not in payment_name_normalized:
            warnings.append(f"⚠️ Name unvollständig: Nur '{tenant.first_name}' statt '{tenant_name}'")
        elif payment_name_normalized != normalize_text(tenant_name) and tenant_last_normalized not in payment_name_normalized and tenant_first_normalized not in payment_name_normalized:
            warnings.append(f"⚠️ Name abweichend: '{payment_name}' statt '{tenant_name}'")
    
    # Warnung wenn Name nur im Verwendungszweck steht
    if not payment_name_normalized and payment_purpose:
        if tenant_first_normalized in payment_purpose and tenant_last_normalized not in payment_purpose:
            warnings.append(f"⚠️ Name nur teilweise im Verwendungszweck: Nur '{tenant.first_name}' gefunden")
    
    return {
        "score": score,
        "max_score": max_score,
        "confidence": confidence,
        "reasons": reasons,
        "warnings": warnings,  # Neue Warnungen-Liste
        "matched_amount": min(payment_amount, remaining_amount) if remaining_amount > 0 else Decimal(0)
    }


def match_cashbook_to_charge(
    db: Session,
    entry: CashBookEntry,
    charge: Charge,
    owner_id: int
) -> Optional[Dict]:
    """
    SPEZIELLE Matching-Logik für Kassenbuch-Einträge mit klaren Regeln:
    
    REGEL 1: Wenn tenant_id vorhanden → IMMER matchen (auch bei Teilzahlung)
    REGEL 2: Wenn Name im Verwendungszweck UND Betrag passt (auch Teilzahlung) → matchen
    REGEL 3: Wenn nur Betrag passt, aber Name fehlt → nicht matchen (zu unsicher)
    
    Returns:
        Dict mit score, confidence, reasons, warnings, matched_amount oder None
    """
    from decimal import Decimal
    
    lease = db.query(Lease).filter(Lease.id == charge.lease_id).first()
    if not lease:
        return None
    
    tenant = db.query(Tenant).filter(Tenant.id == lease.tenant_id).first()
    if not tenant:
        return None
    
    unit = db.query(Unit).filter(Unit.id == lease.unit_id).first()
    
    score = 0
    max_score = 100
    reasons = []
    warnings = []
    
    payment_amount = Decimal(str(entry.amount))
    remaining_amount = charge.amount - charge.paid_amount
    
    # REGEL 1: tenant_id vorhanden → sehr hohe Priorität
    if entry.tenant_id:
        if entry.tenant_id == tenant.id:
            score += 50  # Sehr hohe Punktzahl für tenant_id-Match
            reasons.append(f"✅ Tenant-ID passt: {tenant.first_name} {tenant.last_name}")
            
            # Wenn tenant_id passt, akzeptiere auch Teilzahlungen
            if remaining_amount > 0:
                if payment_amount <= remaining_amount:
                    if payment_amount == remaining_amount:
                        score += 30
                        reasons.append(f"✅ Betrag exakt: {payment_amount}€")
                    else:
                        score += 20  # Teilzahlung ist OK wenn tenant_id passt
                        diff = remaining_amount - payment_amount
                        # Runde auf 2 Dezimalstellen für bessere Lesbarkeit
                        diff_rounded = float(Decimal(str(diff)).quantize(Decimal('0.01')))
                        payment_rounded = float(Decimal(str(payment_amount)).quantize(Decimal('0.01')))
                        remaining_rounded = float(Decimal(str(remaining_amount)).quantize(Decimal('0.01')))
                        warnings.append(f"⚠️ Unterzahlung: {payment_rounded:.2f}€ bezahlt, {diff_rounded:.2f}€ noch ausstehend (Sollbetrag: {remaining_rounded:.2f}€)")
                        reasons.append(f"✅ Teilzahlung akzeptiert: {payment_amount}€ von {remaining_amount}€")
                    
                    # Datum-Check (optional, aber gibt Bonus)
                    if entry.entry_date and charge.due_date:
                        days_diff = abs((entry.entry_date - charge.due_date).days)
                        if days_diff <= 30:
                            score += 10
                            reasons.append(f"✅ Datum passt: ±{days_diff} Tage")
                    
                    # Verwendungszweck-Check (optional)
                    if entry.purpose:
                        purpose_normalized = normalize_text(entry.purpose)
                        tenant_last_normalized = normalize_text(tenant.last_name)
                        tenant_first_normalized = normalize_text(tenant.first_name)
                        
                        if tenant_last_normalized in purpose_normalized:
                            score += 5
                            reasons.append(f"✅ Nachname im Verwendungszweck")
                        elif tenant_first_normalized in purpose_normalized:
                            score += 3
                            reasons.append(f"✅ Vorname im Verwendungszweck")
                    
                    confidence = min(1.0, float(score) / float(max_score))
                    
                    return {
                        "score": score,
                        "max_score": max_score,
                        "confidence": confidence,
                        "reasons": reasons,
                        "warnings": warnings,
                        "matched_amount": payment_amount
                    }
                else:
                    # Zahlung ist größer als offener Betrag (Überzahlung)
                    amount_diff = payment_amount - remaining_amount
                    # Akzeptiere Überzahlungen flexibel (bis zu 200% oder max. 100€)
                    max_overpayment = min(remaining_amount * Decimal('2'), Decimal('100'))
                    
                    if amount_diff <= max_overpayment:
                        # Überzahlung akzeptieren
                        amount_diff_percent = float(amount_diff) / float(remaining_amount) if remaining_amount > 0 else 1.0
                        
                        if amount_diff_percent < 0.20:  # Bis 20% Überzahlung
                            score += 20
                        elif amount_diff_percent < 0.50:  # Bis 50% Überzahlung
                            score += 15
                        elif amount_diff_percent < 1.0:  # Bis 100% Überzahlung
                            score += 10
                        else:  # Über 100% Überzahlung
                            score += 5
                        
                        # Runde auf 2 Dezimalstellen für bessere Lesbarkeit
                        amount_diff_rounded = float(Decimal(str(amount_diff)).quantize(Decimal('0.01')))
                        payment_rounded = float(Decimal(str(payment_amount)).quantize(Decimal('0.01')))
                        remaining_rounded = float(Decimal(str(remaining_amount)).quantize(Decimal('0.01')))
                        warnings.append(f"⚠️ Überzahlung: {payment_rounded:.2f}€ bezahlt, {amount_diff_rounded:.2f}€ zu viel (Sollbetrag: {remaining_rounded:.2f}€)")
                        reasons.append(f"✅ Überzahlung akzeptiert: {payment_amount}€ (offen: {remaining_amount}€)")
                        
                        confidence = min(1.0, float(score) / float(max_score))
                        
                        return {
                            "score": score,
                            "max_score": max_score,
                            "confidence": confidence,
                            "reasons": reasons,
                            "warnings": warnings,
                            "matched_amount": remaining_amount  # Nur offenen Betrag zuordnen
                        }
                    else:
                        reasons.append(f"❌ Zahlung viel zu hoch: {payment_amount}€ vs {remaining_amount}€ (Differenz: {amount_diff}€)")
                        return None
            else:
                reasons.append("⚠️ Charge bereits vollständig bezahlt")
                return None
        else:
            # tenant_id passt nicht → nicht matchen
            return None
    
    # REGEL 2: Name im Verwendungszweck UND Betrag passt
    if not entry.purpose:
        return None  # Kein Verwendungszweck → zu unsicher
    
    purpose_normalized = normalize_text(entry.purpose)
    tenant_last_normalized = normalize_text(tenant.last_name)
    tenant_first_normalized = normalize_text(tenant.first_name)
    
    name_found = False
    
    if tenant_last_normalized in purpose_normalized:
        score += 25  # Nachname im Verwendungszweck
        reasons.append(f"✅ Nachname im Verwendungszweck: {tenant.last_name}")
        name_found = True
    elif tenant_first_normalized in purpose_normalized:
        score += 15  # Vorname im Verwendungszweck
        reasons.append(f"✅ Vorname im Verwendungszweck: {tenant.first_name}")
        name_found = True
    
    if not name_found:
        return None  # Kein Name gefunden → zu unsicher
    
    # Betrag-Check (flexibel für Teilzahlungen)
    if remaining_amount > 0:
        if payment_amount <= remaining_amount:
            amount_diff = abs(payment_amount - remaining_amount)
            amount_diff_percent = float(amount_diff) / float(remaining_amount) if remaining_amount > 0 else 1.0
            
            if amount_diff == 0:
                score += 30
                reasons.append(f"✅ Betrag exakt: {payment_amount}€")
            elif amount_diff_percent < 0.20:  # Bis 20% Abweichung
                score += 25
                diff = remaining_amount - payment_amount
                # Runde auf 2 Dezimalstellen für bessere Lesbarkeit
                diff_rounded = float(Decimal(str(diff)).quantize(Decimal('0.01')))
                payment_rounded = float(Decimal(str(payment_amount)).quantize(Decimal('0.01')))
                remaining_rounded = float(Decimal(str(remaining_amount)).quantize(Decimal('0.01')))
                warnings.append(f"⚠️ Unterzahlung: {payment_rounded:.2f}€ bezahlt, {diff_rounded:.2f}€ noch ausstehend (Sollbetrag: {remaining_rounded:.2f}€)")
                reasons.append(f"✅ Teilzahlung akzeptiert: {payment_amount}€ von {remaining_amount}€")
            elif amount_diff_percent < 0.50:  # Bis 50% Abweichung
                score += 15
                diff = remaining_amount - payment_amount
                # Runde auf 2 Dezimalstellen für bessere Lesbarkeit
                diff_rounded = float(Decimal(str(diff)).quantize(Decimal('0.01')))
                payment_rounded = float(Decimal(str(payment_amount)).quantize(Decimal('0.01')))
                remaining_rounded = float(Decimal(str(remaining_amount)).quantize(Decimal('0.01')))
                warnings.append(f"⚠️ Unterzahlung: {payment_rounded:.2f}€ bezahlt, {diff_rounded:.2f}€ noch ausstehend (Sollbetrag: {remaining_rounded:.2f}€)")
                reasons.append(f"⚠️ Teilzahlung (größere Abweichung): {payment_amount}€ von {remaining_amount}€")
            else:
                reasons.append(f"❌ Betrag passt nicht: {payment_amount}€ vs {remaining_amount}€")
                return None
        else:
            # Überzahlung
            amount_diff = payment_amount - remaining_amount
            # Akzeptiere Überzahlungen flexibel (bis zu 200% oder max. 100€)
            max_overpayment = min(remaining_amount * Decimal('2'), Decimal('100'))
            
            if amount_diff <= max_overpayment:
                amount_diff_percent = float(amount_diff) / float(remaining_amount) if remaining_amount > 0 else 1.0
                
                if amount_diff_percent < 0.20:  # Bis 20% Überzahlung
                    score += 20
                elif amount_diff_percent < 0.50:  # Bis 50% Überzahlung
                    score += 15
                elif amount_diff_percent < 1.0:  # Bis 100% Überzahlung
                    score += 10
                else:  # Über 100% Überzahlung
                    score += 5
                
                # Runde auf 2 Dezimalstellen für bessere Lesbarkeit
                amount_diff_rounded = float(Decimal(str(amount_diff)).quantize(Decimal('0.01')))
                payment_rounded = float(Decimal(str(payment_amount)).quantize(Decimal('0.01')))
                remaining_rounded = float(Decimal(str(remaining_amount)).quantize(Decimal('0.01')))
                warnings.append(f"⚠️ Überzahlung: {payment_rounded:.2f}€ bezahlt, {amount_diff_rounded:.2f}€ zu viel (Sollbetrag: {remaining_rounded:.2f}€)")
                reasons.append(f"✅ Überzahlung akzeptiert: {payment_amount}€ (offen: {remaining_amount}€)")
            else:
                reasons.append(f"❌ Zahlung viel zu hoch: {payment_amount}€ vs {remaining_amount}€ (Differenz: {amount_diff}€)")
                return None
        
        # Datum-Check (optional)
        if entry.entry_date and charge.due_date:
            days_diff = abs((entry.entry_date - charge.due_date).days)
            if days_diff <= 30:
                score += 10
                reasons.append(f"✅ Datum passt: ±{days_diff} Tage")
        
        confidence = min(1.0, float(score) / float(max_score))
        
        # Mindest-Confidence: 40% wenn Name gefunden UND Betrag passt
        if confidence >= 0.40:
            # matched_amount: Bei Überzahlung nur den offenen Betrag zuordnen
            matched_amount = min(payment_amount, remaining_amount)
            
            return {
                "score": score,
                "max_score": max_score,
                "confidence": confidence,
                "reasons": reasons,
                "warnings": warnings,
                "matched_amount": matched_amount
            }
        else:
            reasons.append(f"❌ Confidence zu niedrig: {confidence:.1%} < 40%")
            return None
    else:
        reasons.append("⚠️ Charge bereits vollständig bezahlt")
        return None


def match_payment_to_charge(
    db: Session,
    payment_data: Dict,
    charge: Charge,
    owner_id: int,
    source_type: str = "unknown",  # "csv", "cashbook", "manual", "bank_transaction"
    min_confidence: float = 0.4  # Mindest-Confidence (Standard: 40%)
) -> Optional[Dict]:
    """
    Ordne eine Zahlung einer Charge zu
    
    Args:
        db: Database session
        payment_data: Dict mit amount, date, iban, name, purpose
        charge: Charge-Objekt
        owner_id: Owner ID
        source_type: "csv", "cashbook", "manual", "bank_transaction"
    
    Returns:
        Dict mit match_info oder None wenn kein Match
    """
    # Hole Lease, Tenant, Unit
    lease = db.query(Lease).filter(Lease.id == charge.lease_id).first()
    if not lease:
        logger.debug(f"   ❌ Charge {charge.id}: Kein Lease gefunden")
        return None
    
    tenant = db.query(Tenant).filter(Tenant.id == lease.tenant_id).first()
    if not tenant:
        logger.debug(f"   ❌ Charge {charge.id}: Kein Tenant gefunden")
        return None
    
    unit = db.query(Unit).filter(Unit.id == lease.unit_id).first()
    
    # Debug: Zeige Tenant-Informationen
    tenant_name = f"{tenant.first_name} {tenant.last_name}"
    logger.info(f"   🔍 Charge {charge.id}: Mieter={tenant_name}, Betrag={charge.amount}€, Offen={charge.amount - charge.paid_amount}€")
    
    # Berechne Match-Score
    match_result = calculate_match_score(payment_data, charge, tenant, unit)
    
    logger.info(f"   📊 Charge {charge.id}: Score={match_result['score']}, Confidence={match_result['confidence']:.2%}, Min={min_confidence:.0%}")
    logger.info(f"      Reasons: {', '.join(match_result.get('reasons', [])[:3])}")
    
    # Verwende übergebene min_confidence (Standard: 40%, flexibler)
    # Für manuelle Buchungen wird diese bereits in universal_reconcile reduziert
    if match_result["confidence"] < min_confidence:
        logger.info(f"   ❌ Charge {charge.id}: Confidence {match_result['confidence']:.2%} < {min_confidence:.0%} - ABGELEHNT")
        return None
    
    logger.info(f"   ✅ Charge {charge.id}: Confidence {match_result['confidence']:.2%} >= {min_confidence:.0%} - Match akzeptiert")
    
    # Prüfe ob Charge noch offen ist
    remaining_amount = charge.amount - charge.paid_amount
    if remaining_amount <= 0:
        logger.debug(f"   ❌ Charge {charge.id}: Bereits vollständig bezahlt (offen: {remaining_amount}€)")
        return None
    
    payment_amount = Decimal(str(payment_data.get('amount', 0)))
    matched_amount = min(payment_amount, remaining_amount)
    
    return {
        "charge_id": charge.id,
        "matched_amount": float(matched_amount),
        "score": match_result["score"],
        "confidence": match_result["confidence"],
        "reasons": match_result["reasons"],
        "warnings": match_result.get("warnings", []),  # WICHTIG: Warnungen zurückgeben!
        "source_type": source_type
    }


def universal_reconcile(
    db: Session,
    owner_id: int,
    client_id: Optional[str] = None,
    fiscal_year_id: Optional[str] = None,
    min_confidence: float = 0.6,
    sources: Optional[List[str]] = None  # ["csv", "cashbook", "manual"] - None = alle
) -> Dict:
    """
    Universeller Abgleich: Gleicht alle Zahlungsquellen mit offenen Charges ab
    
    Quellen:
    1. CSV-Import (BankTransaction aus CSV) - "csv" oder "bank_transaction"
    2. Kassenbuch (CashBookEntry ohne charge_id) - "cashbook"
    3. Manuelle Transaktionen (BankTransaction manuell erstellt) - "manual"
    
    Args:
        db: Database session
        owner_id: Owner ID
        client_id: Optional Client ID Filter
        fiscal_year_id: Optional Fiscal Year ID Filter
        min_confidence: Mindest-Confidence für automatisches Matching (0.0-1.0)
        sources: Liste der zu verwendenden Quellen (None = alle)
    
    Returns:
        Dict mit Statistiken
    """
    stats = {
        "processed": 0,
        "matched": 0,
        "no_match": 0,
        "errors": 0,
        "details": [],
        "sources": {
            "csv": {"processed": 0, "matched": 0},
            "cashbook": {"processed": 0, "matched": 0},
            "manual": {"processed": 0, "matched": 0}
        }
    }
    
    try:
        # Hole alle offenen Charges
        charges_query = db.query(Charge).join(Lease).filter(
            Charge.status.in_([ChargeStatus.OPEN, ChargeStatus.PARTIALLY_PAID, ChargeStatus.OVERDUE])
        )
        
        # TODO: Add client_id filter after migration
        # if client_id:
        #     charges_query = charges_query.filter(Lease.client_id == client_id)
        
        open_charges = charges_query.all()
        logger.info(f"📋 {len(open_charges)} offene Charges gefunden")
        
        if len(open_charges) == 0:
            logger.warning("⚠️ KEINE offenen Charges gefunden! Abgleich kann nichts matchen.")
            return {
                "processed": 0,
                "matched": 0,
                "no_match": 0,
                "errors": 0,
                "details": [],
                "sources": {
                    "csv": {"processed": 0, "matched": 0},
                    "cashbook": {"processed": 0, "matched": 0},
                    "manual": {"processed": 0, "matched": 0}
                },
                "warning": "Keine offenen Sollbuchungen gefunden. Bitte generieren Sie zuerst eine Sollstellung."
            }
        
        # Zeige Details der ersten 3 Charges für Debugging
        for i, charge in enumerate(open_charges[:3]):
            lease = db.query(Lease).filter(Lease.id == charge.lease_id).first()
            if lease:
                tenant = db.query(Tenant).filter(Tenant.id == lease.tenant_id).first()
                logger.info(f"   Charge {i+1}: {charge.amount}€ offen, Mieter: {tenant.first_name if tenant else 'N/A'} {tenant.last_name if tenant else 'N/A'}, Status: {charge.status}")
        
        # Normalisiere sources (None = alle, sonst nur ausgewählte)
        if sources is None:
            sources = ["csv", "cashbook", "manual"]
        else:
            # Behalte Original-Quellen für präzise Filterung
            sources = list(sources) if isinstance(sources, list) else [s.strip() for s in sources.split(",") if s.strip()]
        
        logger.info(f"🔄 Abgleich mit Quellen: {sources}")
        
        # ========== 1. CSV-Dateien (nur wenn "csv" explizit ausgewählt) ==========
        if "csv" in sources:
            # 1a. Hole CSV-Dateien mit Tabellen und führe Abgleich durch (wie csv-reconcile)
            # Das ist wichtig, weil CSV-Daten oft nur in Tabellen sind, nicht als BankTransaction-Objekte
            csv_files = db.query(CsvFile).filter(
                CsvFile.owner_id == owner_id,
                CsvFile.table_name.isnot(None)  # Nur CSV-Dateien mit Tabellen
            ).all()
            
            logger.info(f"📋 {len(csv_files)} CSV-Datei(en) mit Tabellen gefunden")
            
            if len(csv_files) > 0:
                from ..utils.simple_csv_matcher import simple_match_csv
                
                for csv_file in csv_files:
                    try:
                        logger.info(f"📄 Führe Abgleich mit CSV-Tabelle: {csv_file.table_name} ({csv_file.filename})")
                        csv_stats = simple_match_csv(db, csv_file, owner_id)
                        
                        # Addiere zu Gesamt-Statistiken
                        stats["processed"] += csv_stats.get("processed", 0)
                        stats["matched"] += csv_stats.get("matched", 0)
                        stats["no_match"] += csv_stats.get("no_match", 0)
                        stats["errors"] += csv_stats.get("errors", 0)
                        stats["sources"]["csv"]["processed"] += csv_stats.get("processed", 0)
                        stats["sources"]["csv"]["matched"] += csv_stats.get("matched", 0)
                        stats["details"].extend(csv_stats.get("details", []))
                        
                        logger.info(f"✅ {csv_file.filename}: {csv_stats.get('matched', 0)} von {csv_stats.get('processed', 0)} Zeilen zugeordnet")
                    except Exception as csv_error:
                        logger.error(f"❌ Fehler beim CSV-Abgleich von {csv_file.filename}: {str(csv_error)}")
                        import traceback
                        logger.error(traceback.format_exc())
                        stats["errors"] += 1
                        continue
        else:
            logger.info("⏭️ CSV-Dateien übersprungen (nicht ausgewählt)")
        
        # ========== 2. Manuelle Transaktionen (nur wenn "manual" explizit ausgewählt) ==========
        if "manual" in sources:
            # Hole nur manuelle Transaktionen (vom "Manuelle Buchungen" Konto)
            unmatched_manual_query = db.query(BankTransaction).join(
                BankAccount
            ).filter(
                BankAccount.owner_id == owner_id,
                BankAccount.account_name.ilike("%manuell%"),  # Nur "Manuelle Buchungen" Konto
                BankTransaction.is_matched == False,
                BankTransaction.amount > 0  # Nur Eingänge
            )
            
            unmatched_manual = unmatched_manual_query.all()
            logger.info(f"📝 {len(unmatched_manual)} ungematchte manuelle Transaktionen gefunden")
            
            # Zeige Details der ersten 5 Transaktionen
            for i, trans in enumerate(unmatched_manual[:5]):
                logger.info(f"   Manuelle Transaktion {i+1}: {trans.amount}€, Datum: {trans.transaction_date}, Name: {trans.counterpart_name}, Zweck: {trans.purpose[:50] if trans.purpose else 'N/A'}")
            
            for transaction in unmatched_manual:
                try:
                    stats["processed"] += 1
                    stats["sources"]["manual"]["processed"] += 1
                    
                    payment_data = {
                        "amount": float(transaction.amount),
                        "date": transaction.transaction_date,
                        "iban": transaction.counterpart_iban,
                        "name": transaction.counterpart_name,
                        "purpose": transaction.purpose
                    }
                    
                    # Suche beste Übereinstimmung
                    best_match = None
                    best_score = 0
                    
                    logger.info(f"🔍 Prüfe Manuelle Buchung {transaction.id}: {transaction.amount}€, Name: {transaction.counterpart_name}, Zweck: {transaction.purpose}")
                    logger.info(f"   📋 {len(open_charges)} offene Charges zum Abgleichen verfügbar")
                    
                    # NIEDRIGERE Confidence-Schwelle für manuelle Buchungen (flexibleres Matching)
                    # Für manuelle Buchungen: 20% (sehr flexibel, da Name + Teilzahlung ausreichen sollte)
                    effective_min_confidence = max(0.2, min_confidence - 0.2)  # 20% niedriger für manuelle Buchungen
                    logger.info(f"   🎯 Mindest-Confidence für manuelle Buchungen: {effective_min_confidence:.0%}")
                    
                    for charge in open_charges:
                        match_result = match_payment_to_charge(
                            db, payment_data, charge, owner_id, "bank_transaction", effective_min_confidence
                        )
                        
                        if match_result:
                            logger.info(f"   📊 Charge {charge.id}: Score={match_result['score']}, Confidence={match_result['confidence']:.2%}, Min={effective_min_confidence:.0%}")
                            logger.info(f"      Reasons: {', '.join(match_result.get('reasons', [])[:3])}")
                            
                            if match_result["confidence"] >= effective_min_confidence:
                                if match_result["score"] > best_score:
                                    best_score = match_result["score"]
                                    best_match = match_result
                                    best_match["charge"] = charge
                                    best_match["transaction"] = transaction
                                    logger.info(f"   ✅ Besserer Match gefunden: Charge {charge.id} mit Score {best_score} (Confidence: {match_result['confidence']:.1%})")
                            else:
                                logger.info(f"   ⚠️ Charge {charge.id}: Confidence zu niedrig ({match_result['confidence']:.1%} < {effective_min_confidence:.1%})")
                        else:
                            logger.info(f"   ❌ Charge {charge.id}: match_payment_to_charge hat None zurückgegeben")
                    
                    # Wenn Match gefunden, erstelle PaymentMatch
                    if best_match:
                        charge = best_match["charge"]
                        transaction = best_match["transaction"]
                        matched_amount = Decimal(str(best_match["matched_amount"]))
                        
                        # Erstelle Notiz mit Warnungen bei Abweichungen
                        match_note_parts = [f"Auto-Match (Score: {best_match['score']}, Confidence: {best_match['confidence']:.1%})"]
                        if best_match.get("warnings"):
                            match_note_parts.extend(best_match["warnings"])
                        match_note = " | ".join(match_note_parts)
                        
                        # Erstelle PaymentMatch
                        payment_match = PaymentMatch(
                            transaction_id=transaction.id,
                            charge_id=charge.id,
                            matched_amount=matched_amount,
                            is_automatic=True,
                            note=match_note
                        )
                        db.add(payment_match)
                        
                        # Update Charge
                        charge.paid_amount += matched_amount
                        if charge.paid_amount >= charge.amount:
                            charge.status = ChargeStatus.PAID
                        elif charge.paid_amount > 0:
                            charge.status = ChargeStatus.PARTIALLY_PAID
                        
                        # Update Transaction
                        transaction.matched_amount += matched_amount
                        if transaction.matched_amount >= transaction.amount:
                            transaction.is_matched = True
                        
                        # Aktualisiere BillRun
                        try:
                            from ..routes.billrun_routes import update_bill_run_totals
                            update_bill_run_totals(db, charge.bill_run_id)
                        except Exception as e:
                            logger.error(f"Fehler beim Aktualisieren der BillRun: {str(e)}")
                        
                        stats["matched"] += 1
                        stats["sources"]["manual"]["matched"] += 1
                        
                        stats["details"].append({
                            "source": "manual",
                            "transaction_id": transaction.id,
                            "charge_id": charge.id,
                            "amount": float(matched_amount),
                            "score": best_match["score"],
                            "confidence": best_match["confidence"],
                            "warnings": best_match.get("warnings", [])
                        })
                        
                        logger.info(f"✅ Manuelle Buchung {transaction.id} → Charge {charge.id} ({matched_amount}€)")
                    
                    else:
                        stats["no_match"] += 1
                        logger.info(f"❌ Manuelle Buchung {transaction.id}: Kein Match gefunden")
                        
                except Exception as e:
                    stats["errors"] += 1
                    logger.error(f"Fehler beim Abgleich von Transaktion {transaction.id}: {str(e)}")
                    import traceback
                    logger.error(traceback.format_exc())
                    continue
        else:
            logger.info("⏭️ Manuelle Transaktionen übersprungen (nicht ausgewählt)")
        
        # ========== 3. Kassenbuch (nur wenn "cashbook" explizit ausgewählt) ==========
        if "cashbook" in sources:
            cashbook_query = db.query(CashBookEntry).filter(
                CashBookEntry.owner_id == owner_id,
                CashBookEntry.entry_type == "income",  # Nur Einzahlungen
                CashBookEntry.charge_id.is_(None)  # Noch nicht zugeordnet
            )
            
            if client_id:
                cashbook_query = cashbook_query.filter(CashBookEntry.client_id == client_id)
            if fiscal_year_id:
                cashbook_query = cashbook_query.filter(CashBookEntry.fiscal_year_id == fiscal_year_id)
            
            unmatched_cashbook = cashbook_query.all()
            logger.info(f"💰 {len(unmatched_cashbook)} ungematchte Kassenbuch-Einträge gefunden")
            
            if len(unmatched_cashbook) == 0:
                logger.warning("⚠️ KEINE ungematchten Kassenbuch-Einträge gefunden!")
            else:
                # Zeige Details der ersten 3 Einträge
                for i, entry in enumerate(unmatched_cashbook[:3]):
                    tenant_name = "N/A"
                    if entry.tenant_id:
                        tenant = db.query(Tenant).filter(Tenant.id == entry.tenant_id).first()
                        if tenant:
                            tenant_name = f"{tenant.first_name} {tenant.last_name}"
                    logger.info(f"   Kassenbuch {i+1}: {entry.amount}€, Datum: {entry.entry_date}, Tenant: {tenant_name}, Zweck: {entry.purpose[:50] if entry.purpose else 'N/A'}")
            
            for entry in unmatched_cashbook:
                try:
                    stats["processed"] += 1
                    stats["sources"]["cashbook"]["processed"] += 1
                    
                    payment_data = {
                        "amount": float(entry.amount),
                        "date": entry.entry_date,
                        "iban": None,  # Kassenbuch hat keine IBAN
                        "name": None,  # Kassenbuch hat keinen Namen (könnte aus tenant_id kommen)
                        "purpose": entry.purpose
                    }
                    
                    # Wenn tenant_id vorhanden, hole Tenant-Info
                    if entry.tenant_id:
                        tenant = db.query(Tenant).filter(Tenant.id == entry.tenant_id).first()
                        if tenant:
                            payment_data["name"] = f"{tenant.first_name} {tenant.last_name}"
                            payment_data["iban"] = tenant.iban
                    
                    # Suche beste Übereinstimmung
                    best_match = None
                    best_score = 0
                    
                    logger.info(f"🔍 Prüfe Kassenbuch-Eintrag {entry.id}: {entry.amount}€, Tenant: {entry.tenant_id}, Zweck: {entry.purpose}")
                    
                    for charge in open_charges:
                        # Verwende SPEZIELLE Kassenbuch-Matching-Logik
                        match_result = match_cashbook_to_charge(
                            db, entry, charge, owner_id
                        )
                        
                        if match_result:
                            # Für Kassenbuch-Einträge: Senke Mindest-Confidence deutlich
                            # - Mit tenant_id: 40% (sehr zuverlässig)
                            # - Ohne tenant_id, aber Name im Verwendungszweck: 40% (auch zuverlässig)
                            effective_min_confidence = 0.40  # Einheitlich 40% für Kassenbuch
                            
                            logger.info(f"   📊 Charge {charge.id}: Score={match_result['score']}, Confidence={match_result['confidence']:.2%}, Min={effective_min_confidence:.0%}, Reasons: {', '.join(match_result['reasons'][:3])}")
                            
                            if match_result["confidence"] >= effective_min_confidence:
                                if match_result["score"] > best_score:
                                    best_score = match_result["score"]
                                    best_match = match_result
                                    best_match["charge"] = charge
                                    best_match["entry"] = entry
                                    logger.info(f"   ✅ Besserer Match gefunden: Charge {charge.id} mit Score {best_score}")
                        else:
                            logger.debug(f"   ❌ Charge {charge.id}: Kein Match")
                    
                    # Wenn Match gefunden, verknüpfe Kassenbuch-Eintrag mit Charge
                    if best_match:
                        charge = best_match["charge"]
                        entry = best_match["entry"]
                        matched_amount = Decimal(str(best_match["matched_amount"]))
                        
                        # Erstelle Notiz mit Warnungen bei Abweichungen
                        match_note_parts = [f"Auto-Match (Score: {best_match['score']}, Confidence: {best_match['confidence']:.1%})"]
                        if best_match.get("warnings"):
                            match_note_parts.extend(best_match["warnings"])
                        match_note = " | ".join(match_note_parts)
                        
                        # Aktualisiere Kassenbuch-Eintrag mit Notiz (falls Feld vorhanden)
                        # Für jetzt speichern wir die Warnungen in den Details
                        
                        # Verknüpfe Kassenbuch-Eintrag mit Charge
                        entry.charge_id = charge.id
                        
                        # Update Charge
                        remaining_before = charge.amount - charge.paid_amount
                        charge.paid_amount += matched_amount
                        if charge.paid_amount >= charge.amount:
                            charge.status = ChargeStatus.PAID
                        elif charge.paid_amount > 0:
                            charge.status = ChargeStatus.PARTIALLY_PAID
                        
                        # Aktualisiere BillRun
                        try:
                            from ..routes.billrun_routes import update_bill_run_totals
                            update_bill_run_totals(db, charge.bill_run_id)
                        except Exception as e:
                            logger.error(f"Fehler beim Aktualisieren der BillRun: {str(e)}")
                        
                        stats["matched"] += 1
                        stats["sources"]["cashbook"]["matched"] += 1
                        
                        # Erstelle Detail-Eintrag mit Warnungen
                        detail_entry = {
                            "source": "cashbook",
                            "entry_id": entry.id,
                            "charge_id": charge.id,
                            "amount": float(matched_amount),
                            "score": best_match["score"],
                            "confidence": best_match["confidence"],
                            "warnings": best_match.get("warnings", []),
                            "note": match_note
                        }
                        stats["details"].append(detail_entry)
                        
                        # Log mit Warnungen
                        warning_text = f" ({', '.join(best_match.get('warnings', []))})" if best_match.get("warnings") else ""
                        logger.info(f"✅ Kassenbuch-Eintrag {entry.id} → Charge {charge.id} ({matched_amount}€){warning_text}")
                    
                    else:
                        stats["no_match"] += 1
                        
                except Exception as e:
                    stats["errors"] += 1
                    logger.error(f"Fehler beim Abgleich von Kassenbuch-Eintrag {entry.id}: {str(e)}")
                    continue
        else:
            logger.info("⏭️ Kassenbuch-Einträge übersprungen (nicht ausgewählt)")
        
        # ========== 3. Manuelle Transaktionen ==========
        # (Werden bereits in "bank_transaction" behandelt, da sie auch BankTransaction sind)
        # Hier könnte man später eine Unterscheidung machen, z.B. über ein Flag "is_manual"
        
        db.commit()
        
        logger.info(f"✅ Universeller Abgleich abgeschlossen: {stats['matched']} von {stats['processed']} Zahlungen zugeordnet")
        
        return stats
        
    except Exception as e:
        db.rollback()
        logger.error(f"❌ Fehler beim universellen Abgleich: {str(e)}")
        import traceback
        logger.error(traceback.format_exc())
        raise

