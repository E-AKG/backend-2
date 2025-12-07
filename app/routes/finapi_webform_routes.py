from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from ..db import get_db
from ..models.user import User
from ..models.bank import BankAccount
from ..utils.deps import get_current_user
from ..utils.finapi_service import finapi_service
from datetime import date
import logging

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/finapi-webform", tags=["FinAPI Web Form"])


@router.post("/create-webform")
def create_webform_redirect(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Erstellt einen FinAPI WebForm Redirect-Link
    
    Der Nutzer wird auf das echte FinAPI WebForm weitergeleitet:
    1. Bankauswahl (BIC, BLZ, Name)
    2. Online-Banking Login
    3. TAN-Freigabe
    
    Das komplette WebForm läuft auf FinAPI-Servern, nicht bei uns.
    """
    # Erstelle temporäres Konto für den WebForm-Prozess
    account = BankAccount(
        owner_id=current_user.id,
        account_name="Temporäres Konto",
        iban="",
        bank_name=""
    )
    db.add(account)
    db.commit()
    db.refresh(account)
    
    if not finapi_service.is_configured():
        return {
            "status": "demo",
            "message": "Demo-Modus: Keine echte FinAPI-Verbindung"
        }
    
    try:
        logger.info(f"🔐 Creating FinAPI WebForm redirect for user {current_user.id}")
        
        # 1. FinAPI User erstellen/holen
        finapi_password = f"secure_{current_user.id}_{account.id[:8]}"
        logger.info(f"Creating FinAPI user for {current_user.email}")
        
        user_result = finapi_service.create_user_in_finapi(current_user.email, finapi_password)
        
        if not user_result:
            logger.error("❌ FinAPI User creation returned None")
            raise HTTPException(status_code=500, detail="FinAPI User konnte nicht erstellt werden")
        
        logger.info(f"✅ FinAPI User created: {user_result.get('id')}")
        
        # 2. User Token holen
        user_id = user_result.get('id')
        user_password = user_result.get('password', finapi_password)
        
        user_token = finapi_service.get_user_token(user_id, user_password)
        
        if not user_token:
            logger.error("❌ User token is None")
            raise HTTPException(status_code=500, detail="User Token konnte nicht abgerufen werden")
        
        logger.info(f"✅ User token received: {user_token[:30]}...")
        
        # 3. FinAPI WebForm erstellen
        webform_result = finapi_service.create_webform(user_token)
        
        if not webform_result:
            logger.error("❌ WebForm creation failed")
            raise HTTPException(status_code=500, detail="FinAPI WebForm konnte nicht erstellt werden")
        
        webform_url = webform_result.get('location')
        webform_id = webform_result.get('id')
        
        logger.info(f"✅ FinAPI WebForm created: {webform_url}")
        
        # Speichere FinAPI User-Daten
        account.finapi_user_id = user_id
        account.finapi_user_password = user_password
        account.finapi_access_token = user_token
        account.finapi_webform_id = webform_id
        account.last_sync = date.today()
        
        db.commit()
        
        return {
            "status": "success",
            "webform_url": webform_url,
            "webform_id": webform_id,
            "message": "FinAPI WebForm bereit - Nutzer wird weitergeleitet"
        }
        
    except HTTPException:
        raise
    except Exception as e:
        import traceback
        logger.error(f"❌ WebForm creation failed: {str(e)}")
        logger.error(f"Traceback: {traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=str(e))


from pydantic import BaseModel

class BankImportRequest(BaseModel):
    account_id: str
    bank_id: int
    username: str
    pin: str


@router.post("/import-bank")
def import_bank_direct(
    request: BankImportRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Importiere Bank-Verbindung direkt (für Sandbox/Test)
    
    Für Sandbox: Verwendet Test-Credentials
    Für Produktion: Sollte Web Form Flow verwendet werden
    """
    import requests
    
    account = db.query(BankAccount).filter(
        BankAccount.id == request.account_id,
        BankAccount.owner_id == current_user.id
    ).first()
    
    if not account:
        raise HTTPException(status_code=404, detail="Konto nicht gefunden")
    
    if not account.finapi_user_id or not account.finapi_access_token:
        raise HTTPException(status_code=400, detail="Kein FinAPI Token vorhanden")
    
    try:
        logger.info(f"🔐 Starte Bank-Import für Bank {request.bank_id}...")
        
        # Bank Connection Import (echte Banken oder Sandbox)
        # bankingInterface ist ein QUERY parameter!
        import urllib.parse
        
        params = {
            "bankId": request.bank_id,
            "bankingInterface": "WEB_SCRAPER"  # Für echte Banken
        }
        
        body = {
            "bankingUserId": request.username,
            "bankingPin": request.pin,
            "storePin": False,
        }
        
        logger.info(f"Request Params: {params}")
        logger.info(f"Request Body: {body}")
        logger.info(f"Full URL: {finapi_service.base_url}/api/v2/bankConnections/import?{urllib.parse.urlencode(params)}")
        
        response = requests.post(
            f"{finapi_service.base_url}/api/v2/bankConnections/import",
            params=params,
            headers={
                "Authorization": f"Bearer {account.finapi_access_token}",
                "Accept": "application/json",
                "Content-Type": "application/json"
            },
            json=body
        )
        
        logger.info(f"Response Status: {response.status_code}")
        logger.info(f"Response Body: {response.text}")
        logger.info(f"Response Headers: {dict(response.headers)}")
        
        if response.status_code in [200, 201]:
            connection_data = response.json()
            
            # Hole Accounts aus der Connection
            accounts = connection_data.get("accounts", [])
            
            if accounts:
                # Verwende erstes Konto
                finapi_account = accounts[0]
                account.finapi_account_id = str(finapi_account.get("id"))
                account.iban = finapi_account.get("iban") or account.iban
                account.balance = finapi_account.get("balance")
                account.last_sync = date.today()
                db.commit()
                
                logger.info(f"✅ Bank Connection erfolgreich! Account ID: {account.finapi_account_id}")
                
                return {
                    "status": "success",
                    "message": "Bankverbindung erfolgreich hergestellt!",
                    "account_id": account.finapi_account_id,
                    "iban": account.iban,
                    "balance": float(account.balance) if account.balance else None
                }
            else:
                logger.warning("Keine Accounts in der Response")
                return {"status": "error", "message": "Keine Konten gefunden"}
        
        else:
            error_data = response.json()
            error_msg = error_data.get("errors", [{}])[0].get("message", "Unbekannter Fehler")
            logger.error(f"❌ Bank Import fehlgeschlagen: {error_msg}")
            raise HTTPException(status_code=400, detail=error_msg)
            
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Import failed: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/status")
def check_webform_status(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Prüfe Status des FinAPI WebForms
    """
    account = db.query(BankAccount).filter(
        BankAccount.owner_id == current_user.id,
        BankAccount.finapi_webform_id.isnot(None)
    ).order_by(BankAccount.created_at.desc()).first()
    
    if not account:
        return {"status": "not_started", "message": "Kein WebForm gestartet"}
    
    
    try:
        # Prüfe WebForm Status bei FinAPI
        webform_status = finapi_service.get_webform_status(
            account.finapi_access_token, 
            account.finapi_webform_id
        )
        
        if webform_status and webform_status.get("status") == "completed":
            return {"status": "completed", "message": "WebForm erfolgreich abgeschlossen"}
        elif webform_status and webform_status.get("status") == "error":
            return {"status": "error", "message": webform_status.get("message", "WebForm fehlgeschlagen")}
        else:
            return {"status": "pending", "message": "WebForm läuft noch"}
        
    except Exception as e:
        logger.error(f"Status check failed: {str(e)}")
        return {"status": "error", "message": str(e)}


@router.get("/finalize")
def finalize_connection(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Finalisiere Bank-Verbindung nach erfolgreicher Web Form
    Hole Accounts und Transaktionen von FinAPI
    """
    account = db.query(BankAccount).filter(
        BankAccount.owner_id == current_user.id,
        BankAccount.finapi_webform_id.isnot(None)
    ).order_by(BankAccount.created_at.desc()).first()
    
    if not account:
        raise HTTPException(status_code=404, detail="Kein WebForm-Konto gefunden")
    
    if not account.finapi_access_token:
        raise HTTPException(status_code=400, detail="Kein FinAPI Token vorhanden")
    
    try:
        # Hole Accounts von FinAPI
        accounts = finapi_service.get_accounts(account.finapi_access_token)
        
        if accounts and len(accounts) > 0:
            # Verwende erstes Account
            first_account = accounts[0]
            account.finapi_account_id = str(first_account.get("id"))
            account.iban = first_account.get("iban") or account.iban
            account.balance = first_account.get("balance")
            account.last_sync = date.today()
            db.commit()
            
            logger.info(f"✅ {len(accounts)} Account(s) von FinAPI importiert")
            
            return {
                "status": "success",
                "message": f"{len(accounts)} Konto(n) erfolgreich verbunden!",
                "accounts": len(accounts),
                "iban": account.iban
            }
        else:
            logger.warning("Keine Accounts von FinAPI erhalten")
            return {
                "status": "warning",
                "message": "Verbindung hergestellt, aber keine Konten gefunden"
            }
        
    except Exception as e:
        logger.error(f"Finalize failed: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

