"""LLM Judge for evaluating open-ended tasks.

参考 Skill-Creator 的 grader 设计理念，使用独立 LLM 评估主观质量。
"""

import json
import sys
from pathlib import Path
from typing import Any

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from bourbon.config import ConfigManager
from bourbon.llm import create_client, LLMError


class LLMJudge:
    """LLM-as-a-Judge for evaluating agent outputs."""
    
    def __init__(self):
        self.config = ConfigManager().load_config()
        self.llm = create_client(self.config)
    
    def evaluate(
        self,
        prompt: str,
        output: str,
        criteria: str,
        context: dict | None = None,
    ) -> dict:
        """Evaluate output against criteria.
        
        Args:
            prompt: Original user prompt
            output: Agent's output to evaluate
            criteria: Evaluation criteria description
            context: Additional context (e.g., expected files, code samples)
            
        Returns:
            Dict with "passed" (bool), "reasoning" (str), and "confidence" (float)
        """
        # Build evaluation prompt
        eval_prompt = self._build_eval_prompt(prompt, output, criteria, context)
        
        # Call LLM for evaluation
        messages = [{"role": "user", "content": eval_prompt}]
        
        try:
            response = self.llm.chat(
                messages=messages,
                system=self._get_system_prompt(),
                max_tokens=4000,
            )
            
            # Parse evaluation result
            content = response.get("content", [])
            text_parts = [b.get("text", "") for b in content if b.get("type") == "text"]
            result_text = "".join(text_parts)
            
            return self._parse_result(result_text)
            
        except LLMError as e:
            return {
                "passed": False,
                "reasoning": f"LLM evaluation error: {e}",
                "confidence": 0.0,
            }
    
    def _build_eval_prompt(
        self,
        prompt: str,
        output: str,
        criteria: str,
        context: dict | None = None,
    ) -> str:
        """Build the evaluation prompt."""
        lines = [
            "请评估以下 AI Agent 的输出是否符合预期标准。",
            "",
            "=== 原始任务 ===",
            prompt,
            "",
            "=== Agent 的输出 ===",
            output[:2000],  # Limit output length
            "",
            "=== 评估标准 ===",
            criteria,
            "",
        ]
        
        if context:
            lines.append("=== 附加上下文 ===")
            for key, value in context.items():
                lines.append(f"{key}: {value}")
            lines.append("")
        
        lines.extend([
            "=== 评估要求 ===",
            "1. 仔细阅读输出内容，对照评估标准",
            "2. 给出明确判断：通过 (PASS) 或 不通过 (FAIL)",
            "3. 提供简要的理由说明（2-3句话）",
            "4. 给出置信度评分（0.0-1.0）",
            "",
            "=== 输出格式 ===",
            "请以 JSON 格式返回：",
            '{"passed": true/false, "reasoning": "理由", "confidence": 0.8}',
        ])
        
        return "\n".join(lines)
    
    def _get_system_prompt(self) -> str:
        """Get system prompt for the judge."""
        return (
            "You are an expert evaluator assessing AI agent outputs. "
            "Be objective, fair, and consistent in your evaluations. "
            "Provide your assessment in valid JSON format only."
        )
    
    def _parse_result(self, text: str) -> dict:
        """Parse evaluation result from LLM output."""
        # Try to extract JSON from the text
        try:
            # Look for JSON block
            if "```json" in text:
                json_text = text.split("```json")[1].split("```")[0].strip()
            elif "```" in text:
                json_text = text.split("```")[1].split("```")[0].strip()
            else:
                json_text = text.strip()
            
            result = json.loads(json_text)
            
            # Validate required fields
            return {
                "passed": bool(result.get("passed", False)),
                "reasoning": str(result.get("reasoning", "No reasoning provided")),
                "confidence": float(result.get("confidence", 0.5)),
            }
            
        except (json.JSONDecodeError, IndexError) as e:
            # Fallback: try to infer from text
            text_lower = text.lower()
            passed = "pass" in text_lower and "fail" not in text_lower
            
            return {
                "passed": passed,
                "reasoning": f"Failed to parse JSON: {e}. Raw text: {text[:200]}",
                "confidence": 0.5 if passed else 0.0,
            }


# Singleton instance
_judge_instance: LLMJudge | None = None


def get_judge() -> LLMJudge:
    """Get or create LLM Judge instance."""
    global _judge_instance
    if _judge_instance is None:
        _judge_instance = LLMJudge()
    return _judge_instance


def evaluate_assertion(
    assertion: dict,
    prompt: str,
    output: str,
    context: dict | None = None,
) -> dict:
    """Convenience function to evaluate an LLM judge assertion.
    
    Args:
        assertion: The assertion dict with "criteria" or "description"
        prompt: Original user prompt
        output: Agent output
        context: Additional context
        
    Returns:
        Dict with "passed", "reasoning", "confidence"
    """
    judge = get_judge()
    
    # Get criteria from assertion
    criteria = assertion.get("criteria") or assertion.get("description", "")
    
    return judge.evaluate(prompt, output, criteria, context)
