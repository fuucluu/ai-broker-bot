import smtplib
import time
from email.mime.text import MIMEText


def send_report(state):
    sender = "james.diedrich.23@gmail.com"
    password = "oxfzwfrvzzecormj"
    receiver = "james.diedrich.23@gmail.com"

    subject = "📊 AI Broker Daily Report"

    body = f"""
Equity: {state['equity']}
Cash: {state['cash']}
Daily PnL: {state['daily_pnl']}

Samples: {state['samples']}
Clusters: {state['clusters']}
Last Train: {state['last_train']}

Trades Today: {state['trades_today']} / {state['max_trades']}
Open Positions: {state['open_positions']}
Loss Used: {state['loss_pct_used']}%
"""

    msg = MIMEText(body)
    msg["Subject"] = subject
    msg["From"] = sender
    msg["To"] = receiver

    # 🔥 RETRY SYSTEM
    for attempt in range(3):
        try:
            with smtplib.SMTP("smtp.gmail.com", 587, timeout=10) as server:
                server.starttls()
                server.login(sender, password)
                server.send_message(msg)

            print("✅ Email sent successfully")
            return

        except Exception as e:
            print(f"❌ Email attempt {attempt+1} failed: {e}")
            time.sleep(5)

    print("🚨 Email FAILED after retries")
