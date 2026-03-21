"""Skill 触发准确率评测

适配 skill-creator 的触发评测理念，但使用 Bourbon Agent 进行测试。
参考: https://github.com/anthropics/skills/tree/main/skills/skill-creator

核心概念：
- should-trigger: 应该触发 skill 的 queries
- should-not-trigger: 不应该触发 skill 的 queries
- 计算准确率、精确率、召回率、F1
"""

import json
import time
import argparse
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
import sys

# Add paths
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).parent.parent))

from bourbon.config import ConfigManager
from bourbon.agent import Agent


@dataclass
class TriggerEvalResult:
    """单个 query 的触发评测结果"""
    query: str
    should_trigger: bool
    did_trigger: bool
    confidence: float = 0.0  # 触发置信度（可选）
    reasoning: str = ""  # 触发/未触发的原因
    
    @property
    def is_tp(self) -> bool:
        """True Positive: 应该触发且触发了"""
        return self.should_trigger and self.did_trigger
    
    @property
    def is_tn(self) -> bool:
        """True Negative: 不应该触发且没触发"""
        return not self.should_trigger and not self.did_trigger
    
    @property
    def is_fp(self) -> bool:
        """False Positive: 不应该触发但触发了（误触发）"""
        return not self.should_trigger and self.did_trigger
    
    @property
    def is_fn(self) -> bool:
        """False Negative: 应该触发但没触发（漏触发）"""
        return self.should_trigger and not self.did_trigger
    
    @property
    def is_correct(self) -> bool:
        """判断是否正确"""
        return self.is_tp or self.is_tn


@dataclass
class TriggerMetrics:
    """触发评测指标"""
    total: int
    correct: int
    tp: int  # True Positive
    tn: int  # True Negative
    fp: int  # False Positive
    fn: int  # False Negative
    
    @property
    def accuracy(self) -> float:
        """准确率"""
        return self.correct / self.total if self.total > 0 else 0.0
    
    @property
    def precision(self) -> float:
        """精确率 = TP / (TP + FP)"""
        denom = self.tp + self.fp
        return self.tp / denom if denom > 0 else 0.0
    
    @property
    def recall(self) -> float:
        """召回率 = TP / (TP + FN)"""
        denom = self.tp + self.fn
        return self.tp / denom if denom > 0 else 0.0
    
    @property
    def f1_score(self) -> float:
        """F1 = 2 * (Precision * Recall) / (Precision + Recall)"""
        p, r = self.precision, self.recall
        if p + r == 0:
            return 0.0
        return 2 * p * r / (p + r)
    
    @property
    def false_positive_rate(self) -> float:
        """误触发率 = FP / (FP + TN)"""
        denom = self.fp + self.tn
        return self.fp / denom if denom > 0 else 0.0
    
    def to_dict(self) -> dict:
        return {
            "total": self.total,
            "correct": self.correct,
            "tp": self.tp,
            "tn": self.tn,
            "fp": self.fp,
            "fn": self.fn,
            "accuracy": round(self.accuracy, 4),
            "precision": round(self.precision, 4),
            "recall": round(self.recall, 4),
            "f1_score": round(self.f1_score, 4),
            "false_positive_rate": round(self.false_positive_rate, 4),
        }


