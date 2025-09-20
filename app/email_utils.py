import smtplib
from email.message import EmailMessage
import os
import secrets
from flask import session
from .models import db, Usuario
from app import db

def send_invitation_email(to_email, first_name, invite_url, expiration="48 horas", institution_name=None, role=None):
    EMAIL_ADDRESS = os.getenv('MAIL_USERNAME')
    EMAIL_PASSWORD = os.getenv('MAIL_PASSWORD')
    SMTP_SERVER = os.getenv('MAIL_SERVER', 'smtp.gmail.com')
    SMTP_PORT = int(os.getenv('MAIL_PORT', 587))

    # Cargar plantillas
    base_dir = os.path.join(os.path.dirname(__file__), 'templates/email_templates')
    html_path = os.path.join(base_dir, 'invitation.html')
    txt_path = os.path.join(base_dir, 'invitation.txt')

    # Preparar reemplazos para las plantillas
    replacements = {
        '{{ first_name }}': first_name,
        '{{ invite_url }}': invite_url,
        '{{ expiration }}': expiration,
        '{{ institution_name }}': institution_name or 'nuestra plataforma',
        '{{ role }}': role or 'usuario'
    }

    with open(html_path, encoding='utf-8') as f:
        html_body = f.read()
        for placeholder, value in replacements.items():
            html_body = html_body.replace(placeholder, value)

    with open(txt_path, encoding='utf-8') as f:
        text_body = f.read()
        for placeholder, value in replacements.items():
            text_body = text_body.replace(placeholder, value)

    msg = EmailMessage()
    # Personalizar subject según el contexto
    if institution_name and role:
        msg['Subject'] = f'Invitación para unirte a {institution_name} como {role}'
    else:
        msg['Subject'] = 'Invitación a registrarte'
    
    msg['From'] = EMAIL_ADDRESS
    msg['To'] = to_email

    msg.set_content(text_body)
    msg.add_alternative(html_body, subtype='html')

    try:
        with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as smtp:
            smtp.starttls()
            smtp.login(EMAIL_ADDRESS, EMAIL_PASSWORD)
            smtp.send_message(msg)
            print(f"[OK] Invitación enviada a {to_email}")
    except Exception as e:
        print(f"[ERROR] No se pudo enviar el email a {to_email}: {e}")
        raise  # Re-lanzar la excepción para que el código que llama pueda manejarla


def send_password_reset_email(to_email, first_name, reset_url, expiration="1 hora"):
    """
    Envía un email con el enlace para resetear la contraseña
    """
    EMAIL_ADDRESS = os.getenv('MAIL_USERNAME')
    EMAIL_PASSWORD = os.getenv('MAIL_PASSWORD')
    SMTP_SERVER = os.getenv('MAIL_SERVER', 'smtp.gmail.com')
    SMTP_PORT = int(os.getenv('MAIL_PORT', 587))

    # Cargar plantillas
    base_dir = os.path.join(os.path.dirname(__file__), 'templates/email_templates')
    html_path = os.path.join(base_dir, 'password_reset.html')
    txt_path = os.path.join(base_dir, 'password_reset.txt')

    # Preparar reemplazos para las plantillas
    replacements = {
        '{{ first_name }}': first_name,
        '{{ reset_url }}': reset_url,
        '{{ expiration }}': expiration
    }

    # Cargar template HTML
    with open(html_path, encoding='utf-8') as f:
        html_body = f.read()
        for placeholder, value in replacements.items():
            html_body = html_body.replace(placeholder, value)

    # Cargar template TXT
    with open(txt_path, encoding='utf-8') as f:
        text_body = f.read()
        for placeholder, value in replacements.items():
            text_body = text_body.replace(placeholder, value)

    msg = EmailMessage()
    msg['Subject'] = 'Restablece tu contraseña - EduConnect'
    msg['From'] = EMAIL_ADDRESS
    msg['To'] = to_email

    msg.set_content(text_body)
    msg.add_alternative(html_body, subtype='html')

    try:
        with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as smtp:
            smtp.starttls()
            smtp.login(EMAIL_ADDRESS, EMAIL_PASSWORD)
            smtp.send_message(msg)
            print(f"[OK] Email de reseteo enviado a {to_email}")
    except Exception as e:
        print(f"[ERROR] No se pudo enviar el email de reseteo a {to_email}: {e}")
        raise