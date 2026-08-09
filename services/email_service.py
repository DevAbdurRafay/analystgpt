import os
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from dotenv import load_dotenv

load_dotenv()

# Read MAIL_* credentials from .env (with legacy SMTP_* fallbacks for compatibility)
MAIL_SERVER   = os.getenv("MAIL_SERVER")   or os.getenv("SMTP_HOST",     "smtp.gmail.com")
MAIL_PORT     = int(os.getenv("MAIL_PORT") or os.getenv("SMTP_PORT",     "587"))
MAIL_USE_TLS  = os.getenv("MAIL_USE_TLS",  "True").lower() not in ("false", "0", "no")
MAIL_USERNAME = os.getenv("MAIL_USERNAME") or os.getenv("SMTP_USER")
MAIL_PASSWORD = os.getenv("MAIL_PASSWORD") or os.getenv("SMTP_PASSWORD")
# Set exact Sender Name & Address to prevent spam flags
MAIL_FROM     = "AnalystGPT Security <analysis.workforce@gmail.com>"


def _build_html_email(code: str, purpose: str) -> str:
    """Returns a high-end styled dark-mode HTML email body for a 4-digit OTP verification code."""
    # Ensure digits stay in a single horizontal row with white-space: nowrap and inline-block table cells
    digits_cells = "".join(
        f'<td align="center" valign="middle" style="padding:0 4px;">'
        f'<div style="width:48px;height:56px;line-height:56px;text-align:center;font-size:28px;font-weight:800;'
        f'color:#06B6D4;background:#0f172a;border:2px solid #1e293b;border-radius:10px;'
        f'display:inline-block;letter-spacing:0;box-shadow:0 4px 12px rgba(6,182,212,0.15);">'
        f'{d}</div>'
        f'</td>'
        for d in code
    )
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Your AnalystGPT Security Verification Code</title>
</head>
<body style="margin:0;padding:0;background-color:#05070c;font-family:'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;color:#e2e8f0;">
  <table width="100%" cellpadding="0" cellspacing="0" style="min-height:100vh;background-color:#05070c;padding:32px 16px;">
    <tr>
      <td align="center">
        <table width="100%" cellpadding="0" cellspacing="0"
               style="background:#090d16;border:1px solid rgba(255,255,255,0.08);
                      border-radius:20px;overflow:hidden;max-width:500px;width:100%;box-shadow:0 20px 50px rgba(0,0,0,0.6);">
          <!-- Header -->
          <tr>
            <td style="background:linear-gradient(135deg,#06B6D4 0%,#10B981 100%);
                       padding:30px 32px;text-align:center;">
              <h1 style="margin:0;color:#090d16;font-size:22px;font-weight:900;
                         letter-spacing:-0.5px;text-transform:uppercase;">AnalystGPT</h1>
              <p style="margin:4px 0 0;color:rgba(9,13,22,0.85);font-size:12px;font-weight:600;letter-spacing:1px;text-transform:uppercase;">
                Security Verification
              </p>
            </td>
          </tr>
          <!-- Body -->
          <tr>
            <td style="padding:36px 32px;text-align:center;">
              <h2 style="margin:0 0 12px;color:#f8fafc;font-size:18px;font-weight:700;">
                Verification Code
              </h2>
              <p style="margin:0 0 24px;color:#94a3b8;font-size:14px;line-height:1.6;">
                Use the 4-digit security code below to complete your <strong style="color:#f1f5f9;">{purpose}</strong>.
                This code will expire in <strong style="color:#06B6D4;">2 minutes</strong>.
              </p>

              <!-- OTP 4-Digit Row Container (Strict Single Row) -->
              <div style="text-align:center;margin:0 0 28px;padding:16px 8px;background:rgba(255,255,255,0.02);border:1px solid rgba(255,255,255,0.05);border-radius:14px;white-space:nowrap;">
                <table align="center" cellpadding="0" cellspacing="0" style="margin:0 auto;border-collapse:collapse;white-space:nowrap;">
                  <tr>
                    {digits_cells}
                  </tr>
                </table>
              </div>

              <p style="margin:0 0 4px;color:#64748b;font-size:12px;line-height:1.5;">
                If you did not request this verification code, please safely disregard this email.
              </p>
            </td>
          </tr>
          <!-- Footer -->
          <tr>
            <td style="padding:20px 32px;border-top:1px solid rgba(255,255,255,0.06);
                       background:#070a11;text-align:center;">
              <p style="margin:0;color:#475569;font-size:11px;">
                &copy; 2026 AnalystGPT Security System &nbsp;&bull;&nbsp; All rights reserved
              </p>
            </td>
          </tr>
        </table>
      </td>
    </tr>
  </table>
</body>
</html>"""


class EmailService:
    @staticmethod
    def _dispatch_smtp(email: str, code: str, purpose: str):
        """Internal worker function executed in background thread."""
        subject = "Your AnalystGPT Security Verification Code"
        plain_body = (
            f"Hello,\n\n"
            f"Your 4-digit security verification code is: {code}\n\n"
            f"This code was generated for {purpose}. It expires in 2 minutes.\n"
            f"If you did not request this code, please safely ignore this email.\n\n"
            f"Best regards,\nAnalystGPT Security Team"
        )

        # Print to console for debugging log
        print("\n" + "=" * 50)
        print(" [ASYNC EMAIL DISPATCH OUTBOX]")
        print(f" FROM    : {MAIL_FROM}")
        print(f" TO      : {email}")
        print(f" SUBJECT : {subject}")
        print(f" CODE    : {code}")
        print("=" * 50 + "\n")

        if not MAIL_USERNAME or not MAIL_PASSWORD:
            print(" MAIL credentials missing in .env")
            return

        try:
            msg = MIMEMultipart("alternative")
            msg["From"]    = MAIL_FROM
            msg["To"]      = email
            msg["Subject"] = subject
            msg["Reply-To"] = "analysis.workforce@gmail.com"
            msg["X-Mailer"] = "AnalystGPT Mailer 1.0"
            msg["Auto-Submitted"] = "auto-generated"
            msg["List-Unsubscribe"] = "<mailto:analysis.workforce@gmail.com?subject=unsubscribe>"

            # Attach plain-text first, then HTML (MIME alternative)
            msg.attach(MIMEText(plain_body, "plain", "utf-8"))
            msg.attach(MIMEText(_build_html_email(code, purpose), "html", "utf-8"))

            server = smtplib.SMTP(MAIL_SERVER, MAIL_PORT)
            if MAIL_USE_TLS:
                server.starttls()
            server.login(MAIL_USERNAME, MAIL_PASSWORD)
            server.sendmail(MAIL_USERNAME, email, msg.as_string())
            server.quit()

            print(f" Async Email sent successfully to {email}")

        except Exception as exc:
            print(f" SMTP Error: could not send email to {email}. Reason: {exc}")

    @staticmethod
    def send_otp(email: str, code: str, purpose: str) -> bool:
        """Launches an asynchronous background thread for SMTP dispatch to prevent UI blocking."""
        import threading
        thread = threading.Thread(
            target=EmailService._dispatch_smtp,
            args=(email, code, purpose),
            daemon=True
        )
        thread.start()
        return True


email_service = EmailService()

