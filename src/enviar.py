"""Envía el PDF por correo (opcional). Variables: EMAIL_USER, EMAIL_PASS, EMAIL_TO.
EMAIL_TO admite varias direcciones separadas por coma; se envían en copia oculta (CCO),
así los suscriptores no ven las direcciones de los demás.
Con Gmail hay que crear una "contraseña de aplicación" (gratis) en la cuenta de Google."""
import os
import smtplib
import sys
from email.message import EmailMessage
from pathlib import Path

if __name__ == "__main__":
    ruta = Path(sys.argv[1]) if len(sys.argv) > 1 else None
    user, pw, to = (os.environ.get(k, "").strip() for k in ("EMAIL_USER", "EMAIL_PASS", "EMAIL_TO"))
    dest = [x.strip() for x in to.replace(";", ",").split(",") if x.strip()]
    if not (ruta and ruta.exists() and user and pw and dest):
        print("Envío por correo no configurado; se omite.")
        sys.exit(0)
    m = EmailMessage()
    m["From"], m["To"], m["Subject"] = user, user, f"Radar del mercado eléctrico · {ruta.stem}"
    m["Bcc"] = ", ".join(dest)
    m.set_content("Adjunto el informe semanal del mercado eléctrico, generado automáticamente a partir de datos públicos de ESIOS (REE) y OMIE.")
    m.add_attachment(ruta.read_bytes(), maintype="application", subtype="pdf", filename=ruta.name)
    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as s:
        s.login(user, pw)
        s.send_message(m)
    print(f"Correo enviado a {len(dest)} destinatario(s).")
