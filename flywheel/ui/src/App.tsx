import {
  Link,
  NavLink,
  Route,
  BrowserRouter as Router,
  Routes,
  useParams,
} from 'react-router-dom'
import { useState, type ReactNode } from 'react'
import { QueryClient, QueryClientProvider, useQuery } from '@tanstack/react-query'
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
  type ConfidenceInterval,
  type JudgeReport,
  type RegressionReport,
  type RegressionResult,
  type RunSummary,
  type TraceCase,
} from './api'

function makeQueryClient() {
  return new QueryClient({
    defaultOptions: {
      queries: {
        retry: false,
        staleTime: 20_000,
      },
    },
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
          <NavLink to="/runs">Runs</NavLink>
          <a href="https://cloud.langfuse.com" target="_blank" rel="noreferrer">
            Langfuse
          </a>
        </nav>
      </header>
      <main>
        <Routes>
          <Route path="/" element={<Home />} />
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

function Home() {
  return (
    <section className="home-grid">
      <div>
        <p className="section-label">Lean eval loop</p>
        <h1>Trace failures, replay cases, compare one change.</h1>
        <p className="home-copy">
          Flywheel reads regression and judge reports from local files, then links each run back
          to Langfuse for traces, datasets, scores, and annotations.
        </p>
        <div className="home-actions">
          <Link className="button primary" to="/runs">
            View runs
          </Link>
          <a className="button secondary" href="https://cloud.langfuse.com" target="_blank" rel="noreferrer">
            Open Langfuse
          </a>
        </div>
      </div>
      <div className="home-panel" aria-label="Flywheel loop">
        <div>Sample traces</div>
        <div>Promote cases</div>
        <div>Run harness</div>
        <div>Judge + compare</div>
      </div>
    </section>
  )
}

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
      cell: (info) => (
        <a href={info.getValue()} target="_blank" rel="noreferrer">
          Langfuse
        </a>
      ),
    }),
  ]
  const table = useReactTable({
    data: runsQuery.data ?? [],
    columns,
    getCoreRowModel: getCoreRowModel(),
  })

  if (runsQuery.isLoading) {
    return <PageState title="Loading runs" />
  }
  if (runsQuery.isError) {
    return <PageState title="Runs unavailable" detail="The read API did not return /api/runs." />
  }
  if (!runsQuery.data?.length) {
    return (
      <PageState
        title="No regression runs yet"
        detail="Run sample_traces.py, promote cases in Langfuse, then run_harness.py and run_regression.py."
        action={
          <a href="https://cloud.langfuse.com" target="_blank" rel="noreferrer">
            Sample traces in Langfuse
          </a>
        }
      />
    )
  }

  return (
    <section className="page-section">
      <div className="section-head">
        <div>
          <p className="section-label">Regression runs</p>
          <h1>Runs</h1>
        </div>
        <span className="quiet">{runsQuery.data.length} report-backed runs</span>
      </div>
      <div className="table-wrap">
        <table>
          <thead>
            {table.getHeaderGroups().map((headerGroup) => (
              <tr key={headerGroup.id}>
                {headerGroup.headers.map((header) => (
                  <th key={header.id}>
                    {flexRender(header.column.columnDef.header, header.getContext())}
                  </th>
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
  if (run.judgeF1 === null || run.judgeValidated === null) {
    return (
      <div className="stack-tight">
        <span>{run.judgeVersion}</span>
        <span className="badge neutral">not available</span>
      </div>
    )
  }
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
  const reportQuery = useQuery({
    queryKey: ['run', runId],
    queryFn: () => fetchRegressionReport(runId),
  })
  if (reportQuery.isLoading) {
    return <PageState title="Loading report" />
  }
  if (reportQuery.isError) {
    return (
      <PageState
        title="Report not generated"
        detail="Run regression.py to generate this report, then refresh the read API."
      />
    )
  }
  if (!reportQuery.data) {
    return <PageState title="Report not generated" detail="Run regression.py to generate this report." />
  }
  return <RegressionReportView report={reportQuery.data} />
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
  const className = result === 'better' ? 'good' : result === 'worse' ? 'bad' : 'warn'
  return <span className={`badge ${className}`}>{result}</span>
}

function DeltaTable({ rows }: { rows: RegressionReport['perLabel'] }) {
  return (
    <section className="panel">
      <h2>Per-label failures</h2>
      <table>
        <thead>
          <tr>
            <th>Label</th>
            <th>Baseline</th>
            <th>Candidate</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.label}>
              <td>{row.label}</td>
              <td>{row.baseline}</td>
              <td>{row.candidate}</td>
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
                <a href={item.traceUrl} target="_blank" rel="noreferrer">
                  {item.caseId}
                </a>
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
  const judgeQuery = useQuery({
    queryKey: ['judge', judgeVersion],
    queryFn: () => fetchJudge(judgeVersion),
  })
  if (judgeQuery.isLoading) {
    return <PageState title="Loading judge report" />
  }
  if (judgeQuery.isError) {
    return <PageState title="Judge report not found" detail="Validate the judge to write its report." />
  }
  if (!judgeQuery.data) {
    return <PageState title="Judge report not found" detail="Validate the judge to write its report." />
  }
  return <JudgeReportView report={judgeQuery.data} />
}

function JudgeReportView({ report }: { report: JudgeReport }) {
  const failRow = report.perLabel.find((row) => row.label === 'fail')
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
        <Metric label="Fail-class F1 gate" value={failRow ? formatPercent(failRow.f1) : 'not available'} />
      </div>
      <div className="two-column">
        <section className="panel">
          <h2>Per-label precision / recall / F1</h2>
          <table>
            <thead>
              <tr>
                <th>Label</th>
                <th>Precision</th>
                <th>Recall</th>
                <th>F1</th>
              </tr>
            </thead>
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
  const percent = Math.round(value * 100)
  return `${percent > 0 ? '+' : ''}${percent}%`
}
