#!/usr/bin/env python3
"""Bourbon Eval Runner - P1 阶段

支持多次运行、方差分析和 flaky 检测。
参考 Skill-Creator 评测规范和 τ-bench 的 pass^k 指标。
"""

import json
import sys
import time
import shutil
import tempfile
import statistics
import toml
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# Add paths for imports
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).parent.parent))

from bourbon.config import ConfigManager
from bourbon.agent import Agent, AgentError
from evals.metrics import RunMetrics, AggregatedMetrics, calculate_metrics, calculate_benchmark_stats
from evals.reporter import generate_reports


@dataclass
class EvalResult:
    """单次评测运行的结果"""
    case_id: str
    success: bool
    duration_ms: int
    token_usage: dict = field(default_factory=dict)
    assertions: list[dict] = field(default_factory=list)
    output: str = ""
    error: str = ""
    run_number: int = 1  # 第几次运行
    
    def to_dict(self) -> dict:
        return {
            "case_id": self.case_id,
            "run_number": self.run_number,
            "success": self.success,
            "duration_ms": self.duration_ms,
            "token_usage": self.token_usage,
            "assertions": self.assertions,
            "output": self.output[:1000] if len(self.output) > 1000 else self.output,
            "error": self.error,
        }


@dataclass
class CaseResult:
    """单个用例的完整结果（包含多次运行）"""
    case_id: str
    case_name: str
    category: str
    aggregated: AggregatedMetrics  # 聚合统计
    runs: list[EvalResult]  # 各次运行结果
    
    def to_dict(self) -> dict:
        return {
            "case_id": self.case_id,
            "case_name": self.case_name,
            "category": self.category,
            "summary": {
                "total_runs": self.aggregated.total_runs,
                "passed_runs": self.aggregated.passed_runs,
                "failed_runs": self.aggregated.failed_runs,
                "pass_rate": self.aggregated.pass_rate,
                "is_flaky": self.aggregated.is_flaky,
                "flaky_score": self.aggregated.flaky_score,
                "duration_mean": self.aggregated.duration_mean,
                "duration_stddev": self.aggregated.duration_stddev,
            },
            "runs": [r.to_dict() for r in self.runs],
        }


@dataclass
class BenchmarkResult:
    """Benchmark 完整结果"""
    timestamp: str
    config: dict  # 运行配置
    total_cases: int
    cases: list[CaseResult]
    stats: dict  # 整体统计
    
    def to_dict(self) -> dict:
        return {
            "timestamp": self.timestamp,
            "config": self.config,
            "summary": self.stats,
            "cases": [c.to_dict() for c in self.cases],
        }


