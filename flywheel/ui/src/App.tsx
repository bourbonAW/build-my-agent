import {
  Link,
  NavLink,
  Route,
  BrowserRouter as Router,
  Routes,
  useParams,
} from 'react-router-dom'
import { useState, type ReactNode } from 'react'
import { QueryClient, QueryClientProvider, useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import {
  createColumnHelper,
  flexRender,
  getCoreRowModel,
  useReactTable,
} from '@tanstack/react-table'
import { Bar, BarChart, ResponsiveContainer, XAxis } from 'recharts'
import './App.css'
import {
  fetchJudge,
  fetchRegressionReport,
  fetchRuns,
  fetchPipelineState,
  fetchSamples,
  startSample,
  startPromote,
  startBaselineRun,
  startBaselineJudge,
  startEvalRun,
  startJudgeCompare,
  fetchCases,
  submitLabel,
  type ConfidenceInterval,
  type JudgeReport,
  type PipelineState,
  type RegressionReport,
  type RegressionResult,
  type RunSummary,
  type TraceCase,
  type Case,
  type CaseLabel,
} from './api'

function makeQueryClient() {
  return new QueryClient({
    defaultOptions: { queries: { retry: false, staleTime: 10_000 } },
  })
}

function Shell() {
  return (
    <div className="app-shell">
      <header className="topbar">
        <Link to="/" className="brand" aria-label="Flywheel home">
          <span className="brand-mark">F</span>
          <span>Flywheel</span>
        </Link>
        <nav className="nav-links" aria-label="Primary">
          <NavLink to="/">Control</NavLink>
          <NavLink to="/label">Label</NavLink>
          <NavLink to="/runs">History</NavLink>
          <a href="https://cloud.langfuse.com" target="_blank" rel="noreferrer">
            Langfuse
          </a>
        </nav>
      </header>
      <main>
        <Routes>
          <Route path="/" element={<ControlView />} />
          <Route path="/label" element={<LabelView />} />
          <Route path="/runs" element={<RunsView />} />
          <Route path="/runs/:runId" element={<RunDetailView />} />
          <Route path="/judges/:judgeVersion" element={<JudgeDetailView />} />
        </Routes>
      </main>
    </div>
  )
}

export default function App() {
  const [client] = useState(makeQueryClient)
  return (
    <QueryClientProvider client={client}>
      <Router>
        <Shell />
      </Router>
    </QueryClientProvider>
  )
}

// ── Control view ────────────────────────────────────────────────────────────

function ControlView() {
  const qc = useQueryClient()
  const stateQuery = useQuery({
    queryKey: ['pipeline-state'],
    queryFn: fetchPipelineState,
    refetchInterval: (query) => {
      const status = query.state.data?.task.status
      return status === 'running' ? 1500 : 5000
    },
  })

  const state = stateQuery.data
  const task = state?.task
  const dataset = state?.dataset
  const isRunning = task?.status === 'running'

  const invalidate = () => qc.invalidateQueries({ queryKey: ['pipeline-state'] })

  return (
    <div className="control-layout">
      <DatasetPanel
        dataset={dataset}
        task={task}
        isRunning={isRunning ?? false}
        onRefresh={invalidate}
      />
      <EvalPanel
        state={state}
        task={task}
        isRunning={isRunning ?? false}
        onRefresh={invalidate}
      />
    </div>
  )
}

// ── Dataset panel ───────────────────────────────────────────────────────────

type DatasetPanelProps = {
  dataset: PipelineState['dataset'] | undefined
  task: PipelineState['task'] | undefined
  isRunning: boolean
  onRefresh: () => void
}

function DatasetPanel({ dataset, task, isRunning, onRefresh }: DatasetPanelProps) {
  const qc = useQueryClient()
  const hasDataset = !!dataset?.name
  const baselineScored = dataset?.baselineScored ?? false

  const sampleMutation = useMutation({
    mutationFn: () => startSample(30),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['pipeline-state'] })
      qc.invalidateQueries({ queryKey: ['pipeline-samples'] })
    },
  })

  const baselineRunMutation = useMutation({
    mutationFn: startBaselineRun,
    onSuccess: onRefresh,
  })

  const baselineJudgeMutation = useMutation({
    mutationFn: startBaselineJudge,
    onSuccess: onRefresh,
  })

  const isSampling = task?.type === 'sample' && task.status === 'running'
  const isBaselineRunning =
    (task?.type === 'baseline_harness' || task?.type === 'baseline_judge') &&
    task.status === 'running'

  return (
    <section className="panel control-panel">
      <div className="panel-head">
        <h2>Dataset</h2>
        {hasDataset && (
          <button
            className="button secondary small"
            disabled={isRunning}
            onClick={() => sampleMutation.mutate()}
          >
            + Add traces
          </button>
        )}
      </div>

      {!hasDataset ? (
        <DatasetEmpty onSample={() => sampleMutation.mutate()} loading={sampleMutation.isPending || isSampling} />
      ) : (
        <>
          <div className="dataset-stats">
            <Stat label="Dataset" value={dataset.name} mono />
            <Stat label="Total cases" value={String(dataset.totalCases)} />
          </div>

          <div className="dataset-status">
            <StatusRow
              label="Cases in Langfuse"
              done={hasDataset}
              href="https://cloud.langfuse.com"
              hrefLabel="Open Langfuse ↗"
            />
            <LabelStatusRow />
            <StatusRow label="Baseline scored" done={baselineScored} />
          </div>

          {isBaselineRunning && task && (
            <ProgressBar done={task.done} total={task.total} phase={task.phase} />
          )}

          {task?.type === 'baseline_harness' && task.status === 'error' && (
            <ErrorBox message={task.error} />
          )}

          {!baselineScored && (
            <div className="panel-actions">
              <button
                className="button primary"
                disabled={isRunning || baselineRunMutation.isPending}
                onClick={() => baselineRunMutation.mutate()}
              >
                Run baseline harness
              </button>
              <button
                className="button secondary"
                disabled={isRunning || baselineJudgeMutation.isPending}
                onClick={() => baselineJudgeMutation.mutate()}
              >
                Judge baseline
              </button>
            </div>
          )}
        </>
      )}

      {isSampling && task && (
        <ProgressBar done={task.done} total={task.total} phase="Sampling traces from Langfuse" />
      )}

      <SamplePanel show={!hasDataset || sampleMutation.isSuccess || isSampling} onRefresh={onRefresh} />
    </section>
  )
}

