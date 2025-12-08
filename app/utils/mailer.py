import smtplib
import socket
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from fastapi import HTTPException, status
from ..config import settings
import logging

logger = logging.getLogger(__name__)


def send_verification_email(to_email: str, token: str):
    """
    Send a professional verification email to the user.
    Uses SendGrid API if SENDGRID_API_KEY is set, otherwise falls back to SMTP.
    
    Args:
        to_email: User's email address
        token: JWT verification token
    
    Raises:
        HTTPException: If email sending fails
    """
    # Use SendGrid API if available (better for Render)
    # Check if SENDGRID_API_KEY is set and not empty
    # Fallback: Check if SMTP_PASSWORD looks like a SendGrid API key (starts with SG.)
    sendgrid_key = None
    if settings.SENDGRID_API_KEY and settings.SENDGRID_API_KEY.strip():
        sendgrid_key = settings.SENDGRID_API_KEY.strip()
    elif settings.SMTP_PASSWORD and settings.SMTP_PASSWORD.strip().startswith('SG.'):
        # Fallback: SMTP_PASSWORD contains SendGrid API key
        logger.info("📧 Found SendGrid API key in SMTP_PASSWORD, using SendGrid API")
        sendgrid_key = settings.SMTP_PASSWORD.strip()
    
    if sendgrid_key:
        logger.info("📧 Using SendGrid API (preferred method)")
        return _send_via_sendgrid_api(to_email, token, sendgrid_key)
    else:
        logger.warning("⚠️ SENDGRID_API_KEY not set, falling back to SMTP")
        return _send_via_smtp(to_email, token)


def _get_verification_link(token: str) -> str:
    """Get the verification link URL"""
    if settings.BACKEND_URL:
        backend_url = settings.BACKEND_URL
    else:
        if "localhost" in settings.FRONTEND_URL or "127.0.0.1" in settings.FRONTEND_URL:
            backend_url = settings.FRONTEND_URL.replace(":5173", ":8000").replace("localhost", "127.0.0.1")
        else:
            backend_url = settings.FRONTEND_URL.replace(":5173", ":8000")
    return f"{backend_url}/auth/verify?token={token}"


