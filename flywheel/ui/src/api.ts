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
  confusion: {
    tp: number
    fp: number
    fn: number
    tn: number
  }
  validationSetSize: number
}

export class ApiError extends Error {
  status: number

  constructor(status: number, message: string) {
    super(message)
    this.status = status
  }
}

async function fetchJson<T>(path: string): Promise<T> {
  const response = await fetch(path)
  if (!response.ok) {
    throw new ApiError(response.status, `Request failed: ${path}`)
  }
  return (await response.json()) as T
}

export function fetchRuns() {
  return fetchJson<RunSummary[]>('/api/runs')
}

export function fetchRegressionReport(runId: string) {
  return fetchJson<RegressionReport>(`/api/runs/${runId}`)
}

export function fetchJudge(judgeVersion: string) {
  return fetchJson<JudgeReport>(`/api/judges/${judgeVersion}`)
}
