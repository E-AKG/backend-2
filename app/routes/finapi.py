"""
FinAPI WebForm 2.0 Integration
Automatische Bank-Verknüpfung über FinAPI
"""

import logging
import os
import requests
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from typing import Optional, List
from dotenv import load_dotenv
from sqlalchemy.orm import Session
from ..db import get_db
from ..models.bank import BankAccount, BankTransaction
from ..utils.deps import get_current_user
from ..models.user import User
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
import apscheduler.events
try:
    import pytz
except ImportError:
    pytz = None
    import logging
    logging.warning("pytz not installed, scheduler will use UTC timezone")

# Lade Umgebungsvariablen
load_dotenv()

# Konfiguriere Logger für dieses Modul (zuerst, damit Event Handler ihn nutzen können)
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)  # Stelle sicher, dass INFO-Level gesetzt ist

# Scheduler für täglichen Auto-Sync
scheduler = AsyncIOScheduler()

# Scheduler Event Handler für Debugging
def job_executed(event):
    logger.info(f"📋 Job ausgeführt: {event.job_id} - {event.exception if event.exception else 'Erfolg'}")
    if event.exception:
        logger.error(f"❌ Job-Fehler: {event.exception}")

def job_error(event):
    logger.error(f"❌ Job-Fehler: {event.job_id} - {event.exception}")

def job_missed(event):
    logger.warning(f"⚠️ Job verpasst: {event.job_id}")

# Füge Event Listener hinzu (nach Logger-Definition)
scheduler.add_listener(job_executed, apscheduler.events.EVENT_JOB_EXECUTED)
scheduler.add_listener(job_error, apscheduler.events.EVENT_JOB_ERROR)
scheduler.add_listener(job_missed, apscheduler.events.EVENT_JOB_MISSED)

router = APIRouter(prefix="/api/finapi", tags=["FinAPI"])


class WebFormResponse(BaseModel):
    webFormUrl: str
    webFormId: str
    status: str


class FinAPIService:
    """FinAPI Service für WebForm 2.0 Integration"""
    
    def __init__(self):
        self.base_url = "https://webform-sandbox.finapi.io"
        self.api_base_url = "https://sandbox.finapi.io/api/v2"
        self.client_id = os.getenv("FINAPI_CLIENT_ID")
        self.client_secret = os.getenv("FINAPI_CLIENT_SECRET")
        
        if not self.client_id or not self.client_secret:
            raise ValueError("FINAPI_CLIENT_ID und FINAPI_CLIENT_SECRET müssen in der .env-Datei gesetzt sein")
        
        logger.info(f"FinAPI Service initialisiert mit Client ID: {self.client_id[:20]}...")
    
    def get_client_token(self) -> str:
        """Hole Client Access Token (grant_type=client_credentials)"""
        try:
            logger.info("🔐 Schritt 1: Hole Client Token...")
            
            response = requests.post(
                f"{self.api_base_url}/oauth/token",
                data={
                    "grant_type": "client_credentials",
                    "client_id": self.client_id,
                    "client_secret": self.client_secret
                },
                headers={"Content-Type": "application/x-www-form-urlencoded"}
            )
            
            if response.status_code != 200:
                logger.error(f"❌ Client Token fehlgeschlagen: {response.status_code} - {response.text}")
                raise HTTPException(status_code=500, detail=f"Client Token konnte nicht geholt werden: {response.text}")
            
            client_token = response.json()["access_token"]
            logger.info(f"✅ Client Token erhalten: {client_token[:20]}...")
            
            return client_token
            
        except Exception as e:
            logger.error(f"❌ Fehler beim Holen des Client Tokens: {str(e)}")
            raise HTTPException(status_code=500, detail=str(e))
    
    def create_or_get_user(self, client_token: str, user_id: str = "demo-user", password: str = "demo-pass") -> str:
        """Erstelle Test-User (falls nicht vorhanden)"""
        try:
            logger.info(f"👤 Schritt 2: Prüfe/Erstelle User '{user_id}'...")
            
            # Versuche User zu erstellen
            response = requests.post(
                f"{self.api_base_url}/users",
                headers={
                    "Authorization": f"Bearer {client_token}",
                    "Content-Type": "application/json"
                },
                json={
                    "id": user_id,
                    "password": password
                }
            )
            
            if response.status_code in [200, 201]:
                logger.info(f"✅ User '{user_id}' wurde erstellt")
            elif response.status_code in [409, 422]:
                # 409 = Conflict, 422 = Entity already exists
                logger.info(f"✅ User '{user_id}' existiert bereits (Fehlercode: {response.status_code})")
            else:
                logger.warning(f"⚠️ User-Erstellung: {response.status_code} - {response.text}")
            
            return user_id
            
        except Exception as e:
            logger.error(f"❌ Fehler beim Erstellen/Prüfen des Users: {str(e)}")
            raise HTTPException(status_code=500, detail=str(e))
    
    def get_user_token(self, user_id: str, password: str) -> str:
        """Hole User Access Token (grant_type=password)"""
        try:
            logger.info(f"🔑 Schritt 3: Hole User Token für '{user_id}'...")
            
            response = requests.post(
                f"{self.api_base_url}/oauth/token",
                data={
                    "grant_type": "password",
                    "client_id": self.client_id,
                    "client_secret": self.client_secret,
                    "username": user_id,
                    "password": password
                },
                headers={"Content-Type": "application/x-www-form-urlencoded"}
            )
            
            if response.status_code != 200:
                logger.error(f"❌ User Token fehlgeschlagen: {response.status_code} - {response.text}")
                raise HTTPException(status_code=500, detail=f"User Token konnte nicht geholt werden: {response.text}")
            
            user_token = response.json()["access_token"]
            logger.info(f"✅ User Token erhalten: {user_token[:20]}...")
            
            return user_token
            
        except Exception as e:
            logger.error(f"❌ Fehler beim Holen des User Tokens: {str(e)}")
            raise HTTPException(status_code=500, detail=str(e))
    
    def create_webform(self, user_token: str) -> dict:
        """Erstelle FinAPI WebForm 2.0"""
        try:
            logger.info("🏦 Schritt 4: Erstelle FinAPI WebForm...")
            
            # WICHTIG: Bei UNLICENSED-Mandator KEIN redirectUrl!
            response = requests.post(
                f"{self.base_url}/api/webForms/bankConnectionImport",
                headers={
                    "Authorization": f"Bearer {user_token}",
                    "Content-Type": "application/json"
                },
                json={}
                # Leerer Payload - KEIN redirectUrl bei UNLICENSED!
            )
            
            if response.status_code not in [200, 201]:
                logger.error(f"❌ WebForm-Erstellung fehlgeschlagen: {response.status_code} - {response.text}")
                raise HTTPException(status_code=500, detail=f"WebForm konnte nicht erstellt werden: {response.text}")
            
            data = response.json()
            webform_url = data.get("url") or data.get("webFormUrl")
            webform_id = data.get("id") or data.get("webFormId")
            
            if not webform_url:
                logger.error(f"❌ Keine WebForm URL in der Response: {data}")
                raise HTTPException(status_code=500, detail="Keine WebForm URL erhalten")
            
            logger.info(f"✅ WebForm erstellt: {webform_url}")
            
            return {
                "webFormUrl": webform_url,
                "webFormId": webform_id or "unknown",
                "status": data.get("status", "created")
            }
            
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"❌ Fehler beim Erstellen der WebForm: {str(e)}")
            raise HTTPException(status_code=500, detail=str(e))
    
    def trigger_bank_connection_update(self, user_token: str, bank_connection_id: int) -> Optional[str]:
        """
        Triggere Bank Connection Update via WebForm 2.0 API
        POST /api/tasks/backgroundUpdate
        
        Returns task_id if successful, None otherwise
        """
        try:
            logger.info(f"🔄 Triggere Bank Connection Update für Connection ID {bank_connection_id}...")
            
            response = requests.post(
                f"{self.base_url}/api/tasks/backgroundUpdate",
                headers={
                    "Authorization": f"Bearer {user_token}",
                    "Content-Type": "application/json"
                },
                json={
                    "bankConnectionId": bank_connection_id
                }
            )
            
            if response.status_code == 201:
                task_data = response.json()
                task_id = task_data.get("id")
                logger.info(f"✅ Bank Connection Update Task erstellt: {task_id}")
                return task_id
            else:
                logger.error(f"❌ Bank Connection Update fehlgeschlagen: {response.status_code} - {response.text}")
                return None
            
        except Exception as e:
            logger.error(f"❌ Fehler beim Triggern des Bank Connection Updates: {str(e)}")
            return None


