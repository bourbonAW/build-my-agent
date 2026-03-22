#!/usr/bin/env python3
"""
Test script for Investment Agent Skill
Quick verification that all components work
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

def test_imports():
    """Test that all imports work"""
    print("🔧 Testing imports...")
    
    try:
        from utils.vault_writer import VaultWriter
        print("  ✅ vault_writer")
    except Exception as e:
        print(f"  ❌ vault_writer: {e}")
    
    try:
        from utils.data_cache import DataCache
        print("  ✅ data_cache")
    except Exception as e:
        print(f"  ❌ data_cache: {e}")
    
    try:
        from collectors.eastmoney_collector import EastMoneyCollector
        print("  ✅ eastmoney_collector")
    except Exception as e:
        print(f"  ❌ eastmoney_collector: {e}")
    
    try:
        from collectors.yahoo_collector import YahooCollector
        print("  ✅ yahoo_collector")
    except Exception as e:
        print(f"  ❌ yahoo_collector: {e}")
    
    try:
        from collectors.macro_collector import MacroCollector
        print("  ✅ macro_collector")
    except Exception as e:
        print(f"  ❌ macro_collector: {e}")
    
    print()

def test_vault_writer():
    """Test vault writer"""
    print("📝 Testing Vault Writer...")
    
    try:
        from utils.vault_writer import VaultWriter
        writer = VaultWriter()
        
        # Test creating a sample entry
        test_content = """# Test Entry

This is a test entry to verify the vault writer works.
"""
        filepath = writer.write_daily_report(test_content, suffix="test")
        print(f"  ✅ Created test file: {filepath}")
        
        return True
    except Exception as e:
        print(f"  ❌ Error: {e}")
        return False

def test_cache():
    """Test data cache"""
    print("💾 Testing Data Cache...")
    
    try:
        from utils.data_cache import DataCache
        cache = DataCache()
        
        # Test set/get
        cache.set("test_key", {"value": 123}, ttl=60)
        result = cache.get("test_key")
        
        if result and result.get("value") == 123:
            print(f"  ✅ Cache working correctly")
        else:
            print(f"  ❌ Cache read/write failed")
        
        # Clean up
        cache.delete("test_key")
        
        return True
    except Exception as e:
        print(f"  ❌ Error: {e}")
        return False

def test_yahoo_collector():
    """Test Yahoo Finance collector"""
    print("📈 Testing Yahoo Finance Collector...")
    
    try:
        from collectors.yahoo_collector import get_yahoo_collector
        collector = get_yahoo_collector()
        
        if collector is None:
            print("  ⚠️  yfinance not installed, skipping")
            return None
        
        # Test fetching S&P 500
        data = collector.get_index_data('SPX')
        if data:
            print(f"  ✅ S&P 500: {data.get('close', 'N/A')} ({data.get('change_pct', 0):+.2f}%)")
            return True
        else:
            print(f"  ⚠️  Could not fetch data (may need network)")
            return None
            
    except Exception as e:
        print(f"  ❌ Error: {e}")
        return False

def test_configuration():
    """Test configuration files"""
    print("⚙️  Testing Configuration...")
    
    import yaml
    config_path = Path(__file__).parent / "config" / "portfolio.yaml"
    
    try:
        with open(config_path, 'r', encoding='utf-8') as f:
            config = yaml.safe_load(f)
        
        funds = config.get('portfolio', {}).get('funds', [])
        print(f"  ✅ Loaded {len(funds)} funds from config")
        
        # List first 3 funds
        for fund in funds[:3]:
            print(f"     - {fund['code']}: {fund['name']}")
        
        return True
    except Exception as e:
        print(f"  ❌ Error: {e}")
        return False

def main():
    """Run all tests"""
    print("\n" + "="*60)
    print("INVESTMENT AGENT - COMPONENT TESTS")
    print("="*60 + "\n")
    
    test_imports()
    test_configuration()
    test_vault_writer()
    test_cache()
    test_yahoo_collector()
    
    print("\n" + "="*60)
    print("TESTS COMPLETE")
    print("="*60)
    print("\n📚 Next steps:")
    print("   1. Configure your holdings in config/portfolio.yaml")
    print("   2. Run: python ~/investment-skill")
    print("   3. Or use Claude Code commands:")
    print("      /fund-monitor")
    print("      /macro-liquidity")
    print("      /daily-summary")
    print("      /semi-tracker")
    print()

if __name__ == "__main__":
    main()
