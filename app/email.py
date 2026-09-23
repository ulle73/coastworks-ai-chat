from email.message import EmailMessage

import aiosmtplib

from app.config import settings


async def send_claim(email, token):
    message = EmailMessage()
    message["From"] = settings.EMAIL_FROM
    message["To"] = email
    message["Subject"] = "Din assistent är redo att flytta in"
    message.set_content(
        "Bekräfta din e-post och hämta koden till din hemsida:\n\n"
        f"{settings.APP_ORIGIN}/#confirm={token}\n\n"
        "Länken gäller i 15 minuter och kan bara användas en gång. "
        "Om du inte bad om den kan du ignorera det här mejlet."
    )
    await aiosmtplib.send(
        message,
        hostname=settings.SMTP_HOST,
        port=settings.SMTP_PORT,
        username=settings.SMTP_USERNAME or None,
        password=settings.SMTP_PASSWORD or None,
        start_tls=settings.SMTP_STARTTLS,
        timeout=15,
    )
