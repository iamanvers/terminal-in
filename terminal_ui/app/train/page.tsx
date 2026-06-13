'use client'
import { THEME } from '@/lib/theme'
/**
 * TRAIN MODULE — recursive model training (redesigned).
 *
 * Each cycle rebuilds the SFT dataset (static corpora + the system's OWN closed
 * trades and hindsight-judged planner decisions), LoRA-fine-tunes the base SLM
 * in a subprocess, and records real loss metrics. Layout: a live-run cockpit
 * (step/loss/ETA from the trainer log), the dataset composition, the recursive
 * loop it closes, and the run history with per-run deploy.
 */
import React, { useCallback, useEffect, useMemo, useState } from 'react'
import { api, TrainingRun, TrainingStatus, TrainingProgress } from '@/lib/api'
import { getSocket } from '@/lib/socket'

const C = THEME

const STATE_LABEL: Record<string, { label: string; color: string; busy: boolean }> = {
  idle:             { label: 'IDLE',              color: C.muted,  busy: false },
  building_dataset: { label: 'BUILDING DATASET',  color: C.blue,   busy: true },
  training:         { label: 'TRAINING',          color: C.accent, busy: true },
  collecting:       { label: 'COLLECTING METRICS', color: C.blue,  busy: true },
  completed:        { label: 'COMPLETED',         color: C.green,  busy: false },
  failed:           { label: 'FAILED',            color: C.red,    busy: false },
  unavailable:      { label: 'UNAVAILABLE',       color: C.dim,    busy: false },
}

// Dataset source → label + colour (the 5 planes of the SFT mix)
const SRC_META: Record<string, { label: string; color: string; own?: boolean }> = {
  sentiment:       { label: 'Sentiment',      color: C.steel },
  finance_alpaca:  { label: 'Finance QA',     color: C.blue },
  nse_pairs:       { label: 'NSE strategy QA', color: C.teal },
  local_trades:    { label: 'Own trades',     color: C.accent,      own: true },
  agent_decisions: { label: 'Judged decisions', color: C.accentBright, own: true },
}

function fmtDt(ms: number | null | undefined) {
  return ms ? new Date(ms).toLocaleString('en-IN', { hour12: false, day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit' }) : '—'
}
function fmtDur(a: number | null | undefined, b: number | null | undefined) {
  if (!a || !b) return '—'
  const s = Math.round((b - a) / 1000)
  return s < 60 ? `${s}s` : s < 3600 ? `${Math.floor(s / 60)}m ${s % 60}s` : `${(s / 3600).toFixed(1)}h`
}
function inferBase(runId: string | undefined) {
  if (!runId) return 'base SLM'
  if (runId.includes('3b')) return 'Qwen2.5-3B-Instruct'
  return 'TinyLlama-1.1B'
}

// ── Loss sparkline ──────────────────────────────────────────────────────────
function Sparkline({ values, color = C.accent, h = 40 }: { values: number[]; color?: string; h?: number }) {
  if (values.length < 2) return <div style={{ height: h, display: 'flex', alignItems: 'center', color: C.dim, fontSize: 9.5 }}>loss curve appears after the first logged steps…</div>
  const w = 520
  const min = Math.min(...values), max = Math.max(...values)
  const range = max - min || 1
  const pts = values.map((v, i) => `${(i / (values.length - 1)) * w},${h - ((v - min) / range) * (h - 6) - 3}`)
  return (
    <svg width="100%" height={h} viewBox={`0 0 ${w} ${h}`} preserveAspectRatio="none" style={{ display: 'block' }}>
      <polyline points={pts.join(' ')} fill="none" stroke={color} strokeWidth={1.5} vectorEffect="non-scaling-stroke" />
    </svg>
  )
}

// ── Dataset composition (stacked) ───────────────────────────────────────────
function Composition({ counts }: { counts: Record<string, number> }) {
  const entries = Object.entries(SRC_META).map(([k, m]) => ({ k, ...m, n: counts[k] ?? 0 })).filter(e => e.n > 0)
  const total = entries.reduce((s, e) => s + e.n, 0) || 1
  const own = (counts.local_trades ?? 0) + (counts.agent_decisions ?? 0)
  return (
    <div className="panel" style={{ minHeight: 0 }}>
      <div className="panel-header">DATASET COMPOSITION <span style={{ marginLeft: 'auto', color: C.muted }}>{total.toLocaleString()} samples</span></div>
      <div className="panel-body" style={{ padding: 12, display: 'flex', flexDirection: 'column', gap: 10 }}>
        <div style={{ display: 'flex', height: 14, borderRadius: 3, overflow: 'hidden', border: `1px solid ${C.border}` }}>
          {entries.map(e => <div key={e.k} title={`${e.label}: ${e.n}`} style={{ width: `${(e.n / total) * 100}%`, background: e.color }} />)}
        </div>
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '5px 14px' }}>
          {entries.map(e => (
            <div key={e.k} style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 10 }}>
              <span style={{ width: 8, height: 8, borderRadius: 2, background: e.color, flexShrink: 0 }} />
              <span style={{ color: e.own ? C.text : C.sub, fontWeight: e.own ? 700 : 400 }}>{e.label}</span>
              <span style={{ marginLeft: 'auto', color: C.muted, fontVariantNumeric: 'tabular-nums' }}>{e.n.toLocaleString()}</span>
            </div>
          ))}
        </div>
        <div style={{ marginTop: 2, paddingTop: 8, borderTop: `1px solid ${C.border}`, fontSize: 10, color: C.muted }}>
          OWN TRADING DATA <span style={{ color: C.accent, fontWeight: 700 }}>{own.toLocaleString()}</span>
          <span style={{ color: C.dim }}> — the recursive signal that makes each cycle learn from the last model's decisions.</span>
        </div>
      </div>
    </div>
  )
}