class EvalRunner:
    """评测执行器 - P1 阶段"""
    
    def __init__(self, config_path: Path = None, fast_mode: bool = False, num_runs: int = None):
        self.config_path = config_path or Path("evals/config.toml")
        self.config = self._load_config()
        self.fast_mode = fast_mode
        # 允许命令行覆盖 num_runs
        self.num_runs = num_runs or self.config.get("runner", {}).get("num_runs", 1)
        self.timeout = self.config.get("runner", {}).get("timeout", 60)
        self.bourbon_config = None
        self.case_results: list[CaseResult] = []
        
    def _load_config(self) -> dict:
        """加载评测配置文件"""
        if self.config_path.exists():
            with open(self.config_path) as f:
                return toml.load(f)
        return {}
    
    def _load_bourbon_config(self) -> Any:
        """加载 Bourbon Agent 配置"""
        if self.bourbon_config is None:
            try:
                config_manager = ConfigManager()
                self.bourbon_config = config_manager.load_config()
            except FileNotFoundError as e:
                print(f"Error: Bourbon config not found. Run 'bourbon --init' first.")
                raise
        return self.bourbon_config
    
    def load_cases(self, category: str = None) -> list[dict]:
        """加载评测用例"""
        cases_dir = Path("evals/cases")
        cases = []
        
        for case_file in cases_dir.rglob("*.json"):
            if "trigger" in case_file.name:
                continue
                
            with open(case_file) as f:
                case = json.load(f)
                case["_file"] = str(case_file)
                if category is None or case.get("category") == category:
                    cases.append(case)
        
        return cases
    
    def _setup_workspace(self, case: dict) -> Path:
        """为评测用例创建工作目录"""
        workdir = Path(tempfile.mkdtemp(prefix=f"eval_{case['id']}_"))
        
        setup = case.get("setup", {})
        if "create_files" in setup:
            for rel_path, content in setup["create_files"].items():
                file_path = workdir / rel_path
                file_path.parent.mkdir(parents=True, exist_ok=True)
                file_path.write_text(content, encoding="utf-8")
        
        context = case.get("context", {})
        if "workdir" in context:
            fixture_dir = Path("evals/fixtures") / context["workdir"].split("/")[-1]
            if fixture_dir.exists():
                for item in fixture_dir.iterdir():
                    dest = workdir / item.name
                    if item.is_dir():
                        shutil.copytree(item, dest, dirs_exist_ok=True)
                    else:
                        shutil.copy2(item, dest)
        
        return workdir
    
    def _cleanup_workspace(self, workdir: Path) -> None:
        """清理工作目录"""
        if workdir.exists():
            shutil.rmtree(workdir)
    
    def _execute_assertions(self, case: dict, output: str, workdir: Path) -> list[dict]:
        """执行断言验证"""
        assertions = case.get("assertions", [])
        results = []
        prompt = case.get("prompt", "")
        
        for assertion in assertions:
            check = assertion.get("check", "")
            passed = False
            evidence = ""
            
            try:
                if check.startswith("file_exists:"):
                    path = workdir / check.split(":", 1)[1]
                    passed = path.exists() and path.is_file()
                    evidence = f"File {'exists' if passed else 'not found'}: {path.name}"
                    
                elif check.startswith("file_contains:"):
                    parts = check.split(":", 2)
                    path = workdir / parts[1]
                    expected = parts[2] if len(parts) > 2 else ""
                    if path.exists():
                        content = path.read_text(encoding="utf-8")
                        passed = expected in content
                        evidence = f"Content {'found' if passed else 'not found'}"
                    else:
                        passed = False
                        evidence = f"File not found"
                        
                elif check.startswith("file_not_contains:"):
                    parts = check.split(":", 2)
                    path = workdir / parts[1]
                    expected = parts[2] if len(parts) > 2 else ""
                    if path.exists():
                        content = path.read_text(encoding="utf-8")
                        passed = expected not in content
                        evidence = f"Content correctly {'absent' if passed else 'found'}"
                    else:
                        passed = True
                        evidence = f"File not found"
                        
                elif check.startswith("output_contains:"):
                    expected = check.split(":", 1)[1]
                    passed = expected in output
                    evidence = f"Output {'contains' if passed else 'lacks'}: {expected[:30]}..."
                    
                elif check.startswith("output_not_contains:"):
                    expected = check.split(":", 1)[1]
                    passed = expected not in output
                    evidence = f"Content {'absent' if passed else 'found'}"
                    
                elif check.startswith("output_contains_any:"):
                    list_str = check.split(":", 1)[1].strip()
                    if list_str.startswith("[") and list_str.endswith("]"):
                        items = [x.strip().strip("'\"") for x in list_str[1:-1].split(",")]
                    else:
                        items = [list_str]
                    passed = any(item in output for item in items)
                    matched = sum(1 for i in items if i in output)
                    evidence = f"Matched {matched}/{len(items)}"
                
                elif check.startswith("output_not_contains_any:"):
                    list_str = check.split(":", 1)[1].strip()
                    if list_str.startswith("[") and list_str.endswith("]"):
                        items = [x.strip().strip("'\"") for x in list_str[1:-1].split(",")]
                    else:
                        items = [list_str]
                    passed = not any(item in output for item in items)
                    matched = sum(1 for i in items if i in output)
                    evidence = f"Found {matched}/{len(items)} forbidden items"
                
                elif check.startswith("output_not_contains_regex:"):
                    import re
                    pattern = check.split(":", 1)[1]
                    try:
                        if re.search(pattern, output):
                            matched = re.search(pattern, output).group(0)
                            passed = False
                            evidence = f"Found forbidden pattern: {matched[:30]}..."
                        else:
                            passed = True
                            evidence = f"Pattern not found"
                    except re.error:
                        passed = False
                        evidence = "Invalid regex pattern"
                    
                elif assertion.get("type") == "llm_judge":
                    if self.fast_mode:
                        passed = True
                        evidence = "Skipped (fast mode)"
                    else:
                        from evals.llm_judge import evaluate_assertion
                        judge_result = evaluate_assertion(
                            assertion=assertion,
                            prompt=prompt,
                            output=output,
                            context={"workdir": str(workdir)},
                        )
                        passed = judge_result["passed"]
                        evidence = f"{judge_result['reasoning'][:80]}... (confidence: {judge_result['confidence']:.2f})"
                    
                else:
                    evidence = f"Unknown check type"
                    
            except Exception as e:
                passed = False
                evidence = f"Error: {str(e)[:50]}"
            
            results.append({
                "id": assertion.get("id", "unknown"),
                "text": assertion.get("description", ""),
                "passed": passed,
                "evidence": evidence,
            })
        
        return results
    
    def run_single(self, case: dict, run_number: int = 1) -> EvalResult:
        """执行单次运行"""
        workdir = None
        original_cwd = Path.cwd()
        start = time.time()
        
        try:
            workdir = self._setup_workspace(case)
            import os
            os.chdir(workdir)
            
            bourbon_config = self._load_bourbon_config()
            agent = Agent(config=bourbon_config, workdir=workdir)
            agent.reset_token_usage()
            
            # 禁用 skills
            agent.skills._skills = {}
            agent.system_prompt = agent._build_system_prompt()
            
            prompt = case.get("prompt", "")
            output = agent.step(prompt)
            
            duration = int((time.time() - start) * 1000)
            token_usage = agent.get_token_usage()
            
            assertion_results = self._execute_assertions(case, output, workdir)
            success = all(a["passed"] for a in assertion_results) if assertion_results else True
            
            return EvalResult(
                case_id=case["id"],
                success=success,
                duration_ms=duration,
                token_usage=token_usage,
                assertions=assertion_results,
                output=output,
                run_number=run_number,
            )
            
        except Exception as e:
            duration = int((time.time() - start) * 1000)
            return EvalResult(
                case_id=case["id"],
                success=False,
                duration_ms=duration,
                error=str(e),
                run_number=run_number,
            )
        finally:
            import os
            os.chdir(original_cwd)
            if workdir:
                self._cleanup_workspace(workdir)
    
    def run_case(self, case: dict) -> CaseResult:
        """执行单个用例（支持多次运行）"""
        case_id = case["id"]
        case_name = case.get("name", "Unnamed")
        category = case.get("category", "unknown")
        
        print(f"\n  Running: {case_id} - {case_name}")
        if self.num_runs > 1:
            print(f"  ({self.num_runs} runs for variance analysis)")
        
        runs = []
        for i in range(1, self.num_runs + 1):
            if self.num_runs > 1:
                print(f"    Run {i}/{self.num_runs}...", end=" ", flush=True)
            
            result = self.run_single(case, run_number=i)
            runs.append(result)
            
            # 转换为 RunMetrics
            run_metrics = RunMetrics(
                success=result.success,
                duration_ms=result.duration_ms,
                input_tokens=result.token_usage.get("input_tokens", 0),
                output_tokens=result.token_usage.get("output_tokens", 0),
                total_tokens=result.token_usage.get("total_tokens", 0),
            )
            
            if self.num_runs > 1:
                status = "✓" if result.success else "✗"
                print(f"{status} ({result.duration_ms}ms, {run_metrics.total_tokens} tokens)")
            else:
                # 单次运行时打印断言结果
                for assertion in result.assertions:
                    status = "✓" if assertion["passed"] else "✗"
                    print(f"      {status} {assertion['id']}: {assertion['evidence']}")
        
        # 计算聚合指标
        run_metrics_list = [
            RunMetrics(
                success=r.success,
                duration_ms=r.duration_ms,
                input_tokens=r.token_usage.get("input_tokens", 0),
                output_tokens=r.token_usage.get("output_tokens", 0),
                total_tokens=r.token_usage.get("total_tokens", 0),
            )
            for r in runs
        ]
        aggregated = calculate_metrics(run_metrics_list)
        
        # 打印汇总
        if self.num_runs > 1:
            print(f"  Summary: {aggregated.passed_runs}/{aggregated.total_runs} passed")
            print(f"           {aggregated.duration_mean:.0f}ms (±{aggregated.duration_stddev:.0f}ms)")
            if aggregated.is_flaky:
                print(f"  ⚠️  FLAKY (score: {aggregated.flaky_score:.2f})")
        
        return CaseResult(
            case_id=case_id,
            case_name=case_name,
            category=category,
            aggregated=aggregated,
            runs=runs,
        )
    
    def run_all(self, category: str = None) -> BenchmarkResult:
        """运行所有评测用例"""
        cases = self.load_cases(category)
        
        print(f"Running {len(cases)} eval cases...")
        print(f"Config: num_runs={self.num_runs}, fast_mode={self.fast_mode}")
        
        for case in cases:
            case_result = self.run_case(case)
            self.case_results.append(case_result)
        
        # 计算整体统计
        all_metrics = [c.aggregated for c in self.case_results]
        stats = calculate_benchmark_stats(all_metrics)
        
        return BenchmarkResult(
            timestamp=time.strftime("%Y-%m-%dT%H:%M:%S"),
            config={
                "num_runs": self.num_runs,
                "fast_mode": self.fast_mode,
                "timeout": self.timeout,
            },
            total_cases=len(cases),
            cases=self.case_results,
            stats=stats,
        )
    
    def save_report(self, result: BenchmarkResult, output_dir: Path = None):
        """保存评测报告（JSON + Markdown + HTML）"""
        output_dir = output_dir or Path("evals/results")
        output_dir.mkdir(parents=True, exist_ok=True)
        
        # 使用新的 reporter 生成所有格式
        paths = generate_reports(result, output_dir, formats=["json", "html"])
        
        # 同时生成 Markdown
        timestamp = time.strftime("%Y%m%d_%H%M%S")
        md_path = output_dir / f"benchmark_{timestamp}.md"
        self._write_markdown(md_path, result)
        paths["markdown"] = md_path
        
        print(f"\nReports saved to:")
        for fmt, path in paths.items():
            print(f"  [{fmt}] {path}")
        
        return paths
    
    def _write_markdown(self, path: Path, result: BenchmarkResult):
        """生成 Markdown 报告"""
        lines = [
            "# Bourbon Eval Benchmark Report",
            "",
            f"**Timestamp:** {result.timestamp}",
            f"**Config:** {result.config['num_runs']} runs per case, fast_mode={result.config['fast_mode']}",
            "",
            "## Summary",
            "",
        ]
        
        stats = result.stats
        lines.extend([
            f"| Metric | Value |",
            f"|--------|-------|",
            f"| Total Cases | {stats['total_cases']} |",
            f"| Fully Passed | {stats['fully_passed_cases']} ✅ |",
            f"| Overall Pass Rate | {stats['overall_pass_rate']*100:.1f}% |",
            f"| Flaky Cases | {stats['flaky_cases']} ⚠️ |",
            f"| Flaky Rate | {stats['flaky_rate']*100:.1f}% |",
            f"| Avg Duration | {stats['avg_duration_ms']:.0f}ms (±{stats['avg_duration_stddev_ms']:.0f}ms) |",
            f"| Total Tokens | {stats['total_tokens']:,} |",
            "",
        ])
        
        # 按类别分组
        by_category: dict[str, list[CaseResult]] = {}
        for case in result.cases:
            cat = case.category
            by_category.setdefault(cat, []).append(case)
        
        lines.append("## Results by Category")
        lines.append("")
        
        for category, cases in sorted(by_category.items()):
            lines.append(f"### {category}")
            lines.append("")
            
            for case in cases:
                agg = case.aggregated
                status = "✅" if agg.pass_rate == 1.0 else ("⚠️" if agg.is_flaky else "❌")
                lines.append(f"#### {case.case_id} {status} {case.case_name}")
                lines.append(f"- Runs: {agg.passed_runs}/{agg.total_runs} passed")
                lines.append(f"- Duration: {agg.duration_mean:.0f}ms (±{agg.duration_stddev:.0f}ms, range: {agg.duration_min}-{agg.duration_max}ms)")
                lines.append(f"- Tokens: {agg.total_tokens_mean:.0f} (±{agg.total_tokens_stddev:.0f})")
                if agg.is_flaky:
                    lines.append(f"- **FLAKY** score: {agg.flaky_score:.2f}")
                lines.append("")
                
                # 显示各次运行的断言结果
                if case.runs:
                    lines.append("**Assertions:**")
                    first_run = case.runs[0]
                    for assertion in first_run.assertions:
                        a_status = "✓" if assertion['passed'] else "✗"
                        lines.append(f"- {a_status} {assertion['id']}: {assertion['text']}")
                    lines.append("")
        
        path.write_text("\n".join(lines), encoding="utf-8")


def main():
    """命令行入口"""
    import argparse
    
    parser = argparse.ArgumentParser(description="Bourbon Eval Runner")
    parser.add_argument("--category", help="运行指定类别的评测")
    parser.add_argument("--num-runs", type=int, help="每个用例运行次数（覆盖配置）")
    parser.add_argument("--fast", action="store_true", help="快速模式：跳过 LLM Judge")
    args = parser.parse_args()
    
    runner = EvalRunner(fast_mode=args.fast, num_runs=args.num_runs)
    result = runner.run_all(category=args.category)
    runner.save_report(result)
    
    # 打印摘要
    stats = result.stats
    print(f"\n{'='*60}")
    print(f"Overall Pass Rate: {stats['overall_pass_rate']*100:.1f}% ({stats['fully_passed_cases']}/{stats['total_cases']})")
    print(f"Flaky Cases: {stats['flaky_cases']} ({stats['flaky_rate']*100:.1f}%)")
    print(f"Avg Duration: {stats['avg_duration_ms']:.0f}ms")
    print(f"{'='*60}")
    
    # 如果有失败的用例，返回非零退出码
    if stats['fully_passed_cases'] < stats['total_cases']:
        sys.exit(1)


if __name__ == "__main__":
    main()
