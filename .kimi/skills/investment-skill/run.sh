#!/bin/bash
# Investment Agent - UV wrapper script
# Usage: ./run.sh [fund-monitor|macro-liquidity|daily-summary|semi-tracker|all]

cd "$(dirname "$0")"

COMMAND=${1:-all}

case $COMMAND in
    fund-monitor|fm)
        echo "🔍 Running Fund Monitor..."
        uv run python __main__.py fund-monitor
        ;;
    macro-liquidity|ml)
        echo "🌍 Running Macro Liquidity Monitor..."
        uv run python __main__.py macro-liquidity
        ;;
    daily-summary|ds)
        echo "📰 Running Daily Summary..."
        uv run python __main__.py daily-summary
        ;;
    semi-tracker|st)
        echo "🔬 Running Semiconductor Tracker..."
        uv run python __main__.py semi-tracker
        ;;
    test)
        echo "🧪 Running tests..."
        uv run python test.py
        ;;
    all|*)
        echo "🚀 Running all skills..."
        uv run python __main__.py
        ;;
esac
