import smtplib
import ssl
import time
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from app.config import settings

SMTP_HOST = "smtp.forwardemail.net"
SMTP_PORT = 465


def send_welcome_email(
    slug: str,
    smtp_pass: str,
    wp_admin_password: str,
    client_email: str,
    delay: int = 8,
) -> None:
    """Envoie l'email de bienvenue depuis slug@BASE_DOMAIN vers client_email."""
    time.sleep(delay)

    from_addr = f"{slug}@{settings.BASE_DOMAIN}"
    site_url = f"https://{slug}.{settings.BASE_DOMAIN}"
    wp_admin_url = f"{site_url}/wp-admin"
    portal_url = f"https://portail.{settings.BASE_DOMAIN}"

    subject = f"Votre site WordPress {slug}.{settings.BASE_DOMAIN} est prêt !"

    html = f"""\
<!DOCTYPE html>
<html lang="fr">
<head><meta charset="UTF-8"></head>
<body style="font-family:sans-serif;max-width:600px;margin:auto;padding:24px;color:#333">
  <h2 style="color:#1a1a1a">Votre site WordPress est en ligne !</h2>
  <p>Tout est configuré et prêt à utiliser.</p>

  <table style="width:100%;border-collapse:collapse;margin:24px 0">
    <tr style="background:#f5f5f5">
      <td style="padding:10px 14px;font-weight:bold">Site</td>
      <td style="padding:10px 14px"><a href="{site_url}">{site_url}</a></td>
    </tr>
    <tr>
      <td style="padding:10px 14px;font-weight:bold">Administration</td>
      <td style="padding:10px 14px"><a href="{wp_admin_url}">{wp_admin_url}</a></td>
    </tr>
    <tr style="background:#f5f5f5">
      <td style="padding:10px 14px;font-weight:bold">Identifiant</td>
      <td style="padding:10px 14px"><code>{slug}</code></td>
    </tr>
    <tr>
      <td style="padding:10px 14px;font-weight:bold">Mot de passe</td>
      <td style="padding:10px 14px"><code>{wp_admin_password}</code></td>
    </tr>
    <tr style="background:#f5f5f5">
      <td style="padding:10px 14px;font-weight:bold">Email</td>
      <td style="padding:10px 14px"><code>{from_addr}</code></td>
    </tr>
  </table>

  <p>
    Par mesure de sécurité, nous vous recommandons de changer votre mot de passe
    dès votre première connexion. Rendez-vous sur le portail avec votre adresse
    <strong>{from_addr}</strong> et cliquez sur <em>Mot de passe oublié ?</em> :
  </p>
  <p style="margin:20px 0">
    <a href="{portal_url}" style="background:#a00000;color:#fff;padding:12px 24px;border-radius:6px;text-decoration:none;font-weight:bold">
      Accéder au portail
    </a>
  </p>

  <p style="color:#888;font-size:13px;margin-top:32px">
    Ce message a été envoyé automatiquement par MonMiniLab.
  </p>
</body>
</html>"""

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = from_addr
    msg["To"] = client_email
    msg.attach(MIMEText(html, "html", "utf-8"))

    ctx = ssl.create_default_context()
    with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, context=ctx) as server:
        server.login(from_addr, smtp_pass)
        server.sendmail(from_addr, [client_email], msg.as_bytes())
