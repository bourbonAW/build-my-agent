// ── Existing report types ──────────────────────────────────────────────────

export type RegressionResult = 'better' | 'no_change' | 'worse'

export type ConfidenceInterval = {
  point: number
  low: number
  high: number
}

export type RunSummary = {
  runId: string
  harness: string
  judgeVersion: string
  judgeF1: number | null
  judgeValidated: boolean | null
  passRate: ConfidenceInterval
  nonPassCount: number
  createdAt: string
  langfuseRunUrl: string
}

export type LabelDelta = {
  label: string
  baseline: number
  candidate: number
}

export type TraceCase = {
  caseId: string
  traceUrl: string
}

export type RegressionReport = {
  runId: string
  baselineHarness: string
  candidateHarness: string
  judgeVersion: string
  passRate: ConfidenceInterval
  nonPassCount: number
  passRateDelta: ConfidenceInterval
  result: RegressionResult
  perLabel: LabelDelta[]
  fixed: TraceCase[]
  newlyBroken: TraceCase[]
  candidatePrUrl?: string
}

export type JudgeLabelMetric = {
  label: 'pass' | 'fail'
  precision: number
  recall: number
  f1: number
}

export type JudgeReport = {
  judgeVersion: string
  model: string
  promptVersion: string
  f1: number
  threshold: number
  passes: boolean
  goldFailCount: number
  goldPassCount: number
  minClassSupport: number
  goldFailAbstained: number
  goldPassAbstained: number
  perLabel: JudgeLabelMetric[]
  confusion: { tp: number; fp: number; fn: number; tn: number }
  validationSetSize: number
}

// ── Pipeline types ─────────────────────────────────────────────────────────

export type TaskStatus = 'idle' | 'running' | 'done' | 'error'
export type TaskType =
  | 'idle'
  | 'sample'
  | 'promote'
  | 'baseline_harness'
  | 'baseline_judge'
  | 'candidate_harness'
  | 'judge_compare'

export type PipelineTask = {
  type: TaskType
  status: TaskStatus
  runId: string
  done: number
  total: number
  phase: string
  error: string
  result: string
}

export type DatasetInfo = {
  name: string
  totalCases: number
  judgeTestCases: number
  regressionCases: number
  baselineScored: boolean
  lastUpdated: string
}

export type PipelineState = {
  dataset: DatasetInfo
  task: PipelineTask
  lastRunId: string
  lastResult: string
}

export type LangfuseTrace = {
  id: string
  name?: string
  input?: unknown
  output?: unknown
  scores?: unknown[]
  level?: string
  latency?: number
}

export type SampleResult = {
  traces: LangfuseTrace[]
}

export type LabelStatus = {
  total: number
  labeled: number
  complete: boolean
  error?: string
}

export type CaseLabel = 'pass' | 'fail' | 'skip'

export type Case = {
  caseId: string
  input: string
  frozenOutput: string
  traceUrl: string
  expectedOutput: string
  label: CaseLabel | null
  critique: string
  failureCategory: string | null
  annotatedAt: string
}

export type CasesResult = {
  cases: Case[]
}

export type LabelSubmission = {
  expectedOutput: string
  label: CaseLabel
  critique: string
  failureCategory: string | null
}

// ── Fetch helpers ──────────────────────────────────────────────────────────

export class ApiError extends Error {
  status: number
  constructor(status: number, message: string) {
    super(message)
    this.status = status
  }
}

async function fetchJson<T>(path: string): Promise<T> {
  const res = await fetch(path)
  if (!res.ok) throw new ApiError(res.status, `Request failed: ${path}`)
  return (await res.json()) as T
}

async function postJson<T>(path: string, body?: unknown): Promise<T> {
  const res = await fetch(path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: body !== undefined ? JSON.stringify(body) : undefined,
  })
  if (!res.ok) {
    const text = await res.text().catch(() => '')
    throw new ApiError(res.status, text || `POST failed: ${path}`)
  }
  return (await res.json()) as T
}

// ── Report API ────────────────────────────────────────────────────────────

export const fetchRuns = () => fetchJson<RunSummary[]>('/api/runs')
export const fetchRegressionReport = (runId: string) =>
  fetchJson<RegressionReport>(`/api/runs/${runId}`)
export const fetchJudge = (judgeVersion: string) =>
  fetchJson<JudgeReport>(`/api/judges/${judgeVersion}`)

// ── Pipeline API ──────────────────────────────────────────────────────────

export const fetchPipelineState = () => fetchJson<PipelineState>('/api/pipeline/state')
export const fetchSamples = () => fetchJson<SampleResult>('/api/pipeline/samples')
export const fetchLabelStatus = () => fetchJson<LabelStatus>('/api/pipeline/label-status')

// 100 = Langfuse's trace.list API page-size cap (scripts.sample_traces.LANGFUSE_MAX_FETCH_LIMIT
// on the backend, which validates this too — see /api/pipeline/sample).
export const startSample = (limit = 30) =>
  postJson('/api/pipeline/sample', { limit, fetch_limit: 100 })

export const startPromote = (dataset_name: string, trace_ids: string[]) =>
  postJson<{ promoted: number; skipped: number }>(
    '/api/pipeline/promote',
    { dataset_name, trace_ids },
  )

export const fetchCases = () => fetchJson<CasesResult>('/api/pipeline/cases')

export const submitLabel = (caseId: string, body: LabelSubmission) =>
  postJson<Case>(`/api/pipeline/cases/${caseId}/label`, body)

export const startBaselineRun = () => postJson('/api/pipeline/baseline/run')
export const startBaselineJudge = () => postJson('/api/pipeline/baseline/judge')
export const startEvalRun = (run_id: string) =>
  postJson('/api/pipeline/eval/run', { run_id })
export const startJudgeCompare = () => postJson('/api/pipeline/eval/judge-compare')
