from fastapi import APIRouter, Depends, HTTPException, status, Query, UploadFile, File
from sqlalchemy.orm import Session
from sqlalchemy.exc import SQLAlchemyError
from typing import Optional, List
from decimal import Decimal
from datetime import date, datetime
from ..db import get_db
from ..models.user import User
from ..models.bank import BankAccount, BankTransaction, PaymentMatch, CsvFile
from ..models.billrun import Charge, ChargeStatus
from ..schemas.bank_schema import (
    BankAccountCreate, BankAccountUpdate, BankAccountOut,
    BankTransactionCreate, BankTransactionOut,
    PaymentMatchCreate, PaymentMatchOut
)
from ..utils.deps import get_current_user
from ..utils.subscription_limits import check_csv_upload_limit, check_match_limit
# FinAPI temporär auskommentiert
# from ..utils.finapi_service import finapi_service
# from ..utils.real_finapi_service import real_finapi_service
from ..utils.auto_matcher import auto_match_transactions, get_match_suggestions
import logging
import csv
import io
import json

logger = logging.getLogger(__name__)
router = APIRouter(tags=["Bank"])


def decode_file_content(contents: bytes, filename: str = "") -> str:
    """
    Versucht Datei-Inhalt mit verschiedenen Encodings zu dekodieren.
    Probiert: utf-8-sig, utf-8, latin-1, windows-1252, cp1252
    """
    encodings = ['utf-8-sig', 'utf-8', 'latin-1', 'windows-1252', 'cp1252', 'iso-8859-1']
    
    for encoding in encodings:
        try:
            decoded = contents.decode(encoding)
            if encoding != 'utf-8-sig' and encoding != 'utf-8':
                logger.info(f"📝 Datei {filename} mit {encoding} dekodiert (nicht UTF-8)")
            return decoded
        except (UnicodeDecodeError, LookupError):
            continue
    
    # Wenn alle Encodings fehlschlagen, verwende 'errors=replace' um ungültige Zeichen zu ersetzen
    logger.warning(f"⚠️ Konnte Datei {filename} nicht dekodieren, verwende 'replace' für ungültige Zeichen")
    return contents.decode('utf-8', errors='replace')


# ========= BankAccounts =========