def _get_email_html(verify_link: str) -> str:
    """Get HTML email content"""
    logo_url = f"{settings.FRONTEND_URL}/logo.png"
    return f"""
<!DOCTYPE html>
<html lang="de">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>E-Mail-Verifizierung</title>
</head>
<body style="margin: 0; padding: 0; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif; background-color: #0e7490;">
    <table role="presentation" style="width: 100%; border-collapse: collapse; background-color: #0e7490;">
        <tr>
            <td style="padding: 40px 20px;">
                <table role="presentation" style="max-width: 600px; margin: 0 auto; background-color: #ffffff; border-radius: 16px; box-shadow: 0 10px 30px rgba(8, 145, 178, 0.3); overflow: hidden;">
                    <!-- Header -->
                    <tr>
                        <td style="background: linear-gradient(135deg, #0e7490 0%, #0891b2 100%); padding: 40px 30px; text-align: center;">
                            <img src="{logo_url}" alt="IZENIC" style="max-width: 200px; height: auto; margin-bottom: 20px;" />
                            <h1 style="margin: 0; color: #ffffff; font-size: 28px; font-weight: 700; letter-spacing: -0.5px;">
                                IZENIC
                            </h1>
                            <p style="margin: 10px 0 0 0; color: rgba(255, 255, 255, 0.95); font-size: 16px; font-weight: 500;">
                                Immobilienverwaltung leicht gemacht
                            </p>
                        </td>
                    </tr>
                    
                    <!-- Content -->
                    <tr>
                        <td style="padding: 40px 30px;">
                            <h2 style="margin: 0 0 20px 0; color: #164e63; font-size: 24px; font-weight: 700;">
                                Willkommen bei IZENIC!
                            </h2>
                            
                            <p style="margin: 0 0 20px 0; color: #155e75; font-size: 16px; line-height: 1.7;">
                                Vielen Dank für Ihre Registrierung! Um Ihr Konto zu aktivieren, bestätigen Sie bitte Ihre E-Mail-Adresse.
                            </p>
                            
                            <p style="margin: 0 0 30px 0; color: #155e75; font-size: 16px; line-height: 1.7;">
                                Klicken Sie einfach auf den Button unten, um Ihre E-Mail-Adresse zu verifizieren.
                            </p>
                            
                            <!-- CTA Button -->
                            <table role="presentation" style="width: 100%; border-collapse: collapse; margin: 30px 0;">
                                <tr>
                                    <td style="text-align: center; padding: 20px 0;">
                                        <a href="{verify_link}" 
                                           style="display: inline-block; background: linear-gradient(135deg, #0e7490 0%, #0891b2 100%); color: #ffffff; text-decoration: none; padding: 18px 45px; border-radius: 10px; font-size: 16px; font-weight: 700; box-shadow: 0 6px 20px rgba(14, 116, 144, 0.5); transition: all 0.3s ease;">
                                            E-Mail-Adresse bestätigen
                                        </a>
                                    </td>
                                </tr>
                            </table>
                            
                            <!-- Alternative Link -->
                            <div style="margin: 30px 0; padding: 20px; background-color: #cffafe; border-radius: 10px; border-left: 4px solid #0e7490;">
                                <p style="margin: 0 0 10px 0; color: #0e7490; font-size: 14px; font-weight: 600;">
                                    Falls der Button nicht funktioniert:
                                </p>
                                <p style="margin: 0; color: #155e75; font-size: 14px; line-height: 1.6; word-break: break-all;">
                                    Kopieren Sie diesen Link in Ihren Browser:<br>
                                    <a href="{verify_link}" style="color: #0e7490; text-decoration: none; font-weight: 500;">{verify_link}</a>
                                </p>
                            </div>
                            
                            <!-- Info Box -->
                            <div style="margin: 30px 0; padding: 15px; background-color: #a5f3fc; border-radius: 10px; border-left: 4px solid #0891b2;">
                                <p style="margin: 0; color: #164e63; font-size: 14px; line-height: 1.7;">
                                    <strong>⏰ Wichtig:</strong> Dieser Link ist 1 Stunde gültig. Falls der Link abgelaufen ist, registrieren Sie sich bitte erneut.
                                </p>
                            </div>
                        </td>
                    </tr>
                    
                    <!-- Footer -->
                    <tr>
                        <td style="padding: 30px; background: linear-gradient(135deg, #cffafe 0%, #a5f3fc 100%); border-top: 1px solid #67e8f9; text-align: center;">
                            <p style="margin: 0 0 10px 0; color: #155e75; font-size: 14px; line-height: 1.7;">
                                Mit freundlichen Grüßen,<br>
                                <strong style="color: #164e63; font-size: 16px;">IZENIC</strong>
                            </p>
                            <p style="margin: 20px 0 0 0; color: #0e7490; font-size: 14px; line-height: 1.7; font-weight: 500;">
                                kontakt@izenic.com
                            </p>
                            <p style="margin: 20px 0 0 0; color: #67e8f9; font-size: 12px;">
                                Diese E-Mail wurde automatisch generiert. Bitte antworten Sie nicht auf diese E-Mail.
                            </p>
                        </td>
                    </tr>
                </table>
            </td>
        </tr>
    </table>
</body>
</html>
"""


def _get_email_text(verify_link: str) -> str:
    """Get plain text email content"""
    return f"""IZENIC - E-Mail-Verifizierung

Willkommen bei IZENIC!

Vielen Dank für Ihre Registrierung. Um Ihr Konto zu aktivieren, bestätigen Sie bitte Ihre E-Mail-Adresse, indem Sie auf den folgenden Link klicken:

{verify_link}

WICHTIG: Dieser Link ist 1 Stunde gültig. Falls der Link abgelaufen ist, registrieren Sie sich bitte erneut.

Mit freundlichen Grüßen,
IZENIC

kontakt@izenic.com

Diese E-Mail wurde automatisch generiert. Bitte antworten Sie nicht auf diese E-Mail."""