function DatasetEmpty({ onSample, loading }: { onSample: () => void; loading: boolean }) {
  return (
    <div className="empty-state">
      <p>No dataset yet. Sample recent traces from Langfuse to get started.</p>
      <button className="button primary" onClick={onSample} disabled={loading}>
        {loading ? 'Sampling…' : 'Sample traces'}
      </button>
    </div>
  )
}

function LabelStatusRow() {
  const q = useQuery({
    queryKey: ['label-status'],
    queryFn: fetchCases,
    refetchInterval: 10_000,
  })
  const cases = q.data?.cases ?? []
  const total = cases.length
  const labeled = cases.filter((c) => c.label !== null).length
  const complete = labeled >= total && total > 0
  return (
    <div className="status-row">
      <span>{complete ? '✅' : '○'} Human labels</span>
      <span className="quiet">
        {labeled}/{total}
      </span>
      {!complete && (
        <Link to="/label" className="quiet-link">
          Label cases →
        </Link>
      )}
    </div>
  )
}

function StatusRow({
  label,
  done,
  href,
  hrefLabel,
}: {
  label: string
  done: boolean
  href?: string
  hrefLabel?: string
}) {
  return (
    <div className="status-row">
      <span>{done ? '✅' : '○'} {label}</span>
      {href && !done && (
        <a href={href} target="_blank" rel="noreferrer" className="quiet-link">
          {hrefLabel ?? href}
        </a>
      )}
    </div>
  )
}