@router.get("/api/bank/transactions")
def list_transactions(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Liste aller Bank-Transaktionen des Users"""
    # Hole alle Bank-Konten des Users
    accounts = db.query(BankAccount).filter(
        BankAccount.owner_id == current_user.id
    ).all()
    
    if not accounts:
        return {"transactions": []}
    
    # Hole alle Transaktionen für diese Konten (alle ohne Limit)
    transactions = db.query(BankTransaction).filter(
        BankTransaction.bank_account_id.in_([acc.id for acc in accounts])
    ).order_by(BankTransaction.transaction_date.desc()).all()
    
    return {
        "transactions": [
            {
                "id": txn.id,
                "transaction_date": str(txn.transaction_date),
                "amount": float(txn.amount),
                "purpose": txn.purpose,
                "counterpart_name": txn.counterpart_name,
                "is_matched": txn.is_matched
            }
            for txn in transactions
        ]
    }


@router.get("/api/bank-accounts", response_model=list[BankAccountOut])
def list_bank_accounts(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Liste aller Bankkonten"""
    accounts = db.query(BankAccount).filter(
        BankAccount.owner_id == current_user.id
    ).all()
    return [BankAccountOut.model_validate(acc) for acc in accounts]


@router.post("/api/bank-accounts", response_model=BankAccountOut, status_code=201)
def create_bank_account(
    data: BankAccountCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Erstelle Bankkonto"""
    try:
        account = BankAccount(owner_id=current_user.id, **data.model_dump())
        db.add(account)
        db.commit()
        db.refresh(account)
        return BankAccountOut.model_validate(account)
    except SQLAlchemyError as e:
        db.rollback()
        logger.error(f"Fehler beim Erstellen: {str(e)}")
        raise HTTPException(status_code=500, detail="Fehler beim Erstellen")


@router.put("/api/bank-accounts/{account_id}", response_model=BankAccountOut)
def update_bank_account(
    account_id: str,
    data: BankAccountUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Aktualisiere Bankkonto"""
    account = db.query(BankAccount).filter(
        BankAccount.id == account_id,
        BankAccount.owner_id == current_user.id
    ).first()
    
    if not account:
        raise HTTPException(status_code=404, detail="Konto nicht gefunden")
    
    try:
        for field, value in data.model_dump(exclude_unset=True).items():
            setattr(account, field, value)
        db.commit()
        db.refresh(account)
        return BankAccountOut.model_validate(account)
    except SQLAlchemyError as e:
        db.rollback()
        raise HTTPException(status_code=500, detail="Fehler beim Aktualisieren")


@router.delete("/api/bank-accounts/{account_id}", status_code=204)
def delete_bank_account(
    account_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Lösche Bankkonto (inkl. aller Transaktionen)"""
    account = db.query(BankAccount).filter(
        BankAccount.id == account_id,
        BankAccount.owner_id == current_user.id
    ).first()
    
    if not account:
        raise HTTPException(status_code=404, detail="Konto nicht gefunden")
    
    try:
        db.delete(account)
        db.commit()
        logger.info(f"Bank account deleted: {account_id} by user {current_user.id}")
    except SQLAlchemyError as e:
        db.rollback()
        logger.error(f"Fehler beim Löschen: {str(e)}")
        raise HTTPException(status_code=500, detail="Fehler beim Löschen")


# ========= BankTransactions =========

@router.get("/api/bank-transactions", response_model=dict)
def list_transactions(
    bank_account_id: Optional[str] = Query(None),
    is_matched: Optional[bool] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Liste aller Banktransaktionen"""
    query = db.query(BankTransaction).join(BankAccount).filter(
        BankAccount.owner_id == current_user.id
    )
    
    if bank_account_id:
        query = query.filter(BankTransaction.bank_account_id == bank_account_id)
    if is_matched is not None:
        query = query.filter(BankTransaction.is_matched == is_matched)
    
    total = query.count()
    offset = (page - 1) * page_size
    transactions = query.order_by(
        BankTransaction.transaction_date.desc()
    ).offset(offset).limit(page_size).all()
    
    return {
        "items": [BankTransactionOut.model_validate(t) for t in transactions],
        "page": page,
        "page_size": page_size,
        "total": total
    }


@router.post("/api/bank-transactions", response_model=BankTransactionOut, status_code=201)
def create_transaction(
    data: BankTransactionCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Erstelle manuelle Transaktion (für Tests)"""
    # Prüfe Konto-Zugehörigkeit
    account = db.query(BankAccount).filter(
        BankAccount.id == data.bank_account_id,
        BankAccount.owner_id == current_user.id
    ).first()
    
    if not account:
        raise HTTPException(status_code=404, detail="Konto nicht gefunden")
    
    try:
        transaction = BankTransaction(**data.model_dump())
        db.add(transaction)
        db.commit()
        db.refresh(transaction)
        return BankTransactionOut.model_validate(transaction)
    except SQLAlchemyError as e:
        db.rollback()
        raise HTTPException(status_code=500, detail="Fehler beim Erstellen")


# ========= PaymentMatches =========

@router.post("/api/payment-matches", response_model=PaymentMatchOut, status_code=201)
def create_payment_match(
    data: PaymentMatchCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Ordne Transaktion einer Sollbuchung zu"""
    try:
        # Prüfe Transaction-Zugehörigkeit
        transaction = db.query(BankTransaction).join(BankAccount).filter(
            BankTransaction.id == data.transaction_id,
            BankAccount.owner_id == current_user.id
        ).first()
        
        if not transaction:
            raise HTTPException(status_code=404, detail="Transaktion nicht gefunden")
        
        # Prüfe Charge-Zugehörigkeit (via BillRun)
        charge = db.query(Charge).join(Charge.bill_run).filter(
            Charge.id == data.charge_id
        ).first()
        
        if not charge or charge.bill_run.owner_id != current_user.id:
            raise HTTPException(status_code=404, detail="Sollbuchung nicht gefunden")
        
        # Validierung: Betrag darf nicht größer sein als Restbetrag
        remaining_charge = charge.amount - charge.paid_amount
        if data.matched_amount > remaining_charge:
            raise HTTPException(
                status_code=400,
                detail=f"Betrag zu hoch. Verbleibend: {remaining_charge}"
            )
        
        # Erstelle Match
        match = PaymentMatch(**data.model_dump())
        db.add(match)
        
        # Aktualisiere Charge
        charge.paid_amount += data.matched_amount
        if charge.paid_amount >= charge.amount:
            charge.status = ChargeStatus.PAID
        elif charge.paid_amount > 0:
            charge.status = ChargeStatus.PARTIALLY_PAID
        
        # Aktualisiere Transaction
        transaction.matched_amount += data.matched_amount
        if transaction.matched_amount >= abs(transaction.amount):
            transaction.is_matched = True
        
        db.commit()
        db.refresh(match)
        
        logger.info(f"Payment Match erstellt: {match.id}")
        return PaymentMatchOut.model_validate(match)
        
    except HTTPException:
        raise
    except SQLAlchemyError as e:
        db.rollback()
        logger.error(f"Fehler beim Matching: {str(e)}")
        raise HTTPException(status_code=500, detail="Fehler beim Zuordnen")


@router.delete("/api/payment-matches/{match_id}", status_code=204)
def delete_payment_match(
    match_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Lösche Zahlungszuordnung"""
    match = db.query(PaymentMatch).join(
        BankTransaction
    ).join(BankAccount).filter(
        PaymentMatch.id == match_id,
        BankAccount.owner_id == current_user.id
    ).first()
    
    if not match:
        raise HTTPException(status_code=404, detail="Match nicht gefunden")
    
    try:
        # Rückgängig machen der Beträge
        charge = match.charge
        transaction = match.transaction
        
        charge.paid_amount -= match.matched_amount
        transaction.matched_amount -= match.matched_amount
        
        # Status aktualisieren
        if charge.paid_amount <= 0:
            charge.status = ChargeStatus.OPEN
        elif charge.paid_amount < charge.amount:
            charge.status = ChargeStatus.PARTIALLY_PAID
        
        if transaction.matched_amount < abs(transaction.amount):
            transaction.is_matched = False
        
        db.delete(match)
        db.commit()
        
    except SQLAlchemyError as e:
        db.rollback()
        logger.error(f"Fehler beim Löschen: {str(e)}")
        raise HTTPException(status_code=500, detail="Fehler beim Löschen")


# ========= FinAPI Integration =========
# FinAPI temporär auskommentiert - wird später wieder benötigt

# @router.post("/api/bank-accounts/{account_id}/sync", response_model=dict)
# def sync_transactions_from_finapi(
#     account_id: str,
#     days_back: int = Query(90, ge=1, le=365, description="Tage zurück"),
#     current_user: User = Depends(get_current_user),
#     db: Session = Depends(get_db)
# ):
#     """
#     Synchronisiere Transaktionen von FinAPI für dieses Bankkonto
#     Führt automatisch intelligenten Zahlungsabgleich durch
#     """
#     account = db.query(BankAccount).filter(
#         BankAccount.id == account_id,
#         BankAccount.owner_id == current_user.id
#     ).first()
#     
#     if not account:
#         raise HTTPException(status_code=404, detail="Konto nicht gefunden")
#     
#     try:
#         # Verwende echten FinAPI-Service wenn konfiguriert UND User hat finapi_user_id
#         if real_finapi_service.is_configured() and account.finapi_user_id and account.finapi_user_password:
#             logger.info(f"🔄 Using REAL FinAPI service for account {account_id}")
#             imported_count = real_finapi_service.sync_transactions(db, account, days_back)
#             
#             # Fallback zu Demo wenn keine Transaktionen von FinAPI
#             if imported_count == 0:
#                 logger.warning(f"⚠️ No transactions from FinAPI, using DEMO data as fallback")
#                 imported_count = finapi_service.sync_transactions(db, account, days_back)
#         else:
#             # Demo-Modus: Generiere Demo-Transaktionen
#             logger.info(f"📊 Using DEMO mode for account {account_id}")
#             imported_count = finapi_service.sync_transactions(db, account, days_back)
#         
#         # Erweiteter automatischer Abgleich mit IBAN + Levenshtein
#         match_stats = auto_match_transactions(db, current_user.id, account_id, min_confidence=80.0)
#         
#         logger.info(f"✅ Sync complete: {imported_count} imported, {match_stats['matched']} auto-matched")
#         
#         return {
#             "imported": imported_count,
#             "auto_matched": match_stats["matched"],
#             "multiple_candidates": match_stats["multiple_candidates"],
#             "no_match": match_stats["no_match"],
#             "message": f"{imported_count} Transaktionen importiert, {match_stats['matched']} automatisch zugeordnet"
#         }
#         
#     except Exception as e:
#         logger.error(f"Sync failed: {str(e)}")
#         import traceback
#         logger.error(traceback.format_exc())
#         raise HTTPException(status_code=500, detail="Synchronisation fehlgeschlagen")


# @router.post("/api/bank-transactions/{transaction_id}/auto-match", response_model=dict)
# def auto_match_transaction(
#     transaction_id: str,
#     current_user: User = Depends(get_current_user),
#     db: Session = Depends(get_db)
# ):
#     """
#     Automatische Zuordnung einer Transaktion zu Sollbuchungen
#     """
#     # Prüfe ob Transaktion existiert und dem User gehört
#     transaction = db.query(BankTransaction).filter(
#         BankTransaction.id == transaction_id,
#         BankTransaction.bank_account.has(owner_id=current_user.id)
#     ).first()
#     
#     if not transaction:
#         raise HTTPException(status_code=404, detail="Transaktion nicht gefunden")
#     
#     if transaction.is_matched:
#         raise HTTPException(status_code=400, detail="Transaktion bereits zugeordnet")
#     
#     try:
#         # Führe automatisches Matching durch
#         matches_found, matched_amount = finapi_service.auto_match_single_transaction(
#             db, transaction, current_user.id
#         )
#         
#         logger.info(f"🤖 Auto match for transaction {transaction_id}: {matches_found} matches, {matched_amount} €")
#         
#         return {
#             "status": "success",
#             "transaction_id": transaction_id,
#             "matches_found": matches_found,
#             "matched_amount": matched_amount,
#             "message": f"Automatische Zuordnung abgeschlossen: {matches_found} Matches gefunden"
#         }
#         
#     except Exception as e:
#         logger.error(f"Auto match failed for transaction {transaction_id}: {str(e)}")
#         import traceback
#         logger.error(traceback.format_exc())
#         raise HTTPException(status_code=500, detail="Automatische Zuordnung fehlgeschlagen")


# @router.get("/api/banks")
# def get_available_banks(
#     current_user: User = Depends(get_current_user)
# ):
#     """
#     Hole verfügbare Banken von FinAPI
#     """
#     if not real_finapi_service.is_configured():
#         return {
#             "status": "demo",
#             "message": "FinAPI nicht konfiguriert - Demo-Modus",
#             "banks": []
#         }
#     
#     try:
#         banks = real_finapi_service.get_banks()
#         
#         # Filtere nur deutsche Banken für bessere UX
#         german_banks = [
#             bank for bank in banks 
#             if bank.get('name', '').lower() in [
#                 'sparkasse', 'postbank', 'commerzbank', 'deutsche bank', 
#                 'n26', 'ing', 'dkb', 'volksbank', 'hypovereinsbank'
#             ]
#         ]
#         
#         return {
#             "status": "success",
#             "message": f"{len(german_banks)} deutsche Banken verfügbar",
#             "banks": german_banks[:20]  # Limitiere auf 20 für Performance
#         }
#         
#     except Exception as e:
#         logger.error(f"Failed to get banks: {str(e)}")
#         raise HTTPException(status_code=500, detail=str(e))


# @router.post("/api/bank-accounts/{account_id}/connect-finapi", response_model=dict)
# def connect_to_finapi(
#     account_id: str,
#     current_user: User = Depends(get_current_user),
#     db: Session = Depends(get_db)
# ):
#     """
#     Starte ECHTE FinAPI-Verbindung für dieses Konto
#     
#     Flow:
#     1. Erstelle FinAPI-User (falls noch nicht vorhanden)
#     2. Hole User Access Token
#     3. Starte Bank Connection Import (Web Form)
#     4. Gebe Web Form URL zurück → Frontend öffnet diese
#     5. User authentifiziert sich bei seiner ECHTEN Bank
#     6. FinAPI validiert alles und speichert Verbindung
#     """
#     account = db.query(BankAccount).filter(
#         BankAccount.id == account_id,
#         BankAccount.owner_id == current_user.id
#     ).first()
#     
#     if not account:
#         raise HTTPException(status_code=404, detail="Konto nicht gefunden")
#     
#     # Prüfe ob FinAPI konfiguriert ist
#     if not finapi_service.is_configured():
#         # DEMO-MODUS
#         logger.info(f"Demo mode: Simulating connection for {account_id}")
#         account.finapi_account_id = f"DEMO_finapi_{account.id[:8]}"
#         account.last_sync = date.today()
#         db.commit()
#         
#         return {
#             "status": "demo",
#             "message": "⚠️ DEMO-MODUS: Verbindung simuliert",
#             "info": "Keine echte Bankverbindung. FinAPI-Credentials fehlen.",
#             "redirect_url": None
#         }
#     
#     # === ECHTER FinAPI-Flow ===
#     logger.info(f"🚀 Starting REAL FinAPI connection for account {account_id}")
#     
#     try:
#         # Schritt 1: FinAPI-User erstellen/holen
#         finapi_password = f"secure_{current_user.id}_{account.id[:8]}"
#         user_result = finapi_service.create_user_in_finapi(current_user.email, finapi_password)
#         
#         if not user_result:
#             raise HTTPException(status_code=500, detail="FinAPI User konnte nicht erstellt werden")
#         
#         # Schritt 2: User Token holen
#         user_token = finapi_service.get_user_token(current_user.email, finapi_password)
#         
#         if not user_token:
#             raise HTTPException(status_code=500, detail="FinAPI User Token konnte nicht abgerufen werden")
#         
#         # Schritt 3: Bank Connection Import starten
#         web_form_data = finapi_service.start_bank_connection_import(user_token)
#         
#         if not web_form_data or not web_form_data.get("location"):
#             raise HTTPException(status_code=500, detail="Web Form konnte nicht gestartet werden")
#         
#         # Speichere FinAPI-Token für späteren Zugriff
#         account.finapi_access_token = user_token
#         db.commit()
#         
#         logger.info(f"✅ Web Form URL generiert: {web_form_data['location'][:50]}...")
#         
#         return {
#             "status": "redirect",
#             "message": "🚀 FinAPI Web Form bereit!",
#             "info": "Sie werden zur Bank-Auswahl weitergeleitet. Wählen Sie Ihre echte Bank und loggen Sie sich ein.",
#             "redirect_url": web_form_data["location"],
#             "web_form_id": web_form_data.get("id")
#         }
#         
#     except HTTPException:
#         raise
#     except Exception as e:
#         logger.error(f"❌ FinAPI connection failed: {str(e)}")
#         raise HTTPException(
#             status_code=500,
#             detail=f"FinAPI-Verbindung fehlgeschlagen: {str(e)}"
#         )


# ========= Erweiterte Zahlungsabgleich-Endpunkte =========

@router.get("/api/bank/unmatched", response_model=dict)
def get_unmatched_transactions(
    bank_account_id: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Hole alle nicht zugeordneten Transaktionen mit Match-Vorschlägen
    """
    try:
        # Hole ungematchte Transaktionen
        query = db.query(BankTransaction).join(BankAccount).filter(
            BankAccount.owner_id == current_user.id,
            BankTransaction.is_matched == False,
            BankTransaction.amount > 0  # Nur Eingänge
        )
        
        if bank_account_id:
            query = query.filter(BankTransaction.bank_account_id == bank_account_id)
        
        total = query.count()
        offset = (page - 1) * page_size
        transactions = query.order_by(
            BankTransaction.transaction_date.desc()
        ).offset(offset).limit(page_size).all()
        
        # Füge Match-Vorschläge für jede Transaktion hinzu
        result_items = []
        for trans in transactions:
            suggestions = get_match_suggestions(db, trans.id, current_user.id, min_confidence=50.0)
            
            result_items.append({
                "transaction": BankTransactionOut.model_validate(trans),
                "suggestions": suggestions[:5],  # Top 5 Vorschläge
                "suggestion_count": len(suggestions)
            })
        
        return {
            "items": result_items,
            "page": page,
            "page_size": page_size,
            "total": total
        }
        
    except Exception as e:
        logger.error(f"Failed to get unmatched transactions: {str(e)}")
        raise HTTPException(status_code=500, detail="Fehler beim Laden der Transaktionen")


@router.post("/api/bank/manual-match", response_model=dict, status_code=201)
def manual_match_transaction(
    transaction_id: str,
    charge_id: str,
    matched_amount: Optional[Decimal] = None,
    note: Optional[str] = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Manuelle Zuordnung einer Transaktion zu einer Sollbuchung
    """
    try:
        # Prüfe Transaction-Zugehörigkeit
        transaction = db.query(BankTransaction).join(BankAccount).filter(
            BankTransaction.id == transaction_id,
            BankAccount.owner_id == current_user.id
        ).first()
        
        if not transaction:
            raise HTTPException(status_code=404, detail="Transaktion nicht gefunden")
        
        # Prüfe Charge-Zugehörigkeit
        charge = db.query(Charge).join(BillRun).filter(
            Charge.id == charge_id,
            BillRun.owner_id == current_user.id
        ).first()
        
        if not charge:
            raise HTTPException(status_code=404, detail="Sollbuchung nicht gefunden")
        
        # Berechne matched_amount wenn nicht angegeben
        if matched_amount is None:
            remaining_charge = charge.amount - charge.paid_amount
            remaining_transaction = transaction.amount - transaction.matched_amount
            matched_amount = min(remaining_charge, remaining_transaction)
        
        # Validierung
        remaining_charge = charge.amount - charge.paid_amount
        remaining_transaction = transaction.amount - transaction.matched_amount
        
        if matched_amount > remaining_charge:
            raise HTTPException(
                status_code=400,
                detail=f"Betrag zu hoch. Verbleibend in Sollbuchung: {remaining_charge}€"
            )
        
        if matched_amount > remaining_transaction:
            raise HTTPException(
                status_code=400,
                detail=f"Betrag zu hoch. Verbleibend in Transaktion: {remaining_transaction}€"
            )
        
        # Erstelle PaymentMatch
        payment_match = PaymentMatch(
            transaction_id=transaction_id,
            charge_id=charge_id,
            matched_amount=matched_amount,
            is_automatic=False,  # Manuell zugeordnet
            note=note or "Manuell zugeordnet"
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
        
        db.commit()
        db.refresh(payment_match)
        
        logger.info(f"Manual match created: Transaction {transaction_id} → Charge {charge_id} ({matched_amount}€)")
        
        return {
            "status": "success",
            "match_id": payment_match.id,
            "matched_amount": float(matched_amount),
            "charge_status": charge.status.value,
            "transaction_matched": transaction.is_matched,
            "message": "Zahlung erfolgreich zugeordnet"
        }
        
    except HTTPException:
        raise
    except SQLAlchemyError as e:
        db.rollback()
        logger.error(f"Manual match failed: {str(e)}")
        raise HTTPException(status_code=500, detail="Fehler beim Zuordnen")


@router.get("/api/bank/match-suggestions/{transaction_id}", response_model=dict)
def get_transaction_match_suggestions(
    transaction_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Hole Match-Vorschläge für eine spezifische Transaktion
    """
    try:
        # Prüfe ob Transaktion existiert und dem User gehört
        transaction = db.query(BankTransaction).join(BankAccount).filter(
            BankTransaction.id == transaction_id,
            BankAccount.owner_id == current_user.id
        ).first()
        
        if not transaction:
            raise HTTPException(status_code=404, detail="Transaktion nicht gefunden")
        
        # Hole Vorschläge
        suggestions = get_match_suggestions(db, transaction_id, current_user.id, min_confidence=30.0)
        
        return {
            "transaction_id": transaction_id,
            "suggestions": suggestions,
            "count": len(suggestions)
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get suggestions: {str(e)}")
        raise HTTPException(status_code=500, detail="Fehler beim Laden der Vorschläge")


@router.post("/api/bank/auto-match-all", response_model=dict)
def trigger_auto_match_all(
    bank_account_id: Optional[str] = None,
    min_confidence: float = Query(80.0, ge=0.0, le=100.0),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Triggere automatischen Abgleich für alle ungematchten Transaktionen
    
    Trial users: max 1 match operation
    Paid users: unlimited
    """
    # Check match limit for trial users
    check_match_limit(current_user, db)
    
    try:
        # Validiere Bank Account falls angegeben
        if bank_account_id:
            account = db.query(BankAccount).filter(
                BankAccount.id == bank_account_id,
                BankAccount.owner_id == current_user.id
            ).first()
            
            if not account:
                raise HTTPException(status_code=404, detail="Konto nicht gefunden")
        
        # Führe Auto-Match durch
        match_stats = auto_match_transactions(
            db,
            current_user.id,
            bank_account_id,
            min_confidence
        )
        
        logger.info(f"Manual auto-match trigger: {match_stats}")
        
        return {
            "status": "success",
            "matched": match_stats["matched"],
            "no_match": match_stats["no_match"],
            "multiple_candidates": match_stats["multiple_candidates"],
            "total_processed": match_stats["total_processed"],
            "message": f"{match_stats['matched']} Transaktionen automatisch zugeordnet"
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Auto-match trigger failed: {str(e)}")
        raise HTTPException(status_code=500, detail="Automatischer Abgleich fehlgeschlagen")


# ========= CSV Upload =========

@router.post("/api/bank/upload-csv", response_model=dict)
async def upload_csv_transactions(
    files: List[UploadFile] = File(...),
    bank_account_id: Optional[str] = Query(None, description="Bankkonto ID (optional, wird erstellt falls nicht vorhanden)"),
    account_name: Optional[str] = Query(None, description="Kontoname (wird benötigt wenn bank_account_id nicht angegeben)"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Lade CSV-Dateien mit Transaktionen hoch und importiere sie
    
    Trial users: max 1 CSV file
    Paid users: unlimited
    
    CSV-Format erwartet (flexibel):
    - Datum: date, transaction_date, buchungsdatum, datum (Format: YYYY-MM-DD oder DD.MM.YYYY)
    - Betrag: amount, betrag, wert (Format: Dezimalzahl, z.B. 123.45 oder 123,45)
    - Verwendungszweck: purpose, verwendungszweck, beschreibung, text, memo
    - Empfänger/Absender: counterpart_name, name, empfaenger, absender
    - IBAN: counterpart_iban, iban
    
    Falls kein bank_account_id angegeben wird, wird ein neues Konto erstellt.
    """
    if not files:
        raise HTTPException(status_code=400, detail="Keine Dateien hochgeladen")
    
    # Check CSV upload limit for trial users
    check_csv_upload_limit(current_user, db)
    
    try:
        # Bestimme oder erstelle Bankkonto
        if bank_account_id:
            account = db.query(BankAccount).filter(
                BankAccount.id == bank_account_id,
                BankAccount.owner_id == current_user.id
            ).first()
            if not account:
                raise HTTPException(status_code=404, detail="Bankkonto nicht gefunden")
        else:
            # Erstelle neues Bankkonto
            if not account_name:
                account_name = f"CSV Import {datetime.now().strftime('%Y-%m-%d')}"
            
            account = BankAccount(
                owner_id=current_user.id,
                account_name=account_name,
                bank_name="CSV Import",
                is_active=True
            )
            db.add(account)
            db.flush()  # Um die ID zu bekommen
        
        total_imported = 0
        total_errors = 0
        file_results = []
        
        # Verarbeite jede Datei EINZELN, damit Fehler bei einer Datei nicht alle anderen verhindern
        for file in files:
            # Case-insensitive Prüfung der Dateiendung
            if not file.filename.lower().endswith('.csv'):
                total_errors += 1
                file_results.append({
                    "filename": file.filename,
                    "status": "error",
                    "message": "Nur CSV-Dateien werden unterstützt"
                })
                continue
            
            # Lese Datei-Inhalt ZUERST
            contents = None
            try:
                contents = await file.read()
                logger.info(f"📄 Datei {file.filename} gelesen: {len(contents)} Bytes")
            except Exception as read_error:
                logger.error(f"❌ Konnte Datei {file.filename} nicht lesen: {str(read_error)}")
                file_results.append({
                    "filename": file.filename,
                    "status": "error",
                    "message": f"Datei konnte nicht gelesen werden: {str(read_error)}"
                })
                continue
            
            # Versuche CSV zu parsen
            csv_data_rows = []
            all_headers = []
            imported = 0
            errors = 0
            
            try:
                # Lese CSV-Datei - KEINE VALIDIERUNG, einfach ALLES speichern!
                csv_content = decode_file_content(contents, file.filename)
                
                # Erkenne automatisch das Trennzeichen (Komma oder Semikolon)
                # Prüfe die erste Zeile auf beide Trennzeichen
                first_line = csv_content.split('\n')[0] if '\n' in csv_content else csv_content.split('\r\n')[0] if '\r\n' in csv_content else csv_content
                delimiter = ','
                if ';' in first_line:
                    # Zähle Vorkommen von Semikolon und Komma
                    semicolon_count = first_line.count(';')
                    comma_count = first_line.count(',')
                    if semicolon_count > comma_count:
                        delimiter = ';'
                        logger.info(f"🔍 Erkanntes Trennzeichen: Semikolon (;) für {file.filename}")
                    else:
                        logger.info(f"🔍 Erkanntes Trennzeichen: Komma (,) für {file.filename}")
                else:
                    logger.info(f"🔍 Verwende Standard-Trennzeichen: Komma (,) für {file.filename}")
                
                # Parse CSV mit erkanntem Trennzeichen
                csv_reader = csv.DictReader(io.StringIO(csv_content), delimiter=delimiter)
                
                # Lese alle Zeilen
                rows = list(csv_reader)
                all_headers = list(csv_reader.fieldnames) if csv_reader.fieldnames else []
                
                logger.info(f"📊 CSV {file.filename}: {len(rows)} Zeilen, {len(all_headers)} Spalten")
                
                # Speichere ALLE Zeilen roh
                for row in rows:
                    row_data = {
                        "imported": False,
                        "raw_data": {}
                    }
                    for header in all_headers:
                        row_data["raw_data"][header] = row.get(header, "")
                    csv_data_rows.append(row_data)
                    
            except Exception as parse_error:
                logger.warning(f"⚠️ Fehler beim Parsen von {file.filename}: {str(parse_error)}")
                # Versuche es nochmal mit Semikolon, falls Komma fehlgeschlagen hat
                try:
                    csv_content = decode_file_content(contents, file.filename)
                    csv_reader = csv.DictReader(io.StringIO(csv_content), delimiter=';')
                    rows = list(csv_reader)
                    all_headers = list(csv_reader.fieldnames) if csv_reader.fieldnames else []
                    
                    logger.info(f"📊 CSV {file.filename} (Semikolon): {len(rows)} Zeilen, {len(all_headers)} Spalten")
                    
                    for row in rows:
                        row_data = {
                            "imported": False,
                            "raw_data": {}
                        }
                        for header in all_headers:
                            row_data["raw_data"][header] = row.get(header, "")
                        csv_data_rows.append(row_data)
                except Exception as parse_error2:
                    logger.error(f"❌ Beide Parsing-Versuche fehlgeschlagen für {file.filename}: {str(parse_error2)}")
                    csv_data_rows = [{"error": f"Datei konnte nicht geparst werden: {str(parse_error2)}"}]
                    all_headers = []
            
            # Speichere CSV-Datei in Datenbank - IMMER! Mit eigenem Transaction
            try:
                logger.info(f"💾 Speichere CSV-Datei {file.filename} für User {current_user.id}...")
                
                # Erstelle neue Session für diese Datei, damit Fehler nicht alle anderen verhindern
                csv_file = CsvFile(
                    owner_id=current_user.id,
                    bank_account_id=account.id,
                    filename=file.filename,
                    file_size=len(contents),
                    row_count=len(csv_data_rows),
                    csv_data=json.dumps(csv_data_rows, ensure_ascii=False),
                    column_mapping=json.dumps({"headers": all_headers}, ensure_ascii=False)
                )
                db.add(csv_file)
                db.flush()
                csv_file_id = csv_file.id
                logger.info(f"📝 CSV-Datei hinzugefügt, ID: {csv_file_id}, Owner: {current_user.id}")
                
                # ERSTELLE POSTGRESQL-TABELLE für CSV-Daten - EINFACH!
                from ..utils.csv_table_manager import create_and_fill_csv_table
                
                logger.info(f"🔄 Transformiere CSV zu PostgreSQL-Tabelle...")
                table_name = create_and_fill_csv_table(
                    db, csv_file_id, file.filename, all_headers, csv_data_rows
                )
                
                if table_name:
                    # Speichere Tabellenname in CsvFile
                    csv_file.table_name = table_name
                    logger.info(f"✅ CSV als PostgreSQL-Tabelle gespeichert: {table_name}")
                else:
                    logger.warning(f"⚠️ Konnte Tabelle nicht erstellen")
                db.commit()
                
                logger.info(f"✅ CSV-Datei COMMITTED: {file.filename}, ID: {csv_file_id}, User: {current_user.id}")
                
                # WICHTIG: Expire alle Objekte, damit wir eine frische Query machen
                db.expire_all()
                
                # Verifiziere sofort in neuer Query - mit expliziter Session
                verify_file = db.query(CsvFile).filter(
                    CsvFile.id == csv_file_id,
                    CsvFile.owner_id == current_user.id
                ).first()
                
                if verify_file:
                    logger.info(f"✅ VERIFIZIERT: CSV-Datei {csv_file_id} ist in der DB für User {current_user.id}")
                else:
                    logger.error(f"❌ FEHLER: CSV-Datei {csv_file_id} wurde NICHT gefunden nach Commit!")
                    # Versuche nochmal ohne Filter
                    all_files = db.query(CsvFile).all()
                    logger.error(f"🔍 DEBUG: Gesamt CSV-Dateien in DB: {len(all_files)}")
                    if all_files:
                        logger.error(f"🔍 DEBUG: IDs: {[f.id for f in all_files]}")
                        logger.error(f"🔍 DEBUG: Owner-IDs: {[f.owner_id for f in all_files]}")
                
                file_results.append({
                    "filename": file.filename,
                    "status": "success",
                    "imported": imported,
                    "errors": errors,
                    "csv_file_id": csv_file_id,  # Verwende die gespeicherte ID
                    "rows_saved": len(csv_data_rows),
                    "columns": all_headers
                })
                
            except Exception as save_error:
                total_errors += 1
                logger.error(f"❌ FEHLER beim Speichern von {file.filename}: {str(save_error)}")
                import traceback
                logger.error(traceback.format_exc())
                db.rollback()  # Rollback nur für diese Datei
                file_results.append({
                    "filename": file.filename,
                    "status": "error",
                    "message": f"Datei konnte nicht gespeichert werden: {str(save_error)}"
                })
        
        # Aktualisiere last_sync
        try:
            account.last_sync = date.today()
            db.commit()
        except Exception as e:
            logger.warning(f"Konnte last_sync nicht aktualisieren: {str(e)}")
            db.rollback()
        
        logger.info(f"✅ CSV Import abgeschlossen: {total_imported} Transaktionen importiert aus {len(files)} Dateien")
        
        # Prüfe, wie viele CSV-Dateien gespeichert wurden - mit frischer Query
        try:
            csv_files_count = db.query(CsvFile).filter(
                CsvFile.owner_id == current_user.id
            ).count()
            logger.info(f"📊 CSV-Dateien in DB für User {current_user.id}: {csv_files_count} (gesamt)")
            
            # Prüfe auch für das spezifische Konto
            account_csv_count = db.query(CsvFile).filter(
                CsvFile.owner_id == current_user.id,
                CsvFile.bank_account_id == account.id
            ).count()
            logger.info(f"📊 CSV-Dateien für Konto {account.id}: {account_csv_count}")
            
            # Liste alle CSV-Dateien für Debugging
            all_csv_files = db.query(CsvFile).filter(
                CsvFile.owner_id == current_user.id
            ).all()
            logger.info(f"📋 Alle CSV-Dateien für User {current_user.id}: {[(f.id, f.filename) for f in all_csv_files]}")
        except Exception as e:
            logger.error(f"Fehler beim Zählen der CSV-Dateien: {str(e)}")
            csv_files_count = 0
        
        # KEIN automatischer Abgleich mehr - CSV wird nur hochgeladen
        logger.info(f"✅ CSV-Upload erfolgreich abgeschlossen. {csv_files_count} Datei(en) gespeichert.")
        
        return {
            "status": "success",
            "account_id": account.id,
            "account_name": account.account_name,
            "total_imported": total_imported,
            "total_errors": total_errors,
            "files": file_results,
            "csv_files_saved": csv_files_count,
            "auto_matched": 0,
            "message": f"{len(files)} CSV-Datei(en) erfolgreich hochgeladen und gespeichert. Sie können jetzt den Abgleich manuell durchführen."
        }
        
    except HTTPException:
        raise
    except Exception as e:
        # KEIN Rollback hier - CSV-Dateien wurden bereits einzeln committed!
        logger.error(f"CSV Upload fehlgeschlagen (aber Dateien wurden bereits gespeichert): {str(e)}")
        import traceback
        logger.error(traceback.format_exc())
        
        # Prüfe trotzdem, ob Dateien gespeichert wurden
        try:
            csv_files_count = db.query(CsvFile).filter(
                CsvFile.owner_id == current_user.id
            ).count()
            logger.info(f"📊 CSV-Dateien in DB trotz Fehler: {csv_files_count}")
        except:
            pass
        
        raise HTTPException(status_code=500, detail=f"Fehler beim CSV-Upload: {str(e)}")


@router.post("/api/bank/test-csv-save", response_model=dict)
def test_csv_save(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """TEST: Speichere eine Test-CSV-Datei direkt"""
    try:
        # Erstelle Test-Konto falls nicht vorhanden
        account = db.query(BankAccount).filter(
            BankAccount.owner_id == current_user.id,
            BankAccount.account_name.like("CSV Import%")
        ).first()
        
        if not account:
            account = BankAccount(
                owner_id=current_user.id,
                account_name="CSV Import Test",
                bank_name="CSV Import",
                is_active=True
            )
            db.add(account)
            db.flush()
        
        # Erstelle Test-CSV-Datei
        test_data = [{"raw_data": {"test": "wert1", "test2": "wert2"}, "imported": False}]
        csv_file = CsvFile(
            owner_id=current_user.id,
            bank_account_id=account.id,
            filename="test.csv",
            file_size=100,
            row_count=1,
            csv_data=json.dumps(test_data, ensure_ascii=False),
            column_mapping=json.dumps({"headers": ["test", "test2"]}, ensure_ascii=False)
        )
        db.add(csv_file)
        db.flush()
        logger.info(f"TEST: CSV-Datei hinzugefügt, ID: {csv_file.id}")
        
        db.commit()
        logger.info(f"TEST: CSV-Datei COMMITTED, ID: {csv_file.id}")
        
        # Verifiziere
        verify = db.query(CsvFile).filter(CsvFile.id == csv_file.id).first()
        if verify:
            logger.info(f"TEST: ✅ CSV-Datei {csv_file.id} ist in der DB")
            return {"status": "success", "csv_file_id": csv_file.id, "message": "Test-CSV-Datei gespeichert"}
        else:
            logger.error(f"TEST: ❌ CSV-Datei {csv_file.id} wurde NICHT gefunden!")
            return {"status": "error", "message": "CSV-Datei wurde nicht gefunden nach Commit"}
            
    except Exception as e:
        logger.error(f"TEST Fehler: {str(e)}")
        import traceback
        logger.error(traceback.format_exc())
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Test fehlgeschlagen: {str(e)}")


@router.get("/api/bank/csv-files", response_model=dict)
def list_csv_files(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Liste aller hochgeladenen CSV-Dateien"""
    try:
        # Prüfe ALLE CSV-Dateien in der DB (für Debugging)
        all_csv_files_in_db = db.query(CsvFile).all()
        logger.info(f"🔍 DEBUG: Gesamt CSV-Dateien in DB: {len(all_csv_files_in_db)}")
        if all_csv_files_in_db:
            logger.info(f"🔍 DEBUG: User-IDs: {[f.owner_id for f in all_csv_files_in_db]}")
        
        csv_files = db.query(CsvFile).filter(
            CsvFile.owner_id == current_user.id
        ).order_by(CsvFile.created_at.desc()).all()
        
        logger.info(f"📋 CSV-Dateien für User {current_user.id}: {len(csv_files)} Dateien gefunden")
        
        result = {
            "files": [
                {
                    "id": f.id,
                    "filename": f.filename,
                    "file_size": f.file_size,
                    "row_count": f.row_count,
                    "bank_account_id": f.bank_account_id,
                    "table_name": f.table_name,  # NEU: Zeige Tabellenname
                    "created_at": f.created_at.isoformat(),
                    "updated_at": f.updated_at.isoformat()
                }
                for f in csv_files
            ],
            "total": len(csv_files)
        }
        
        logger.info(f"✅ CSV-Dateien-Liste zurückgegeben: {result['total']} Dateien")
        return result
    except Exception as e:
        logger.error(f"Fehler beim Laden der CSV-Dateien: {str(e)}")
        import traceback
        logger.error(traceback.format_exc())
        raise HTTPException(status_code=500, detail=f"Fehler beim Laden der CSV-Dateien: {str(e)}")


@router.get("/api/bank/csv-files/{csv_file_id}/table-data", response_model=dict)
def get_csv_table_data(
    csv_file_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    limit: int = Query(10, ge=1, le=100)
):
    """DEBUG: Zeige Daten aus PostgreSQL-Tabelle für CSV-Datei"""
    try:
        csv_file = db.query(CsvFile).filter(
            CsvFile.id == csv_file_id,
            CsvFile.owner_id == current_user.id
        ).first()
        
        if not csv_file:
            raise HTTPException(status_code=404, detail="CSV-Datei nicht gefunden")
        
        if not csv_file.table_name:
            return {
                "csv_file_id": csv_file_id,
                "filename": csv_file.filename,
                "table_name": None,
                "message": "Keine PostgreSQL-Tabelle vorhanden",
                "rows": [],
                "row_count": csv_file.row_count,
                "column_mapping": csv_file.column_mapping
            }
        
        # Prüfe ob Tabelle existiert
        from sqlalchemy import inspect, text
        inspector = inspect(db.bind)
        table_exists = csv_file.table_name in inspector.get_table_names()
        
        if not table_exists:
            return {
                "csv_file_id": csv_file_id,
                "filename": csv_file.filename,
                "table_name": csv_file.table_name,
                "message": f"⚠️ Tabelle {csv_file.table_name} existiert nicht in PostgreSQL!",
                "rows": [],
                "available_tables": [t for t in inspector.get_table_names() if 'csv_data' in t][:10]
            }
        
        # Zähle Zeilen in Tabelle
        count_sql = f"SELECT COUNT(*) as count FROM {csv_file.table_name} WHERE csv_file_id = :csv_file_id"
        count_result = db.execute(text(count_sql), {"csv_file_id": csv_file_id})
        table_row_count = count_result.fetchone()[0] if count_result else 0
        
        # Lese Daten aus Tabelle
        from ..utils.csv_table_manager import query_csv_table
        rows = query_csv_table(db, csv_file.table_name, csv_file_id)
        
        # Limitiere auf erste N Zeilen
        limited_rows = rows[:limit]
        
        # Hole Spalten-Info
        if rows:
            columns = list(rows[0].keys())
        else:
            # Versuche Spalten direkt aus Tabelle zu holen
            columns_sql = f"""
            SELECT column_name 
            FROM information_schema.columns 
            WHERE table_name = :table_name
            ORDER BY ordinal_position
            """
            col_result = db.execute(text(columns_sql), {"table_name": csv_file.table_name})
            columns = [row[0] for row in col_result]
        
        return {
            "csv_file_id": csv_file_id,
            "filename": csv_file.filename,
            "table_name": csv_file.table_name,
            "table_exists": table_exists,
            "table_row_count": table_row_count,
            "csv_file_row_count": csv_file.row_count,
            "total_rows": len(rows),
            "showing_rows": len(limited_rows),
            "columns": columns,
            "rows": limited_rows,
            "column_mapping": csv_file.column_mapping
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Fehler beim Lesen der Tabellen-Daten: {str(e)}")
        import traceback
        logger.error(traceback.format_exc())
        raise HTTPException(status_code=500, detail=f"Fehler: {str(e)}")


@router.get("/api/bank/csv-files/{csv_file_id}", response_model=dict)
def get_csv_file(
    csv_file_id: str,
    page: int = Query(1, ge=1),
    page_size: int = Query(15, ge=1, le=100),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Hole CSV-Datei mit Paginierung"""
    csv_file = db.query(CsvFile).filter(
        CsvFile.id == csv_file_id,
        CsvFile.owner_id == current_user.id
    ).first()
    
    if not csv_file:
        raise HTTPException(status_code=404, detail="CSV-Datei nicht gefunden")
    
    # Parse CSV-Daten
    csv_data = json.loads(csv_file.csv_data)
    column_mapping = json.loads(csv_file.column_mapping) if csv_file.column_mapping else {}
    
    # Paginierung
    total_rows = len(csv_data)
    total_pages = (total_rows + page_size - 1) // page_size
    start_idx = (page - 1) * page_size
    end_idx = start_idx + page_size
    paginated_data = csv_data[start_idx:end_idx]
    
    return {
        "id": csv_file.id,
        "filename": csv_file.filename,
        "file_size": csv_file.file_size,
        "row_count": csv_file.row_count,
        "column_mapping": column_mapping,
        "page": page,
        "page_size": page_size,
        "total_pages": total_pages,
        "total_rows": total_rows,
        "data": paginated_data
    }


@router.delete("/api/bank/csv-files/{csv_file_id}", status_code=204)
def delete_csv_file(
    csv_file_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Lösche CSV-Datei"""
    csv_file = db.query(CsvFile).filter(
        CsvFile.id == csv_file_id,
        CsvFile.owner_id == current_user.id
    ).first()
    
    if not csv_file:
        raise HTTPException(status_code=404, detail="CSV-Datei nicht gefunden")
    
    try:
        db.delete(csv_file)
        db.commit()
        logger.info(f"CSV-Datei gelöscht: {csv_file_id} von User {current_user.id}")
    except SQLAlchemyError as e:
        db.rollback()
        logger.error(f"Fehler beim Löschen der CSV-Datei: {str(e)}")
        raise HTTPException(status_code=500, detail="Fehler beim Löschen")


@router.post("/api/bank/csv-reconcile", response_model=dict)
def reconcile_csv_transactions(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    CSV-Abgleich: Nutzt direkt PostgreSQL-Tabellen und führt automatisches Matching durch
    
    Trial users: max 1 match operation
    Paid users: unlimited
    """
    # Check match limit for trial users
    check_match_limit(current_user, db)
    
    try:
        logger.info(f"🔄 Starte CSV-Abgleich für User {current_user.id}")
        
        # Hole alle CSV-Dateien des Users MIT PostgreSQL-Tabellen
        csv_files = db.query(CsvFile).filter(
            CsvFile.owner_id == current_user.id,
            CsvFile.table_name.isnot(None)  # Nur CSV-Dateien mit Tabellen
        ).all()
        
        if not csv_files:
            return {
                "status": "info",
                "message": "Keine CSV-Dateien mit PostgreSQL-Tabellen gefunden",
                "processed": 0,
                "matched": 0,
                "errors": 0
            }
        
        logger.info(f"📋 {len(csv_files)} CSV-Datei(en) mit Tabellen gefunden")
        
        # Führe EINFACHEN Abgleich durch: CSV-Daten ↔ Tool-Daten
        from ..utils.simple_csv_matcher import simple_match_csv
        
        total_matched = 0
        total_processed = 0
        total_errors = 0
        all_details = []
        
        for csv_file in csv_files:
            try:
                logger.info(f"📄 Führe einfachen Abgleich mit CSV-Tabelle: {csv_file.table_name} ({csv_file.filename})")
                
                # Einfacher Abgleich: Direkter Vergleich
                csv_stats = simple_match_csv(
                    db, csv_file, current_user.id
                )
                
                total_matched += csv_stats.get("matched", 0)
                total_processed += csv_stats.get("processed", 0)
                total_errors += csv_stats.get("errors", 0)
                all_details.extend(csv_stats.get("details", []))
                
                logger.info(f"✅ {csv_file.filename}: {csv_stats.get('matched', 0)} von {csv_stats.get('processed', 0)} Zeilen zugeordnet")
                
            except Exception as file_error:
                logger.error(f"❌ Fehler beim Abgleich von {csv_file.filename}: {str(file_error)}")
                import traceback
                logger.error(traceback.format_exc())
                total_errors += 1
                continue
        
        logger.info(f"✅ CSV-Abgleich abgeschlossen: {total_processed} verarbeitet, {total_matched} zugeordnet, {total_errors} Fehler")
        
        return {
            "status": "success",
            "message": f"Abgleich abgeschlossen: {total_matched} von {total_processed} Transaktionen zugeordnet",
            "processed": total_processed,
            "matched": total_matched,
            "errors": total_errors,
            "details": all_details  # Details zu jedem Match
        }
        
    except Exception as e:
        db.rollback()
        logger.error(f"❌ Fehler beim CSV-Abgleich: {str(e)}")
        import traceback
        logger.error(traceback.format_exc())
        raise HTTPException(status_code=500, detail=f"Fehler beim CSV-Abgleich: {str(e)}")

