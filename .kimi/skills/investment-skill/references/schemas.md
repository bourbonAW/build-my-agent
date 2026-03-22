# Reference Schemas

JSON schemas and data structures for the investment-agent skill.

## Evals JSON Schema

```json
{
  "skill_name": "string - Skill identifier",
  "version": "string - Skill version",
  "description": "string - Description of test suite",
  "evals": [
    {
      "id": "integer - Unique test ID",
      "eval_name": "string - Descriptive name (kebab-case)",
      "prompt": "string - User prompt to test",
      "expected_output": "string - Description of expected result",
      "files": ["array of file paths for test input"],
      "assertions": [
        {
          "name": "string - Assertion identifier",
          "type": "string - Assertion type",
          "target": "string or array - What to check",
          "description": "string - Human-readable description"
        }
      ],
      "metadata": {
        "category": "string - Test category",
        "difficulty": "string - low/medium/high",
        "estimated_duration": "integer - Expected runtime in seconds",
        "should_trigger": "boolean - Whether skill should trigger (default: true)"
      }
    }
  ],
  "metadata": {
    "total_evals": "integer",
    "positive_tests": "integer",
    "negative_tests": "integer",
    "categories": ["array of category names"]
  }
}
```

### Assertion Types

- **file_exists**: Check if output file was created
  ```json
  {
    "type": "file_exists",
    "target": "daily/*_report.md"
  }
  ```

- **content_contains**: Check if output contains specific text
  ```json
  {
    "type": "content_contains",
    "target": ["预警级别", "VIX"]
  }
  ```

- **skill_not_invoked**: For negative tests
  ```json
  {
    "type": "skill_not_invoked",
    "target": "investment-agent"
  }
  ```

## Grading JSON Schema

```json
{
  "eval_id": "integer",
  "eval_name": "string",
  "run_id": "string - unique run identifier",
  "timestamp": "string - ISO 8601 format",
  "assertions": [
    {
      "text": "string - Assertion description",
      "passed": "boolean - Whether assertion passed",
      "evidence": "string - Explanation of result"
    }
  ],
  "overall_score": "float - 0.0 to 1.0",
  "notes": "string - Grader observations"
}
```

## Benchmark JSON Schema

```json
{
  "skill_name": "string",
  "iteration": "integer",
  "timestamp": "string",
  "results": [
    {
      "skill": "string - Module name",
      "iterations": "integer - Number of test runs",
      "success_rate": "float - 0.0 to 1.0",
      "duration_mean": "float - Average duration in seconds",
      "duration_min": "float - Minimum duration",
      "duration_max": "float - Maximum duration",
      "duration_stdev": "float - Standard deviation"
    }
  ],
  "overall": {
    "avg_success_rate": "float",
    "avg_duration": "float",
    "total_tests": "integer"
  }
}
```

## Timing JSON Schema

```json
{
  "total_tokens": "integer - Token count from Claude API",
  "duration_ms": "integer - Execution time in milliseconds",
  "total_duration_seconds": "float - Human-readable duration"
}
```

## Skill Metadata Schema

```yaml
name: "string - Skill identifier"
description: "string - When to trigger, what it does (pushy style recommended)"
version: "string - Semantic versioning"
author: "string - Author name"
compatibility:
  python: "string - Python version requirement"
  dependencies: ["array of required packages"]
  platforms: ["array of supported platforms"]
  integrations: ["array of supported integrations"]
```

## Portfolio Config Schema

```yaml
portfolio:
  funds:
    - code: "string - Fund code (e.g., '019455')"
      name: "string - Full fund name"
      category: "string - semiconductor/commodity/equity/etc"
      region: "string - asia/global/us/etc"
      weight: "float - Portfolio weight (0.0-1.0)"
      
  alerts:
    daily_decline_threshold: "float - % decline to trigger alert"
    consecutive_decline_days: "integer - Days of decline before warning"
    daily_surge_threshold: "float - % surge to trigger alert"
    vix_critical: "float - VIX level for critical warning"
    vix_extreme: "float - VIX level for extreme warning"
```

## Report Output Schema

```markdown
---
date: "YYYY-MM-DD HH:MM"
category: "report_type"
warning_level: "GREEN/YELLOW/ORANGE/RED"
generated_by: "module_name"
---

# Report Title

**Warning Level:** 🟢/🟡/🟠/🔴 LEVEL

## Executive Summary
Brief overview of findings

## Key Signals (if applicable)
List of indicator signals with severity

## Strategic Recommendations
Actionable advice

## Forward-Looking Summary
Predictive analysis
```

## Best Practices

1. **File Naming**: Use timestamps in filenames for easy sorting
   - Format: `{type}_{YYYY-MM-DD}_{HHMM}.md`
   
2. **Warning Levels**: Consistent across all modules
   - 🟢 Green: Normal, no action
   - 🟡 Yellow: Elevated, monitor closely
   - 🟠 Orange: Warning, prepare action
   - 🔴 Red: Critical, action required
   
3. **Data Types**: Use appropriate types
   - Prices: float with 2-4 decimal places
   - Percentages: float (0.15 for 15%)
   - Dates: ISO 8601 format
   - Money: integer (cents) or float with 2 decimals

4. **Error Handling**: Always include fallback values
   ```python
   value = data.get('field', default_value)
   ```
