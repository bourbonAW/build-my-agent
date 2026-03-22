#!/usr/bin/env python3
"""
Generate Comprehensive Report - 整合所有模块结果生成综合报告

Usage:
    python scripts/generate_comprehensive_report.py
    python scripts/generate_comprehensive_report.py --date 2026-03-10
"""

import json
import re
from pathlib import Path
from datetime import datetime, timedelta
import argparse

def find_latest_report(pattern, directory):
    """查找最新的报告文件"""
    vault_path = Path.home() / "vault-notes"
    search_path = vault_path / directory
    
    if not search_path.exists():
        return None
    
    # 查找匹配的文件
    files = list(search_path.glob(pattern))
    if not files:
        return None
    
    # 按修改时间排序，取最新的
    latest = max(files, key=lambda f: f.stat().st_mtime)
    return latest

def extract_warning_level(content, module_name=None):
    """从报告内容中提取预警级别"""
    # 首先尝试标准标记
    if "🔴" in content or "RED" in content or "Red" in content:
        return "🔴 RED"
    elif "🟠" in content or "ORANGE" in content or "Orange" in content:
        return "🟠 ORANGE"
    elif "🟡" in content or "YELLOW" in content or "Yellow" in content:
        return "🟡 YELLOW"
    elif "🟢" in content or "GREEN" in content or "Green" in content:
        return "🟢 GREEN"
    
    # 特殊处理：Fund Monitor - 基于Alerts数量和涨跌幅判断
    if module_name == "Fund Monitor":
        # 查找Alerts数量
        alerts_match = re.search(r'Alerts?[:：]\s*(\d+)', content, re.IGNORECASE)
        alerts = int(alerts_match.group(1)) if alerts_match else 0
        
        # 查找平均涨跌幅
        change_match = re.search(r'(?:Average Daily Change|日涨跌)[:：]?\s*([\-+]?\d+\.?\d*)%', content)
        avg_change = float(change_match.group(1)) if change_match else 0
        
        if alerts >= 3 or avg_change <= -3.0:
            return "🔴 RED"
        elif alerts >= 1 or avg_change <= -1.5:
            return "🟡 YELLOW"
        else:
            return "🟢 GREEN"
    
    # 特殊处理：Semiconductor - 基于涨跌幅判断
    if module_name == "Semiconductor":
        # 查找SOX指数涨跌幅
        sox_match = re.search(r'SOX[^\n]*?([\-+]?\d+\.?\d*)%', content)
        sox_change = float(sox_match.group(1)) if sox_match else 0
        
        if sox_change <= -3.0:
            return "🔴 RED"
        elif sox_change <= -1.5:
            return "🟡 YELLOW"
        else:
            return "🟢 GREEN"
    
    return "⚪ UNKNOWN"

