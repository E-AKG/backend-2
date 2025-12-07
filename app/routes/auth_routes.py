from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from sqlalchemy.exc import SQLAlchemyError
from passlib.context import CryptContext
from ..db import get_db
from ..models.user import User
from ..schemas.user_schema import UserCreate, UserLogin, TokenResponse
from ..utils.jwt_handler import create_token, decode_token
from ..utils.mailer import send_verification_email
import logging

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["Authentication"])
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


@router.post("/register", status_code=status.HTTP_201_CREATED)
def register(user: UserCreate, db: Session = Depends(get_db)):
    """
    Register a new user account.
    
    - **email**: Valid email address
    - **password**: Minimum 8 characters, must contain at least one letter and one digit
    
    Returns a message indicating that a verification email has been sent.
    """
    try:
        # Log registration attempt
        logger.info(f"Registration attempt for email: {user.email}")
        
        # Check if user already exists
        existing_user = db.query(User).filter(User.email == user.email).first()
        if existing_user:
            logger.warning(f"Registration failed: email already exists - {user.email}")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Email already registered. Please use a different email or try logging in."
            )
        
        # Hash password and create user
        hashed_password = pwd_context.hash(user.password)
        new_user = User(email=user.email, password=hashed_password)
        
        db.add(new_user)
        db.commit()
        db.refresh(new_user)
        
        logger.info(f"New user registered: {new_user.email}")
        
        # Generate verification token and send email
        verification_token = create_token({"sub": new_user.email})
        send_verification_email(new_user.email, verification_token)
        
        return {
            "message": "Verifizierungs-E-Mail wurde versendet. Bitte überprüfen Sie Ihr Postfach (auch den Spam-Ordner) und bestätigen Sie Ihre E-Mail-Adresse."
        }
        
    except HTTPException:
        raise
    except ValueError as e:
        # Pydantic validation errors (e.g., password too long, missing digit/letter)
        error_msg = str(e)
        logger.warning(f"Registration failed: validation error - {error_msg} for email: {user.email}")
        if "72 bytes" in error_msg or "longer than" in error_msg.lower():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Das Passwort ist zu lang. Bitte verwenden Sie ein Passwort mit maximal 72 Zeichen."
            )
        # Translate common validation errors to German
        if "at least one digit" in error_msg.lower():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Das Passwort muss mindestens eine Ziffer enthalten."
            )
        if "at least one letter" in error_msg.lower() or "at least one alpha" in error_msg.lower():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Das Passwort muss mindestens einen Buchstaben enthalten."
            )
        if "at least 8 characters" in error_msg.lower() or "8 characters long" in error_msg.lower():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Das Passwort muss mindestens 8 Zeichen lang sein."
            )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=error_msg
        )
    except SQLAlchemyError as e:
        db.rollback()
        logger.error(f"Database error during registration: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An error occurred while creating your account. Please try again."
        )
    except Exception as e:
        db.rollback()
        error_msg = str(e)
        logger.error(f"Unexpected error during registration: {error_msg}")
        # Check if it's a bcrypt password length error
        if "72 bytes" in error_msg or "cannot be longer" in error_msg.lower():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Das Passwort ist zu lang. Bitte verwenden Sie ein Passwort mit maximal 72 Zeichen."
            )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An unexpected error occurred. Please try again later."
        )


@router.get("/verify")
def verify_email(token: str, db: Session = Depends(get_db)):
    """
    Verify user email address using the token from the verification email.
    
    - **token**: JWT token from verification email
    """
    from fastapi.responses import HTMLResponse
    
    try:
        # Decode token (will raise HTTPException if invalid/expired)
        payload = decode_token(token)
        email = payload.get("sub")
        
        if not email:
            return HTMLResponse(content=_error_html("Ungültiger Token", "Der Verifizierungs-Link ist ungültig."), status_code=400)
        
        # Find user
        user = db.query(User).filter(User.email == email).first()
        if not user:
            return HTMLResponse(content=_error_html("Benutzer nicht gefunden", "Dieser Account wurde möglicherweise gelöscht."), status_code=404)
        
        # Check if already verified
        if user.is_verified:
            return HTMLResponse(content=_success_html("Bereits verifiziert", "Deine E-Mail ist bereits verifiziert. Du kannst dich jetzt einloggen!"))
        
        # Mark as verified
        user.is_verified = True
        db.commit()
        
        logger.info(f"User verified: {user.email}")
        
        return HTMLResponse(content=_success_html("E-Mail verifiziert! ✓", "Dein Account wurde erfolgreich verifiziert. Du kannst dich jetzt einloggen!"))
        
    except HTTPException as e:
        if "expired" in e.detail.lower():
            return HTMLResponse(content=_error_html("Token abgelaufen", "Der Verifizierungs-Link ist abgelaufen. Bitte registriere dich erneut."), status_code=401)
        return HTMLResponse(content=_error_html("Fehler", e.detail), status_code=e.status_code)
    except SQLAlchemyError as e:
        db.rollback()
        logger.error(f"Database error during verification: {str(e)}")
        return HTMLResponse(content=_error_html("Datenbankfehler", "Ein Fehler ist aufgetreten. Bitte versuche es später erneut."), status_code=500)
    except Exception as e:
        db.rollback()
        logger.error(f"Unexpected error during verification: {str(e)}")
        return HTMLResponse(content=_error_html("Unerwarteter Fehler", "Ein unerwarteter Fehler ist aufgetreten. Bitte versuche es später erneut."), status_code=500)


