# Investment Agent Skill

An intelligent investment analysis system for Obsidian vault integration.

## Quick Start

### 1. Install Dependencies

```bash
# Install Python dependencies
pip install akshare yfinance playwright pyyaml jinja2 pandas requests

# Install Playwright browser
playwright install chromium
```

### 2. Configure Your Portfolio

Edit `config/portfolio.yaml` to add your fund holdings:

```yaml
portfolio:
  funds:
    - code: "019455"
      name: "华泰柏瑞中韩半导体ETF联接C"
      category: "semiconductor"
      shares: 1000          # Your actual holdings
      cost_basis: 1.50     # Your average cost per share
```

### 3. Run Analysis

```bash
# Run all skills
python ~/investment-skill

# Or specific skill
python ~/investment-skill fund-monitor
python ~/investment-skill macro-liquidity
python ~/investment-skill daily-summary
python ~/investment-skill semi-tracker
```

### 4. Install as Claude Code Skill

```bash
# Create symlink to Claude Code skills directory
ln -s ~/investment-skill ~/.claude/skills/investment-agent

# Now you can use in Claude Code:
/fund-monitor
/macro-liquidity
/daily-summary
/semi-tracker
/investment-daily
```

## Features

### 📊 Fund Monitor (`/fund-monitor`)

- Track all 12 portfolio funds automatically
- Calculate P&L based on your holdings
- Detect significant price movements
- Alert on consecutive declines
- Auto-save reports to vault

**Alerts:**
- Daily decline > 3%
- Daily surge > 5%
- 3+ consecutive down days
- Deviation from benchmark > 5%

### 🌍 Macro Liquidity (`/macro-liquidity`)

- Monitor Fed balance sheet changes
- Track US Dollar Index (DXY)
- Watch Treasury yields and yield curve
- Monitor SOFR rate
- Track gold prices
- Assess portfolio impact

**Alerts:**
- Fed balance sheet contraction > 5%
- SOFR > 5.5%
- DXY > 105 (strong USD)
- Yield curve inversion
- Gold price moves > 3%

### 📰 Daily Summary (`/daily-summary`)

- Global market overview (US, HK, CN)
- Portfolio performance summary
- Key news highlights
- Today's watchlist
- Strategy notes
- Links to related vault notes

### 🔬 Semiconductor Tracker (`/semi-tracker`)

- SOX index analysis
- Major chip stock tracking (NVDA, AMD, etc.)
- Memory price trends (weekly)
- Correlation with portfolio funds
- Technical analysis (support/resistance)
- Trend assessment

## Data Sources

| Source | Type | Coverage |
|--------|------|----------|
| **EastMoney** | Web scraping | A-share funds, NAV data |
| **AKShare** | Python SDK | Chinese markets, macro data |
| **Yahoo Finance** | Python SDK | Global markets, US stocks, commodities |
| **Federal Reserve** | API | Macro indicators, yields |

All data sources are **FREE** to use.

## Vault Integration

### Automatic File Creation

**Daily Reports:**
```
vault-notes/daily/
├── 2026-02-22_investment.md        # Daily summary
├── 2026-02-22_fund_report.md       # Fund monitoring
└── 2026-02-22_fund_alert.md        # Alerts only
```

**Knowledge Base:**
```
vault-notes/knowledge/investment/
├── portfolio/
│   └── current_allocation.md
├── macro/
│   └── liquidity_2026-02.md
└── industries/
    └── semiconductor/
        ├── daily_analysis_2026-02-22.md
        └── weekly_analysis_2026-W08.md
```

### Wiki-Links

Reports automatically include links:
- `[[knowledge/investment/portfolio/allocation|Portfolio]]`
- `[[knowledge/investment/macro/|Macro Analysis]]`
- `[[knowledge/investment/industries/semiconductor/|Semiconductor]]`

## Configuration

### Data Sources (`config/sources.yaml`)

Configure which data sources to use and rate limiting:

```yaml
sources:
  fund_data:
    primary: "eastmoney"
    backup: "akshare"
    
  rate_limit:
    enabled: true
    default_delay: 1.0
```

### Alert Thresholds (`config/portfolio.yaml`)

Customize alert levels:

