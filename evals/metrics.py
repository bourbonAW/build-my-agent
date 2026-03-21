"""统计工具：多次运行的方差分析与 flaky 检测

参考 τ-bench 的 pass^k 指标和 Skill-Creator 的方差分析
"""

import statistics
from dataclasses import dataclass
from typing import Any


@dataclass
class RunMetrics:
    """单次运行的指标"""
    success: bool
    duration_ms: int
    input_tokens: int
    output_tokens: int
    total_tokens: int


@dataclass
class AggregatedMetrics:
    """多次运行的聚合指标"""
    # 运行次数
    total_runs: int
    passed_runs: int
    failed_runs: int
    
    # 通过率相关 (pass^k 概念)
    pass_rate: float  # 单次通过率
    pass_at_1: float  # pass@1 = pass_rate
    
    # 耗时统计
    duration_mean: float
    duration_stddev: float
    duration_min: int
    duration_max: int
    
    # Token 统计
    input_tokens_mean: float
    output_tokens_mean: float
    total_tokens_mean: float
    total_tokens_stddev: float
    
    # Flaky 检测
    is_flaky: bool  # 是否不稳定（多次运行结果不一致）
    flaky_score: float  # 不稳定程度 (0-1, 越高越不稳定)
    
    # 原始数据
    raw_runs: list[RunMetrics]


def calculate_metrics(runs: list[RunMetrics]) -> AggregatedMetrics:
    """计算多次运行的聚合指标
    
    Args:
        runs: 多次运行的指标列表
        
    Returns:
        AggregatedMetrics 聚合结果
    """
    if not runs:
        raise ValueError("No runs provided")
    
    total_runs = len(runs)
    passed_runs = sum(1 for r in runs if r.success)
    failed_runs = total_runs - passed_runs
    pass_rate = passed_runs / total_runs
    
    # 耗时统计
    durations = [r.duration_ms for r in runs]
    duration_mean = statistics.mean(durations)
    duration_stddev = statistics.stdev(durations) if len(durations) > 1 else 0.0
    duration_min = min(durations)
    duration_max = max(durations)
    
    # Token 统计
    input_tokens = [r.input_tokens for r in runs]
    output_tokens = [r.output_tokens for r in runs]
    total_tokens = [r.total_tokens for r in runs]
    
    input_tokens_mean = statistics.mean(input_tokens)
    output_tokens_mean = statistics.mean(output_tokens)
    total_tokens_mean = statistics.mean(total_tokens)
    total_tokens_stddev = statistics.stdev(total_tokens) if len(total_tokens) > 1 else 0.0
    
    # Flaky 检测
    # 定义：通过率不在 0% 或 100% 的为 flaky
    is_flaky = 0 < pass_rate < 1
    # Flaky 分数：距离 0% 或 100% 的最小距离
    flaky_score = min(pass_rate, 1 - pass_rate) * 2  # 0.5 通过率 -> 1.0 flaky_score
    
    return AggregatedMetrics(
        total_runs=total_runs,
        passed_runs=passed_runs,
        failed_runs=failed_runs,
        pass_rate=pass_rate,
        pass_at_1=pass_rate,
        duration_mean=duration_mean,
        duration_stddev=duration_stddev,
        duration_min=duration_min,
        duration_max=duration_max,
        input_tokens_mean=input_tokens_mean,
        output_tokens_mean=output_tokens_mean,
        total_tokens_mean=total_tokens_mean,
        total_tokens_stddev=total_tokens_stddev,
        is_flaky=is_flaky,
        flaky_score=flaky_score,
        raw_runs=runs,
    )


def calculate_benchmark_stats(all_metrics: list[AggregatedMetrics]) -> dict[str, Any]:
    """计算整个 benchmark 的统计信息
    
    Args:
        all_metrics: 所有用例的聚合指标
        
    Returns:
        Dict with benchmark-level statistics
    """
    if not all_metrics:
        return {}
    
    total_cases = len(all_metrics)
    flaky_cases = sum(1 for m in all_metrics if m.is_flaky)
    
    # 整体通过率（所有运行都通过才算通过）
    fully_passed = sum(1 for m in all_metrics if m.pass_rate == 1.0)
    overall_pass_rate = fully_passed / total_cases
    
    # 平均耗时和方差
    all_durations = [m.duration_mean for m in all_metrics]
    avg_duration = statistics.mean(all_durations)
    avg_duration_stddev = statistics.stdev(all_durations) if len(all_durations) > 1 else 0.0
    
    # 总 token
    total_tokens = sum(m.total_tokens_mean * m.total_runs for m in all_metrics)
    
    return {
        "total_cases": total_cases,
        "fully_passed_cases": fully_passed,
        "overall_pass_rate": overall_pass_rate,
        "flaky_cases": flaky_cases,
        "flaky_rate": flaky_cases / total_cases,
        "avg_duration_ms": avg_duration,
        "avg_duration_stddev_ms": avg_duration_stddev,
        "total_tokens": int(total_tokens),
    }


def format_variance_report(metrics: AggregatedMetrics) -> str:
    """生成方差分析文本报告
    
    Args:
        metrics: 聚合指标
        
    Returns:
        格式化的文本报告
    """
    lines = [
        f"  运行次数: {metrics.total_runs} (通过: {metrics.passed_runs}, 失败: {metrics.failed_runs})",
        f"  通过率: {metrics.pass_rate*100:.1f}%",
        f"  耗时: {metrics.duration_mean:.0f}ms (±{metrics.duration_stddev:.0f}ms)",
        f"         范围: [{metrics.duration_min}ms - {metrics.duration_max}ms]",
        f"  Token: {metrics.total_tokens_mean:.0f} (±{metrics.total_tokens_stddev:.0f})",
    ]
    
    if metrics.is_flaky:
        lines.append(f"  ⚠️  **FLAKY** (不稳定度: {metrics.flaky_score:.2f})")
    
    return "\n".join(lines)