def _send_via_sendgrid_api(to_email: str, token: str, api_key: str = None):
    """Send email using SendGrid API (preferred method) - using official SendGrid pattern"""
    try:
        import os
        from sendgrid import SendGridAPIClient
        from sendgrid.helpers.mail import Mail
        
        # Get API key: use provided key, then settings, then environment variable (like SendGrid example)
        sendgrid_api_key = api_key or settings.SENDGRID_API_KEY or os.environ.get('SENDGRID_API_KEY')
        
        # Debug: Check if API key is set (without logging the actual key)
        if not sendgrid_api_key:
            logger.error("❌ SendGrid API key is None or empty")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="SendGrid API key is not configured. Please set SENDGRID_API_KEY environment variable."
            )
        
        # Check if API key looks valid (starts with SG. and has reasonable length)
        sendgrid_api_key = sendgrid_api_key.strip()
        if not sendgrid_api_key.startswith('SG.'):
            logger.error(f"❌ SendGrid API key does not start with 'SG.' (starts with: {sendgrid_api_key[:5] if len(sendgrid_api_key) > 5 else 'too short'}...)")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="SendGrid API key format is invalid. It should start with 'SG.'"
            )
        
        if len(sendgrid_api_key) < 50:
            logger.error(f"❌ SendGrid API key seems too short (length: {len(sendgrid_api_key)})")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="SendGrid API key seems invalid (too short)."
            )
        
        logger.info(f"📧 Sending verification email via SendGrid API to: {to_email}")
        logger.info(f"🔑 Using SendGrid API key (length: {len(sendgrid_api_key)}, starts with: {sendgrid_api_key[:5]}...)")
        
        verify_link = _get_verification_link(token)
        logger.info(f"🔗 Verifizierungs-Link: {verify_link}")
        
        from_email = settings.SMTP_FROM_EMAIL.strip() if settings.SMTP_FROM_EMAIL and settings.SMTP_FROM_EMAIL.strip() else "kontakt@izenic.com"
        logger.info(f"📮 From email: {from_email}")
        
        # Check if from_email is verified in SendGrid
        if not from_email or from_email == "kontakt@izenic.com":
            logger.warning("⚠️ Using default from_email. Make sure 'kontakt@izenic.com' is verified in SendGrid!")
        
        # Get email content
        html_content = _get_email_html(verify_link)
        text_content = _get_email_text(verify_link)
        
        # Create Mail object (exactly like SendGrid example)
        message = Mail(
            from_email=from_email,
            to_emails=to_email,
            subject="E-Mail-Verifizierung – IZENIC",
            html_content=html_content,
            plain_text_content=text_content
        )
        
        # Send via SendGrid API (exactly like SendGrid example)
        sg = SendGridAPIClient(sendgrid_api_key)
        # sg.set_sendgrid_data_residency("eu")  # Uncomment if using EU subuser
        response = sg.send(message)
        
        logger.info(f"✅ Verification email sent successfully via SendGrid API to {to_email}")
        logger.info(f"📊 Response Status: {response.status_code}")
        logger.info(f"📊 Response Body: {response.body}")
        logger.info(f"📊 Response Headers: {response.headers}")
        
    except ImportError:
        logger.error("❌ SendGrid library not installed. Install with: pip install sendgrid")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="SendGrid library not installed. Please install sendgrid package."
        )
    except Exception as e:
        error_msg = str(e)
        error_type = type(e).__name__
        logger.error(f"❌ SendGrid API error: {error_msg}")
        logger.error(f"❌ Error type: {error_type}")
        
        # Provide more specific error messages
        if "401" in error_msg or "Unauthorized" in error_msg or "UnauthorizedError" in error_type:
            logger.error("❌ SendGrid API Key is invalid or missing permissions")
            logger.error("💡 Solution: Create a new API Key in SendGrid with 'Full Access' or 'Mail Send' permissions")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="SendGrid API authentication failed. Please check your API key configuration."
            )
        elif "403" in error_msg or "Forbidden" in error_msg:
            logger.error("❌ SendGrid API Key lacks required permissions")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="SendGrid API key does not have required permissions. Please ensure it has 'Mail Send' access."
            )
        
        import traceback
        logger.error(f"❌ Traceback: {traceback.format_exc()}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to send verification email via SendGrid API. Please try again later."
        )


