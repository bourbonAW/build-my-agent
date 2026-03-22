# Quick Start Guide

## Installation

### 1. Install Python Dependencies

```bash
cd ~/investment-skill
pip install -r requirements.txt

# Install Playwright browser (for web scraping)
playwright install chromium
```

### 2. Configure Your Holdings

Edit `config/portfolio.yaml` and add your actual holdings:

```yaml
portfolio:
  funds:
    - code: "019455"
      name: "华泰柏瑞中韩半导体ETF联接C"
      category: "semiconductor"
      region: "asia"
      shares: 1000          # ← UPDATE: Your actual shares
      cost_basis: 1.50     # ← UPDATE: Your average cost per share
```

### 3. Test Installation

```bash
# Run component tests
python ~/investment-skill/test.py
```

### 4. Run Analysis

```bash
# Run all skills
python ~/investment-skill

# Or individual skills
python ~/investment-skill fund-monitor
python ~/investment-skill macro-liquidity
python ~/investment-skill daily-summary
python ~/investment-skill semi-tracker
```

## Usage in Claude Code

After installation, these commands are available:

```
/fund-monitor              # Monitor portfolio funds
/fund-monitor --alert      # Show only alerts

/macro-liquidity           # Check macro conditions
/macro-liquidity --alert   # Show only alerts

/daily-summary             # Generate daily report

/semi-tracker              # Track semiconductor
/semi-tracker --weekly     # Weekly deep dive

/investment-daily          # Run all skills
/investment-daily --quick  # Quick mode
```

## Directory Structure

```
~/investment-skill/
├── SKILL.md                    # Full documentation
├── README.md                   # This file
├── __main__.py                 # CLI entry point
├── test.py                     # Test script
├── requirements.txt            # Python dependencies
├── config/
│   ├── portfolio.yaml          # Your holdings ← EDIT THIS
│   └── sources.yaml            # Data sources
├── skills/                     # Core analysis modules
│   ├── fund_monitor/           # Portfolio monitoring
│   ├── macro_liquidity/        # Macro analysis
│   ├── daily_summary/          # Daily reports
│   └── semiconductor_tracker/  # Industry tracking
├── collectors/                 # Data collection
│   ├── eastmoney_collector.py  # Fund data
│   ├── akshare_collector.py    # Chinese markets
│   ├── yahoo_collector.py      # Global markets
│   └── macro_collector.py      # Macro indicators
└── utils/
    ├── vault_writer.py         # Obsidian integration
    └── data_cache.py           # Caching system
```

## Output Locations

All reports are automatically saved to your Obsidian vault:

**Daily Reports:**
- `~/vault-notes/daily/YYYY-MM-DD_investment.md`
- `~/vault-notes/daily/YYYY-MM-DD_fund_report.md`
- `~/vault-notes/daily/YYYY-MM-DD_fund_alert.md`

**Knowledge Base:**
- `~/vault-notes/knowledge/investment/macro/liquidity_YYYY-MM.md`
- `~/vault-notes/knowledge/investment/industries/semiconductor/daily_analysis_YYYY-MM-DD.md`

## Troubleshooting

### "ModuleNotFoundError: No module named 'akshare'"

```bash
pip install akshare
```

### "playwright not installed"

```bash
pip install playwright
playwright install chromium
```

### "No such file or directory: ~/vault-notes"

The vault should already exist at `~/vault-notes`. If not, create it:

```bash
mkdir -p ~/vault-notes/daily
mkdir -p ~/vault-notes/knowledge/investment
```

## Next Steps

1. ✅ Configure your holdings in `config/portfolio.yaml`
2. ✅ Run `python ~/investment-skill/test.py` to verify
3. ✅ Run `python ~/investment-skill` to generate first report
4. ✅ Open Obsidian and view reports in `daily/` folder
5. ✅ Set up automation (cron or LaunchAgent)

## Support

- See `SKILL.md` for detailed documentation
- Check code comments for implementation details
- Review example configurations in `config/`
