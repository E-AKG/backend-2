"""
Erweiterter Zahlungsabgleich mit intelligentem Matching
Verwendet Levenshtein Distance, IBAN-Matching, und erweiterte Heuristiken
"""
import logging
import re
from typing import List, Dict, Optional, Tuple
from decimal import Decimal
from datetime import date, timedelta
from sqlalchemy.orm import Session
from ..models.bank import BankTransaction, PaymentMatch
from ..models.billrun import Charge, ChargeStatus, BillRun
from ..models.lease import Lease
from ..models.tenant import Tenant
from ..models.auto_match_log import AutoMatchLog

logger = logging.getLogger(__name__)


def levenshtein_distance(s1: str, s2: str) -> int:
    """
    Berechne Levenshtein Distance zwischen zwei Strings
    (Anzahl der Einfügungen, Löschungen, Ersetzungen)
    """
    if len(s1) < len(s2):
        return levenshtein_distance(s2, s1)

    if len(s2) == 0:
        return len(s1)

    previous_row = range(len(s2) + 1)
    for i, c1 in enumerate(s1):
        current_row = [i + 1]
        for j, c2 in enumerate(s2):
            insertions = previous_row[j + 1] + 1
            deletions = current_row[j] + 1
            substitutions = previous_row[j] + (c1 != c2)
            current_row.append(min(insertions, deletions, substitutions))
        previous_row = current_row

    return previous_row[-1]


def levenshtein_similarity(s1: str, s2: str) -> float:
    """
    Berechne Ähnlichkeit zwischen zwei Strings (0.0 - 1.0)
    1.0 = identisch, 0.0 = völlig unterschiedlich
    """
    if not s1 or not s2:
        return 0.0
    
    s1_clean = s1.lower().strip()
    s2_clean = s2.lower().strip()
    
    if s1_clean == s2_clean:
        return 1.0
    
    distance = levenshtein_distance(s1_clean, s2_clean)
    max_len = max(len(s1_clean), len(s2_clean))
    
    if max_len == 0:
        return 0.0
    
    return 1.0 - (distance / max_len)


def normalize_iban(iban: Optional[str]) -> str:
    """Normalisiere IBAN (Großbuchstaben, keine Leerzeichen)"""
    if not iban:
        return ""
    return iban.replace(" ", "").upper()


def normalize_text(text: str) -> str:
    """Normalisiere Text für besseres Matching (Umlaute, Leerzeichen, etc.)"""
    if not text:
        return ""
    # Normalisiere Umlaute
    text = text.lower().strip()
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
    # Entferne mehrfache Leerzeichen
    text = re.sub(r'\s+', ' ', text)
    return text


def extract_name_parts(name: str) -> List[str]:
    """Extrahiere relevante Namens-Teile (Nachname, Vorname, Initialen)"""
    if not name:
        return []
    normalized = normalize_text(name)
    parts = normalized.split()
    # Filtere sehr kurze Teile (wahrscheinlich Initialen oder Präpositionen)
    relevant_parts = [p for p in parts if len(p) > 2]
    return relevant_parts