def _send_via_smtp(to_email: str, token: str):
    """Send email using SMTP (fallback method)"""
    if not settings.SMTP_HOST or not settings.SMTP_PORT or not settings.SMTP_USER or not settings.SMTP_PASSWORD:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="SMTP configuration incomplete. Please set SMTP_HOST, SMTP_PORT, SMTP_USER, and SMTP_PASSWORD."
        )
    
    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = "E-Mail-Verifizierung – IZENIC"
        # Verwende SMTP_FROM_EMAIL falls gesetzt, sonst SMTP_USER
        from_email = settings.SMTP_FROM_EMAIL.strip() if settings.SMTP_FROM_EMAIL and settings.SMTP_FROM_EMAIL.strip() else settings.SMTP_USER
        msg["From"] = from_email
        msg["To"] = to_email
        
        logger.info(f"📧 Sending verification email from: {from_email} to: {to_email}")

        verify_link = _get_verification_link(token)
        logger.info(f"🔗 Verifizierungs-Link: {verify_link}")

        # Get email content
        html = _get_email_html(verify_link)
        text = _get_email_text(verify_link)

        msg.attach(MIMEText(text, "plain", "utf-8"))
        msg.attach(MIMEText(html, "html", "utf-8"))

        logger.info(f"🔌 Connecting to SMTP server: {settings.SMTP_HOST}:{settings.SMTP_PORT}")
        # Set timeout to prevent hanging (10 seconds)
        server = smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT, timeout=10)
        logger.info(f"✅ Connected to SMTP server")
        
        logger.info(f"🔐 Starting TLS...")
        server.starttls()
        logger.info(f"✅ TLS started")
        
        logger.info(f"🔑 Logging in as {settings.SMTP_USER}...")
        server.login(settings.SMTP_USER, settings.SMTP_PASSWORD)
        logger.info(f"✅ Logged in successfully")
        
        logger.info(f"📤 Sending email to {to_email}...")
        result = server.sendmail(from_email, to_email, msg.as_string())
        server.quit()
        
        if result:
            logger.warning(f"⚠️ SMTP server returned errors: {result}")
        else:
            logger.info(f"✅ Verification email sent successfully to {to_email} from {from_email}")
        
    except smtplib.SMTPConnectError as e:
        logger.error(f"❌ SMTP connection error: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not connect to email server. Please contact support."
        )
    except (socket.timeout, TimeoutError) as e:
        logger.error(f"❌ SMTP timeout error: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Email server timeout. Please try again later."
        )
    except smtplib.SMTPAuthenticationError as e:
        logger.error(f"❌ SMTP authentication failed for {settings.SMTP_USER}: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Email configuration error. Please contact support."
        )
    except smtplib.SMTPException as e:
        logger.error(f"❌ SMTP error sending email to {to_email}: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to send verification email. Please try again later."
        )
    except Exception as e:
        logger.error(f"❌ Unexpected error sending email to {to_email}: {str(e)}")
        logger.error(f"❌ Error type: {type(e).__name__}")
        import traceback
        logger.error(f"❌ Traceback: {traceback.format_exc()}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An unexpected error occurred. Please try again later."
        )