// ── The recursive loop it closes ────────────────────────────────────────────
function RecursiveLoop() {
  const steps = ['TRADE', 'JUDGE', 'HINDSIGHT', 'RETRAIN', 'DEPLOY']
  return (
    <div className="panel" style={{ minHeight: 0 }}>
      <div className="panel-header">THE RECURSIVE LOOP</div>
      <div className="panel-body" style={{ padding: 12, display: 'flex', flexDirection: 'column', gap: 8 }}>
        <div style={{ display: 'flex', alignItems: 'center', flexWrap: 'wrap', gap: 4 }}>
          {steps.map((s, i) => (
            <React.Fragment key={s}>
              <span style={{ fontSize: 9.5, fontWeight: 700, letterSpacing: '.05em', color: i === 3 ? C.accent : C.sub, border: `1px solid ${i === 3 ? '#0094FB44' : C.border}`, background: i === 3 ? '#0094FB0E' : C.card, borderRadius: 3, padding: '3px 7px' }}>{s}</span>
              {i < steps.length - 1 && <span style={{ color: C.dim, fontSize: 11 }}>→</span>}
            </React.Fragment>
          ))}
          <span style={{ color: C.dim, fontSize: 11 }}>↺</span>
        </div>
        <div className="t-prose" style={{ fontSize: 10.5, color: C.muted }}>
          The model judges a candidate; the hindsight loop re-prices that decision 4–72h later against
          what actually happened; the verdict + outcome becomes a training row. So every cycle fine-tunes
          on the consequences of the previous model's own calls — graded by realised P&amp;L, not eloquence.
        </div>
      </div>
    </div>
  )
}

