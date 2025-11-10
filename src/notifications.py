import json
import smtplib
from email.message import EmailMessage
from typing import Dict, Optional
import urllib.request
import logging

LOG = logging.getLogger("miner-notifications")

def send_webhook(url: str, payload: Dict) -> bool:
    try:
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.getcode() in (200, 201, 202)
    except Exception as e:
        LOG.exception("Webhook send failed: %s", e)
        return False

def send_email(smtp_cfg: Dict, subject: str, body: str, recipients: Optional[list] = None) -> bool:
    try:
        msg = EmailMessage()
        msg["Subject"] = subject
        msg["From"] = smtp_cfg.get("from_addr")
        msg["To"] = ",".join(recipients or smtp_cfg.get("recipients", []))
        msg.set_content(body)

        host = smtp_cfg.get("host", "localhost")
        port = int(smtp_cfg.get("port", 25))
        user = smtp_cfg.get("user")
        password = smtp_cfg.get("password")
        use_tls = smtp_cfg.get("tls", False)

        if use_tls:
            s = smtplib.SMTP(host, port, timeout=10)
            s.starttls()
        else:
            s = smtplib.SMTP(host, port, timeout=10)

        if user and password:
            s.login(user, password)

        s.send_message(msg)
        s.quit()
        return True
    except Exception as e:
        LOG.exception("Email send failed: %s", e)
        return False

def notify_alerts(alerts: Dict, cfg: Dict) -> Dict:
    results = {"webhook": None, "email": None}
    payload = {"type": "miner_alert", "alerts": alerts}
    if not cfg:
        return results
    webhook = cfg.get("webhook_url") or cfg.get("slack_webhook")
    if webhook:
        results["webhook"] = send_webhook(webhook, payload)

    smtp = cfg.get("smtp")
    if smtp and smtp.get("enabled"):
        subject = smtp.get("subject", "Miner alerts")
        body = json.dumps(alerts, indent=2)
        recipients = smtp.get("recipients")
        results["email"] = send_email(smtp, subject, body, recipients)

    return results