class TriggerEvaluator:
    """Skill 触发评测器"""
    
    def __init__(self, skill_name: str, skill_description: str, workdir: Path = None):
        self.skill_name = skill_name
        self.skill_description = skill_description
        self.workdir = workdir or Path.cwd()
        self.bourbon_config = None
        
    def _load_config(self) -> Any:
        """加载 Bourbon 配置"""
        if self.bourbon_config is None:
            config_manager = ConfigManager()
            self.bourbon_config = config_manager.load_config()
        return self.bourbon_config
    
    def _check_trigger(self, query: str) -> tuple[bool, str]:
        """检查单个 query 是否会触发 skill
        
        方法：创建一个包含 skill description 的 Agent，然后发送 query，
        检查 Agent 是否尝试激活 skill。
        
        Returns:
            (did_trigger, reasoning)
        """
        try:
            config = self._load_config()
            agent = Agent(config=config, workdir=self.workdir)
            
            # 在系统提示中添加 skill catalog
            # 模拟 skill 在 available_skills 中的情况
            skill_catalog = f"""
SKILLS
======

The following skills provide specialized instructions for specific tasks.
When a task matches a skill's description, use the 'skill' tool to load
its full instructions before proceeding.

- {self.skill_name}: {self.skill_description}

To activate a skill, use:
  skill(name="{self.skill_name}")
"""
            # 修改系统提示
            original_prompt = agent.system_prompt
            agent.system_prompt = original_prompt + "\n\n" + skill_catalog
            
            # 执行 query
            output = agent.step(query)
            
            # 检查输出中是否包含触发 skill 的迹象
            # 注意：这里我们只能检查输出文本，无法直接检查是否调用了 skill 工具
            # 在实际场景中，可能需要检查 Agent 的行为/工具调用
            
            # 启发式检测：检查输出中是否提到 skill 或表现出使用了 skill
            trigger_indicators = [
                f"{self.skill_name}",
                "skill",
                "根据 skill 的指示",
            ]
            
            did_trigger = any(indicator.lower() in output.lower() for indicator in trigger_indicators)
            
            reasoning = f"Output indicates skill usage: {did_trigger}"
            return did_trigger, reasoning
            
        except Exception as e:
            return False, f"Error during evaluation: {e}"
    
    def evaluate_single(self, query: str, should_trigger: bool) -> TriggerEvalResult:
        """评测单个 query"""
        did_trigger, reasoning = self._check_trigger(query)
        
        return TriggerEvalResult(
            query=query,
            should_trigger=should_trigger,
            did_trigger=did_trigger,
            reasoning=reasoning,
        )
    
    def evaluate_set(self, eval_set: list[dict]) -> tuple[list[TriggerEvalResult], TriggerMetrics]:
        """评测一组 queries
        
        Args:
            eval_set: 列表，每个元素是 {"query": str, "should_trigger": bool}
            
        Returns:
            (results, metrics)
        """
        results = []
        
        print(f"Evaluating {len(eval_set)} queries for skill '{self.skill_name}'...")
        
        for i, item in enumerate(eval_set, 1):
            query = item["query"]
            should_trigger = item.get("should_trigger", True)
            
            print(f"  [{i}/{len(eval_set)}] Testing: {query[:50]}...")
            
            result = self.evaluate_single(query, should_trigger)
            results.append(result)
            
            status = "✓" if result.is_correct else "✗"
            expected = "trigger" if should_trigger else "no-trigger"
            actual = "triggered" if result.did_trigger else "not-triggered"
            print(f"      {status} Expected: {expected}, Got: {actual}")
        
        # 计算指标
        tp = sum(1 for r in results if r.is_tp)
        tn = sum(1 for r in results if r.is_tn)
        fp = sum(1 for r in results if r.is_fp)
        fn = sum(1 for r in results if r.is_fn)
        
        metrics = TriggerMetrics(
            total=len(results),
            correct=tp + tn,
            tp=tp,
            tn=tn,
            fp=fp,
            fn=fn,
        )
        
        return results, metrics
    
    def generate_report(self, results: list[TriggerEvalResult], metrics: TriggerMetrics, output_path: Path = None):
        """生成评测报告"""
        report = {
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "skill_name": self.skill_name,
            "skill_description": self.skill_description,
            "metrics": metrics.to_dict(),
            "results": [
                {
                    "query": r.query,
                    "should_trigger": r.should_trigger,
                    "did_trigger": r.did_trigger,
                    "is_correct": r.is_correct,
                    "type": "TP" if r.is_tp else "TN" if r.is_tn else "FP" if r.is_fp else "FN",
                    "reasoning": r.reasoning,
                }
                for r in results
            ],
        }
        
        if output_path:
            output_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
            print(f"\nReport saved to: {output_path}")
        
        return report


def main():
    parser = argparse.ArgumentParser(description="Skill Trigger Evaluation")
    parser.add_argument("--skill-path", type=Path, required=True, help="Path to SKILL.md file")
    parser.add_argument("--eval-set", type=Path, required=True, help="Path to eval set JSON file")
    parser.add_argument("--output", type=Path, help="Output report path")
    parser.add_argument("--workdir", type=Path, help="Working directory")
    args = parser.parse_args()
    
    # 解析 skill
    from bourbon.skills import SkillManager
    skill_manager = SkillManager(args.workdir or Path.cwd())
    
    # 手动加载 skill
    skill_path = args.skill_path
    if skill_path.exists():
        import re
        content = skill_path.read_text()
        
        # 解析 frontmatter
        name_match = re.search(r'^name:\s*(.+)$', content, re.MULTILINE)
        desc_match = re.search(r'^description:\s*(.+)$', content, re.MULTILINE)
        
        skill_name = name_match.group(1).strip() if name_match else skill_path.stem
        skill_description = desc_match.group(1).strip() if desc_match else ""
    else:
        print(f"Error: Skill file not found: {skill_path}")
        sys.exit(1)
    
    # 加载 eval set
    if not args.eval_set.exists():
        print(f"Error: Eval set file not found: {args.eval_set}")
        sys.exit(1)
    
    eval_set = json.loads(args.eval_set.read_text())
    
    # 运行评测
    evaluator = TriggerEvaluator(skill_name, skill_description, args.workdir)
    results, metrics = evaluator.evaluate_set(eval_set)
    
    # 打印摘要
    print(f"\n{'='*60}")
    print(f"Trigger Evaluation Results for '{skill_name}'")
    print(f"{'='*60}")
    print(f"Total queries: {metrics.total}")
    print(f"Accuracy: {metrics.accuracy*100:.1f}%")
    print(f"Precision: {metrics.precision*100:.1f}%")
    print(f"Recall: {metrics.recall*100:.1f}%")
    print(f"F1 Score: {metrics.f1_score:.3f}")
    print(f"False Positive Rate: {metrics.false_positive_rate*100:.1f}%")
    print(f"\nBreakdown:")
    print(f"  TP (正确触发): {metrics.tp}")
    print(f"  TN (正确未触发): {metrics.tn}")
    print(f"  FP (误触发): {metrics.fp}")
    print(f"  FN (漏触发): {metrics.fn}")
    print(f"{'='*60}")
    
    # 生成报告
    evaluator.generate_report(results, metrics, args.output)
    
    # 如果有大量错误，返回非零退出码
    if metrics.accuracy < 0.7:
        sys.exit(1)


if __name__ == "__main__":
    main()