def extract_key_findings(content, module_name=None, max_items=3):
    """提取关键发现"""
    findings = []
    
    # 模块特定的提取模式
    if module_name == "Fund Monitor":
        # 提取基金组合关键数据
        patterns = [
            (r'Average Daily Change[:：]?\s*([\-\+]?\d+\.?\d*)%', "日涨跌: {value}%"),
            (r'Total Position Value[:：]?\s*¥?([\d,]+\.?\d*)', "持仓总值: ¥{value}"),
            (r'Unrealized P&L[:：]?\s*.*?([\-\+]?)¥?([\d,]+\.?\d*)', "未实现盈亏: {sign}¥{value}"),
            (r'Up/Down/Flat[:：]?\s*(\d+)\s*/\s*(\d+)', "涨跌分布: {value1}涨/{value2}跌"),
        ]
        for pattern, template in patterns:
            match = re.search(pattern, content, re.IGNORECASE)
            if match:
                if len(match.groups()) == 2 and "{value1}" in template:
                    findings.append(template.format(value1=match.group(1), value2=match.group(2)))
                elif len(match.groups()) == 2:
                    sign = match.group(1) if match.group(1) else ""
                    findings.append(template.format(sign=sign, value=match.group(2)))
                else:
                    findings.append(template.format(value=match.group(1)))
            if len(findings) >= max_items:
                break
                
    elif module_name == "Leading Indicators":
        # 提取领先指标关键信息
        patterns = [
            (r'流动性评估[:：]?\s*(.+?)(?:\n|$)', "{value}"),
            (r'关键领先指标信号\s*\((\d+)个\)', "监控指标数: {value}"),
        ]
        for pattern, template in patterns:
            match = re.search(pattern, content, re.IGNORECASE)
            if match:
                findings.append(template.format(value=match.group(1).strip()))
            if len(findings) >= max_items:
                break
                
    elif module_name == "China Market":
        # 提取中国市场关键信息（定性描述）
        patterns = [
            (r'估值状况\s*[:：]?\s*([✅🟢].+?)(?:\n|$)', "{value}"),
            (r'杠杆状况\s*[:：]?\s*([✅🟢].+?)(?:\n|$)', "{value}"),
            (r'情绪状况\s*[:：]?\s*([✅🟢].+?)(?:\n|$)', "{value}"),
            (r'资金流向\s*[:：]?\s*([✅🟢].+?)(?:\n|$)', "{value}"),
        ]
        for pattern, template in patterns:
            match = re.search(pattern, content, re.IGNORECASE)
            if match:
                findings.append(template.format(value=match.group(1).strip()))
            if len(findings) >= max_items:
                break
                
    elif module_name == "Macro Liquidity":
        # 提取宏观流动性关键信息
        patterns = [
            (r'Assessment.*?([🟢🔴🟡🟠][^\n]+)', "评估: {value}"),
            (r'Price.*?\\\$([\d,\.]+)', "黄金价格: USD {value}"),
        ]
        for pattern, template in patterns:
            match = re.search(pattern, content, re.IGNORECASE)
            if match:
                findings.append(template.format(value=match.group(1).strip()))
            if len(findings) >= max_items:
                break
                
    elif module_name == "Semiconductor":
        # 提取半导体关键数据
        patterns = [
            (r'Daily Change[:：]?\s*[📈📉]\s*([\-\+]?\d+\.?\d*)%', "SOX涨跌: {value}%"),
            (r'Value[:：]?\s*([\d\.]+)', "SOX指数: {value}"),
            (r'Overall Sentiment[:：]?\s*(.+?)(?:\n|$)', "市场情绪: {value}"),
        ]
        for pattern, template in patterns:
            match = re.search(pattern, content, re.IGNORECASE)
            if match:
                findings.append(template.format(value=match.group(1).strip()))
            if len(findings) >= max_items:
                break
    
    # 通用提取：查找关键段落（仅在特定模块未匹配到时使用）
    if not findings:
        patterns = [
            r"关键发现[:：](.+?)(?:\n\n|\Z)",
            r"Summary[:：](.+?)(?:\n\n|\Z)",
            r"流动性评估[:：](.+?)(?:\n\n|\Z)",
        ]
        
        for pattern in patterns:
            match = re.search(pattern, content, re.DOTALL | re.IGNORECASE)
            if match:
                text = match.group(1).strip()
                items = [item.strip() for item in re.split(r'[\n•\-]', text) if item.strip()]
                # 过滤掉只包含数字或星号的项
                filtered_items = []
                for item in items:
                    # 去除Markdown加粗标记
                    clean_item = item.strip('*').strip()
                    # 跳过纯数字或太短的内容
                    if len(clean_item) > 5 and not clean_item.isdigit():
                        filtered_items.append(clean_item)
                findings.extend(filtered_items[:max_items])
                break
    
    return findings if findings else ["No key findings extracted"]

