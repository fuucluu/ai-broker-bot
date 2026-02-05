#!/usr/bin/env python3
"""
AI Broker - Automated Paper Trading System
==========================================

PAPER MODE ONLY - This system is designed exclusively for paper trading.
No real money is at risk. All trades are simulated via Alpaca paper trading.

Usage:
    python main.py

Kill switch:
    Create a file named 'STOP_TRADING' in the project root to halt new trades.

Environment variables required:
    ALPACA_API_KEY      - Your Alpaca API key
    ALPACA_API_SECRET   - Your Alpaca API secret

Optional:
    NEWSAPI_KEY         - NewsAPI key for news intelligence (if enabled)

"""
import os
import sys

def main():
    # Pre-flight safety checks
    print("\n" + "="*60)
    print("    AI BROKER - PAPER TRADING SYSTEM")
    print("    ⚠️  PAPER MODE ONLY - NO REAL MONEY ⚠️")
    print("="*60 + "\n")
    
    # Check for ALLOW_LIVE (must abort if set)
    if os.environ.get('ALLOW_LIVE', '').lower() in ('true', '1', 'yes'):
        print("❌ FATAL: ALLOW_LIVE environment variable detected!")
        print("   This system is PAPER-ONLY and cannot be run in live mode.")
        print("   Remove ALLOW_LIVE from your environment and try again.")
        sys.exit(1)
    
    # Check for required environment variables
    api_key = os.environ.get('ALPACA_API_KEY', '')
    api_secret = os.environ.get('ALPACA_API_SECRET', '')
    
    if not api_key or not api_secret:
        print("❌ Missing required environment variables:")
        if not api_key:
            print("   - ALPACA_API_KEY")
        if not api_secret:
            print("   - ALPACA_API_SECRET")
        print("\nSet these variables and try again.")
        print("Example (Linux/Mac):")
        print("  export ALPACA_API_KEY='your_key'")
        print("  export ALPACA_API_SECRET='your_secret'")
        print("\nExample (Windows PowerShell):")
        print("  $env:ALPACA_API_KEY='your_key'")
        print("  $env:ALPACA_API_SECRET='your_secret'")
        sys.exit(1)
    
    # Check Python version
    if sys.version_info < (3, 10):
        print(f"❌ Python 3.10+ required (you have {sys.version})")
        sys.exit(1)
    
    print("✅ Environment checks passed")
    print("✅ Starting AI Broker in PAPER MODE...")
    print()
    
    # Import and run
    try:
        from engine.runtime import TradingEngine
        engine = TradingEngine()
        engine.run()
    except KeyboardInterrupt:
        print("\n\nShutdown requested. Goodbye!")
    except Exception as e:
        print(f"\n❌ Fatal error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    main()