def _success_html(title: str, message: str) -> str:
    """Generate success HTML page"""
    return f"""
    <!DOCTYPE html>
    <html lang="de">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>{title} - IZENIC ImmoAssist</title>
        <style>
            * {{ margin: 0; padding: 0; box-sizing: border-box; }}
            body {{
                font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Oxygen, Ubuntu, Cantarell, sans-serif;
                background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                min-height: 100vh;
                display: flex;
                align-items: center;
                justify-content: center;
                padding: 20px;
            }}
            .container {{
                background: white;
                border-radius: 20px;
                box-shadow: 0 20px 60px rgba(0,0,0,0.3);
                padding: 60px 40px;
                max-width: 500px;
                width: 100%;
                text-align: center;
            }}
            .icon {{
                width: 80px;
                height: 80px;
                background: #10b981;
                border-radius: 50%;
                display: flex;
                align-items: center;
                justify-content: center;
                margin: 0 auto 30px;
                animation: scaleIn 0.5s ease-out;
            }}
            .icon svg {{
                width: 50px;
                height: 50px;
                stroke: white;
                stroke-width: 3;
                fill: none;
            }}
            h1 {{
                color: #1f2937;
                font-size: 32px;
                margin-bottom: 20px;
                font-weight: 700;
            }}
            p {{
                color: #6b7280;
                font-size: 18px;
                line-height: 1.6;
                margin-bottom: 40px;
            }}
            .button {{
                background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                color: white;
                padding: 16px 32px;
                border-radius: 12px;
                text-decoration: none;
                display: inline-block;
                font-weight: 600;
                font-size: 16px;
                transition: transform 0.2s, box-shadow 0.2s;
            }}
            .button:hover {{
                transform: translateY(-2px);
                box-shadow: 0 10px 30px rgba(102, 126, 234, 0.4);
            }}
            @keyframes scaleIn {{
                from {{ transform: scale(0); }}
                to {{ transform: scale(1); }}
            }}
        </style>
    </head>
    <body>
        <div class="container">
            <div class="icon">
                <svg viewBox="0 0 24 24">
                    <polyline points="20 6 9 17 4 12"></polyline>
                </svg>
            </div>
            <h1>{title}</h1>
            <p>{message}</p>
            <a href="http://localhost:5173/login" class="button">Zum Login →</a>
        </div>
    </body>
    </html>
    """


def _error_html(title: str, message: str) -> str:
    """Generate error HTML page"""
    return f"""
    <!DOCTYPE html>
    <html lang="de">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>{title} - IZENIC ImmoAssist</title>
        <style>
            * {{ margin: 0; padding: 0; box-sizing: border-box; }}
            body {{
                font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Oxygen, Ubuntu, Cantarell, sans-serif;
                background: linear-gradient(135deg, #f093fb 0%, #f5576c 100%);
                min-height: 100vh;
                display: flex;
                align-items: center;
                justify-content: center;
                padding: 20px;
            }}
            .container {{
                background: white;
                border-radius: 20px;
                box-shadow: 0 20px 60px rgba(0,0,0,0.3);
                padding: 60px 40px;
                max-width: 500px;
                width: 100%;
                text-align: center;
            }}
            .icon {{
                width: 80px;
                height: 80px;
                background: #ef4444;
                border-radius: 50%;
                display: flex;
                align-items: center;
                justify-content: center;
                margin: 0 auto 30px;
            }}
            .icon svg {{
                width: 50px;
                height: 50px;
                stroke: white;
                stroke-width: 3;
                fill: none;
            }}
            h1 {{
                color: #1f2937;
                font-size: 32px;
                margin-bottom: 20px;
                font-weight: 700;
            }}
            p {{
                color: #6b7280;
                font-size: 18px;
                line-height: 1.6;
                margin-bottom: 40px;
            }}
            .button {{
                background: linear-gradient(135deg, #f093fb 0%, #f5576c 100%);
                color: white;
                padding: 16px 32px;
                border-radius: 12px;
                text-decoration: none;
                display: inline-block;
                font-weight: 600;
                font-size: 16px;
                transition: transform 0.2s, box-shadow 0.2s;
            }}
            .button:hover {{
                transform: translateY(-2px);
                box-shadow: 0 10px 30px rgba(240, 147, 251, 0.4);
            }}
        </style>
    </head>
    <body>
        <div class="container">
            <div class="icon">
                <svg viewBox="0 0 24 24">
                    <line x1="18" y1="6" x2="6" y2="18"></line>
                    <line x1="6" y1="6" x2="18" y2="18"></line>
                </svg>
            </div>
            <h1>{title}</h1>
            <p>{message}</p>
            <a href="http://localhost:5173/register" class="button">Zur Registrierung →</a>
        </div>
    </body>
    </html>
    """


@router.post("/login", response_model=TokenResponse)
def login(credentials: UserLogin, db: Session = Depends(get_db)):
    """
    Authenticate user and return access token.
    
    - **email**: Registered email address
    - **password**: User password
    
    Returns an access token for authenticated requests.
    """
    try:
        # Find user by email
        user = db.query(User).filter(User.email == credentials.email).first()
        
        # Check if user exists and password is correct
        if not user or not pwd_context.verify(credentials.password, user.password):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid email or password.",
                headers={"WWW-Authenticate": "Bearer"}
            )
        
        # Check if email is verified
        if not user.is_verified:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Bitte verifizieren Sie Ihre E-Mail-Adresse vor dem Login. Überprüfen Sie Ihr Postfach (auch den Spam-Ordner) auf die Verifizierungs-E-Mail."
            )
        
        # Generate access token
        access_token = create_token({"sub": user.email, "user_id": user.id})
        
        logger.info(f"User logged in: {user.email}")
        
        return {
            "access_token": access_token,
            "token_type": "bearer"
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Unexpected error during login: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An unexpected error occurred. Please try again later."
        )