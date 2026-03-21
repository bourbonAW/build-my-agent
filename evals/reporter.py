"""报告生成器 - 支持 Markdown 和 HTML 格式"""

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass
class ReportConfig:
    """报告配置"""
    format: list[str]  # ["json", "markdown", "html"]
    output_dir: Path
    include_outputs: bool = True  # 是否包含详细输出
    max_output_length: int = 500


class HTMLReporter:
    """生成 HTML 格式的评测报告"""
    
    def __init__(self, config: ReportConfig):
        self.config = config
    
    def generate(self, result: dict) -> str:
        """生成完整 HTML 报告"""
        html = [
            "<!DOCTYPE html>",
            "<html lang=\"zh-CN\">",
            "<head>",
            "    <meta charset=\"UTF-8\">",
            "    <meta name=\"viewport\" content=\"width=device-width, initial-scale=1.0\">",
            f"    <title>Bourbon Eval Report - {result['timestamp']}</title>",
            self._get_css(),
            "</head>",
            "<body>",
            self._generate_header(result),
            self._generate_summary(result),
            self._generate_details(result),
            self._generate_footer(),
            "</body>",
            "</html>",
        ]
        return "\n".join(html)
    
    def _get_css(self) -> str:
        """返回 CSS 样式"""
        return """    <style>
        :root {
            --primary: #2563eb;
            --success: #10b981;
            --warning: #f59e0b;
            --danger: #ef4444;
            --gray-100: #f3f4f6;
            --gray-200: #e5e7eb;
            --gray-700: #374151;
            --gray-900: #111827;
        }
        
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }
        
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: var(--gray-100);
            color: var(--gray-900);
            line-height: 1.6;
        }
        
        .container {
            max-width: 1200px;
            margin: 0 auto;
            padding: 2rem;
        }
        
        header {
            background: white;
            padding: 2rem;
            border-radius: 12px;
            box-shadow: 0 1px 3px rgba(0,0,0,0.1);
            margin-bottom: 2rem;
        }
        
        h1 {
            font-size: 1.875rem;
            margin-bottom: 0.5rem;
        }
        
        .timestamp {
            color: var(--gray-700);
            font-size: 0.875rem;
        }
        
        .summary-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 1rem;
            margin-bottom: 2rem;
        }
        
        .metric-card {
            background: white;
            padding: 1.5rem;
            border-radius: 12px;
            box-shadow: 0 1px 3px rgba(0,0,0,0.1);
        }
        
        .metric-label {
            font-size: 0.875rem;
            color: var(--gray-700);
            margin-bottom: 0.5rem;
        }
        
        .metric-value {
            font-size: 1.5rem;
            font-weight: 600;
        }
        
        .metric-value.success { color: var(--success); }
        .metric-value.warning { color: var(--warning); }
        .metric-value.danger { color: var(--danger); }
        
        .case-section {
            background: white;
            border-radius: 12px;
            box-shadow: 0 1px 3px rgba(0,0,0,0.1);
            margin-bottom: 1.5rem;
            overflow: hidden;
        }
        
        .case-header {
            padding: 1.25rem 1.5rem;
            background: var(--gray-100);
            border-bottom: 1px solid var(--gray-200);
            display: flex;
            justify-content: space-between;
            align-items: center;
        }
        
        .case-title {
            font-size: 1.125rem;
            font-weight: 600;
        }
        
        .case-status {
            display: inline-flex;
            align-items: center;
            gap: 0.5rem;
            padding: 0.375rem 0.75rem;
            border-radius: 9999px;
            font-size: 0.875rem;
            font-weight: 500;
        }
        
        .case-status.passed {
            background: #d1fae5;
            color: #065f46;
        }
        
        .case-status.flaky {
            background: #fef3c7;
            color: #92400e;
        }
        
        .case-status.failed {
            background: #fee2e2;
            color: #991b1b;
        }
        
        .case-body {
            padding: 1.5rem;
        }
        
        .stats-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
            gap: 1rem;
            margin-bottom: 1.5rem;
        }
        
        .stat-item {
            padding: 1rem;
            background: var(--gray-100);
            border-radius: 8px;
        }
        
        .stat-label {
            font-size: 0.75rem;
            color: var(--gray-700);
            text-transform: uppercase;
            letter-spacing: 0.05em;
            margin-bottom: 0.25rem;
        }
        
        .stat-value {
            font-size: 1.125rem;
            font-weight: 600;
        }
        
        .runs-table {
            width: 100%;
            border-collapse: collapse;
            margin-top: 1rem;
        }
        
        .runs-table th,
        .runs-table td {
            padding: 0.75rem;
            text-align: left;
            border-bottom: 1px solid var(--gray-200);
        }
        
        .runs-table th {
            font-weight: 600;
            color: var(--gray-700);
            font-size: 0.875rem;
        }
        
        .badge {
            display: inline-flex;
            align-items: center;
            padding: 0.25rem 0.5rem;
            border-radius: 4px;
            font-size: 0.75rem;
            font-weight: 500;
        }
        
        .badge.success {
            background: #d1fae5;
            color: #065f46;
        }
        
        .badge.failed {
            background: #fee2e2;
            color: #991b1b;
        }
        
        .assertions-list {
            list-style: none;
            margin-top: 1rem;
        }
        
        .assertion-item {
            padding: 0.75rem;
            border-radius: 6px;
            margin-bottom: 0.5rem;
            display: flex;
            align-items: center;
            gap: 0.75rem;
        }
        
        .assertion-item.passed {
            background: #f0fdf4;
        }
        
        .assertion-item.failed {
            background: #fef2f2;
        }
        
        .assertion-icon {
            font-weight: 600;
        }
        
        footer {
            text-align: center;
            padding: 2rem;
            color: var(--gray-700);
            font-size: 0.875rem;
        }
    </style>"""
    
    def _generate_header(self, result: dict) -> str:
        """生成报告头部"""
        config = result.get('config', {})
        return f"""
    <div class="container">
        <header>
            <h1>🥃 Bourbon Eval Report</h1>
            <p class="timestamp">{result['timestamp']} | {config.get('num_runs', 1)} runs per case</p>
        </header>"""
    
    def _generate_summary(self, result: dict) -> str:
        """生成摘要部分"""
        stats = result.get('summary', {})
        
        # 确定通过率的颜色类
        pass_rate = stats.get('overall_pass_rate', 0)
        if pass_rate >= 0.8:
            pass_class = "success"
        elif pass_rate >= 0.5:
            pass_class = "warning"
        else:
            pass_class = "danger"
        
        # flaky rate 颜色
        flaky_rate = stats.get('flaky_rate', 0)
        if flaky_rate <= 0.1:
            flaky_class = "success"
        elif flaky_rate <= 0.3:
            flaky_class = "warning"
        else:
            flaky_class = "danger"
        
        return f"""
        <div class="summary-grid">
            <div class="metric-card">
                <div class="metric-label">Total Cases</div>
                <div class="metric-value">{stats.get('total_cases', 0)}</div>
            </div>
            <div class="metric-card">
                <div class="metric-label">Fully Passed</div>
                <div class="metric-value success">{stats.get('fully_passed_cases', 0)}</div>
            </div>
            <div class="metric-card">
                <div class="metric-label">Pass Rate</div>
                <div class="metric-value {pass_class}">{pass_rate*100:.1f}%</div>
            </div>
            <div class="metric-card">
                <div class="metric-label">Flaky Cases</div>
                <div class="metric-value {flaky_class}">{stats.get('flaky_cases', 0)} ({flaky_rate*100:.1f}%)</div>
            </div>
            <div class="metric-card">
                <div class="metric-label">Avg Duration</div>
                <div class="metric-value">{stats.get('avg_duration_ms', 0):.0f}ms</div>
            </div>
            <div class="metric-card">
                <div class="metric-label">Total Tokens</div>
                <div class="metric-value">{stats.get('total_tokens', 0):,}</div>
            </div>
        </div>"""
    
    def _generate_details(self, result: dict) -> str:
        """生成详细结果"""
        cases = result.get('cases', [])
        sections = []
        
        for case in cases:
            sections.append(self._generate_case_section(case))
        
        return "\n".join(sections)
    
    def _generate_case_section(self, case: dict) -> str:
        """生成单个用例的 HTML"""
        summary = case.get('summary', {})
        case_id = case.get('case_id', 'unknown')
        case_name = case.get('case_name', 'Unnamed')
        
        # 确定状态
        is_flaky = summary.get('is_flaky', False)
        pass_rate = summary.get('pass_rate', 0)
        
        if pass_rate == 1.0:
            status_class = "passed"
            status_text = "✓ Passed"
        elif is_flaky:
            status_class = "flaky"
            status_text = f"⚠ Flaky ({summary.get('passed_runs', 0)}/{summary.get('total_runs', 1)})"
        else:
            status_class = "failed"
            status_text = f"✗ Failed ({summary.get('passed_runs', 0)}/{summary.get('total_runs', 1)})"
        
        # 统计信息
        stats_html = f"""
            <div class="stats-grid">
                <div class="stat-item">
                    <div class="stat-label">Pass Rate</div>
                    <div class="stat-value">{pass_rate*100:.0f}%</div>
                </div>
                <div class="stat-item">
                    <div class="stat-label">Duration</div>
                    <div class="stat-value">{summary.get('duration_mean', 0):.0f}ms ±{summary.get('duration_stddev', 0):.0f}ms</div>
                </div>
                <div class="stat-item">
                    <div class="stat-label">Flaky Score</div>
                    <div class="stat-value">{summary.get('flaky_score', 0):.2f}</div>
                </div>
            </div>"""
        
        # 各次运行表格
        runs = case.get('runs', [])
        if len(runs) > 1:
            rows = []
            for run in runs:
                success = run.get('success', False)
                badge_class = "success" if success else "failed"
                badge_text = "Pass" if success else "Fail"
                
                token_usage = run.get('token_usage', {})
                tokens = token_usage.get('total_tokens', 0)
                
                rows.append(f"""
                    <tr>
                        <td>Run {run.get('run_number', 1)}</td>
                        <td><span class="badge {badge_class}">{badge_text}</span></td>
                        <td>{run.get('duration_ms', 0)}ms</td>
                        <td>{tokens:,}</td>
                    </tr>""")
            
            runs_html = f"""
            <table class="runs-table">
                <thead>
                    <tr>
                        <th>Run</th>
                        <th>Status</th>
                        <th>Duration</th>
                        <th>Tokens</th>
                    </tr>
                </thead>
                <tbody>{''.join(rows)}</tbody>
            </table>"""
        else:
            runs_html = ""
        
        # 断言列表
        assertions = case.get('runs', [{}])[0].get('assertions', []) if case.get('runs') else []
        if assertions:
            assertion_items = []
            for a in assertions:
                passed = a.get('passed', False)
                item_class = "passed" if passed else "failed"
                icon = "✓" if passed else "✗"
                assertion_items.append(f"""
                    <li class="assertion-item {item_class}">
                        <span class="assertion-icon">{icon}</span>
                        <span>{a.get('id', 'unknown')}: {a.get('text', '')}</span>
                    </li>""")
            
            assertions_html = f"""
            <h4>Assertions</h4>
            <ul class="assertions-list">{''.join(assertion_items)}</ul>"""
        else:
            assertions_html = ""
        
        return f"""
        <section class="case-section">
            <div class="case-header">
                <div class="case-title">{case_id}: {case_name}</div>
                <span class="case-status {status_class}">{status_text}</span>
            </div>
            <div class="case-body">
                {stats_html}
                {runs_html}
                {assertions_html}
            </div>
        </section>"""
    
    def _generate_footer(self) -> str:
        """生成页脚"""
        return """
        <footer>
            <p>Generated by Bourbon Eval Framework</p>
        </footer>
    </div>"""
    
    def save(self, result: dict, output_path: Path) -> None:
        """保存 HTML 报告"""
        html = self.generate(result)
        output_path.write_text(html, encoding="utf-8")


def generate_reports(result, output_dir: Path, formats: list[str] = None):
    """生成所有格式的报告
    
    Args:
        result: 评测结果
        output_dir: 输出目录
        formats: 格式列表 ["json", "markdown", "html"]
    """
    if formats is None:
        formats = ["json", "markdown", "html"]
    
    output_dir.mkdir(parents=True, exist_ok=True)
    timestamp = result.timestamp.replace("T", "_").replace(":", "")
    paths = {}
    
    # JSON
    if "json" in formats:
        json_path = output_dir / f"benchmark_{timestamp}.json"
        with open(json_path, "w") as f:
            json.dump(result.to_dict(), f, indent=2, ensure_ascii=False)
        paths["json"] = json_path
    
    # HTML
    if "html" in formats:
        html_path = output_dir / f"benchmark_{timestamp}.html"
        config = ReportConfig(format=["html"], output_dir=output_dir)
        reporter = HTMLReporter(config)
        reporter.save(result.to_dict(), html_path)
        paths["html"] = html_path
    
    return paths