# Globale Instanz
finapi_service = FinAPIService()


@router.post("/callback")
async def finapi_callback(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    WebForm Callback - speichere Bank-Verbindungen in der Datenbank
    
    Wird nach erfolgreichem Abschluss der WebForm aufgerufen
    """
    try:
        logger.info(f"🔄 Starte Abruf der Bank-Verbindungen für User {current_user.id}...")
        
        # Hole User Token (demo-user für WebForm 2.0 Flow)
        # TODO: In Produktion sollte hier ein echter User erstellt/verwendet werden
        demo_user_id = "demo-user"
        demo_user_pass = "demo-pass"
        
        # Erstelle oder hole User ID von FinAPI
        client_token = finapi_service.get_client_token()
        user_id = finapi_service.create_or_get_user(client_token, demo_user_id, demo_user_pass)
        
        # Hole User Token
        user_token = finapi_service.get_user_token(user_id, demo_user_pass)
        
        if not user_token:
            raise HTTPException(status_code=500, detail="User Token konnte nicht geholt werden")
        
        # Hole Bank-Verbindungen von FinAPI
        response = requests.get(
            f"{finapi_service.api_base_url}/bankConnections",
            headers={
                "Authorization": f"Bearer {user_token}",
                "Content-Type": "application/json"
            }
        )
        
        if response.status_code != 200:
            logger.error(f"❌ Bank-Verbindungen konnten nicht geholt werden: {response.status_code} - {response.text}")
            raise HTTPException(status_code=500, detail="Bank-Verbindungen konnten nicht geholt werden")
        
        data = response.json()
        bank_connections = data.get("connections", [])
        
        logger.info(f"✅ {len(bank_connections)} Bank-Verbindungen gefunden")
        
        # Speichere Bank-Verbindungen in der Datenbank
        saved_count = 0
        
        for conn in bank_connections:
            conn_id = conn.get("id")  # FinAPI Bank Connection ID
            bank_name = conn.get("bank", {}).get("name", "Unknown Bank")
            account_ids = conn.get("accountIds", [])
            
            logger.info(f"📊 Speichere Bank-Verbindung: {bank_name} (ID: {conn_id}) mit {len(account_ids)} Account(s)")
            
            # Speichere jeden Account
            for account_id in account_ids:
                # Prüfe ob Account bereits existiert
                existing = db.query(BankAccount).filter(
                    BankAccount.finapi_account_id == str(account_id),
                    BankAccount.owner_id == current_user.id
                ).first()
                
                if existing:
                    logger.info(f"ℹ️ Account {account_id} existiert bereits")
                    # Aktualisiere Token, Credentials und Connection ID falls fehlen
                    updated = False
                    if not existing.finapi_user_id or not existing.finapi_user_password:
                        existing.finapi_access_token = user_token
                        existing.finapi_user_id = demo_user_id
                        existing.finapi_user_password = demo_user_pass
                        updated = True
                    if not existing.finapi_connection_id:
                        existing.finapi_connection_id = str(conn_id)
                        updated = True
                    if updated:
                        db.commit()
                        logger.info(f"✅ Token, Credentials und Connection ID für existierenden Account aktualisiert")
                    continue
                
                # Erstelle neue Bank-Verbindung
                bank_account = BankAccount(
                    owner_id=current_user.id,
                    account_name=f"{bank_name} - {account_id}",
                    bank_name=bank_name,
                    finapi_account_id=str(account_id),
                    finapi_connection_id=str(conn_id),  # Speichere Connection ID für Updates
                    finapi_access_token=user_token,
                    finapi_user_id=demo_user_id,  # Speichere User ID für Token-Refresh
                    finapi_user_password=demo_user_pass,  # Speichere Password für Token-Refresh
                    iban=None  # Wird später von FinAPI gefüllt
                )
                
                db.add(bank_account)
                saved_count += 1
                logger.info(f"💾 Gespeichert: {bank_name} Account {account_id}")
        
        db.commit()
        
        logger.info(f"✅ {saved_count} neue Accounts gespeichert")
        
        return {
            "success": True,
            "connections_found": len(bank_connections),
            "connections_saved": saved_count
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Fehler beim Speichern der Bank-Verbindungen: {str(e)}")
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/transactions/sync")
async def sync_transactions(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Sync Bank-Transaktionen von FinAPI
    
    Ruft für alle verknüpften Bank-Konten die Transaktionen ab und speichert sie
    """
    try:
        logger.info(f"🔄 Starte Transaktionen-Sync für User {current_user.id}...")
        
        # Hole alle Bank-Konten des Users
        bank_accounts = db.query(BankAccount).filter(
            BankAccount.owner_id == current_user.id,
            BankAccount.is_active == True
        ).all()
        
        if not bank_accounts:
            logger.info("ℹ️ Keine Bank-Konten gefunden")
            return {
                "success": True,
                "transactions_fetched": 0,
                "transactions_saved": 0,
                "message": "Keine Bank-Konten gefunden"
            }
        
        total_fetched = 0
        total_saved = 0
        
        logger.info(f"📊 Verarbeite {len(bank_accounts)} Bank-Account(s)")
        
        for bank_account in bank_accounts:
            logger.info(f"🔄 Verarbeite Account: {bank_account.account_name} (Bank: {bank_account.bank_name})")
            
            if not bank_account.finapi_account_id:
                logger.warning(f"⚠️ Account {bank_account.account_name} hat keine finapi_account_id")
                continue
            
            # Verwende gespeicherten Access Token vom Account, falls vorhanden, sonst hole neuen
            user_token = None
            
            if bank_account.finapi_access_token:
                user_token = bank_account.finapi_access_token
                logger.info(f"📊 Nutze gespeicherten Access Token für Bank: {bank_account.bank_name}")
            elif bank_account.finapi_user_id and bank_account.finapi_user_password:
                # Hole neuen Token mit gespeicherten Credentials
                logger.info(f"🔄 Hole neuen User Token für {bank_account.bank_name}")
                user_token = finapi_service.get_user_token(bank_account.finapi_user_id, bank_account.finapi_user_password)
                if user_token:
                    # Speichere neuen Token
                    bank_account.finapi_access_token = user_token
                    db.commit()
            else:
                # Fallback: Hole neuen Token mit demo-user
                logger.warning(f"⚠️ Keine Credentials für {bank_account.bank_name}, nutze demo-user")
                user_token = finapi_service.get_user_token("demo-user", "demo-pass")
                if not user_token:
                    logger.error(f"❌ User Token konnte nicht geholt werden für {bank_account.bank_name}")
                    continue
            
            try:
                logger.info(f"📊 Hole Transaktionen für Bank: {bank_account.bank_name}")
                logger.info(f"   Account ID: {bank_account.id}")
                logger.info(f"   FinAPI Account ID: {bank_account.finapi_account_id}")
                logger.info(f"   Last Sync: {bank_account.last_sync}")
                
                # Schritt 0: Triggere Bank Connection Update via WebForm 2.0 API
                # Dies holt neue Transaktionen von der Bank
                if bank_account.finapi_connection_id:
                    logger.info(f"🔄 Triggere Bank Connection Update für Connection ID {bank_account.finapi_connection_id}...")
                    task_id = finapi_service.trigger_bank_connection_update(user_token, int(bank_account.finapi_connection_id))
                    if task_id:
                        # Warte länger, damit FinAPI Zeit hat, die Daten von der Bank zu holen
                        import time
                        logger.info(f"⏳ Warte 15 Sekunden, damit FinAPI Transaktionen von der Bank laden kann...")
                        time.sleep(15)  # Erhöht von 5 auf 15 Sekunden
                    else:
                        logger.warning("⚠️ Update-Task konnte nicht erstellt werden, versuche trotzdem Transaktionen zu holen")
                else:
                    logger.info("ℹ️ Keine Connection ID vorhanden, überspringe Update-Trigger")
                
                # Schritt 1: Hole alle Accounts des Users
                logger.info(f"📊 Hole alle Accounts des Users...")
                
                accounts_response = requests.get(
                    f"{finapi_service.api_base_url}/accounts",
                    headers={
                        "Authorization": f"Bearer {user_token}",
                        "Content-Type": "application/json"
                    },
                    params={
                        "page": 1,
                        "perPage": 100
                    }
                )
                
                logger.info(f"   API Response Status: {accounts_response.status_code}")
                
                if accounts_response.status_code == 200:
                    accounts_data = accounts_response.json()
                    accounts_list = accounts_data.get("accounts", [])
                    logger.info(f"✅ {len(accounts_list)} Accounts gefunden")
                elif accounts_response.status_code == 401:
                    # Token ist abgelaufen, hole neuen Token
                    logger.warning(f"⚠️ Access Token abgelaufen für {bank_account.bank_name}, hole neuen Token...")
                    
                    if bank_account.finapi_user_id and bank_account.finapi_user_password:
                        # Hole neuen Token mit gespeicherten Credentials
                        user_token = finapi_service.get_user_token(bank_account.finapi_user_id, bank_account.finapi_user_password)
                        if user_token:
                            bank_account.finapi_access_token = user_token
                            db.commit()
                            logger.info(f"✅ Neuer Token erhalten, wiederhole Request...")
                            
                            # Wiederhole Request mit neuem Token
                            accounts_response = requests.get(
                                f"{finapi_service.api_base_url}/accounts",
                                headers={
                                    "Authorization": f"Bearer {user_token}",
                                    "Content-Type": "application/json"
                                },
                                params={
                                    "page": 1,
                                    "perPage": 100
                                }
                            )
                            
                            if accounts_response.status_code == 200:
                                accounts_data = accounts_response.json()
                                accounts_list = accounts_data.get("accounts", [])
                                logger.info(f"✅ {len(accounts_list)} Accounts gefunden")
                            else:
                                logger.error(f"❌ Wiederholter Request fehlgeschlagen: {accounts_response.status_code}")
                                continue
                        else:
                            logger.error(f"❌ Neuer Token konnte nicht geholt werden")
                            continue
                    else:
                        logger.error(f"❌ Keine Credentials für Token-Refresh vorhanden")
                        continue
                else:
                    logger.error(f"❌ Fehler beim Abrufen der Accounts: {accounts_response.status_code} - {accounts_response.text}")
                    continue
                
                if accounts_response.status_code == 200:
                    
                    if not accounts_list:
                        logger.warning(f"⚠️ Keine Accounts für Bank {bank_account.bank_name} gefunden")
                        continue
                    
                    # Schritt 2: Hole Transaktionen für jeden Account
                    account_transactions_count = 0  # Initialize outside loop
                    saved_for_account = 0
                    skipped_for_account = 0
                    
                    for account in accounts_list:
                        account_id = account.get("id")
                        
                        logger.info(f"📊 Hole Transaktionen für Account {account_id}...")
                        
                        # Hole Account-Details (könnte Transaktionen enthalten)
                        account_response = requests.get(
                            f"{finapi_service.api_base_url}/accounts/{account_id}",
                            headers={
                                "Authorization": f"Bearer {user_token}",
                                "Content-Type": "application/json"
                            }
                        )
                        
                        transactions = []
                        
                        if account_response.status_code == 200:
                            account_data = account_response.json()
                            logger.info(f"📊 Account {account_id}: {account_data.get('accountName', 'Unknown')}")
                            
                            # Versuche Transaktionen direkt vom Account zu holen
                            transactions = account_data.get("transactions", [])
                            
                            # Falls keine Transaktionen im Account, versuche separate API
                            if not transactions:
                                # Bestimme Datumsbereich basierend auf last_sync
                                from datetime import date, timedelta, datetime
                                
                                # Hole Transaktionen mit Datumsfilter bis heute
                                max_date = date.today()
                                
                                from_date = None
                                if bank_account.last_sync:
                                    # Lade ab dem Tag nach dem letzten Sync (+1 Tag um Überschneidungen zu vermeiden)
                                    from_date = bank_account.last_sync + timedelta(days=1)
                                    
                                    # Stelle sicher, dass from_date nicht in der Zukunft liegt
                                    if from_date > max_date:
                                        # Wenn last_sync heute oder in der Zukunft ist, lade die letzten 7 Tage
                                        from_date = max_date - timedelta(days=7)
                                        logger.warning(f"⚠️ last_sync ({bank_account.last_sync}) ist zu neu, lade letzte 7 Tage ab {from_date}")
                                    
                                    # Aber nicht älter als 90 Tage
                                    min_date = date.today() - timedelta(days=90)
                                    if from_date < min_date:
                                        from_date = min_date
                                    
                                    logger.info(f"📅 Using last_sync date: {bank_account.last_sync}, loading from: {from_date} to {max_date}")
                                else:
                                    # Kein last_sync, lade letzten 90 Tage
                                    from_date = date.today() - timedelta(days=90)
                                    logger.info(f"📅 No last_sync date, loading last 90 days from: {from_date} to {max_date}")
                                
                                page = 1
                                transactions = []
                                
                                while True:
                                    # Baue Parameter auf
                                    params = {
                                        "accountIds": account_id,
                                        "view": "userView",
                                        "page": page,
                                        "perPage": 500,  # Maximale Anzahl pro Seite
                                        "order": "id,asc",  # Sortierung für konsistente Paginierung
                                        "minBankBookingDate": from_date.isoformat(),
                                        "maxBankBookingDate": max_date.isoformat()  # Explizit bis heute
                                    }
                                    
                                    logger.info(f"📥 Fetching transactions page {page} from {from_date.isoformat()} to {max_date.isoformat()}")
                                    
                                    trans_response = requests.get(
                                        f"{finapi_service.api_base_url}/transactions",
                                        headers={"Authorization": f"Bearer {user_token}"},
                                        params=params
                                    )
                                    
                                    if trans_response.status_code == 200:
                                        page_data = trans_response.json()
                                        page_transactions = page_data.get("transactions", [])
                                        transactions.extend(page_transactions)
                                        
                                        # Prüfe ob es weitere Seiten gibt
                                        paging = page_data.get("paging", {})
                                        total_pages = paging.get("pageCount", 1)
                                        
                                        logger.info(f"📄 Seite {page}/{total_pages}: {len(page_transactions)} Transaktionen")
                                        
                                        if page >= total_pages:
                                            break
                                        
                                        page += 1
                                    else:
                                        error_detail = trans_response.text
                                        try:
                                            error_json = trans_response.json()
                                            error_detail = error_json.get("errors", [])
                                            if isinstance(error_detail, list) and error_detail:
                                                error_detail = error_detail[0].get("message", str(error_detail))
                                        except:
                                            pass
                                        
                                        logger.error(f"❌ Fehler beim Abrufen von Seite {page}: {trans_response.status_code}")
                                        logger.error(f"   Request URL: {trans_response.url}")
                                        logger.error(f"   Request Params: {params}")
                                        logger.error(f"   Response: {error_detail}")
                                        
                                        # Bei 400-Fehler könnte es ein Parameter-Problem sein, versuche ohne Datumsfilter
                                        if trans_response.status_code == 400 and page == 1:
                                            logger.warning(f"⚠️ 400-Fehler erkannt, versuche ohne Datumsfilter...")
                                            params_fallback = {
                                                "accountIds": account_id,
                                                "view": "userView",
                                                "page": page,
                                                "perPage": 500,
                                                "order": "id,asc"
                                            }
                                            fallback_response = requests.get(
                                                f"{finapi_service.api_base_url}/transactions",
                                                headers={"Authorization": f"Bearer {user_token}"},
                                                params=params_fallback
                                            )
                                            if fallback_response.status_code == 200:
                                                logger.info("✅ Fallback erfolgreich: Transaktionen ohne Datumsfilter geladen")
                                                page_data = fallback_response.json()
                                                page_transactions = page_data.get("transactions", [])
                                                # Filtere manuell nach Datum
                                                filtered_transactions = []
                                                for txn in page_transactions:
                                                    booking_date = txn.get("bookingDate") or txn.get("bankBookingDate")
                                                    if booking_date:
                                                        try:
                                                            if isinstance(booking_date, str):
                                                                txn_date = datetime.strptime(booking_date.split('T')[0], '%Y-%m-%d').date() if 'T' in booking_date else datetime.strptime(booking_date, '%Y-%m-%d').date()
                                                                if from_date <= txn_date <= max_date:
                                                                    filtered_transactions.append(txn)
                                                        except:
                                                            pass
                                                transactions.extend(filtered_transactions)
                                                logger.info(f"✅ {len(filtered_transactions)} Transaktionen im Datumsbereich {from_date} bis {max_date}")
                                        
                                        break
                            
                            account_transactions_count = len(transactions)
                            total_fetched += account_transactions_count
                            logger.info(f"✅ {account_transactions_count} Transaktionen von FinAPI geholt für Account {account_id}")
                            
                            if transactions:
                                # Zeige Datumsbereich der geladenen Transaktionen
                                dates = []
                                for txn in transactions:
                                    booking_date = txn.get("bookingDate") or txn.get("bankBookingDate") or txn.get("valueDate")
                                    if booking_date:
                                        dates.append(booking_date.split('T')[0] if 'T' in str(booking_date) else str(booking_date))
                                if dates:
                                    dates.sort()
                                    logger.info(f"   📅 Datumsbereich der Transaktionen: {dates[0]} bis {dates[-1]}")
                            
                            # Speichere Transaktionen
                            saved_for_account = 0
                            skipped_for_account = 0
                            
                            for txn in transactions:
                                # Konvertiere ID zu String für Vergleich
                                txn_id = str(txn.get("id")) if txn.get("id") else None
                                
                                if not txn_id:
                                    continue
                                
                                # Prüfe ob Transaktion bereits existiert
                                existing = db.query(BankTransaction).filter(
                                    BankTransaction.finapi_transaction_id == txn_id
                                ).first()
                                
                                if existing:
                                    skipped_for_account += 1
                                    continue
                                
                                # Erstelle neue Transaktion
                                from datetime import datetime
                                
                                # Parse Datum sicher - FinAPI nutzt bookingDate oder valueDate
                                booking_date = txn.get("bookingDate") or txn.get("valueDate") or txn.get("date")
                                parsed_date = None
                                if booking_date:
                                    try:
                                        # Versuche verschiedene Formate
                                        if isinstance(booking_date, str):
                                            # ISO-Format oder YYYY-MM-DD
                                            if 'T' in booking_date:
                                                parsed_date = datetime.fromisoformat(booking_date.replace('Z', '+00:00')).date()
                                            else:
                                                parsed_date = datetime.strptime(booking_date, '%Y-%m-%d').date()
                                    except Exception as e:
                                        logger.warning(f"⚠️ Datum konnte nicht geparst werden: {booking_date} - {e}")
                                        pass
                                
                                # Falls immer noch kein Datum, nutze aktuelles Datum
                                if not parsed_date:
                                    parsed_date = datetime.now().date()
                                
                                bank_transaction = BankTransaction(
                                    bank_account_id=bank_account.id,
                                    transaction_date=parsed_date,
                                    amount=txn.get("amount", 0),
                                    purpose=txn.get("purpose"),
                                    counterpart_name=txn.get("counterpartName"),
                                    counterpart_iban=txn.get("counterpartIban"),
                                    finapi_transaction_id=txn_id,
                                    is_matched=False
                                )
                                
                                db.add(bank_transaction)
                                total_saved += 1
                                saved_for_account += 1
                        else:
                            logger.error(f"❌ Fehler beim Abrufen für Account {account_id}: {account_response.status_code}")
                            # Setze account_transactions_count auf 0 für diesen Fehlerfall
                            if account_transactions_count == 0:
                                account_transactions_count = 0
                    
                    # Aktualisiere last_sync auch wenn keine neuen Transaktionen
                    if bank_account.last_sync is None or bank_account.last_sync < date.today():
                        bank_account.last_sync = date.today()
                    
                    # Log immer, auch wenn keine Transaktionen gefunden wurden
                    if saved_for_account > 0:
                        logger.info(f"✅ Account {bank_account.bank_name}: {account_transactions_count} Transaktionen geholt, {saved_for_account} neue gespeichert, {skipped_for_account} übersprungen (last_sync: {bank_account.last_sync})")
                    elif account_transactions_count > 0:
                        logger.info(f"ℹ️ Account {bank_account.bank_name}: {account_transactions_count} Transaktionen geholt, {skipped_for_account} bereits vorhanden, 0 neue gespeichert (last_sync: {bank_account.last_sync})")
                    else:
                        logger.info(f"ℹ️ Account {bank_account.bank_name}: 0 Transaktionen von FinAPI erhalten (last_sync: {bank_account.last_sync})")
                    
                else:
                    logger.error(f"❌ Fehler beim Abrufen der Accounts: {accounts_response.status_code} - {accounts_response.text}")
                    
            except Exception as e:
                logger.error(f"❌ Fehler beim Syncen von {bank_account.bank_name}: {str(e)}")
                import traceback
                logger.error(f"   Traceback: {traceback.format_exc()}")
                continue
        
        db.commit()
        
        logger.info(f"✅ Sync abgeschlossen: {total_saved} neue Transaktionen gespeichert")
        
        # Automatisches Matching nach Sync
        match_stats = None
        if total_saved > 0:
            try:
                logger.info(f"🔄 Starte automatisches Matching...")
                from ..services.matching_service import auto_match_transactions
                
                match_stats = auto_match_transactions(db, current_user.id)
                logger.info(f"✅ Matching: {match_stats['matched']} zugeordnet")
                
            except Exception as e:
                logger.error(f"❌ Fehler beim automatischen Matching: {str(e)}")
        
        return {
            "success": True,
            "transactions_fetched": total_fetched,
            "transactions_saved": total_saved,
            "accounts_processed": len(bank_accounts),
            "matching_stats": match_stats
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Fehler beim Transaktionen-Sync: {str(e)}")
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/connect-bank")
async def connect_bank() -> WebFormResponse:
    """
    Erstellt eine FinAPI WebForm 2.0 Session für Bank-Verknüpfung
    
    Flow:
    1. Client Token holen (grant_type=client_credentials)
    2. User erstellen/prüfen (demo-user)
    3. User Token holen (grant_type=password)
    4. WebForm erstellen (POST /api/webForms/bankConnectionImport)
    5. WebForm URL zurückgeben
    """
    try:
        logger.info("🚀 Starte FinAPI WebForm-Erstellung...")
        
        # 1. Client Token
        client_token = finapi_service.get_client_token()
        
        # 2. User erstellen/prüfen
        user_id = finapi_service.create_or_get_user(client_token)
        
        # 3. User Token
        user_token = finapi_service.get_user_token(user_id, "demo-pass")
        
        # 4. WebForm erstellen
        webform_data = finapi_service.create_webform(user_token)
        
        logger.info("✅ FinAPI WebForm erfolgreich erstellt!")
        
        return WebFormResponse(**webform_data)
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Unerwarteter Fehler: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


# Auto-Sync Job - läuft täglich um 06:00 Uhr
async def auto_sync_transactions():
    """
    Hintergrund-Job: Synchronisiert automatisch alle Bank-Transaktionen
    Läuft jeden Morgen um 06:00 Uhr
    Nutzt die gleiche Logik wie /transactions/sync (mit Bank Connection Update!)
    """
    import asyncio
    from ..db import SessionLocal
    from ..models.user import User
    
    try:
        logger.info("=" * 60)
        logger.info("⏰ ⏰ ⏰ AUTOMATISCHER SYNC WURDE AUSGELÖST ⏰ ⏰ ⏰")
        logger.info("=" * 60)
        logger.info("⏰ Starte automatischen Transaktionen-Sync...")
        
        # Hole alle aktiven Bank-Konten aller User
        db = SessionLocal()
        bank_accounts = db.query(BankAccount).filter(
            BankAccount.is_active == True
        ).all()
        
        if not bank_accounts:
            logger.info("ℹ️ Keine Bank-Konten für Sync gefunden")
            db.close()
            return
        
        logger.info(f"📊 Sync für {len(bank_accounts)} Bank-Konten...")
        
        # Gruppe Konten nach User
        from collections import defaultdict
        accounts_by_user = defaultdict(list)
        
        for account in bank_accounts:
            accounts_by_user[account.owner_id].append(account)
        
        # Für jeden User: Hole alle Accounts und rufe sync_transactions-ähnliche Logik auf
        for user_id, accounts in accounts_by_user.items():
            try:
                logger.info(f"🔄 Sync für User {user_id} ({len(accounts)} Konten)...")
                
                # Hole User für Token-Refresh falls nötig
                user = db.query(User).filter(User.id == user_id).first()
                if not user:
                    logger.error(f"❌ User {user_id} nicht gefunden")
                    continue
                
                for bank_account in accounts:
                    if not bank_account.finapi_account_id:
                        continue
                    
                    # Verwende gespeicherten Access Token vom Account, falls vorhanden
                    # Falls Token abgelaufen ist, hole neuen
                    user_token = None
                    if bank_account.finapi_user_id and bank_account.finapi_user_password:
                        # Hole immer neuen Token mit gespeicherten Credentials (Token könnten abgelaufen sein)
                        logger.info(f"🔄 Hole User Token für {bank_account.bank_name}...")
                        user_token = finapi_service.get_user_token(bank_account.finapi_user_id, bank_account.finapi_user_password)
                        if user_token:
                            bank_account.finapi_access_token = user_token
                            db.commit()
                            logger.info(f"✅ Neuer Token erhalten für {bank_account.bank_name}")
                    elif bank_account.finapi_access_token:
                        # Fallback: Versuche gespeicherten Token zu verwenden
                        user_token = bank_account.finapi_access_token
                        logger.info(f"📊 Nutze gespeicherten Access Token für {bank_account.bank_name}")
                    else:
                        # Letzter Fallback: demo-user
                        logger.warning(f"⚠️ Keine Credentials für {bank_account.bank_name}, nutze demo-user")
                        user_token = finapi_service.get_user_token("demo-user", "demo-pass")
                    
                    if not user_token:
                        logger.error(f"❌ User Token konnte nicht geholt werden für {bank_account.bank_name}")
                        continue
                    
                    try:
                        # Schritt 0: Triggere Bank Connection Update (wie in manueller Sync)
                        if bank_account.finapi_connection_id:
                            logger.info(f"🔄 Triggere Bank Connection Update für {bank_account.bank_name} (Connection ID: {bank_account.finapi_connection_id})...")
                            task_id = finapi_service.trigger_bank_connection_update(user_token, int(bank_account.finapi_connection_id))
                            if task_id:
                                import asyncio
                                logger.info(f"⏳ Warte 15 Sekunden, damit FinAPI Transaktionen von der Bank laden kann...")
                                await asyncio.sleep(15)  # Async sleep statt blocking sleep
                            else:
                                logger.warning("⚠️ Update-Task konnte nicht erstellt werden, versuche trotzdem Transaktionen zu holen")
                        else:
                            logger.info("ℹ️ Keine Connection ID vorhanden, überspringe Update-Trigger")
                        
                        # Hole alle Accounts vom User
                        accounts_response = requests.get(
                            f"{finapi_service.api_base_url}/accounts",
                            headers={"Authorization": f"Bearer {user_token}"},
                            params={"page": 1, "perPage": 100}
                        )
                        
                        if accounts_response.status_code != 200:
                            logger.error(f"❌ Accounts nicht abrufbar: {accounts_response.status_code}")
                            continue
                        
                        accounts_list = accounts_response.json().get("accounts", [])
                        if not accounts_list:
                            continue
                        
                        # Für jeden Account: Hole Transaktionen basierend auf last_sync
                        from datetime import date, timedelta
                        max_date = date.today()
                        from_date = bank_account.last_sync + timedelta(days=1) if bank_account.last_sync else max_date - timedelta(days=90)
                        
                        if from_date > max_date:
                            from_date = max_date - timedelta(days=7)
                        
                        # Hole Transaktionen
                        page = 1
                        total_saved = 0
                        saved_for_account = 0
                        
                        while True:
                            params = {
                                "accountIds": bank_account.finapi_account_id,
                                "view": "userView",
                                "page": page,
                                "perPage": 500,
                                "order": "id,asc",
                                "minBankBookingDate": from_date.isoformat(),
                                "maxBankBookingDate": max_date.isoformat()
                            }
                            
                            trans_response = requests.get(
                                f"{finapi_service.api_base_url}/transactions",
                                headers={"Authorization": f"Bearer {user_token}"},
                                params=params
                            )
                            
                            if trans_response.status_code == 200:
                                data = trans_response.json()
                                transactions = data.get("transactions", [])
                                
                                for txn in transactions:
                                    txn_id = str(txn.get("id"))
                                    if not txn_id:
                                        continue
                                    
                                    existing = db.query(BankTransaction).filter(
                                        BankTransaction.finapi_transaction_id == txn_id
                                    ).first()
                                    
                                    if not existing:
                                        from datetime import datetime
                                        booking_date = txn.get("bookingDate") or txn.get("valueDate") or txn.get("date")
                                        parsed_date = None
                                        if booking_date:
                                            try:
                                                if isinstance(booking_date, str):
                                                    if 'T' in booking_date:
                                                        parsed_date = datetime.fromisoformat(booking_date.replace('Z', '+00:00')).date()
                                                    else:
                                                        parsed_date = datetime.strptime(booking_date, '%Y-%m-%d').date()
                                            except:
                                                pass
                                        
                                        if not parsed_date:
                                            parsed_date = date.today()
                                        
                                        bank_transaction = BankTransaction(
                                            bank_account_id=bank_account.id,
                                            transaction_date=parsed_date,
                                            amount=txn.get("amount", 0),
                                            purpose=txn.get("purpose"),
                                            counterpart_name=txn.get("counterpartName"),
                                            counterpart_iban=txn.get("counterpartIban"),
                                            finapi_transaction_id=txn_id,
                                            is_matched=False
                                        )
                                        db.add(bank_transaction)
                                        total_saved += 1
                                        saved_for_account += 1
                                
                                paging = data.get("paging", {})
                                total_pages = paging.get("pageCount", 1)
                                if page >= total_pages:
                                    break
                                page += 1
                            else:
                                break
                        
                        # Update last_sync
                        if bank_account.last_sync is None or bank_account.last_sync < date.today():
                            bank_account.last_sync = date.today()
                        
                        if saved_for_account > 0:
                            logger.info(f"✅ {bank_account.bank_name}: {saved_for_account} neue Transaktionen gespeichert")
                        
                        db.commit()
                        
                    except Exception as e:
                        logger.error(f"❌ Fehler beim Sync von {bank_account.bank_name}: {str(e)}")
                        import traceback
                        logger.error(f"   Traceback: {traceback.format_exc()}")
                        db.rollback()
                        continue
                
                # Automatisches Matching nach Sync (immer ausführen, auch wenn keine neuen Transaktionen)
                try:
                    logger.info(f"🔄 Starte automatisches Matching für User {user_id}...")
                    from ..services.matching_service import auto_match_transactions
                    match_stats = auto_match_transactions(db, user_id)
                    logger.info(f"✅ Matching: {match_stats['matched']} zugeordnet, {match_stats.get('open', 0)} offen")
                except Exception as e:
                    logger.error(f"❌ Fehler beim Matching: {str(e)}")
                    import traceback
                    logger.error(f"   Traceback: {traceback.format_exc()}")
                
            except Exception as e:
                logger.error(f"❌ Fehler beim Sync für User {user_id}: {str(e)}")
                import traceback
                logger.error(f"   Traceback: {traceback.format_exc()}")
                db.rollback()
                continue
        
        logger.info("✅ Automatischer Sync abgeschlossen")
        
    except Exception as e:
        logger.error(f"❌ Fehler im Auto-Sync: {str(e)}")
        import traceback
        logger.error(f"   Traceback: {traceback.format_exc()}")
    finally:
        if db:
            db.close()


# Test-Endpoint: Manueller Trigger für Auto-Sync (für Tests)
@router.post("/transactions/sync-now")
async def trigger_sync_now(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Triggere den Auto-Sync sofort (für Tests)
    WARNUNG: Nur für Entwicklung/Testing - führt sofortigen Sync aus
    """
    try:
        logger.info("=" * 60)
        logger.info(f"🧪 MANUELLER SYNC-TRIGGER für User {current_user.id}")
        logger.info("=" * 60)
        # Rufe die Auto-Sync Funktion direkt auf
        await auto_sync_transactions()
        return {
            "success": True,
            "message": "Auto-Sync wurde manuell ausgelöst. Prüfe Logs für Details."
        }
    except Exception as e:
        logger.error(f"❌ Fehler beim manuellen Sync-Trigger: {str(e)}")
        import traceback
        logger.error(traceback.format_exc())
        raise HTTPException(status_code=500, detail=str(e))


# Endpoint: Scheduler Status anzeigen
@router.get("/scheduler/status")
async def get_scheduler_status(
    current_user: User = Depends(get_current_user)
):
    """
    Zeige Status des Schedulers
    """
    try:
        job = scheduler.get_job('daily_bank_sync')
        if job:
            return {
                "scheduler_running": scheduler.running,
                "job_id": job.id,
                "job_name": job.name,
                "next_run_time": str(job.next_run_time) if job.next_run_time else None,
                "timezone": str(job.trigger.timezone) if hasattr(job.trigger, 'timezone') else "UTC"
            }
        else:
            return {
                "scheduler_running": scheduler.running,
                "job_id": None,
                "message": "Kein Job gefunden"
            }
    except Exception as e:
        logger.error(f"❌ Fehler beim Abrufen des Scheduler-Status: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


# Starte Scheduler
def start_transaction_scheduler():
    """Starte den täglichen Auto-Sync um 06:00 Uhr (Europe/Berlin Zeitzone)"""
    logger.info("=" * 60)
    logger.info("📅 INITIALISIERE TRANSACTION SCHEDULER")
    logger.info("=" * 60)
    try:
        # Verwende Europe/Berlin Zeitzone (berücksichtigt automatisch Sommerzeit)
        if pytz:
            berlin_tz = pytz.timezone('Europe/Berlin')
            cron_trigger = CronTrigger(hour=6, minute=0, timezone=berlin_tz)
            timezone_info = "Europe/Berlin"
        else:
            # Fallback zu UTC wenn pytz nicht verfügbar
            cron_trigger = CronTrigger(hour=6, minute=0)
            timezone_info = "UTC"
        
        # Wrapper-Funktion für bessere Async-Unterstützung
        async def run_auto_sync():
            try:
                await auto_sync_transactions()
            except Exception as e:
                logger.error(f"❌ Fehler in run_auto_sync Wrapper: {str(e)}")
                import traceback
                logger.error(traceback.format_exc())
        
        scheduler.add_job(
            run_auto_sync,
            cron_trigger,
            id='daily_bank_sync',
            name='Täglicher Bank-Transaktionen-Sync',
            replace_existing=True,
            max_instances=1,  # Nur eine Instanz gleichzeitig
            coalesce=True,  # Wenn Job verpasst wurde, führe nur einmal aus
            misfire_grace_time=300  # 5 Minuten Toleranz für verpasste Ausführungen
        )
        
        if not scheduler.running:
            scheduler.start()
            logger.info("✅ Scheduler wurde gestartet")
        else:
            logger.info("ℹ️ Scheduler läuft bereits")
        
        # Hole Job-Info für Logging
        job = scheduler.get_job('daily_bank_sync')
        if job:
            next_run = job.next_run_time
            logger.info("=" * 60)
            logger.info(f"📅 SCHEDULER KONFIGURIERT")
            logger.info(f"   Job ID: {job.id}")
            logger.info(f"   Job Name: {job.name}")
            logger.info(f"   Zeitzone: {timezone_info}")
            logger.info(f"   Zeitplan: Täglich um 06:00 Uhr")
            logger.info(f"   Nächster Lauf: {next_run}")
            logger.info(f"   Scheduler Status: {'RUNNING' if scheduler.running else 'STOPPED'}")
            logger.info("=" * 60)
        else:
            logger.error("❌ Job konnte nicht erstellt werden!")
    except Exception as e:
        logger.error(f"❌ Fehler beim Starten des Schedulers: {str(e)}")
        import traceback
        logger.error(traceback.format_exc())