// ── Live run cockpit ────────────────────────────────────────────────────────
function LiveRun({ prog, base }: { prog: TrainingProgress; base: string }) {
  const step = prog.global_step ?? 0
  const max = prog.max_steps ?? 0
  const pct = max > 0 ? Math.min(100, (step / max) * 100) : 0
  const losses = prog.losses ?? []
  const lossDelta = losses.length >= 2 ? losses[losses.length - 1] - losses[0] : null
  return (
    <div className="panel" style={{ minHeight: 0 }}>
      <div className="panel-header">
        <span style={{ display: 'inline-block', width: 6, height: 6, borderRadius: '50%', background: C.accent, marginRight: 7, animation: 'blink 1s infinite' }} />
        LIVE RUN <span style={{ color: C.muted, fontWeight: 400, marginLeft: 6 }}>{prog.run_id}</span>
        <span style={{ marginLeft: 'auto', color: C.accentBright }}>{base}</span>
      </div>
      <div className="panel-body" style={{ padding: 14, display: 'flex', flexDirection: 'column', gap: 14 }}>
        <div>
          <div style={{ display: 'flex', alignItems: 'baseline', gap: 8, marginBottom: 6 }}>
            <span style={{ fontSize: 26, fontWeight: 700, color: C.text, fontVariantNumeric: 'tabular-nums' }}>{step}</span>
            <span style={{ fontSize: 13, color: C.muted }}>/ {max || '—'} steps</span>
            <span style={{ marginLeft: 'auto', fontSize: 12, color: C.accent, fontWeight: 700 }}>{pct.toFixed(1)}%</span>
          </div>
          <div style={{ height: 6, background: C.card, borderRadius: 3, overflow: 'hidden' }}>
            <div style={{ height: '100%', width: `${pct}%`, background: C.accent, borderRadius: 3, transition: 'width .6s ease' }} />
          </div>
        </div>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4,1fr)', gap: 10 }}>
          <Metric label="CURRENT LOSS" value={prog.loss != null ? prog.loss.toFixed(3) : '—'} color={C.text} />
          <Metric label="LOSS Δ" value={lossDelta != null ? `${lossDelta > 0 ? '+' : ''}${lossDelta.toFixed(3)}` : '—'} color={lossDelta != null && lossDelta < 0 ? C.green : C.muted} />
          <Metric label="SEC / STEP" value={prog.sec_per_step != null ? `${prog.sec_per_step.toFixed(0)}s` : '—'} color={C.sub} />
          <Metric label="ETA" value={prog.eta ?? '—'} color={C.accentBright} />
        </div>
        <div>
          <div style={{ fontSize: 9, color: C.dim, letterSpacing: '.08em', marginBottom: 4 }}>LOSS CURVE</div>
          <Sparkline values={losses} />
        </div>
        <div style={{ fontSize: 9.5, color: C.dim }}>
          Elapsed {prog.elapsed ?? '—'} · CPU training is thermally throttled (60–470 s/step); metrics update as the trainer logs.
        </div>
      </div>
    </div>
  )
}
function Metric({ label, value, color }: { label: string; value: string; color: string }) {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
      <span style={{ fontSize: 9, color: C.dim, letterSpacing: '.07em' }}>{label}</span>
      <span style={{ fontSize: 14, fontWeight: 700, color, fontVariantNumeric: 'tabular-nums' }}>{value}</span>
    </div>
  )
}

// ── Last completed run summary (when nothing is live) ───────────────────────
function LastRun({ run }: { run: TrainingRun }) {
  const st = STATE_LABEL[run.status] ?? { label: run.status.toUpperCase(), color: C.muted }
  const improved = run.initial_loss != null && run.final_loss != null && run.final_loss < run.initial_loss
  return (
    <div className="panel" style={{ minHeight: 0 }}>
      <div className="panel-header">LATEST RUN <span style={{ color: C.muted, fontWeight: 400, marginLeft: 6 }}>{run.run_id}</span>
        <span style={{ marginLeft: 'auto', color: st.color, fontWeight: 700 }}>{st.label}</span></div>
      <div className="panel-body" style={{ padding: 14, display: 'grid', gridTemplateColumns: 'repeat(4,1fr)', gap: 12 }}>
        <Metric label="BASE" value={inferBase(run.run_id)} color={C.accentBright} />
        <Metric label="SAMPLES" value={run.dataset_samples?.toLocaleString() ?? '—'} color={C.text} />
        <Metric label="STEPS" value={run.trained_steps != null ? String(run.trained_steps) : '—'} color={C.sub} />
        <Metric label="DURATION" value={fmtDur(run.started_at, run.finished_at)} color={C.muted} />
        <div style={{ gridColumn: '1 / 5' }}>
          <span style={{ fontSize: 9, color: C.dim, letterSpacing: '.07em' }}>LOSS START → END</span>
          <div style={{ fontSize: 16, fontWeight: 700, color: improved ? C.green : C.sub, fontVariantNumeric: 'tabular-nums', marginTop: 2 }}>
            {run.initial_loss != null && run.final_loss != null ? `${run.initial_loss.toFixed(3)} → ${run.final_loss.toFixed(3)}` : 'no metrics'}
            {improved && <span style={{ fontSize: 10, color: C.green, marginLeft: 8 }}>▼ {((1 - run.final_loss! / run.initial_loss!) * 100).toFixed(0)}%</span>}
          </div>
        </div>
      </div>
    </div>
  )
}

