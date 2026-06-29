import { expect, test } from '@playwright/test'

test('opens a run and exposes a Langfuse trace link', async ({ page }) => {
  await page.route('**/api/runs', async (route) => {
    await route.fulfill({
      json: [
        {
          runId: 'run_1',
          harness: 'abc@m',
          judgeVersion: 'jv1',
          judgeF1: 0.82,
          judgeValidated: true,
          passRate: { point: 0.8, low: 0.7, high: 0.9 },
          nonPassCount: 2,
          createdAt: '2026-06-24',
          langfuseRunUrl: 'http://lf/r/run_1',
        },
      ],
    })
  })
  await page.route('**/api/runs/run_1', async (route) => {
    await route.fulfill({
      json: {
        runId: 'run_1',
        baselineHarness: 'abc@m',
        candidateHarness: 'def@m',
        judgeVersion: 'jv1',
        passRate: { point: 0.8, low: 0.7, high: 0.9 },
        nonPassCount: 2,
        passRateDelta: { point: 0.2, low: -0.1, high: 0.35 },
        result: 'better',
        perLabel: [{ label: 'tool_misuse', baseline: 2, candidate: 1 }],
        fixed: [{ caseId: 'case_with_trace', traceUrl: 'http://lf/t/case_with_trace' }],
        newlyBroken: [],
      },
    })
  })

  await page.goto('/runs')
  await page.getByRole('link', { name: 'run_1' }).click()

  await expect(page.getByText('better')).toBeVisible()
  await expect(page.getByRole('link', { name: 'case_with_trace' })).toHaveAttribute(
    'href',
    'http://lf/t/case_with_trace',
  )
})
