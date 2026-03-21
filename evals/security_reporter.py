"""安全评估报告生成器

专门针对红队测试的安全报告
"""

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass
class SecurityReport:
    """安全评估报告"""
    timestamp: str
    total_tests: int
    passed: int
    failed: int
    risk_summary: dict  # 按风险等级统计
    cwe_coverage: dict  # 按CWE类别覆盖
    owasp_coverage: dict  # 按OWASP类别覆盖
    details: list[dict]  # 每个测试的详情
    
    def to_dict(self) -> dict:
        return {
            "timestamp": self.timestamp,
            "summary": {
                "total_tests": self.total_tests,
                "passed": self.passed,
                "failed": self.failed,
                "pass_rate": self.passed / self.total_tests if self.total_tests > 0 else 0,
            },
            "risk_summary": self.risk_summary,
            "cwe_coverage": self.cwe_coverage,
            "owasp_coverage": self.owasp_coverage,
            "details": self.details,
        }


def generate_security_report(results: list[dict]) -> SecurityReport:
    """从测试结果生成安全报告
    
    Args:
        results: 安全测试用例的结果列表
    """
    from collections import defaultdict
    import time
    
    risk_summary = defaultdict(lambda: {"total": 0, "passed": 0, "failed": 0})
    cwe_coverage = defaultdict(lambda: {"total": 0, "passed": 0})
    owasp_coverage = defaultdict(lambda: {"total": 0, "passed": 0})
    
    details = []
    total_passed = 0
    
    for result in results:
        case_id = result.get("case_id", "unknown")
        success = result.get("success", False)
        
        # 获取用例元数据
        case_metadata = result.get("case_metadata", {})
        risk_level = case_metadata.get("risk_level", "unknown")
        cwe = case_metadata.get("cwe", "unknown")
        owasp = case_metadata.get("owasp_llm", "unknown")
        
        # 统计风险等级
        risk_summary[risk_level]["total"] += 1
        if success:
            risk_summary[risk_level]["passed"] += 1
            total_passed += 1
        else:
            risk_summary[risk_level]["failed"] += 1
        
        # 统计CWE覆盖
        cwe_coverage[cwe]["total"] += 1
        if success:
            cwe_coverage[cwe]["passed"] += 1
        
        # 统计OWASP覆盖
        owasp_coverage[owasp]["total"] += 1
        if success:
            owasp_coverage[owasp]["passed"] += 1
        
        # 详细记录
        details.append({
            "case_id": case_id,
            "name": case_metadata.get("name", ""),
            "description": case_metadata.get("description", ""),
            "risk_level": risk_level,
            "cwe": cwe,
            "owasp": owasp,
            "passed": success,
            "evidence": result.get("evidence", ""),
        })
    
    return SecurityReport(
        timestamp=time.strftime("%Y-%m-%dT%H:%M:%S"),
        total_tests=len(results),
        passed=total_passed,
        failed=len(results) - total_passed,
        risk_summary=dict(risk_summary),
        cwe_coverage=dict(cwe_coverage),
        owasp_coverage=dict(owasp_coverage),
        details=details,
    )


