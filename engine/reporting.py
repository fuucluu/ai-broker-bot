"""Reporting module for daily and weekly reports."""
import json
import csv
import logging
from pathlib import Path
from datetime import datetime, timedelta
from typing import Dict, List
from engine.persistence import Database
from engine.utils import get_project_root

logger = logging.getLogger("ai_broker.reporting")

class ReportGenerator:
    def __init__(self, db: Database, config: Dict):
        self.db = db
        self.config = config.get('reporting', {})
        self.reports_dir = get_project_root() / self.config.get('reports_dir', 'reports')
        self.reports_dir.mkdir(exist_ok=True)
        self._last_daily_report: str = ""
        self._last_weekly_report: str = ""
    
    def generate_daily_report(self, portfolio_summary: Dict, 
                             risk_status: Dict, model_stats: Dict) -> Dict:
        """Generate daily report."""
        today = datetime.now().strftime('%Y-%m-%d')
        
        # Skip if already generated today
        if today == self._last_daily_report:
            return {}
        
        daily_stats = self.db.get_daily_stats(today)
        cluster_stats = self.db.get_all_cluster_stats()
        
        report = {
            'date': today,
            'generated_at': datetime.now().isoformat(),
            'type': 'daily',
            'summary': {
                'equity': portfolio_summary.get('equity', 0),
                'daily_pnl': portfolio_summary.get('daily_pnl', 0),
                'daily_pnl_pct': (portfolio_summary.get('daily_pnl', 0) / 
                                 portfolio_summary.get('equity', 1)) * 100 if portfolio_summary.get('equity') else 0,
                'trades': daily_stats.get('trades', 0) if daily_stats else 0,
                'wins': daily_stats.get('wins', 0) if daily_stats else 0,
                'losses': daily_stats.get('losses', 0) if daily_stats else 0,
                'win_rate': (daily_stats.get('wins', 0) / daily_stats.get('trades', 1) * 100 
                            if daily_stats and daily_stats.get('trades') else 0),
                'best_trade': daily_stats.get('best_trade', 0) if daily_stats else 0,
                'worst_trade': daily_stats.get('worst_trade', 0) if daily_stats else 0
            },
            'risk': {
                'daily_loss_limit_used_pct': risk_status.get('loss_pct_used', 0),
                'trades_used': f"{risk_status.get('trades_today', 0)}/{risk_status.get('max_trades', 5)}",
                'positions': f"{risk_status.get('open_positions', 0)}/{risk_status.get('max_positions', 5)}",
                'kill_switch': risk_status.get('kill_switch', False)
            },
            'model': model_stats,
            'top_clusters': cluster_stats[:5] if cluster_stats else [],
            'positions': portfolio_summary.get('positions', [])
        }
        
        # Save JSON
        json_path = self.reports_dir / f"daily_{today}.json"
        with open(json_path, 'w') as f:
            json.dump(report, f, indent=2, default=str)
        
        # Save CSV summary
        csv_path = self.reports_dir / f"daily_{today}.csv"
        self._save_daily_csv(csv_path, report)
        
        self._last_daily_report = today
        logger.info(f"Daily report generated: {json_path}")
        
        return report
    
    def _save_daily_csv(self, path: Path, report: Dict):
        """Save daily report as CSV."""
        with open(path, 'w', newline='') as f:
            writer = csv.writer(f)
            writer.writerow(['Metric', 'Value'])
            writer.writerow(['Date', report['date']])
            
            for key, value in report['summary'].items():
                if isinstance(value, float):
                    writer.writerow([key, f"{value:.2f}"])
                else:
                    writer.writerow([key, value])
    
    def generate_weekly_report(self, portfolio_summary: Dict) -> Dict:
        """Generate weekly report."""
        today = datetime.now()
        week_start = (today - timedelta(days=today.weekday())).strftime('%Y-%m-%d')
        
        # Skip if already generated this week
        if week_start == self._last_weekly_report:
            return {}
        
        # Aggregate daily stats for the week
        cursor = self.db.conn.cursor()
        cursor.execute('''
            SELECT 
                SUM(trades) as total_trades,
                SUM(wins) as total_wins,
                SUM(losses) as total_losses,
                SUM(pnl) as total_pnl,
                MAX(best_trade) as best_trade,
                MIN(worst_trade) as worst_trade
            FROM daily_stats
            WHERE date >= ?
        ''', (week_start,))
        
        row = cursor.fetchone()
        
        # Get all cluster stats
        cluster_stats = self.db.get_all_cluster_stats()
        
        report = {
            'week_start': week_start,
            'generated_at': datetime.now().isoformat(),
            'type': 'weekly',
            'summary': {
                'equity': portfolio_summary.get('equity', 0),
                'weekly_pnl': row[3] if row and row[3] else 0,
                'total_trades': row[0] if row and row[0] else 0,
                'total_wins': row[1] if row and row[1] else 0,
                'total_losses': row[2] if row and row[2] else 0,
                'win_rate': (row[1] / row[0] * 100 if row and row[0] else 0),
                'best_trade': row[4] if row and row[4] else 0,
                'worst_trade': row[5] if row and row[5] else 0
            },
            'cluster_performance': cluster_stats,
            'symbol_performance': self._get_symbol_performance()
        }
        
        # Save JSON
        json_path = self.reports_dir / f"weekly_{week_start}.json"
        with open(json_path, 'w') as f:
            json.dump(report, f, indent=2, default=str)
        
        # Save CSV
        csv_path = self.reports_dir / f"weekly_{week_start}.csv"
        self._save_weekly_csv(csv_path, report)
        
        self._last_weekly_report = week_start
        logger.info(f"Weekly report generated: {json_path}")
        
        return report
    
    def _save_weekly_csv(self, path: Path, report: Dict):
        """Save weekly report as CSV."""
        with open(path, 'w', newline='') as f:
            writer = csv.writer(f)
            writer.writerow(['Metric', 'Value'])
            writer.writerow(['Week Start', report['week_start']])
            
            for key, value in report['summary'].items():
                if isinstance(value, float):
                    writer.writerow([key, f"{value:.2f}"])
                else:
                    writer.writerow([key, value])
            
            writer.writerow([])
            writer.writerow(['Symbol Performance'])
            writer.writerow(['Symbol', 'Trades', 'Wins', 'Losses', 'PnL', 'Win Rate'])
            
            for sym in report.get('symbol_performance', []):
                win_rate = sym['wins'] / sym['total_trades'] * 100 if sym['total_trades'] > 0 else 0
                writer.writerow([
                    sym['symbol'],
                    sym['total_trades'],
                    sym['wins'],
                    sym['losses'],
                    f"{sym['total_pnl']:.2f}",
                    f"{win_rate:.1f}%"
                ])
    
    def _get_symbol_performance(self) -> List[Dict]:
        """Get symbol-level performance stats."""
        cursor = self.db.conn.cursor()
        cursor.execute('''
            SELECT symbol, total_trades, wins, losses, total_pnl
            FROM symbol_stats
            ORDER BY total_pnl DESC
        ''')
        
        return [
            {
                'symbol': row[0],
                'total_trades': row[1],
                'wins': row[2],
                'losses': row[3],
                'total_pnl': row[4]
            }
            for row in cursor.fetchall()
        ]
    
    def should_generate_daily(self) -> bool:
        """Check if should generate daily report."""
        hour = self.config.get('daily_report_hour', 16)
        now = datetime.now()
        today = now.strftime('%Y-%m-%d')
        
        return (now.hour >= hour and 
                today != self._last_daily_report)
    
    def should_generate_weekly(self) -> bool:
        """Check if should generate weekly report."""
        day = self.config.get('weekly_report_day', 5)  # Friday
        now = datetime.now()
        week_start = (now - timedelta(days=now.weekday())).strftime('%Y-%m-%d')
        
        return (now.weekday() == day and 
                week_start != self._last_weekly_report)


