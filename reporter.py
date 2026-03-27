import smtplib
from email.mime.text import MIMEText
from datetime import datetime

def send_report(state):
    sender_email = "james.diedrich.23@gmail.com"
    receiver_email = "james.diedrich.23@gmail.com"
    app_password = "oxfzwfrvzzecormj"

    subject = "AI Broker Daily Report"

    body = f"""
AI BROKER REPORT
Time (UTC): {datetime.utcnow()}

-----------------------------
ACCOUNT
-----------------------------
Equity: {state['equity']}
Cash: {state['cash']}
Daily PnL: {state['daily_pnl']}

-----------------------------
MODEL
-----------------------------
Samples: {state['samples']}
Clusters: {state['clusters']}
Last Train: {state['last_train']}

-----------------------------
RISK
-----------------------------
Trades Today: {state['trades_today']} / {state['max_trades']}
Open Positions: {state['open_positions']}
Loss Used: {state['loss_pct_used']:.2f}%

-----------------------------
STATUS: OK
-----------------------------
"""

    msg = MIMEText(body)
    msg["Subject"] = subject
    msg["From"] = sender_email
    msg["To"] = receiver_email

    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(sender_email, app_password)
            server.send_message(msg)
        print("Email sent successfully.")
    except Exception as e:
        print("Email failed:", e)
