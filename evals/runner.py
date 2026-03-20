#!/usr/bin/env python3
"""Bourbon Eval Runner

执行评测用例并收集结果。
参考 Skill-Creator 评测规范设计。
"""

import json
import time
import toml
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class EvalResult:
    """单个评测用例的结果"""
    case_id: str
    success: bool
    duration_ms: int
    token_usage: dict = field(default_factory=dict)
    assertions: list[dict] = field(default_factory=list)
    output: str = ""
    error: str = ""
    
    def to_dict(self) -> dict:
        return {
            "case_id": self.case_id,
            "success": self.success,
            "duration_ms": self.duration_ms,
            "token_usage": self.token_usage,
            "assertions": self.assertions,
            "output": self.output[:1000] if len(self.output) > 1000 else self.output,
            "error": self.error,
        }


@dataclass
class BenchmarkResult:
    """Benchmark 聚合结果"""
    timestamp: str
    total_cases: int
    passed: int
    failed: int
    pass_rate: float
    avg_duration_ms: float
    total_tokens: int
    cases: list[dict] = field(default_factory=list)
    
    def to_dict(self) -> dict:
        return {
            "timestamp": self.timestamp,
            "summary": {
                "total": self.total_cases,
                "passed": self.passed,
                "failed": self.failed,
                "pass_rate": round(self.pass_rate, 4),
                "avg_duration_ms": round(self.avg_duration_ms, 2),
                "total_tokens": self.total_tokens,
            },
            "cases": self.cases,
        }


class EvalRunner:
    """评测执行器"""
    
    def __init__(self, config_path: Path = None):
        self.config_path = config_path or Path("evals/config.yaml")
        self.config = self._load_config()
        self.results: list[EvalResult] = []
        
    def _load_config(self) -> dict:
        """加载配置文件"""
        if self.config_path.exists():
            with open(self.config_path) as f:
                return toml.load(f)
        return {}
    
    def load_cases(self, category: str = None) -> list[dict]:
        """加载评测用例"""
        cases_dir = Path("evals/cases")
        cases = []
        
        # 遍历所有 .json 文件
        for case_file in cases_dir.rglob("*.json"):
            # 跳过 skill-trigger 类型（特殊处理）
            if "trigger" in case_file.name:
                continue
                
            with open(case_file) as f:
                case = json.load(f)
                case["_file"] = str(case_file)
                if category is None or case.get("category") == category:
                    cases.append(case)
        
        return cases
    
    def run_case(self, case: dict) -> EvalResult:
        """执行单个评测用例（简化版框架）"""
        start = time.time()
        
        # TODO: 实际调用 Bourbon Agent
        # 这里先返回一个占位结果
        
        duration = int((time.time() - start) * 1000)
        
        return EvalResult(
            case_id=case["id"],
            success=True,  # 实际应根据断言判断
            duration_ms=duration,
            assertions=[],
            output="",
        )
    
    def run_all(self, category: str = None) -> BenchmarkResult:
        """运行所有评测用例"""
        cases = self.load_cases(category)
        
        print(f"Running {len(cases)} eval cases...")
        
        for case in cases:
            print(f"  - {case['id']}: {case.get('name', 'Unnamed')}")
            result = self.run_case(case)
            self.results.append(result)
        
        # 聚合结果
        passed = sum(1 for r in self.results if r.success)
        total = len(self.results)
        
        return BenchmarkResult(
            timestamp=time.strftime("%Y-%m-%dT%H:%M:%S"),
            total_cases=total,
            passed=passed,
            failed=total - passed,
            pass_rate=passed / total if total > 0 else 0,
            avg_duration_ms=sum(r.duration_ms for r in self.results) / total if total > 0 else 0,
            total_tokens=sum(r.token_usage.get("total", 0) for r in self.results),
            cases=[r.to_dict() for r in self.results],
        )
    
    def save_report(self, result: BenchmarkResult, output_dir: Path = None):
        """保存评测报告"""
        output_dir = output_dir or Path("evals/results")
        output_dir.mkdir(parents=True, exist_ok=True)
        
        timestamp = time.strftime("%Y%m%d_%H%M%S")
        
        # JSON 报告
        json_path = output_dir / f"benchmark_{timestamp}.json"
        with open(json_path, "w") as f:
            json.dump(result.to_dict(), f, indent=2, ensure_ascii=False)
        
        # Markdown 摘要
        md_path = output_dir / f"benchmark_{timestamp}.md"
        self._write_markdown(md_path, result)
        
        print(f"\nReport saved to:")
        print(f"  - {json_path}")
        print(f"  - {md_path}")
        
        return json_path, md_path
    
    def _write_markdown(self, path: Path, result: BenchmarkResult):
        """生成 Markdown 报告"""
        summary = result.to_dict()["summary"]
        
        lines = [
            "# Bourbon Eval Benchmark Report",
            "",
            f"**Timestamp:** {result.timestamp}",
            "",
            "## Summary",
            "",
            f"| Metric | Value |",
            f"|--------|-------|",
            f"| Total Cases | {summary['total']} |",
            f"| Passed | {summary['passed']} ✅ |",
            f"| Failed | {summary['failed']} ❌ |",
            f"| Pass Rate | {summary['pass_rate']*100:.1f}% |",
            f"| Avg Duration | {summary['avg_duration_ms']:.0f}ms |",
            f"| Total Tokens | {summary['total_tokens']} |",
            "",
            "## Details",
            "",
        ]
        
        for case in result.cases:
            status = "✅" if case["success"] else "❌"
            lines.append(f"### {case['case_id']} {status}")
            lines.append(f"- Duration: {case['duration_ms']}ms")
            if case['error']:
                lines.append(f"- Error: {case['error']}")
            lines.append("")
        
        path.write_text("\n".join(lines), encoding="utf-8")


def main():
    """命令行入口"""
    runner = EvalRunner()
    result = runner.run_all()
    runner.save_report(result)
    
    # 打印摘要
    summary = result.to_dict()["summary"]
    print(f"\n{'='*50}")
    print(f"Pass Rate: {summary['pass_rate']*100:.1f}% ({summary['passed']}/{summary['total']})")
    print(f"Avg Duration: {summary['avg_duration_ms']:.0f}ms")
    print(f"{'='*50}")


if __name__ == "__main__":
    main()
