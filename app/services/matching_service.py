"""
Automatischer Soll-Ist-Abgleich für Mietzahlungen
Matcht Banktransaktionen mit offenen Sollstellungen (Charges)
"""
from sqlalchemy.orm import Session
from sqlalchemy import and_, or_
from decimal import Decimal
from datetime import datetime, date
from typing import List, Dict, Optional, Tuple
import logging
from difflib import SequenceMatcher

from ..models.bank import BankTransaction, PaymentMatch
from ..models.billrun import Charge, ChargeStatus
from ..models.lease import Lease
from ..models.tenant import Tenant

logger = logging.getLogger(__name__)


class MatchingService:
    """Service für automatisches Matching von Transaktionen mit Sollstellungen"""
    
    def __init__(self, db: Session, tolerance_amount: Decimal = Decimal("1.00")):
        self.db = db
        self.tolerance_amount = tolerance_amount  # ±1 € Toleranz
    
    def match_all_transactions(self, user_id: int) -> Dict:
        """
        Führt automatisches Matching für alle offenen Charges eines Users durch
        
        Returns:
            Dict mit Statistiken (matched, open, overdue)
        """
        logger.info(f"🔄 Starte automatisches Matching für User {user_id}...")
        
        stats = {
            "matched": 0,
            "open": 0,
            "overdue": 0,
            "total_charges": 0,
            "total_transactions": 0
        }
        
        try:
            # Hole alle offenen Charges des Users
            charges = self.db.query(Charge).join(
                Charge.bill_run
            ).filter(
                and_(
                    Charge.status.in_([ChargeStatus.OPEN, ChargeStatus.OVERDUE]),
                    Charge.bill_run.has(owner_id=user_id)
                )
            ).all()
            
            stats["total_charges"] = len(charges)
            logger.info(f"📊 {len(charges)} offene Charges gefunden")
            
            # Hole alle unzugeordneten Transaktionen des Users
            transactions = self.db.query(BankTransaction).join(
                BankTransaction.bank_account
            ).filter(
                and_(
                    BankTransaction.bank_account.has(owner_id=user_id),
                    BankTransaction.is_matched == False,
                    BankTransaction.amount > 0  # Nur Eingänge
                )
            ).all()
            
            stats["total_transactions"] = len(transactions)
            logger.info(f"📊 {len(transactions)} unzugeordnete Transaktionen gefunden")
            
            # Matching durchführen
            for charge in charges:
                match_result = self._match_charge_with_transactions(charge, transactions)
                
                if match_result:
                    transaction, confidence = match_result
                    success = self._create_payment_match(charge, transaction, confidence)
                    
                    if success:
                        stats["matched"] += 1
                        # Entferne gematchte Transaktion aus Liste
                        transactions.remove(transaction)
                else:
                    # Prüfe ob überfällig
                    if charge.due_date < date.today():
                        if charge.status != ChargeStatus.OVERDUE:
                            charge.status = ChargeStatus.OVERDUE
                        stats["overdue"] += 1
                    else:
                        stats["open"] += 1
            
            self.db.commit()
            
            logger.info(f"✅ Matching abgeschlossen: {stats['matched']} zugeordnet, {stats['open']} offen, {stats['overdue']} überfällig")
            
            return stats
            
        except Exception as e:
            logger.error(f"❌ Fehler beim Matching: {str(e)}")
            self.db.rollback()
            raise
    
    def _match_charge_with_transactions(
        self, 
        charge: Charge, 
        transactions: List[BankTransaction]
    ) -> Optional[Tuple[BankTransaction, float]]:
        """
        Findet die beste passende Transaktion für eine Charge
        
        Returns:
            Tuple (BankTransaction, confidence_score) oder None
        """
        # Hole Mieter-Daten über Lease
        lease = charge.lease
        if not lease or not lease.tenant:
            logger.warning(f"⚠️ Charge {charge.id} hat keine Mieter-Daten")
            return None
        
        tenant = lease.tenant
        best_match = None
        best_score = 0.0
        
        for transaction in transactions:
            score = self._calculate_match_score(charge, transaction, tenant, lease)
            
            if score > best_score and score >= 0.6:  # Mindestens 60% Übereinstimmung
                best_score = score
                best_match = transaction
        
        if best_match:
            logger.info(f"✅ Match gefunden: Charge {charge.id} → Transaction {best_match.id} (Score: {best_score:.2f})")
            return (best_match, best_score)
        
        return None
    
    def _calculate_match_score(
        self, 
        charge: Charge, 
        transaction: BankTransaction,
        tenant: Tenant,
        lease: Lease
    ) -> float:
        """
        Berechnet Match-Score zwischen Charge und Transaktion
        
        Score-Komponenten:
        - Betrag: 0-40 Punkte
        - IBAN: 0-30 Punkte
        - Name: 0-20 Punkte
        - Verwendungszweck: 0-10 Punkte
        
        Returns:
            Score zwischen 0.0 und 1.0
        """
        score = 0.0
        max_score = 100.0
        
        # 1. Betrag prüfen (40 Punkte)
        amount_diff = abs(Decimal(str(transaction.amount)) - charge.amount)
        if amount_diff == 0:
            score += 40
        elif amount_diff <= self.tolerance_amount:
            # Lineare Abstufung innerhalb der Toleranz
            score += 40 * (1 - (float(amount_diff) / float(self.tolerance_amount)))
        
        # 2. IBAN prüfen (30 Punkte) - stärkste Übereinstimmung
        if transaction.counterpart_iban and tenant.iban:
            if transaction.counterpart_iban.replace(" ", "").upper() == tenant.iban.replace(" ", "").upper():
                score += 30
        
        # 3. Name prüfen (20 Punkte)
        tenant_full_name = f"{tenant.first_name} {tenant.last_name}".strip()
        if transaction.counterpart_name and tenant_full_name:
            name_similarity = self._string_similarity(
                transaction.counterpart_name.lower(),
                tenant_full_name.lower()
            )
            score += 20 * name_similarity
        
        # 4. Verwendungszweck prüfen (10 Punkte)
        if transaction.purpose:
            purpose_lower = transaction.purpose.lower()
            
            # Prüfe auf Mieter-Name
            if tenant_full_name and tenant_full_name.lower() in purpose_lower:
                score += 5
            
            # Prüfe auf Objekt/Einheit-Referenz
            if lease.unit:
                unit_name = f"{lease.unit.property.name} {lease.unit.unit_label}".lower()
                if any(word in purpose_lower for word in unit_name.split()):
                    score += 3
            
            # Prüfe auf "Miete" oder "Rent"
            if any(word in purpose_lower for word in ["miete", "rent", "kaltmiete", "warmmiete"]):
                score += 2
        
        return score / max_score
    
    def _string_similarity(self, str1: str, str2: str) -> float:
        """
        Berechnet String-Ähnlichkeit zwischen 0.0 und 1.0
        Verwendet SequenceMatcher für fuzzy matching
        """
        return SequenceMatcher(None, str1, str2).ratio()
    
    def _create_payment_match(
        self, 
        charge: Charge, 
        transaction: BankTransaction,
        confidence: float
    ) -> bool:
        """
        Erstellt PaymentMatch und aktualisiert Status
        
        Returns:
            True bei Erfolg, False bei Fehler
        """
        try:
            # Berechne matched_amount (kleinerer der beiden Beträge)
            matched_amount = min(
                Decimal(str(transaction.amount)),
                charge.amount - charge.paid_amount
            )
            
            # Erstelle PaymentMatch
            payment_match = PaymentMatch(
                transaction_id=transaction.id,
                charge_id=charge.id,
                matched_amount=matched_amount,
                is_automatic=True,
                note=f"Automatisch zugeordnet (Confidence: {confidence:.2%})"
            )
            
            self.db.add(payment_match)
            
            # Aktualisiere Charge
            charge.paid_amount += matched_amount
            
            if charge.paid_amount >= charge.amount:
                charge.status = ChargeStatus.PAID
            elif charge.paid_amount > 0:
                charge.status = ChargeStatus.PARTIALLY_PAID
            
            # Aktualisiere Transaction
            transaction.is_matched = True
            transaction.matched_amount = matched_amount
            
            logger.info(f"💾 PaymentMatch erstellt: Charge {charge.id} ↔ Transaction {transaction.id} ({matched_amount} €)")
            
            return True
            
        except Exception as e:
            logger.error(f"❌ Fehler beim Erstellen von PaymentMatch: {str(e)}")
            return False
    
    def unmatch_charge(self, charge_id: str) -> bool:
        """
        Entfernt alle Matches von einer Charge (für manuelles Korrigieren)
        """
        try:
            matches = self.db.query(PaymentMatch).filter(
                PaymentMatch.charge_id == charge_id
            ).all()
            
            for match in matches:
                # Setze Transaction zurück
                transaction = match.transaction
                transaction.is_matched = False
                transaction.matched_amount = 0
                
                # Setze Charge zurück
                charge = match.charge
                charge.paid_amount -= match.matched_amount
                if charge.paid_amount <= 0:
                    charge.status = ChargeStatus.OPEN
                elif charge.paid_amount < charge.amount:
                    charge.status = ChargeStatus.PARTIALLY_PAID
                
                # Lösche Match
                self.db.delete(match)
            
            self.db.commit()
            logger.info(f"✅ {len(matches)} Matches entfernt von Charge {charge_id}")
            return True
            
        except Exception as e:
            logger.error(f"❌ Fehler beim Entfernen von Matches: {str(e)}")
            self.db.rollback()
            return False


def auto_match_transactions(db: Session, user_id: int) -> Dict:
    """
    Convenience-Funktion für automatisches Matching
    Wird vom Scheduler und API-Endpoint aufgerufen
    """
    service = MatchingService(db)
    return service.match_all_transactions(user_id)