def generate_security_html_report(report: SecurityReport) -> str:
    """生成HTML格式的安全报告"""
    
    summary = report.to_dict()["summary"]
    pass_rate = summary["pass_rate"]
    
    # 根据通过率确定颜色
    if pass_rate >= 0.8:
        score_color = "#10b981"  # green
        score_text = "Good"
    elif pass_rate >= 0.5:
        score_color = "#f59e0b"  # yellow
        score_text = "Needs Improvement"
    else:
        score_color = "#ef4444"  # red
        score_text = "Critical"
    
    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Security Assessment Report - {report.timestamp}</title>
    <style>
        :root {{
            --critical: #dc2626;
            --high: #ea580c;
            --medium: #ca8a04;
            --low: #16a34a;
            --bg: #f8fafc;
            --card: #ffffff;
            --text: #1e293b;
        }}
        
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: var(--bg);
            color: var(--text);
            line-height: 1.6;
        }}
        
        .container {{
            max-width: 1200px;
            margin: 0 auto;
            padding: 2rem;
        }}
        
        header {{
            background: var(--card);
            padding: 2rem;
            border-radius: 12px;
            box-shadow: 0 1px 3px rgba(0,0,0,0.1);
            margin-bottom: 2rem;
        }}
        
        h1 {{
            font-size: 2rem;
            margin-bottom: 0.5rem;
            display: flex;
            align-items: center;
            gap: 0.5rem;
        }}
        
        .security-badge {{
            display: inline-flex;
            align-items: center;
            padding: 0.5rem 1rem;
            border-radius: 9999px;
            font-size: 0.875rem;
            font-weight: 600;
            background: {score_color}20;
            color: {score_color};
        }}
        
        .score-circle {{
            width: 120px;
            height: 120px;
            border-radius: 50%;
            border: 8px solid {score_color};
            display: flex;
            flex-direction: column;
            align-items: center;
            justify-content: center;
            margin: 1rem auto;
        }}
        
        .score-value {{
            font-size: 2rem;
            font-weight: 700;
            color: {score_color};
        }}
        
        .score-label {{
            font-size: 0.75rem;
            color: #64748b;
        }}
        
        .grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));
            gap: 1.5rem;
            margin-bottom: 2rem;
        }}
        
        .card {{
            background: var(--card);
            padding: 1.5rem;
            border-radius: 12px;
            box-shadow: 0 1px 3px rgba(0,0,0,0.1);
        }}
        
        .card h3 {{
            font-size: 1rem;
            color: #64748b;
            margin-bottom: 1rem;
        }}
        
        .risk-item {{
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding: 0.75rem;
            border-radius: 6px;
            margin-bottom: 0.5rem;
        }}
        
        .risk-critical {{ background: #fef2f2; border-left: 4px solid var(--critical); }}
        .risk-high {{ background: #fff7ed; border-left: 4px solid var(--high); }}
        .risk-medium {{ background: #fefce8; border-left: 4px solid var(--medium); }}
        .risk-low {{ background: #f0fdf4; border-left: 4px solid var(--low); }}
        
        .test-table {{
            width: 100%;
            background: var(--card);
            border-radius: 12px;
            overflow: hidden;
            box-shadow: 0 1px 3px rgba(0,0,0,0.1);
        }}
        
        .test-table th,
        .test-table td {{
            padding: 1rem;
            text-align: left;
            border-bottom: 1px solid #e2e8f0;
        }}
        
        .test-table th {{
            background: #f8fafc;
            font-weight: 600;
            color: #64748b;
            font-size: 0.875rem;
        }}
        
        .badge {{
            display: inline-flex;
            padding: 0.25rem 0.75rem;
            border-radius: 9999px;
            font-size: 0.75rem;
            font-weight: 600;
        }}
        
        .badge-passed {{ background: #dcfce7; color: #166534; }}
        .badge-failed {{ background: #fee2e2; color: #991b1b; }}
        
        .badge-risk-critical {{ background: #fecaca; color: #991b1b; }}
        .badge-risk-high {{ background: #fed7aa; color: #9a3412; }}
        .badge-risk-medium {{ background: #fef08a; color: #854d0e; }}
        .badge-risk-low {{ background: #bbf7d0; color: #166534; }}
        
        footer {{
            text-align: center;
            padding: 2rem;
            color: #64748b;
        }}
    </style>
</head>
<body>
    <div class="container">
        <header>
            <h1>🛡️ Security Assessment Report</h1>
            <p>{report.timestamp}</p>
            <div class="score-circle">
                <div class="score-value">{pass_rate*100:.0f}%</div>
                <div class="score-label">{score_text}</div>
            </div>
        </header>
        
        <div class="grid">
            <div class="card">
                <h3>Risk Distribution</h3>
                {generate_risk_html(report.risk_summary)}
            </div>
            
            <div class="card">
                <h3>OWASP LLM Coverage</h3>
                {generate_owasp_html(report.owasp_coverage)}
            </div>
        </div>
        
        <h2 style="margin-bottom: 1rem;">Test Details</h2>
        <table class="test-table">
            <thead>
                <tr>
                    <th>Test ID</th>
                    <th>Name</th>
                    <th>Risk Level</th>
                    <th>CWE</th>
                    <th>Status</th>
                </tr>
            </thead>
            <tbody>
                {generate_test_rows(report.details)}
            </tbody>
        </table>
        
        <footer>
            <p>Bourbon Security Red Team Evaluation Framework</p>
        </footer>
    </div>
</body>
</html>"""
    
    return html


def generate_risk_html(risk_summary: dict) -> str:
    """生成风险分布HTML"""
    risk_order = ["critical", "high", "medium", "low"]
    items = []
    
    for risk in risk_order:
        if risk in risk_summary:
            data = risk_summary[risk]
            total = data["total"]
            passed = data["passed"]
            failed = data["failed"]
            
            items.append(f"""
                <div class="risk-item risk-{risk}">
                    <span style="text-transform: uppercase; font-weight: 600;">{risk}</span>
                    <span>{passed}/{total} passed</span>
                </div>""")
    
    return "\n".join(items) if items else "<p>No risk data available</p>"


def generate_owasp_html(owasp_coverage: dict) -> str:
    """生成OWASP覆盖HTML"""
    items = []
    
    for owasp_id, data in sorted(owasp_coverage.items()):
        total = data["total"]
        passed = data["passed"]
        coverage = passed / total * 100 if total > 0 else 0
        
        color = "#16a34a" if coverage >= 80 else "#ca8a04" if coverage >= 50 else "#dc2626"
        
        items.append(f"""
            <div style="margin-bottom: 0.75rem;">
                <div style="display: flex; justify-content: space-between; margin-bottom: 0.25rem;">
                    <span style="font-size: 0.875rem;">{owasp_id}</span>
                    <span style="font-size: 0.875rem; font-weight: 600;">{coverage:.0f}%</span>
                </div>
                <div style="background: #e2e8f0; height: 8px; border-radius: 4px; overflow: hidden;">
                    <div style="background: {color}; width: {coverage}%; height: 100%; transition: width 0.3s;"></div>
                </div>
            </div>""")
    
    return "\n".join(items) if items else "<p>No OWASP data available</p>"


def generate_test_rows(details: list[dict]) -> str:
    """生成测试详情行"""
    rows = []
    
    for test in details:
        status_class = "passed" if test["passed"] else "failed"
        status_text = "✓ PASS" if test["passed"] else "✗ FAIL"
        
        risk = test.get("risk_level", "unknown")
        risk_class = f"badge-risk-{risk}"
        
        rows.append(f"""
            <tr>
                <td><code>{test['case_id']}</code></td>
                <td>{test['name']}</td>
                <td><span class="badge {risk_class}">{risk.upper()}</span></td>
                <td><code>{test.get('cwe', 'N/A')}</code></td>
                <td><span class="badge badge-{status_class}">{status_text}</span></td>
            </tr>""")
    
    return "\n".join(rows) if rows else "<tr><td colspan='5'>No tests</td></tr>"


def save_security_report(report: SecurityReport, output_dir: Path) -> tuple[Path, Path]:
    """保存安全报告（JSON + HTML）"""
    output_dir.mkdir(parents=True, exist_ok=True)
    timestamp = report.timestamp.replace("T", "_").replace(":", "")
    
    # JSON
    json_path = output_dir / f"security_report_{timestamp}.json"
    with open(json_path, "w") as f:
        json.dump(report.to_dict(), f, indent=2, ensure_ascii=False)
    
    # HTML
    html_path = output_dir / f"security_report_{timestamp}.html"
    html = generate_security_html_report(report)
    html_path.write_text(html, encoding="utf-8")
    
    return json_path, html_path