function SamplePanel({ show, onRefresh }: { show: boolean; onRefresh: () => void }) {
  const qc = useQueryClient()
  const samplesQuery = useQuery({
    queryKey: ['pipeline-samples'],
    queryFn: fetchSamples,
    enabled: show,
  })

  const promoteMutation = useMutation({
    mutationFn: ({ name, ids }: { name: string; ids: string[] }) =>
      startPromote(name, ids),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['pipeline-state'] })
      qc.invalidateQueries({ queryKey: ['pipeline-samples'] })
      onRefresh()
    },
  })

  const [selected, setSelected] = useState<Set<string>>(new Set())
  const [datasetName, setDatasetName] = useState('bourbon-evals')

  const traces = samplesQuery.data?.traces ?? []

  if (!show || traces.length === 0) return null

  const toggle = (id: string) =>
    setSelected((prev) => {
      const next = new Set(prev)
      next.has(id) ? next.delete(id) : next.add(id)
      return next
    })

  const selectAll = () => setSelected(new Set(traces.map((t) => String(t.id))))
  const clearAll = () => setSelected(new Set())

  return (
    <div className="sample-panel">
      <div className="sample-head">
        <h3>{traces.length} sampled traces</h3>
        <div className="sample-actions">
          <button className="button secondary small" onClick={selectAll}>All</button>
          <button className="button secondary small" onClick={clearAll}>None</button>
        </div>
      </div>
      <ul className="trace-select-list">
        {traces.map((t) => {
          const id = String(t.id)
          return (
            <li key={id} className={selected.has(id) ? 'selected' : ''} onClick={() => toggle(id)}>
              <input type="checkbox" readOnly checked={selected.has(id)} />
              <span className="trace-id">{id.slice(0, 8)}…</span>
              <span className="trace-name quiet">{t.name ?? ''}</span>
            </li>
          )
        })}
      </ul>
      <div className="promote-row">
        <input
          className="dataset-name-input"
          value={datasetName}
          onChange={(e) => setDatasetName(e.target.value)}
          placeholder="Dataset name"
        />
        <button
          className="button primary"
          disabled={selected.size === 0 || promoteMutation.isPending}
          onClick={() => promoteMutation.mutate({ name: datasetName, ids: [...selected] })}
        >
          Promote {selected.size > 0 ? `${selected.size} cases` : 'cases'}
        </button>
      </div>
      {promoteMutation.isSuccess && (
        <p className="success-msg">
          ✅ Promoted to Langfuse.{' '}
          <a href="https://cloud.langfuse.com" target="_blank" rel="noreferrer">
            Open Langfuse to label ↗
          </a>
        </p>
      )}
      {promoteMutation.isError && (
        <ErrorBox message={(promoteMutation.error as Error).message} />
      )}
    </div>
  )
}

// ── Eval panel ──────────────────────────────────────────────────────────────

type EvalPanelProps = {
  state: PipelineState | undefined
  task: PipelineState['task'] | undefined
  isRunning: boolean
  onRefresh: () => void
}

function EvalPanel({ state, task, isRunning, onRefresh }: EvalPanelProps) {
  const qc = useQueryClient()
  const [runId, setRunId] = useState('')
  const locked = !(state?.dataset.baselineScored)

  const evalRunMutation = useMutation({
    mutationFn: () => startEvalRun(runId),
    onSuccess: onRefresh,
  })

  const judgeCompareMutation = useMutation({
    mutationFn: startJudgeCompare,
    onSuccess: () => {
      onRefresh()
      qc.invalidateQueries({ queryKey: ['runs'] })
    },
  })

  const isCandidateRunning = task?.type === 'candidate_harness' && task.status === 'running'
  const isJudgeRunning = task?.type === 'judge_compare' && task.status === 'running'
  const candidateDone = task?.type === 'candidate_harness' && task.status === 'done'
  const lastRunId = state?.lastRunId ?? ''
  const lastResult = state?.lastResult ?? task?.result ?? ''

  return (
    <section className={`panel control-panel ${locked ? 'locked' : ''}`}>
      <div className="panel-head">
        <h2>Evaluate candidate</h2>
        {locked && <span className="badge warn">Complete baseline first</span>}
      </div>

      {locked ? (
        <p className="quiet">Build and score a baseline before evaluating candidates.</p>
      ) : (
        <>
          <div className="eval-run-row">
            <input
              className="run-id-input"
              placeholder="run-id (e.g. candidate-v2)"
              value={runId}
              onChange={(e) => setRunId(e.target.value)}
              disabled={isRunning}
            />
            <button
              className="button primary"
              disabled={isRunning || !runId || evalRunMutation.isPending}
              onClick={() => evalRunMutation.mutate()}
            >
              Run harness
            </button>
          </div>

          {isCandidateRunning && task && (
            <ProgressBar done={task.done} total={task.total} phase={`Running ${task.runId}`} />
          )}

          {(candidateDone || lastRunId) && !isCandidateRunning && (
            <div className="eval-phase">
              <p className="quiet">
                Harness done for <code>{lastRunId || task?.runId}</code>.
              </p>
              <button
                className="button primary"
                disabled={isRunning || judgeCompareMutation.isPending}
                onClick={() => judgeCompareMutation.mutate()}
              >
                Judge + compare
              </button>
            </div>
          )}

          {isJudgeRunning && task && (
            <ProgressBar done={task.done} total={task.total} phase={task.phase} />
          )}

          {task?.type === 'judge_compare' && task.status === 'error' && (
            <ErrorBox message={task.error} />
          )}

          {lastResult && (
            <div className="result-row">
              <ResultBadge result={lastResult as RegressionResult} />
              {lastRunId && (
                <Link to={`/runs/${lastRunId}`} className="quiet-link">
                  View full report →
                </Link>
              )}
            </div>
          )}
        </>
      )}
    </section>
  )
}