def calculate_match_score(
    transaction: BankTransaction,
    charge: Charge,
    tenant: Tenant,
    unit_label: Optional[str] = None
) -> Dict:
    """
    Verbesserter Match-Score zwischen Transaktion und Sollbuchung
    
    Intelligentes Scoring-System mit multiplen Signalen:
    - IBAN-Match: 40 Punkte (höchste Priorität, sehr zuverlässig)
    - Namen-Match: 35 Punkte (Fuzzy + exakt, in Name UND Verwendungszweck)
    - Betrags-Match: 25 Punkte (exakt bis ±5%)
    - Datums-Match: 15 Punkte (flexibel ±30 Tage)
    - Verwendungszweck: 10 Punkte (Name + Einheit + Keywords)
    
    Bonus-Punkte für Kombinationen von Signalen!
    
    Returns:
        Dict mit total_score, einzelnen Scores und Notizen
    """
    scores = {
        "iban": 0,
        "name": 0,
        "amount": 0,
        "date": 0,
        "purpose": 0,
        "total": 0,
        "details": []
    }
    
    # 1. IBAN-MATCHING (40 Punkte) - Höchste Priorität, sehr zuverlässig
    if transaction.counterpart_iban:
        trans_iban = normalize_iban(transaction.counterpart_iban)
        
        # Prüfe ob Mieter eine IBAN hinterlegt hat
        if tenant.iban:
            tenant_iban = normalize_iban(tenant.iban)
            
            # Exakter IBAN-Match = JACKPOT! Sehr zuverlässig
            if trans_iban == tenant_iban:
                scores["iban"] = 40
                scores["details"].append(f"✅ IBAN-Match! ({trans_iban[:10]}...)")
            else:
                # Keine Übereinstimmung, aber wenigstens deutsche IBAN
                if trans_iban.startswith('DE') and len(trans_iban) == 22:
                    scores["iban"] = 5
                    scores["details"].append("Deutsche IBAN erkannt (aber nicht übereinstimmend)")
        else:
            # Mieter hat keine IBAN hinterlegt
            if trans_iban.startswith('DE') and len(trans_iban) == 22:
                scores["iban"] = 8
                scores["details"].append("Deutsche IBAN erkannt (Mieter-IBAN fehlt)")
    
    # 2. NAMEN-MATCHING (35 Punkte) - Intelligentes Multi-Signal Matching
    tenant_full_name = f"{tenant.first_name} {tenant.last_name}"
    tenant_last_name = tenant.last_name
    tenant_first_name = tenant.first_name
    
    # Normalisiere alle Namen für besseres Matching
    tenant_full_normalized = normalize_text(tenant_full_name)
    tenant_last_normalized = normalize_text(tenant_last_name)
    tenant_first_normalized = normalize_text(tenant_first_name)
    
    counterpart_name = transaction.counterpart_name or ""
    purpose_text = transaction.purpose or ""
    
    counterpart_normalized = normalize_text(counterpart_name)
    purpose_normalized = normalize_text(purpose_text)
    
    name_signals = []
    
    # Signal 1: Exakter Nachname im Counterpart Name
    if counterpart_normalized and tenant_last_normalized:
        if tenant_last_normalized in counterpart_normalized:
            name_signals.append(("Nachname in Absendername", 25))
        # Fuzzy Match auf Nachname
        elif levenshtein_similarity(tenant_last_normalized, counterpart_normalized) > 0.85:
            similarity = levenshtein_similarity(tenant_last_normalized, counterpart_normalized)
            name_signals.append((f"Ähnlicher Nachname (Fuzzy: {similarity:.0%})", int(20 * similarity)))
        # Vorname im Counterpart
        elif tenant_first_normalized and tenant_first_normalized in counterpart_normalized:
            name_signals.append(("Vorname in Absendername", 12))
    
    # Signal 2: Name im Verwendungszweck (sehr wichtig!)
    if purpose_normalized:
        # Entferne Sonderzeichen für flexibleres Matching (z.B. "Akgün - Wohnung" → "Akgun Wohnung")
        purpose_clean = re.sub(r'[^\w\s]', ' ', purpose_normalized)
        purpose_clean = re.sub(r'\s+', ' ', purpose_clean).strip()
        
        # Nachname im Verwendungszweck
        if tenant_last_normalized and tenant_last_normalized in purpose_clean:
            name_signals.append(("Nachname im Verwendungszweck", 20))
        # Vorname im Verwendungszweck
        elif tenant_first_normalized and tenant_first_normalized in purpose_clean:
            name_signals.append(("Vorname im Verwendungszweck", 10))
        # Vollständiger Name im Verwendungszweck (Bonus!)
        elif tenant_full_normalized and tenant_full_normalized in purpose_clean:
            name_signals.append(("Vollständiger Name im Verwendungszweck", 15))
        # Auch in original purpose_normalized prüfen (falls Sonderzeichen wichtig sind)
        elif tenant_last_normalized and tenant_last_normalized in purpose_normalized:
            name_signals.append(("Nachname im Verwendungszweck (mit Sonderzeichen)", 18))
    
    # Kombiniere Signale (höchstes Signal + Bonus für Kombinationen)
    if name_signals:
        # Sortiere nach Punkten (höchste zuerst)
        name_signals.sort(key=lambda x: x[1], reverse=True)
        best_signal = name_signals[0]
        scores["name"] = best_signal[1]
        scores["details"].append(best_signal[0])
        
        # Bonus für mehrere Signale (Name in Counterpart UND Verwendungszweck)
        if len(name_signals) > 1:
            bonus = min(5, len(name_signals) * 2)  # Max 5 Bonus-Punkte
            scores["name"] += bonus
            scores["details"].append(f"Bonus: Name in {len(name_signals)} Stellen gefunden (+{bonus})")
        
        # Cap bei 35 Punkten
        scores["name"] = min(35, scores["name"])
    
    # 3. BETRAGS-MATCHING (25 Punkte) - Wichtig für Zuordnung
    remaining_amount = charge.amount - charge.paid_amount
    amount_diff = abs(float(transaction.amount) - float(remaining_amount))
    amount_diff_percent = amount_diff / float(remaining_amount) if remaining_amount > 0 else 1.0
    
    if amount_diff == 0:
        scores["amount"] = 25
        scores["details"].append(f"Betrag exakt: {transaction.amount}€")
    elif amount_diff_percent < 0.005:  # ±0.5% (sehr nah)
        scores["amount"] = 23
        scores["details"].append(f"Betrag sehr nah: {transaction.amount}€ (±0.5%)")
    elif amount_diff_percent < 0.01:  # ±1%
        scores["amount"] = 20
        scores["details"].append(f"Betrag nah: {transaction.amount}€ (±1%)")
    elif amount_diff_percent < 0.02:  # ±2%
        scores["amount"] = 18
        scores["details"].append(f"Betrag ähnlich: {transaction.amount}€ (±2%)")
    elif amount_diff_percent < 0.05:  # ±5%
        scores["amount"] = 12
        scores["details"].append(f"Betrag in Toleranz: {transaction.amount}€ vs {remaining_amount}€ (±5%)")
    elif amount_diff_percent < 0.10:  # ±10%
        scores["amount"] = 5
        scores["details"].append(f"Betrag abweichend: {transaction.amount}€ vs {remaining_amount}€ (±10%)")
    
    # 4. DATUMS-MATCHING (15 Punkte) - Flexibel für verschiedene Zahlungsgewohnheiten
    days_diff = abs((transaction.transaction_date - charge.due_date).days)
    
    if days_diff == 0:
        scores["date"] = 15
        scores["details"].append(f"Datum exakt am Fälligkeitsdatum")
    elif days_diff <= 2:
        scores["date"] = 14
        scores["details"].append(f"Datum sehr nah: ±{days_diff} Tag(e) vom Fälligkeitsdatum")
    elif days_diff <= 5:
        scores["date"] = 12
        scores["details"].append(f"Datum nah: ±{days_diff} Tage vom Fälligkeitsdatum")
    elif days_diff <= 7:
        scores["date"] = 10
        scores["details"].append(f"Datum innerhalb ±{days_diff} Tage vom Fälligkeitsdatum")
    elif days_diff <= 14:
        scores["date"] = 8
        scores["details"].append(f"Datum innerhalb ±{days_diff} Tage vom Fälligkeitsdatum")
    elif days_diff <= 21:
        scores["date"] = 5
        scores["details"].append(f"Datum innerhalb ±{days_diff} Tage (früh/spät)")
    elif days_diff <= 30:
        scores["date"] = 3
        scores["details"].append(f"Datum im gleichen Monat (±{days_diff} Tage)")
    else:
        # Auch späte Zahlungen können passen (z.B. Nachzahlung)
        scores["date"] = 1
        scores["details"].append(f"Datum abweichend: ±{days_diff} Tage")
    
    # 5. VERWENDUNGSZWECK-MATCHING (10 Punkte) - Wichtige zusätzliche Signale
    if purpose_normalized:
        purpose_signals = []
        
        # Signal 1: Miete-Keywords
        purpose_keywords = ['miete', 'rent', 'wohnung', 'apartment', 'unit', 'mieter', 'mietzahlung']
        if any(keyword in purpose_normalized for keyword in purpose_keywords):
            purpose_signals.append(("Miete-Keyword gefunden", 3))
        
        # Signal 2: Monat/Jahr im Verwendungszweck
        month_names = ['januar', 'februar', 'märz', 'april', 'mai', 'juni', 
                       'juli', 'august', 'september', 'oktober', 'november', 'dezember']
        charge_month = charge.due_date.month
        if month_names[charge_month - 1] in purpose_normalized:
            purpose_signals.append((f"Monat '{month_names[charge_month - 1]}' gefunden", 2))
        
        # Signal 3: Einheiten-Label (sehr wichtig!)
        if unit_label:
            unit_label_normalized = normalize_text(unit_label)
            
            # Exakter Match (z.B. "Wohnung 1B" in "Akgün Wohnung 1B" oder "Akgün - Wohnung 1B")
            # Entferne Sonderzeichen für flexibleres Matching
            unit_clean = re.sub(r'[^\w\s]', ' ', unit_label_normalized)  # Ersetze Sonderzeichen durch Leerzeichen
            purpose_clean = re.sub(r'[^\w\s]', ' ', purpose_normalized)  # Gleiches für Purpose
            
            if unit_label_normalized in purpose_normalized or unit_clean.strip() in purpose_clean:
                purpose_signals.append((f"Einheit '{unit_label}' exakt gefunden", 5))
            else:
                # Flexibler Match: Suche nach relevanten Teilen
                unit_parts = unit_clean.split()
                generic_words = ['wohnung', 'apartment', 'unit', 'einheit', 'nr', 'no', 'number', 'app']
                
                # Suche nach allen relevanten Teilen (nicht nur dem ersten)
                found_parts = []
                for part in unit_parts:
                    if part not in generic_words and len(part) > 1:
                        if part in purpose_clean:
                            found_parts.append(part)
                
                if found_parts:
                    # Mehrere Teile gefunden = höhere Punktzahl
                    points = min(5, 2 + len(found_parts))
                    purpose_signals.append((f"Einheit-Teile '{', '.join(found_parts)}' (aus '{unit_label}') gefunden", points))
        
        # Kombiniere Purpose-Signale
        if purpose_signals:
            scores["purpose"] = sum(signal[1] for signal in purpose_signals)
            scores["details"].extend([signal[0] for signal in purpose_signals])
            # Cap bei 10 Punkten
            scores["purpose"] = min(10, scores["purpose"])
    
    # Gesamtscore berechnen
    scores["total"] = scores["iban"] + scores["name"] + scores["amount"] + scores["date"] + scores["purpose"]
    
    # BONUS: Kombinations-Bonus für starke Signale zusammen
    strong_signals = 0
    if scores["iban"] >= 35:  # IBAN-Match
        strong_signals += 1
    if scores["name"] >= 20:  # Guter Name-Match
        strong_signals += 1
    if scores["amount"] >= 18:  # Guter Betrags-Match
        strong_signals += 1
    if scores["date"] >= 10:  # Guter Datums-Match
        strong_signals += 1
    if scores["purpose"] >= 5:  # Guter Purpose-Match
        strong_signals += 1
    
    # Bonus für 3+ starke Signale
    if strong_signals >= 3:
        bonus = min(5, (strong_signals - 2) * 2)  # Max 5 Bonus-Punkte
        scores["total"] += bonus
        scores["details"].append(f"🎯 Kombinations-Bonus: {strong_signals} starke Signale (+{bonus})")
    
    return scores


