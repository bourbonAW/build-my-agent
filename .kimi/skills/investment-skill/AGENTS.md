# Agent Memory - Investment Skill

## Environment Preferences

### Package Management
- **优先使用**: `uv` (而非 pip/pip3)
- **安装依赖**: `uv pip install <package>`
- **运行脚本**: `uv run <script>`

### Key Commands
```bash
# Install dependencies
uv pip install yfinance akshare playwright

# Run monitoring scripts
cd ~/investment-skill && uv run python scripts/run_all_monitors.py

# Generate reports
uv run python scripts/generate_executive_summary.py
```

## Project Structure
- Main skill location: `~/investment-skill/`
- Reports output: `~/vault-notes/knowledge/investment/`
- Daily reports: `~/vault-notes/daily/`

## Important Notes
- All monitoring scripts should be run from `~/investment-skill/` directory
- PYTHONPATH needs to include project root for imports to work
- Reports are timestamped and should be checked for data completeness