// ── Shared UI atoms ─────────────────────────────────────────────────────────

function ProgressBar({ done, total, phase }: { done: number; total: number; phase: string }) {
  const pct = total > 0 ? Math.min(100, Math.round((done / total) * 100)) : 0
  return (
    <div className="progress-block">
      {phase && <p className="progress-phase">{phase}</p>}
      <div className="progress-bar-bg">
        <div className="progress-bar-fill" style={{ width: `${pct}%` }} />
      </div>
      <p className="progress-count">
        {done}/{total}
      </p>
    </div>
  )
}

function ErrorBox({ message }: { message: string }) {
  return <div className="error-box">{message}</div>
}

function Stat({ label, value, mono }: { label: string; value: string; mono?: boolean }) {
  return (
    <div className="stat">
      <span className="quiet">{label}</span>
      <strong className={mono ? 'mono' : undefined}>{value}</strong>
    </div>
  )
}

// ── Label view ──────────────────────────────────────────────────────────────

function LabelView() {
  const qc = useQueryClient()
  const casesQuery = useQuery({ queryKey: ['cases'], queryFn: fetchCases })
  const cases = casesQuery.data?.cases ?? []

  const firstUnlabeledIndex = cases.findIndex((c) => c.label === null)
  const [index, setIndex] = useState(0)
  const [expectedOutput, setExpectedOutput] = useState('')
  const [critique, setCritique] = useState('')
  const [failureCategory, setFailureCategory] = useState('')

  const current: Case | undefined = cases[index]

  const labelMutation = useMutation({
    mutationFn: (label: CaseLabel) => {
      if (!current) throw new Error('no case selected')
      return submitLabel(current.caseId, {
        expectedOutput,
        label,
        critique,
        failureCategory: failureCategory || null,
      })
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['cases'] })
      qc.invalidateQueries({ queryKey: ['label-status'] })
      const next = cases.findIndex((c, i) => i > index && c.label === null)
      if (next >= 0) selectCase(next)
    },
  })

  function selectCase(i: number) {
    setIndex(i)
    const c = cases[i]
    setExpectedOutput(c?.expectedOutput ?? '')
    setCritique(c?.critique ?? '')
    setFailureCategory(c?.failureCategory ?? '')
  }

  function navigate(delta: number) {
    const next = index + delta
    if (next < 0 || next >= cases.length) return
    selectCase(next)
  }

  if (casesQuery.isLoading) return <PageState title="Loading cases" />
  if (!cases.length)
    return (
      <PageState
        title="No cases yet"
        detail="Sample and promote traces from Control before labeling."
        action={<Link to="/">Go to Control →</Link>}
      />
    )

  const startIndex = firstUnlabeledIndex >= 0 ? firstUnlabeledIndex : 0
  if (index === 0 && startIndex !== 0 && expectedOutput === '' && critique === '') {
    // Land on the first unlabeled case on initial load only.
    selectCase(startIndex)
  }

  return (
    <section className="page-section label-layout">
      <div className="label-strip">
        {cases.map((c, i) => (
          <button
            key={c.caseId}
            className={`label-strip-item ${i === index ? 'active' : ''}`}
            onClick={() => selectCase(i)}
          >
            {c.label ? '✓' : '○'} {c.caseId.slice(0, 8)}…
          </button>
        ))}
      </div>
      {current && (
        <div className="label-detail">
          <h3>Input</h3>
          <pre className="label-text">{current.input}</pre>
          <h3>Actual output (frozen)</h3>
          <pre className="label-text">{current.frozenOutput}</pre>
          <a href={current.traceUrl} target="_blank" rel="noreferrer">
            View original trace ↗
          </a>
          <h3>Expected output</h3>
          <textarea
            value={expectedOutput}
            onChange={(e) => setExpectedOutput(e.target.value)}
            rows={4}
          />
          <div className="label-buttons">
            <button
              className="button primary"
              disabled={labelMutation.isPending}
              onClick={() => labelMutation.mutate('pass')}
            >
              Pass
            </button>
            <button
              className="button secondary"
              disabled={labelMutation.isPending}
              onClick={() => labelMutation.mutate('fail')}
            >
              Fail
            </button>
            <button
              className="button secondary"
              disabled={labelMutation.isPending}
              onClick={() => labelMutation.mutate('skip')}
            >
              Skip
            </button>
          </div>
          <label>
            Critique (optional)
            <textarea value={critique} onChange={(e) => setCritique(e.target.value)} rows={2} />
          </label>
          <label>
            Failure category (optional)
            <input value={failureCategory} onChange={(e) => setFailureCategory(e.target.value)} />
          </label>
          <div className="label-nav">
            <button onClick={() => navigate(-1)} disabled={index === 0}>
              ← prev
            </button>
            <button onClick={() => navigate(1)} disabled={index === cases.length - 1}>
              next →
            </button>
          </div>
        </div>
      )}
    </section>
  )
}