def auto_match_transactions(
    db: Session,
    owner_id: int,
    bank_account_id: Optional[str] = None,
    min_confidence: float = 80.0
) -> Dict:
    """
    Erweiterte automatische Zahlungszuordnung
    
    Args:
        db: Database Session
        owner_id: Benutzer ID
        bank_account_id: Optional - nur Transaktionen dieses Kontos
        min_confidence: Minimaler Confidence Score (default: 80%)
    
    Returns:
        Dict mit Statistiken: matched, skipped, multiple_candidates, no_match
    """
    logger.info(f"🤖 Starting enhanced auto-match for owner {owner_id}")
    
    stats = {
        "matched": 0,
        "skipped": 0,
        "multiple_candidates": 0,
        "no_match": 0,
        "total_processed": 0
    }
    
    # Hole ungematchte Transaktionen (nur Eingänge)
    query = db.query(BankTransaction).filter(
        BankTransaction.is_matched == False,
        BankTransaction.amount > 0,  # Nur Eingänge
        BankTransaction.bank_account.has(owner_id=owner_id)
    )
    
    if bank_account_id:
        query = query.filter(BankTransaction.bank_account_id == bank_account_id)
    
    unmatched_transactions = query.all()
    logger.info(f"Found {len(unmatched_transactions)} unmatched transactions")
    
    # Hole offene Sollbuchungen
    open_charges = db.query(Charge).join(
        BillRun
    ).filter(
        BillRun.owner_id == owner_id,
        Charge.status.in_([ChargeStatus.OPEN, ChargeStatus.PARTIALLY_PAID])
    ).all()
    
    logger.info(f"Found {len(open_charges)} open charges")
    
    for transaction in unmatched_transactions:
        stats["total_processed"] += 1
        
        logger.info(f"\n{'='*60}")
        logger.info(f"Processing Transaction {transaction.id}")
        logger.info(f"  Amount: {transaction.amount}€")
        logger.info(f"  Date: {transaction.transaction_date}")
        logger.info(f"  Counterpart: {transaction.counterpart_name}")
        logger.info(f"  Purpose: {transaction.purpose}")
        
        # Finde Matches für diese Transaktion
        candidates = []
        
        for charge in open_charges:
            # Hole Lease und Tenant für diese Charge
            lease = db.query(Lease).filter(Lease.id == charge.lease_id).first()
            if not lease:
                continue
            
            tenant = db.query(Tenant).filter(Tenant.id == lease.tenant_id).first()
            if not tenant:
                continue
            
            # Hole Unit Label
            from ..models.unit import Unit
            unit = db.query(Unit).filter(Unit.id == lease.unit_id).first()
            unit_label = unit.unit_label if unit else None
            
            # Berechne Match-Score
            score_result = calculate_match_score(transaction, charge, tenant, unit_label)
            
            logger.info(f"  Charge {charge.id}: {charge.amount}€, Due: {charge.due_date}")
            logger.info(f"    Tenant: {tenant.first_name} {tenant.last_name}")
            logger.info(f"    Score: {score_result['total']} (IBAN:{score_result['iban']}, Name:{score_result['name']}, "
                       f"Amount:{score_result['amount']}, Date:{score_result['date']}, Purpose:{score_result['purpose']})")
            
            if score_result["total"] >= min_confidence:
                remaining = charge.amount - charge.paid_amount
                matched_amount = min(transaction.amount, remaining)
                
                candidates.append({
                    "charge": charge,
                    "tenant": tenant,
                    "score": score_result["total"],
                    "score_details": score_result,
                    "matched_amount": matched_amount
                })
                
                logger.info(f"    ✅ CANDIDATE: Score {score_result['total']}% >= {min_confidence}%")
            else:
                logger.info(f"    ❌ SKIP: Score {score_result['total']}% < {min_confidence}%")
        
        # Verarbeite Ergebnis
        if len(candidates) == 0:
            # Kein Match gefunden
            stats["no_match"] += 1
            _log_auto_match(db, transaction, None, "no_match", 0, 0, 0, 0, 0, 0,
                           "Kein Match über Confidence-Threshold gefunden")
            logger.info(f"  Result: NO MATCH")
            
        elif len(candidates) == 1:
            # Eindeutiger Match - automatisch zuordnen
            candidate = candidates[0]
            charge = candidate["charge"]
            score = candidate["score"]
            score_details = candidate["score_details"]
            matched_amount = candidate["matched_amount"]
            
            # Erstelle PaymentMatch
            payment_match = PaymentMatch(
                transaction_id=transaction.id,
                charge_id=charge.id,
                matched_amount=matched_amount,
                is_automatic=True,
                note=f"Auto-Match (Score: {score}%) - {', '.join(score_details['details'][:3])}"
            )
            db.add(payment_match)
            
            # Update Charge
            charge.paid_amount += matched_amount
            if charge.paid_amount >= charge.amount:
                charge.status = ChargeStatus.PAID
            else:
                charge.status = ChargeStatus.PARTIALLY_PAID
            
            # Update Transaction
            transaction.matched_amount += matched_amount
            if transaction.matched_amount >= transaction.amount:
                transaction.is_matched = True
            
            # Log
            _log_auto_match(
                db, transaction, charge, "matched", score,
                score_details["iban"], score_details["name"], score_details["amount"],
                score_details["date"], score_details["purpose"],
                f"Automatisch zugeordnet: {matched_amount}€"
            )
            
            stats["matched"] += 1
            logger.info(f"  Result: ✅ MATCHED to Charge {charge.id} (Score: {score}%)")
            
        else:
            # Mehrere Kandidaten - markiere für manuelle Prüfung
            stats["multiple_candidates"] += 1
            best_candidate = max(candidates, key=lambda x: x["score"])
            
            _log_auto_match(
                db, transaction, None, "multiple_candidates", best_candidate["score"],
                0, 0, 0, 0, 0,
                f"{len(candidates)} mögliche Matches gefunden (beste: {best_candidate['score']}%)"
            )
            
            logger.info(f"  Result: ⚠️ MULTIPLE CANDIDATES ({len(candidates)})")
    
    # Commit alle Änderungen
    if stats["matched"] > 0:
        db.commit()
        logger.info(f"\n{'='*60}")
        logger.info(f"✅ Auto-Match completed:")
        logger.info(f"  Processed: {stats['total_processed']}")
        logger.info(f"  Matched: {stats['matched']}")
        logger.info(f"  No Match: {stats['no_match']}")
        logger.info(f"  Multiple Candidates: {stats['multiple_candidates']}")
    
    return stats