def generate_executive_summary(reports_data):
    """生成执行摘要"""
    summary = []
    summary.append("# 📊 Investment Agent - Daily Executive Summary\n")
    summary.append(f"**Generated:** {datetime.now().strftime('%Y-%m-%d %H:%M')}\n")
    summary.append("---\n\n")
    
    # 预警级别矩阵
    summary.append("## 🎯 Warning Level Matrix\n\n")
    summary.append("| Module | Warning Level | Status |\n")
    summary.append("|--------|--------------|--------|\n")
    
    max_level = "🟢 GREEN"
    for module, data in reports_data.items():
        level = data.get('warning_level', '⚪ UNKNOWN')
        status = "✅ Normal" if "GREEN" in level else "⚠️ Attention" if "YELLOW" in level else "🔴 Action Required"
        summary.append(f"| {module} | {level} | {status} |\n")
        
        # 跟踪最高预警级别
        if "RED" in level:
            max_level = "🔴 RED"
        elif "ORANGE" in level and max_level not in ["🔴 RED"]:
            max_level = "🟠 ORANGE"
        elif "YELLOW" in level and max_level not in ["🔴 RED", "🟠 ORANGE"]:
            max_level = "🟡 YELLOW"
    
    summary.append(f"\n**Overall Status:** {max_level}\n\n")
    
    # 关键发现
    summary.append("## 🔍 Key Findings\n\n")
    for module, data in reports_data.items():
        if data.get('findings'):
            summary.append(f"### {module}\n")
            for finding in data['findings'][:2]:  # 每个模块最多2条
                summary.append(f"- {finding}\n")
            summary.append("\n")
    
    # 行动建议
    summary.append("## 💡 Recommended Actions\n\n")
    
    if max_level == "🔴 RED":
        summary.append("🚨 **IMMEDIATE ACTION REQUIRED**\n")
        summary.append("- Consider reducing equity exposure by 20-30%\n")
        summary.append("- Increase gold/hedge positions\n")
        summary.append("- Review stop-loss levels\n\n")
    elif max_level == "🟠 ORANGE":
        summary.append("⚠️ **PREPARE DEFENSIVE MEASURES**\n")
        summary.append("- Monitor closely for deterioration\n")
        summary.append("- Have action plan ready\n")
        summary.append("- Consider partial hedging\n\n")
    elif max_level == "🟡 YELLOW":
        summary.append("👁️ **STAY VIGILANT**\n")
        summary.append("- Normal fluctuations, no action needed\n")
        summary.append("- Continue monitoring\n")
        summary.append("- Maintain current positions\n\n")
    else:
        summary.append("✅ **ALL SYSTEMS NORMAL**\n")
        summary.append("- Maintain current strategy\n")
        summary.append("- Enjoy the ride\n")
        summary.append("- Check again tomorrow\n\n")
    
    return ''.join(summary)

def main():
    """主函数"""
    parser = argparse.ArgumentParser(description='Generate comprehensive report from all modules')
    parser.add_argument('--date', type=str, help='Specific date (YYYY-MM-DD), default is today')
    args = parser.parse_args()
    
    if args.date:
        date_str = args.date
    else:
        date_str = datetime.now().strftime('%Y-%m-%d')
    
    print(f"🔄 Generating comprehensive report for {date_str}...")
    
    # 查找各模块的最新报告
    reports_data = {}
    
    modules = {
        'Fund Monitor': ('daily', f'{date_str}_fund_report.md'),
        'Leading Indicators': ('knowledge/investment/macro', f'leading_indicator_alert_{date_str}*.md'),
        'China Market': ('knowledge/investment/macro', f'china_market_alert_{date_str}*.md'),
        'Macro Liquidity': ('knowledge/investment/macro', 'liquidity_*.md'),
        'Semiconductor': ('knowledge/investment/industries/semiconductor', f'daily_analysis_{date_str}.md'),
    }
    
    for module_name, (directory, pattern) in modules.items():
        print(f"  📄 Searching for {module_name}...")
        
        report_file = find_latest_report(pattern, directory)
        
        if report_file and report_file.exists():
            content = report_file.read_text(encoding='utf-8')
            warning_level = extract_warning_level(content, module_name)
            findings = extract_key_findings(content, module_name)
            
            reports_data[module_name] = {
                'file': str(report_file),
                'warning_level': warning_level,
                'findings': findings
            }
            print(f"    ✅ Found: {warning_level}")
        else:
            reports_data[module_name] = {
                'file': None,
                'warning_level': '⚪ NOT FOUND',
                'findings': []
            }
            print(f"    ⚠️  Not found")
    
    # 生成执行摘要
    summary = generate_executive_summary(reports_data)
    
    # 保存到vault
    vault_path = Path.home() / "vault-notes" / "daily"
    vault_path.mkdir(parents=True, exist_ok=True)
    
    output_file = vault_path / f"{date_str}_executive_summary.md"
    output_file.write_text(summary, encoding='utf-8')
    
    print(f"\n✅ Executive summary generated!")
    print(f"📄 Saved to: {output_file}")
    
    # 打印摘要
    print(f"\n{'='*60}")
    print(summary[:1000] + "..." if len(summary) > 1000 else summary)
    print(f"{'='*60}")

if __name__ == "__main__":
    main()
