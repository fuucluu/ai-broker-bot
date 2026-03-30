import requests

def send_report(state):
    api_key = "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"

    url = "https://api.sendgrid.com/v3/mail/send"

    body = f"""
AI Broker Daily Report

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

    data = {
        "personalizations": [
            {
                "to": [{"email": "james.diedrich.23@gmail.com"}],
                "subject": "📊 AI Broker Daily Report"
            }
        ],
        "from": {"email": "james.diedrich.23@gmail.com"},
        "content": [
            {
                "type": "text/plain",
                "value": body
            }
        ]
    }

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }

    try:
        response = requests.post(url, json=data, headers=headers)

        if response.status_code == 202:
            print("✅ Email sent via SendGrid")
        else:
            print(f"❌ SendGrid failed: {response.text}")

    except Exception as e:
        print(f"🚨 SendGrid error: {e}")