```yaml
alerts:
  daily_decline_threshold: -3.0    # Adjust as needed
  daily_surge_threshold: 5.0
  consecutive_decline_days: 3
```

## Automation

### macOS LaunchAgent

Create `~/Library/LaunchAgents/com.investment.agent.plist`:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.investment.agent</string>
    <key>ProgramArguments</key>
    <array>
        <string>/usr/local/bin/python3</string>
        <string>/Users/YOUR_USERNAME/investment-skill</string>
    </array>
    <key>StartCalendarInterval</key>
    <dict>
        <key>Hour</key>
        <integer>8</integer>
        <key>Minute</key>
        <integer>0</integer>
        <key>Weekday</key>
        <integer>1</integer> <!-- Monday -->
        <integer>2</integer> <!-- Tuesday -->
        <integer>3</integer> <!-- Wednesday -->
        <integer>4</integer> <!-- Thursday -->
        <integer>5</integer> <!-- Friday -->
    </dict>
    <key>StandardOutPath</key>
    <string>/Users/YOUR_USERNAME/.investment-skill/logs/agent.log</string>
    <key>StandardErrorPath</key>
    <string>/Users/YOUR_USERNAME/.investment-skill/logs/agent.error.log</string>
</dict>
</plist>
```

Load the agent:
```bash
launchctl load ~/Library/LaunchAgents/com.investment.agent.plist
```

### Cron (Linux/macOS)

```bash
# Edit crontab
crontab -e

# Add daily at 8 AM on weekdays
0 8 * * 1-5 cd ~/investment-skill && python3 . >> ~/.investment-skill/logs/cron.log 2>&1
```

## Command Reference

| Command | Description | Options |
|---------|-------------|---------|
| `python .` | Run all skills | `--quick` Skip detailed analysis |
| `python . fund-monitor` | Monitor funds | `--alert` Show only alerts |
| `python . macro-liquidity` | Macro analysis | `--alert` Show only alerts |
| `python . daily-summary` | Daily report | - |
| `python . semi-tracker` | Semiconductor tracking | `--weekly` Weekly deep dive |

## Troubleshooting

### Playwright Not Found

```bash
pip install playwright
playwright install chromium
```

### AKShare Errors

```bash
pip install --upgrade akshare
```

### Permission Denied

```bash
chmod +x ~/investment-skill/__main__.py
```

### Vault Not Found

Ensure `~/vault-notes` exists or set custom path:

```python
# In utils/vault_writer.py
vault = VaultWriter("/path/to/your/vault")
```

## Development

### Adding New Data Sources

1. Create collector in `collectors/`
2. Implement required methods:
   - `fetch_fund_data(code)`
   - `fetch_macro_data(indicator)`
3. Register in `config/sources.yaml`

### Adding New Skills

1. Create directory in `skills/`
2. Implement `run()` or `analyze()` method
3. Add CLI command in `__main__.py`
4. Update SKILL.md

### Testing

```bash
# Test individual collector
python -c "from collectors.eastmoney_collector import fetch_fund; print(fetch_fund('000216'))"

# Test skill
python -m skills.fund_monitor
```

## Architecture

```
┌─────────────────────────────────────────────────┐
│                 CLI Interface                    │
│            (__main__.py)                        │
└─────────────────────────────────────────────────┘
                        │
        ┌───────────────┼───────────────┐
        ▼               ▼               ▼
┌──────────────┐ ┌──────────────┐ ┌──────────────┐
│   Fund       │ │    Macro     │ │    Daily     │
│   Monitor    │ │   Liquidity  │ │   Summary    │
└──────────────┘ └──────────────┘ └──────────────┘
        │               │               │
        └───────────────┼───────────────┘
                        ▼
            ┌───────────────────┐
            │    Collectors     │
            ├─────────┬─────────┤
            │EastMoney│ Yahoo   │
            │AKShare  │  FRED   │
            └─────────┴─────────┘
                        │
                        ▼
            ┌───────────────────┐
            │  Vault Writer     │
            │  (Obsidian)       │
            └───────────────────┘
```

## License

Private use only. This is a personal investment tool.

## Support

For issues or feature requests, check:
- SKILL.md for detailed documentation
- Code comments for implementation details
- Sample configurations in `config/`

---

**Happy Investing! 📈**
