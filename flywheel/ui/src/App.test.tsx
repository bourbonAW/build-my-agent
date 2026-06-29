import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest'
import { cleanup, render, screen, within } from '@testing-library/react'
import App from './App'
import type { JudgeReport, RegressionReport, RunSummary } from './api'

const runs: RunSummary[] = [
  {
    runId: 'run_valid',
    harness: 'abc@m',
    judgeVersion: 'jv_valid',
    judgeF1: 0.82,
    judgeValidated: true,
    passRate: { point: 0.8, low: 0.7, high: 0.9 },
    nonPassCount: 2,
    createdAt: '2026-06-24',
    langfuseRunUrl: 'http://lf/r/run_valid',
  },
  {
    runId: 'run_bad',
    harness: 'def@m',
    judgeVersion: 'jv_bad',
    judgeF1: 0.66,
    judgeValidated: false,
    passRate: { point: 0.4, low: 0.25, high: 0.58 },
    nonPassCount: 6,
    createdAt: '2026-06-24',
    langfuseRunUrl: 'http://lf/r/run_bad',
  },
  {
    runId: 'run_na',
    harness: 'ghi@m',
    judgeVersion: 'jv_missing',
    judgeF1: null,
    judgeValidated: null,
    passRate: { point: 0.5, low: 0.3, high: 0.7 },
    nonPassCount: 5,
    createdAt: '2026-06-24',
    langfuseRunUrl: 'http://lf/r/run_na',
  },
]

const judgeReport: JudgeReport = {
  judgeVersion: 'jv_bad',
  model: 'claude-opus-4-8',
  promptVersion: 'p1',
  f1: 0.72,
  threshold: 0.7,
  passes: false,
  goldFailCount: 5,
  goldPassCount: 5,
  minClassSupport: 5,
  goldFailAbstained: 3,
  goldPassAbstained: 2,
  perLabel: [
    { label: 'pass', precision: 1, recall: 1, f1: 1 },
    { label: 'fail', precision: 1, recall: 0.4, f1: 0.57 },
  ],
  confusion: { tp: 2, fp: 0, fn: 3, tn: 5 },
  validationSetSize: 10,
}

function regressionReport(result: RegressionReport['result']): RegressionReport {
  return {
    runId: `run_${result}`,
    baselineHarness: 'abc@m',
    candidateHarness: 'def@m',
    judgeVersion: 'jv1',
    passRate: { point: 0.75, low: 0.55, high: 0.9 },
    nonPassCount: 1,
    passRateDelta: { point: 0.25, low: -0.05, high: 0.45 },
    result,
    perLabel: [{ label: 'tool_misuse', baseline: 2, candidate: 1 }],
    fixed: [
      { caseId: 'case_without_trace', traceUrl: '' },
      { caseId: 'case_with_trace', traceUrl: 'http://lf/t/case_with_trace' },
    ],
    newlyBroken: [{ caseId: 'broken_case', traceUrl: 'http://lf/t/broken_case' }],
  }
}

function mockApi(responses: Record<string, unknown | { status: number; body: unknown }>) {
  vi.stubGlobal(
    'fetch',
    vi.fn(async (input: RequestInfo | URL) => {
      const raw = typeof input === 'string' ? input : input.toString()
      const path = raw.startsWith('http') ? new URL(raw).pathname : raw
      const entry = responses[path]
      if (!entry) {
        return new Response(JSON.stringify({ detail: 'not found' }), { status: 404 })
      }
      if (typeof entry === 'object' && entry !== null && 'status' in entry) {
        const errorEntry = entry as { status: number; body: unknown }
        return new Response(JSON.stringify(errorEntry.body), { status: errorEntry.status })
      }
      return new Response(JSON.stringify(entry), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      })
    }),
  )
}

function renderPath(path: string) {
  window.history.pushState({}, '', path)
  return render(<App />)
}

beforeEach(() => {
  window.history.pushState({}, '', '/')
})

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
})

test('runs table renders rows, CI, and all judge states', async () => {
  mockApi({ '/api/runs': runs })
  renderPath('/runs')

  expect(await screen.findByText('run_valid')).toBeInTheDocument()
  expect(screen.getByText('CI 70%-90%')).toBeInTheDocument()
  expect(screen.getByText('82%')).toBeInTheDocument()
  expect(screen.getByText('validated')).toBeInTheDocument()

  expect(screen.getByText('66%')).toBeInTheDocument()
  const notValidated = screen.getByRole('link', { name: 'judge: not validated' })
  expect(notValidated).toHaveAttribute('href', '/judges/jv_bad')
  expect(screen.getByText('not available')).toBeInTheDocument()
})

test('empty runs state explains how to create eval data', async () => {
  mockApi({ '/api/runs': [] })
  renderPath('/runs')

  expect(await screen.findByText('No regression runs yet')).toBeInTheDocument()
  expect(screen.getByText(/run_harness.py/)).toBeInTheDocument()
  expect(screen.getByRole('link', { name: 'Sample traces in Langfuse' })).toBeInTheDocument()
})

describe.each(['better', 'no_change', 'worse'] as const)('regression result %s', (result) => {
  test('renders badge, invariant, per-labels, and trace links', async () => {
    mockApi({ [`/api/runs/run_${result}`]: regressionReport(result) })
    renderPath(`/runs/run_${result}`)

    expect(await screen.findByText(result)).toBeInTheDocument()
    expect(screen.getByText('regression set ∩ judge case pool = ∅')).toBeInTheDocument()
    expect(screen.getByText('tool_misuse')).toBeInTheDocument()
    expect(screen.getByText('case_without_trace').closest('a')).toBeNull()
    expect(screen.getByRole('link', { name: 'case_with_trace' })).toHaveAttribute(
      'href',
      'http://lf/t/case_with_trace',
    )
  })
})

test('missing regression report renders a not-generated state', async () => {
  mockApi({ '/api/runs/missing': { status: 404, body: { detail: 'missing' } } })
  renderPath('/runs/missing')

  expect(await screen.findByText('Report not generated')).toBeInTheDocument()
  expect(screen.getByText(/Run regression.py/)).toBeInTheDocument()
})

test('judge report renders macro-F1 gate, fail-class F1, and abstention split', async () => {
  mockApi({ '/api/judges/jv_bad': judgeReport })
  renderPath('/judges/jv_bad')

  expect(await screen.findByText('jv_bad')).toBeInTheDocument()
  expect(screen.getByText('judge: not validated')).toBeInTheDocument()
  expect(screen.getByText('threshold 70%')).toBeInTheDocument()
  expect(screen.getByText('fail (gate)')).toBeInTheDocument()
  expect(screen.getAllByText('57%')[0]).toBeInTheDocument()
  expect(screen.getByText('3 (3 abstained)')).toBeInTheDocument()
  expect(screen.getByText('5 (2 abstained)')).toBeInTheDocument()
  expect(within(screen.getByText('Macro-F1').closest('.metric')!).getByText('72%')).toBeInTheDocument()
})
