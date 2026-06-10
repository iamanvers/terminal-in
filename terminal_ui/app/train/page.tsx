'use client'
/**
 * TRAIN MODULE — recursive model training.
 *
 * Each cycle rebuilds the SFT dataset (static corpora + the system's OWN
 * closed trades and hindsight-judged planner decisions), LoRA-fine-tunes the
 * base SLM in a subprocess, and records real loss metrics per run. The loop
 * is "recursive" because every cycle trains on the outcomes of decisions the
 * previous model made.
 */
import React, { useCallback, useEffect, useState } from 'react'
import { api, TrainingRun, TrainingStatus } from '@/lib/api'
import { getSocket } from '@/lib/socket'

const C = {
  bg: '#070707', panel: '#0D0D0D', card: '#111111',
  border: '#1A1A1A', border2: '#242424',
  text: '#E4E4E4', sub: '#9A9A9A', muted: '#5C5C5C', dim: '#383838',
  green: '#22C55E', red: '#EF4444', amber: '#F7931E', blue: '#38BDF8', purple: '#AB47BC',
}

const STATE_LABEL: Record<string, { label: string; color: string; busy: boolean }> = {
  idle:             { label: 'IDLE',              color: C.muted,  busy: false },
  building_dataset: { label: 'BUILDING DATASET',  color: C.blue,   busy: true },
  training:         { label: 'TRAINING',          color: C.amber,  busy: true },
  collecting:       { label: 'COLLECTING METRICS', color: C.blue,  busy: true },
  completed:        { label: 'COMPLETED',         color: C.green,  busy: false },
  failed:           { label: 'FAILED',            color: C.red,    busy: false },
  unavailable:      { label: 'UNAVAILABLE',       color: C.dim,    busy: false },
}

function fmtDt(ms: number | null | undefined) {
  return ms ? new Date(ms).toLocaleString('en-IN', { hour12: false, day: '2-digit', month: 'short' }) : '—'
}
function fmtDur(a: number | null | undefined, b: number | null | undefined) {
  if (!a || !b) return '—'
  const s = Math.round((b - a) / 1000)
  return s < 60 ? `${s}s` : s < 3600 ? `${Math.floor(s / 60)}m ${s % 60}s` : `${(s / 3600).toFixed(1)}h`
}

// ── Pipeline diagram ──────────────────────────────────────────────────────────
function PipelineDiagram({ state }: { state: string }) {
  const steps = [
    { key: 'building_dataset', label: 'DATASET',  desc: 'corpora + own trades + judged decisions' },
    { key: 'training',         label: 'LoRA',     desc: 'TinyLlama-1.1B fine-tune (subprocess)' },
    { key: 'collecting',       label: 'METRICS',  desc: 'real loss curve from trainer state' },
    { key: 'deploy',           label: 'DEPLOY',   desc: 'merge → GGUF → Ollama (manual)' },
  ]
  const activeIdx = steps.findIndex(s => s.key === state)
  return (
    <div style={{ display: 'flex', alignItems: 'stretch', gap: 0 }}>
      {steps.map((s, i) => {
        const active = i === activeIdx
        const done = activeIdx === -1 ? false : i < activeIdx
        return (
          <React.Fragment key={s.key}>
            <div style={{
              flex: 1, padding: '10px 12px', borderRadius: 4,
              border: `1px solid ${active ? C.amber + '66' : C.border}`,
              background: active ? '#F7931E0A' : C.card,
            }}>
              <div style={{ fontSize: 10, fontWeight: 700, letterSpacing: '.08em', color: active ? C.amber : done ? C.green : C.muted }}>
                {done ? '✓ ' : ''}{s.label}
              </div>
              <div style={{ fontSize: 8, color: C.muted, marginTop: 3, lineHeight: 1.4 }}>{s.desc}</div>
            </div>
            {i < steps.length - 1 && (
              <div style={{ alignSelf: 'center', color: C.dim, padding: '0 6px', fontSize: 12 }}>→</div>
            )}
          </React.Fragment>
        )
      })}
    </div>
  )
}