// ── Run history ─────────────────────────────────────────────────────────────
function RunHistory({ runs, onDeploy, deployingId }: { runs: TrainingRun[]; onDeploy: (id: string) => void; deployingId: string | null }) {
  return (
    <div className="panel">
      <div className="panel-header">RUN HISTORY <span style={{ marginLeft: 'auto', color: C.muted }}>{runs.length}</span></div>
      <div className="panel-body">
        {runs.length === 0 ? (
          <div style={{ padding: 30, textAlign: 'center', fontSize: 10.5, color: C.muted }}>
            No training runs yet. Start a smoke test (200 steps) to validate the pipeline, then a full run.
          </div>
        ) : (
          <table>
            <thead><tr>
              <th>STARTED</th><th>BASE</th><th>STATUS</th><th>SAMPLES</th><th>STEPS</th>
              <th>LOSS START→END</th><th>DURATION</th><th></th>
            </tr></thead>
            <tbody>
              {runs.map(r => {
                const st = STATE_LABEL[r.status] ?? { label: r.status.toUpperCase(), color: C.muted }
                const improved = r.initial_loss != null && r.final_loss != null && r.final_loss < r.initial_loss
                const canDeploy = r.status === 'completed' && !!r.adapter_dir
                return (
                  <tr key={r.run_id}>
                    <td style={{ color: C.sub }}>{fmtDt(r.started_at)}</td>
                    <td style={{ color: C.muted }}>{inferBase(r.run_id)}</td>
                    <td style={{ color: st.color, fontWeight: 700 }}>{st.label}</td>
                    <td style={{ color: C.text }}>{r.dataset_samples?.toLocaleString() ?? '—'}</td>
                    <td style={{ color: C.sub }}>{r.trained_steps ?? (r.max_steps && r.max_steps > 0 ? `(${r.max_steps} cap)` : '—')}</td>
                    <td style={{ color: improved ? C.green : C.sub, fontVariantNumeric: 'tabular-nums' }}>
                      {r.initial_loss != null && r.final_loss != null ? `${r.initial_loss.toFixed(3)} → ${r.final_loss.toFixed(3)}` : '—'}
                    </td>
                    <td style={{ color: C.muted }}>{fmtDur(r.started_at, r.finished_at)}</td>
                    <td style={{ textAlign: 'right' }}>
                      {canDeploy && (
                        <button className="btn" disabled={deployingId === r.run_id} onClick={() => onDeploy(r.run_id)}
                          title="Merge adapter → GGUF → ollama create (then eval-gate before promoting)"
                          style={{ fontSize: 9, padding: '2px 8px' }}>
                          {deployingId === r.run_id ? '…' : '⇪ DEPLOY'}
                        </button>
                      )}
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        )}
      </div>
    </div>
  )
}

// ── Page ──────────────────────────────────────────────────────────────────────
export default function TrainPage() {
  const [status, setStatus] = useState<TrainingStatus | null>(null)
  const [prog, setProg]     = useState<TrainingProgress | null>(null)
  const [runs, setRuns]     = useState<TrainingRun[]>([])
  const [busy, setBusy]     = useState(false)
  const [msg, setMsg]       = useState<string | null>(null)
  const [deployingId, setDeployingId] = useState<string | null>(null)

  const load = useCallback(async () => {
    const [st, rn, pg] = await Promise.allSettled([api.trainingStatus(), api.trainingRuns(20), api.trainingProgress()])
    if (st.status === 'fulfilled') setStatus(st.value)
    if (rn.status === 'fulfilled') setRuns(rn.value)
    if (pg.status === 'fulfilled') setProg(pg.value)
  }, [])

  useEffect(() => { load() }, [load])
  useEffect(() => { const t = setInterval(load, 6_000); return () => clearInterval(t) }, [load])
  useEffect(() => {
    const s = getSocket()
    const onStatus = () => load()
    s.on('training_status', onStatus)
    return () => { s.off('training_status', onStatus) }
  }, [load])

  // Live state combines Flask-owned runs (status.state) AND detached runs
  // (only visible via /progress reading the trainer log).
  const live = !!prog?.active
  const flaskState = status?.state ?? 'unavailable'
  const displayState = live ? 'training' : flaskState
  const stCfg = STATE_LABEL[displayState] ?? STATE_LABEL.unavailable
  const running = stCfg.busy || live
  const detached = live && flaskState === 'idle'

  async function start(maxSteps: number) {
    setBusy(true); setMsg(null)
    try {
      const res = await api.trainingStart(maxSteps)
      setMsg(res.ok ? `Run ${res.run_id} started` : res.error ?? 'failed to start')
    } catch { setMsg('network error') }
    finally { setBusy(false); load() }
  }
  async function stop() {
    setBusy(true)
    try { await api.trainingStop() } catch { /* surfaced via status */ }
    finally { setBusy(false); load() }
  }
  async function deploy(runId: string) {
    setDeployingId(runId); setMsg(null)
    try {
      const res = await api.trainingDeploy(runId)
      setMsg(res.ok ? `Deploying ${runId} → Ollama (merge→GGUF→create)…` : res.error ?? 'deploy failed')
    } catch { setMsg('network error') }
    finally { setTimeout(() => setDeployingId(null), 2000); load() }
  }

  const cur = status?.current_run
  const counts = useMemo(() => (cur?.dataset_counts ?? runs.find(r => r.run_id === prog?.run_id)?.dataset_counts ?? runs[0]?.dataset_counts ?? {}) as Record<string, number>, [cur, runs, prog])
  const lastRun = runs[0]

  return (
    <div style={{ flex: 1, minHeight: 0, display: 'flex', flexDirection: 'column', gap: 8, padding: '10px 14px', background: 'transparent', overflow: 'hidden' }}>

      {/* Header strip */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 14, background: C.panel, border: `1px solid ${C.border}`, borderRadius: 5, padding: '10px 14px', flexShrink: 0 }}>
        <div>
          <div className="t-display" style={{ fontSize: 16 }}>Recursive Model Training</div>
          <div className="t-prose" style={{ fontSize: 11.5, marginTop: 2 }}>
            The financial SLM retrains on its own record — every closed trade and hindsight-judged decision becomes training signal.
          </div>
        </div>
        <div style={{ flex: 1 }} />
        <span style={{
          fontSize: 10, fontWeight: 700, letterSpacing: '.08em', padding: '3px 10px', borderRadius: 3,
          border: `1px solid ${stCfg.color}55`, color: stCfg.color, background: `${stCfg.color}10`,
        }}>
          {running && <span style={{ display: 'inline-block', width: 6, height: 6, borderRadius: '50%', background: stCfg.color, marginRight: 6, animation: 'blink 1s infinite' }} />}
          {stCfg.label}{detached && ' · DETACHED'}
        </span>
        {flaskState !== 'idle' && stCfg.busy ? (
          <button className="btn btn--danger" onClick={stop} disabled={busy}>■ ABORT</button>
        ) : (
          <>
            <button className="btn" onClick={() => start(200)} disabled={busy || running || flaskState === 'unavailable'}
              title="200-step validation run">SMOKE TEST</button>
            <button className="btn btn--primary" onClick={() => start(-1)} disabled={busy || running || flaskState === 'unavailable'}
              title="Full run — several hours on CPU">▶ FULL RUN</button>
          </>
        )}
      </div>

      {msg && <div style={{ fontSize: 10.5, color: C.accent, padding: '0 4px', flexShrink: 0 }}>{msg}</div>}
      {detached && <div style={{ fontSize: 10, color: C.muted, padding: '0 4px', flexShrink: 0 }}>◷ A detached run (launched outside the app) is in progress — start is disabled; abort it from the terminal.</div>}

      {/* Top: live cockpit | composition + loop */}
      <div style={{ display: 'grid', gridTemplateColumns: '1.35fr 1fr', gap: 8, flexShrink: 0 }}>
        {live && prog ? <LiveRun prog={prog} base={inferBase(prog.run_id)} /> : lastRun ? <LastRun run={lastRun} /> : (
          <div className="panel"><div className="panel-header">RUN COCKPIT</div><div className="panel-body" style={{ padding: 24, textAlign: 'center', color: C.muted, fontSize: 10.5 }}>No runs yet — start a smoke test to validate the pipeline.</div></div>
        )}
        <div style={{ display: 'flex', flexDirection: 'column', gap: 8, minHeight: 0 }}>
          {Object.keys(counts).length > 0 && <Composition counts={counts} />}
          <RecursiveLoop />
        </div>
      </div>

      {/* Run history */}
      <div style={{ flex: 1, minHeight: 0 }}>
        <RunHistory runs={runs} onDeploy={deploy} deployingId={deployingId} />
      </div>

      {/* Deploy / eval-gate note */}
      <div style={{ fontSize: 10, color: C.dim, padding: '2px 4px', flexShrink: 0 }}>
        Deploy merges the adapter → GGUF (llama.cpp) → <code style={{ color: C.muted }}>ollama create financial-analyst-vN</code>. A new model is <strong>eval-gated</strong> (42-item set) before it replaces the planner/analyst — it must beat the incumbent with no category regression.
      </div>
    </div>
  )
}