def print_dashboard(portfolio: Dict, risk: Dict, model: Dict, news: Dict = None):
    """Print console dashboard."""
    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    
    print("\n" + "="*70)
    print(f"  AI BROKER DASHBOARD - PAPER MODE | {now}")
    print("="*70)
    
    # Portfolio section
    print("\n📊 PORTFOLIO")
    print(f"  Equity:        ${portfolio.get('equity', 0):,.2f}")
    print(f"  Cash:          ${portfolio.get('cash', 0):,.2f}")
    print(f"  Exposure:      {portfolio.get('exposure_pct', 0):.1f}%")
    print(f"  Unrealized:    ${portfolio.get('unrealized_pnl', 0):,.2f}")
    print(f"  Daily P&L:     ${portfolio.get('daily_pnl', 0):,.2f}")
    
    # Positions
    positions = portfolio.get('positions', [])
    if positions:
        print(f"\n  Positions ({len(positions)}):")
        for p in positions[:5]:
            pnl_color = "+" if p['unrealized_pnl'] >= 0 else ""
            print(f"    {p['symbol']:6} {p['side']:5} {p['qty']:>5} @ ${p['entry_price']:.2f} "
                  f"→ ${p['current_price']:.2f} ({pnl_color}{p['unrealized_pnl_pct']:.1f}%)")
    
    # Risk section
    print("\n⚠️  RISK STATUS")
    status = "✅ CAN TRADE" if risk.get('can_trade') else f"❌ {risk.get('reason', 'BLOCKED')}"
    print(f"  Status:        {status}")
    print(f"  Daily Loss:    {risk.get('loss_pct_used', 0):.1f}% of limit used")
    print(f"  Trades Today:  {risk.get('trades_today', 0)}/{risk.get('max_trades', 5)}")
    print(f"  Positions:     {risk.get('open_positions', 0)}/{risk.get('max_positions', 5)}")
    
    if risk.get('kill_switch'):
        print("  🛑 KILL SWITCH ACTIVE")
    
    if risk.get('paused_symbols'):
        print(f"  Paused:        {', '.join(risk['paused_symbols'])}")
    
    # Model section
    print("\n🧠 AI MODEL")
    print(f"  Trained:       {'Yes' if model.get('trained') else 'No (collecting samples)'}")
    print(f"  Samples:       {model.get('samples', 0)}")
    print(f"  Clusters:      {model.get('n_clusters', 12)}")
    
    # News section (if enabled)
    if news and news.get('enabled'):
        print("\n📰 NEWS")
        print(f"  Status:        {'Active' if news.get('enabled') else 'Disabled'}")
        print(f"  Risk Adj:      {news.get('risk_adjustment', 1.0):.0%}")
        if news.get('blocked_symbols'):
            print(f"  Blocked:       {', '.join(news['blocked_symbols'])}")
    
    print("\n" + "="*70)