// ── Run history table ─────────────────────────────────────────────────────────
function RunHistory({ runs }: { runs: TrainingRun[] }) {
  return (
    <div className="panel">
      <div className="panel-header">RUN HISTORY</div>
      <div className="panel-body">
        {runs.length === 0 ? (
          <div style={{ padding: 30, textAlign: 'center', fontSize: 10, color: C.muted }}>
            No training runs yet. Start a smoke test (200 steps) to validate the pipeline,
            then a full run overnight.
          </div>
        ) : (
          <table>
            <thead><tr>
              <th>STARTED</th><th>STATUS</th><th>SAMPLES</th><th>STEPS</th>
              <th>LOSS START→END</th><th>DURATION</th><th>NOTE</th>
            </tr></thead>
            <tbody>
              {runs.map(r => {
                const st = STATE_LABEL[r.status] ?? { label: r.status.toUpperCase(), color: C.muted }
                const lossImproved = r.initial_loss != null && r.final_loss != null && r.final_loss < r.initial_loss
                return (
                  <tr key={r.run_id}>
                    <td style={{ color: C.sub }}>{fmtDt(r.started_at)}</td>
                    <td style={{ color: st.color, fontWeight: 700 }}>{st.label}</td>
                    <td style={{ color: C.text }}>{r.dataset_samples?.toLocaleString() ?? '—'}</td>
                    <td style={{ color: C.sub }}>{r.trained_steps ?? (r.max_steps && r.max_steps > 0 ? `(${r.max_steps} cap)` : '—')}</td>
                    <td style={{ color: lossImproved ? C.green : C.sub, fontVariantNumeric: 'tabular-nums' }}>
                      {r.initial_loss != null && r.final_loss != null
                        ? `${r.initial_loss.toFixed(3)} → ${r.final_loss.toFixed(3)}`
                        : '—'}
                    </td>
                    <td style={{ color: C.muted }}>{fmtDur(r.started_at, r.finished_at)}</td>
                    <td style={{ color: r.error ? C.red : C.muted, maxWidth: 260, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }} title={r.error ?? ''}>
                      {r.error ?? (r.dataset_counts ? `decisions: ${r.dataset_counts.agent_decisions ?? 0} · trades: ${r.dataset_counts.local_trades ?? 0}` : '')}
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
  const [runs, setRuns]     = useState<TrainingRun[]>([])
  const [busy, setBusy]     = useState(false)
  const [msg, setMsg]       = useState<string | null>(null)

  const load = useCallback(async () => {
    const [st, rn] = await Promise.allSettled([api.trainingStatus(), api.trainingRuns(20)])
    if (st.status === 'fulfilled') setStatus(st.value)
    if (rn.status === 'fulfilled') setRuns(rn.value)
  }, [])

  useEffect(() => { load() }, [load])
  useEffect(() => { const t = setInterval(load, 10_000); return () => clearInterval(t) }, [load])
  useEffect(() => {
    const s = getSocket()
    const onStatus = () => load()
    s.on('training_status', onStatus)
    return () => { s.off('training_status', onStatus) }
  }, [load])

  const state = status?.state ?? 'unavailable'
  const stCfg = STATE_LABEL[state] ?? STATE_LABEL.unavailable
  const running = stCfg.busy

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

  const cur = status?.current_run
  const counts = cur?.dataset_counts

  return (
    <div style={{ flex: 1, minHeight: 0, display: 'flex', flexDirection: 'column', gap: 8, padding: '10px 14px', background: C.bg, overflow: 'hidden' }}>

      {/* Header strip */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 14, background: C.panel, border: `1px solid ${C.border}`, borderRadius: 5, padding: '10px 14px', flexShrink: 0 }}>
        <div>
          <div style={{ fontSize: 12, fontWeight: 700, color: C.text, letterSpacing: '.1em' }}>RECURSIVE MODEL TRAINING</div>
          <div style={{ fontSize: 9, color: C.muted, marginTop: 2 }}>
            The financial SLM retrains on its own trading record — every closed trade and hindsight-judged planner decision becomes training signal.
          </div>
        </div>
        <div style={{ flex: 1 }} />
        <span style={{
          fontSize: 9, fontWeight: 700, letterSpacing: '.08em', padding: '3px 10px', borderRadius: 3,
          border: `1px solid ${stCfg.color}55`, color: stCfg.color, background: `${stCfg.color}10`,
        }}>
          {running && <span style={{ display: 'inline-block', width: 6, height: 6, borderRadius: '50%', background: stCfg.color, marginRight: 6, animation: 'blink 1s infinite' }} />}
          {stCfg.label}
        </span>
        {running ? (
          <button className="btn btn--danger" onClick={stop} disabled={busy}>■ ABORT</button>
        ) : (
          <>
            <button className="btn" onClick={() => start(200)} disabled={busy || state === 'unavailable'}
              title="200-step validation run (~30-60 min on CPU)">SMOKE TEST</button>
            <button className="btn btn--primary" onClick={() => start(-1)} disabled={busy || state === 'unavailable'}
              title="Full 3-epoch run — several hours on CPU, run overnight">▶ FULL RUN</button>
          </>
        )}
      </div>

      {msg && <div style={{ fontSize: 10, color: C.amber, padding: '0 4px', flexShrink: 0 }}>{msg}</div>}

      {/* Pipeline + current run */}
      <div style={{ background: C.panel, border: `1px solid ${C.border}`, borderRadius: 5, padding: 14, flexShrink: 0 }}>
        <PipelineDiagram state={state} />
        {cur && (
          <div style={{ display: 'flex', gap: 24, marginTop: 12, paddingTop: 10, borderTop: `1px solid ${C.border}` }}>
            <span style={{ fontSize: 9, color: C.muted }}>RUN <span style={{ color: C.text }}>{cur.run_id}</span></span>
            {cur.dataset_samples != null && <span style={{ fontSize: 9, color: C.muted }}>SAMPLES <span style={{ color: C.text }}>{cur.dataset_samples.toLocaleString()}</span></span>}
            {counts && (
              <span style={{ fontSize: 9, color: C.muted }}>
                OWN DATA <span style={{ color: C.amber }}>{(counts.local_trades ?? 0) + (counts.agent_decisions ?? 0)}</span>
                <span style={{ color: C.dim }}> ({counts.local_trades ?? 0} trades · {counts.agent_decisions ?? 0} judged decisions)</span>
              </span>
            )}
            {cur.max_steps != null && cur.max_steps > 0 && <span style={{ fontSize: 9, color: C.muted }}>CAP <span style={{ color: C.text }}>{cur.max_steps} steps</span></span>}
            {cur.final_loss != null && <span style={{ fontSize: 9, color: C.muted }}>FINAL LOSS <span style={{ color: C.green }}>{cur.final_loss}</span></span>}
            {cur.error && <span style={{ fontSize: 9, color: C.red }}>{cur.error}</span>}
          </div>
        )}
      </div>

      {/* Run history */}
      <div style={{ flex: 1, minHeight: 0 }}>
        <RunHistory runs={runs} />
      </div>

      {/* Deploy note */}
      <div style={{ fontSize: 9, color: C.dim, padding: '2px 4px', flexShrink: 0 }}>
        Deploy: completed adapters live in data/training/runs/&lt;run_id&gt;/adapter — merge → GGUF (llama.cpp) → <code style={{ color: C.muted }}>ollama create financial-analyst</code>. Until then the planner uses the prompt-tuned base model.
      </div>
    </div>
  )
}