def _log_auto_match(
    db: Session,
    transaction: BankTransaction,
    charge: Optional[Charge],
    result: str,
    confidence: float,
    iban_score: int,
    name_score: int,
    amount_score: int,
    date_score: int,
    purpose_score: int,
    note: str
):
    """Erstelle Log-Eintrag für Auto-Match-Versuch"""
    log_entry = AutoMatchLog(
        transaction_id=transaction.id,
        charge_id=charge.id if charge else None,
        result=result,
        confidence_score=Decimal(str(confidence)),
        iban_match=iban_score,
        name_match=name_score,
        amount_match=amount_score,
        date_match=date_score,
        purpose_match=purpose_score,
        note=note
    )
    db.add(log_entry)


def get_match_suggestions(
    db: Session,
    transaction_id: str,
    owner_id: int,
    min_confidence: float = 50.0
) -> List[Dict]:
    """
    Hole Match-Vorschläge für eine Transaktion
    (auch unter Confidence-Threshold, für manuelle Auswahl)
    
    Returns:
        Liste von Vorschlägen mit charge, score, tenant, unit
    """
    transaction = db.query(BankTransaction).filter(
        BankTransaction.id == transaction_id,
        BankTransaction.bank_account.has(owner_id=owner_id)
    ).first()
    
    if not transaction:
        return []
    
    # Hole offene Sollbuchungen
    open_charges = db.query(Charge).join(
        BillRun
    ).filter(
        BillRun.owner_id == owner_id,
        Charge.status.in_([ChargeStatus.OPEN, ChargeStatus.PARTIALLY_PAID])
    ).all()
    
    suggestions = []
    
    for charge in open_charges:
        lease = db.query(Lease).filter(Lease.id == charge.lease_id).first()
        if not lease:
            continue
        
        tenant = db.query(Tenant).filter(Tenant.id == lease.tenant_id).first()
        if not tenant:
            continue
        
        from ..models.unit import Unit
        unit = db.query(Unit).filter(Unit.id == lease.unit_id).first()
        unit_label = unit.unit_label if unit else None
        
        # Berechne Score
        score_result = calculate_match_score(transaction, charge, tenant, unit_label)
        
        if score_result["total"] >= min_confidence:
            remaining = charge.amount - charge.paid_amount
            matched_amount = min(transaction.amount, remaining)
            
            suggestions.append({
                "charge_id": charge.id,
                "charge_amount": float(charge.amount),
                "charge_remaining": float(remaining),
                "due_date": charge.due_date.isoformat(),
                "tenant_name": f"{tenant.first_name} {tenant.last_name}",
                "unit_label": unit_label,
                "confidence_score": score_result["total"],
                "score_breakdown": {
                    "iban": score_result["iban"],
                    "name": score_result["name"],
                    "amount": score_result["amount"],
                    "date": score_result["date"],
                    "purpose": score_result["purpose"]
                },
                "matched_amount": float(matched_amount),
                "details": score_result["details"]
            })
    
    # Sortiere nach Score (höchster zuerst)
    suggestions.sort(key=lambda x: x["confidence_score"], reverse=True)
    
    return suggestions