// ── Runs history ────────────────────────────────────────────────────────────

const runColumn = createColumnHelper<RunSummary>()

function RunsView() {
  const runsQuery = useQuery({ queryKey: ['runs'], queryFn: fetchRuns })
  const columns = [
    runColumn.accessor('runId', {
      header: 'Run',
      cell: (info) => <Link to={`/runs/${info.getValue()}`}>{info.getValue()}</Link>,
    }),
    runColumn.accessor('harness', {
      header: 'Harness',
      cell: (info) => <code>{info.getValue()}</code>,
    }),
    runColumn.accessor('judgeVersion', {
      header: 'Judge',
      cell: (info) => <JudgeStatus run={info.row.original} />,
    }),
    runColumn.accessor('passRate', {
      header: 'Pass rate',
      cell: (info) => <PassRateCell ci={info.getValue()} />,
    }),
    runColumn.accessor('nonPassCount', {
      header: '# not passed',
      cell: (info) => <span className="number">{info.getValue()}</span>,
    }),
    runColumn.accessor('langfuseRunUrl', {
      header: 'Trace',
      cell: (info) =>
        info.getValue() ? (
          <a href={info.getValue()} target="_blank" rel="noreferrer">
            Langfuse
          </a>
        ) : null,
    }),
  ]
  const table = useReactTable({ data: runsQuery.data ?? [], columns, getCoreRowModel: getCoreRowModel() })

  if (runsQuery.isLoading) return <PageState title="Loading runs" />
  if (runsQuery.isError) return <PageState title="Runs unavailable" detail="The read API did not return /api/runs." />
  if (!runsQuery.data?.length)
    return (
      <PageState
        title="No regression runs yet"
        detail="Complete the flywheel loop to generate your first run."
        action={<Link to="/">Go to Control →</Link>}
      />
    )

  return (
    <section className="page-section">
      <div className="section-head">
        <div>
          <p className="section-label">Regression runs</p>
          <h1>History</h1>
        </div>
        <span className="quiet">{runsQuery.data.length} report-backed runs</span>
      </div>
      <div className="table-wrap">
        <table>
          <thead>
            {table.getHeaderGroups().map((hg) => (
              <tr key={hg.id}>
                {hg.headers.map((h) => (
                  <th key={h.id}>{flexRender(h.column.columnDef.header, h.getContext())}</th>
                ))}
              </tr>
            ))}
          </thead>
          <tbody>
            {table.getRowModel().rows.map((row) => (
              <tr key={row.id}>
                {row.getVisibleCells().map((cell) => (
                  <td key={cell.id}>{flexRender(cell.column.columnDef.cell, cell.getContext())}</td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  )
}

function JudgeStatus({ run }: { run: RunSummary }) {
  if (run.judgeF1 === null || run.judgeValidated === null)
    return (
      <div className="stack-tight">
        <span>{run.judgeVersion}</span>
        <span className="badge neutral">not available</span>
      </div>
    )
  return (
    <div className="stack-tight">
      <span>
        {run.judgeVersion} <strong>{formatPercent(run.judgeF1)}</strong>
      </span>
      {run.judgeValidated ? (
        <span className="badge good">validated</span>
      ) : (
        <Link className="badge warn" to={`/judges/${run.judgeVersion}`}>
          judge: not validated
        </Link>
      )}
    </div>
  )
}

function PassRateCell({ ci }: { ci: ConfidenceInterval }) {
  const data = [{ name: 'pass', point: Math.round(ci.point * 100) }]
  return (
    <div className="pass-rate-cell">
      <span>{formatPercent(ci.point)}</span>
      <ResponsiveContainer width={96} height={24}>
        <BarChart data={data} layout="vertical" margin={{ top: 4, right: 0, bottom: 4, left: 0 }}>
          <XAxis type="number" domain={[0, 100]} hide />
          <Bar dataKey="point" fill="#256f46" radius={[2, 2, 2, 2]} />
        </BarChart>
      </ResponsiveContainer>
      <small>
        CI {formatPercent(ci.low)}-{formatPercent(ci.high)}
      </small>
    </div>
  )
}

function RunDetailView() {
  const { runId = '' } = useParams()
  const q = useQuery({ queryKey: ['run', runId], queryFn: () => fetchRegressionReport(runId) })
  if (q.isLoading) return <PageState title="Loading report" />
  if (q.isError)
    return <PageState title="Report not generated" detail="Run judge-compare to generate this report." />
  if (!q.data) return <PageState title="Report not generated" />
  return <RegressionReportView report={q.data} />
}

function RegressionReportView({ report }: { report: RegressionReport }) {
  return (
    <section className="page-section">
      <div className="section-head">
        <div>
          <p className="section-label">Regression report</p>
          <h1>{report.runId}</h1>
        </div>
        <ResultBadge result={report.result} />
      </div>
      <div className="summary-grid">
        <Metric label="Baseline" value={report.baselineHarness} mono />
        <Metric label="Candidate" value={report.candidateHarness} mono />
        <Metric label="Judge" value={report.judgeVersion} note="same judge enforced" />
        <Metric label="Pass rate" value={formatPercent(report.passRate.point)} />
        <Metric label="Non-pass" value={String(report.nonPassCount)} />
      </div>
      <div className="band-row">
        <strong>Pass-rate delta</strong>
        <span>{formatSignedPercent(report.passRateDelta.point)}</span>
        <small>
          descriptive band {formatSignedPercent(report.passRateDelta.low)} to{' '}
          {formatSignedPercent(report.passRateDelta.high)}
        </small>
      </div>
      <p className="invariant">regression set ∩ judge case pool = ∅</p>
      <div className="two-column">
        <DeltaTable rows={report.perLabel} />
        <TraceLists fixed={report.fixed} newlyBroken={report.newlyBroken} />
      </div>
    </section>
  )
}

function ResultBadge({ result }: { result: RegressionResult }) {
  const cls = result === 'better' ? 'good' : result === 'worse' ? 'bad' : 'warn'
  return <span className={`badge ${cls}`}>{result}</span>
}

function DeltaTable({ rows }: { rows: RegressionReport['perLabel'] }) {
  return (
    <section className="panel">
      <h2>Per-label failures</h2>
      <table>
        <thead>
          <tr><th>Label</th><th>Baseline</th><th>Candidate</th></tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.label}>
              <td>{row.label}</td><td>{row.baseline}</td><td>{row.candidate}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  )
}

function TraceLists({ fixed, newlyBroken }: { fixed: TraceCase[]; newlyBroken: TraceCase[] }) {
  return (
    <section className="panel trace-panel">
      <h2>Trace evidence</h2>
      <TraceList title="Fixed" cases={fixed} />
      <TraceList title="Newly broken" cases={newlyBroken} />
    </section>
  )
}

function TraceList({ title, cases }: { title: string; cases: TraceCase[] }) {
  return (
    <div>
      <h3>{title}</h3>
      {cases.length === 0 ? (
        <p className="quiet">None</p>
      ) : (
        <ul className="trace-list">
          {cases.map((item) => (
            <li key={`${title}-${item.caseId}`}>
              {item.traceUrl ? (
                <a href={item.traceUrl} target="_blank" rel="noreferrer">{item.caseId}</a>
              ) : (
                <span>{item.caseId}</span>
              )}
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}

function JudgeDetailView() {
  const { judgeVersion = '' } = useParams()
  const q = useQuery({ queryKey: ['judge', judgeVersion], queryFn: () => fetchJudge(judgeVersion) })
  if (q.isLoading) return <PageState title="Loading judge report" />
  if (q.isError) return <PageState title="Judge report not found" detail="Validate the judge to write its report." />
  if (!q.data) return <PageState title="Judge report not found" />
  return <JudgeReportView report={q.data} />
}

function JudgeReportView({ report }: { report: JudgeReport }) {
  const failRow = report.perLabel.find((r) => r.label === 'fail')
  return (
    <section className="page-section">
      <div className="section-head">
        <div>
          <p className="section-label">Judge validation</p>
          <h1>{report.judgeVersion}</h1>
        </div>
        <span className={`badge ${report.passes ? 'good' : 'warn'}`}>
          {report.passes ? 'validated' : 'judge: not validated'}
        </span>
      </div>
      <div className="summary-grid">
        <Metric label="Macro-F1" value={formatPercent(report.f1)} note={`threshold ${formatPercent(report.threshold)}`} />
        <Metric label="Gold fail" value={`${report.goldFailCount}/${report.minClassSupport}`} />
        <Metric label="Gold pass" value={`${report.goldPassCount}/${report.minClassSupport}`} />
        <Metric label="Fail-class F1 gate" value={failRow ? formatPercent(failRow.f1) : 'n/a'} />
      </div>
      <div className="two-column">
        <section className="panel">
          <h2>Per-label precision / recall / F1</h2>
          <table>
            <thead><tr><th>Label</th><th>Precision</th><th>Recall</th><th>F1</th></tr></thead>
            <tbody>
              {report.perLabel.map((row) => (
                <tr key={row.label}>
                  <td>{row.label === 'fail' ? `${row.label} (gate)` : row.label}</td>
                  <td>{formatPercent(row.precision)}</td>
                  <td>{formatPercent(row.recall)}</td>
                  <td>{formatPercent(row.f1)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
        <section className="panel">
          <h2>Confusion matrix</h2>
          <div className="confusion-grid">
            <Metric label="TP" value={String(report.confusion.tp)} />
            <Metric label="FP" value={String(report.confusion.fp)} />
            <Metric label="FN" value={`${report.confusion.fn} (${report.goldFailAbstained} abstained)`} />
            <Metric label="TN" value={`${report.confusion.tn} (${report.goldPassAbstained} abstained)`} />
          </div>
        </section>
      </div>
    </section>
  )
}

function Metric({ label, value, note, mono = false }: { label: string; value: string; note?: string; mono?: boolean }) {
  return (
    <div className="metric">
      <span>{label}</span>
      <strong className={mono ? 'mono' : undefined}>{value}</strong>
      {note ? <small>{note}</small> : null}
    </div>
  )
}

function PageState({ title, detail, action }: { title: string; detail?: string; action?: ReactNode }) {
  return (
    <section className="page-state">
      <h1>{title}</h1>
      {detail ? <p>{detail}</p> : null}
      {action ? <div className="state-action">{action}</div> : null}
    </section>
  )
}

function formatPercent(value: number) {
  return `${Math.round(value * 100)}%`
}

function formatSignedPercent(value: number) {
  const p = Math.round(value * 100)
  return `${p > 0 ? '+' : ''}${p}%`
}
