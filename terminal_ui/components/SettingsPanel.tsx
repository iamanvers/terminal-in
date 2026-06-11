'use client'
// Operator settings (PRD 5b.2) — slide-over from the top-right gear.
// Schema-driven: the backend describes every setting (type, group, range,
// hot vs restart) and this panel renders it. Secrets arrive masked and are
// only sent back if the operator types a new value.
import React from 'react'

type Setting = {
  env: string; group: string; label: string
  type: 'bool' | 'number' | 'text' | 'select' | 'password'
  options: string[] | null
  min: number | null; max: number | null
  help: string | null; hot: boolean
  value: string; overridden: boolean
}

const GROUP_ORDER = ['Trading', 'Planner', 'Broker', 'Data', 'Reports', 'System']

export default function SettingsPanel({ open, onClose }: { open: boolean; onClose: () => void }) {
  const [settings, setSettings] = React.useState<Setting[]>([])
  const [draft, setDraft] = React.useState<Record<string, string>>({})
  const [saving, setSaving] = React.useState(false)
  const [notice, setNotice] = React.useState<{ kind: 'ok' | 'err'; text: string } | null>(null)

  React.useEffect(() => {
    if (!open) return
    setNotice(null)
    fetch('/api/settings')
      .then(r => r.json())
      .then(d => { setSettings(d.settings ?? []); setDraft({}) })
      .catch(() => setNotice({ kind: 'err', text: 'Could not load settings — backend offline?' }))
  }, [open])

  const dirty = Object.keys(draft).length > 0

  const save = async () => {
    if (!dirty || saving) return
    setSaving(true)
    setNotice(null)
    try {
      const r = await fetch('/api/settings', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(draft),
      })
      const d = await r.json()
      if (!r.ok) throw new Error(d.error || 'save failed')
      const restart = (d.restart_required ?? []) as string[]
      setNotice({
        kind: 'ok',
        text: restart.length
          ? `Saved. Restart required for: ${restart.join(', ')}`
          : 'Saved — applied immediately.',
      })
      setDraft({})
      const fresh = await fetch('/api/settings').then(x => x.json())
      setSettings(fresh.settings ?? [])
    } catch (e: any) {
      setNotice({ kind: 'err', text: String(e?.message ?? e) })
    } finally {
      setSaving(false)
    }
  }

  if (!open) return null

  const groups = GROUP_ORDER.filter(g => settings.some(s => s.group === g))

  return (
    <>
      {/* scrim */}
      <div
        onClick={onClose}
        style={{ position: 'fixed', inset: 0, background: 'rgba(6,7,9,0.55)', zIndex: 80, backdropFilter: 'blur(2px)' }}
      />
      {/* slide-over */}
      <aside
        style={{
          position: 'fixed', top: 0, right: 0, bottom: 0, width: 380, zIndex: 81,
          background: '#121419', borderLeft: '1px solid #333841',
          display: 'flex', flexDirection: 'column',
          boxShadow: '-18px 0 48px rgba(0,0,0,0.45)',
          animation: 'slideIn 0.22s cubic-bezier(.22,1,.36,1)',
        }}
      >
        <style>{`@keyframes slideIn { from { transform: translateX(28px); opacity: 0 } to { transform: none; opacity: 1 } }`}</style>

        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '12px 16px', borderBottom: '1px solid #23272E', flexShrink: 0 }}>
          <span style={{ fontFamily: 'var(--font-mono, monospace)', fontSize: 12, fontWeight: 700, letterSpacing: '0.1em', color: '#ECEEF1' }}>
            SETTINGS
          </span>
          <button onClick={onClose} aria-label="Close settings"
            style={{ background: 'none', border: 'none', color: '#71767F', fontSize: 16, cursor: 'pointer', padding: 4, lineHeight: 1 }}>
            ×
          </button>
        </div>

        <div style={{ flex: 1, overflowY: 'auto', padding: '8px 16px 16px' }}>
          {groups.map(g => (
            <section key={g} style={{ marginTop: 14 }}>
              <div style={{ fontSize: 9.5, fontWeight: 700, letterSpacing: '0.12em', color: '#0094FB', textTransform: 'uppercase', marginBottom: 8 }}>
                {g}
              </div>
              {settings.filter(s => s.group === g).map(s => {
                const v = draft[s.env] ?? s.value
                const inputStyle: React.CSSProperties = {
                  width: '100%', background: '#0A0B0D', border: '1px solid #23272E', borderRadius: 6,
                  color: '#ECEEF1', fontSize: 11, padding: '6px 8px', fontFamily: 'var(--font-mono, monospace)',
                }
                return (
                  <label key={s.env} style={{ display: 'block', marginBottom: 10 }}>
                    <span style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 10.5, color: '#AEB3BB', marginBottom: 4 }}>
                      {s.label}
                      {!s.hot && (
                        <span style={{ fontSize: 8.5, color: '#FFB02E', border: '1px solid #FFB02E44', borderRadius: 4, padding: '0 4px', letterSpacing: '0.06em' }}>
                          RESTART
                        </span>
                      )}
                      {s.overridden && (
                        <span style={{ fontSize: 8.5, color: '#0094FB', letterSpacing: '0.06em' }}>OVERRIDE</span>
                      )}
                    </span>
                    {s.type === 'bool' ? (
                      <select style={inputStyle} value={String(v).toLowerCase()}
                        onChange={e => setDraft(p => ({ ...p, [s.env]: e.target.value }))}>
                        <option value="true">enabled</option>
                        <option value="false">disabled</option>
                      </select>
                    ) : s.type === 'select' ? (
                      <select style={inputStyle} value={v}
                        onChange={e => setDraft(p => ({ ...p, [s.env]: e.target.value }))}>
                        {(s.options ?? []).map(o => <option key={o} value={o}>{o}</option>)}
                      </select>
                    ) : (
                      <input
                        style={inputStyle}
                        type={s.type === 'password' ? 'password' : s.type === 'number' ? 'number' : 'text'}
                        value={v}
                        min={s.min ?? undefined} max={s.max ?? undefined}
                        step={s.type === 'number' ? 'any' : undefined}
                        onChange={e => setDraft(p => ({ ...p, [s.env]: e.target.value }))}
                      />
                    )}
                    {s.help && <span style={{ fontSize: 9.5, color: '#71767F' }}>{s.help}</span>}
                  </label>
                )
              })}
            </section>
          ))}
        </div>

        <div style={{ padding: '12px 16px', borderTop: '1px solid #23272E', flexShrink: 0 }}>
          {notice && (
            <div style={{ fontSize: 10, marginBottom: 8, color: notice.kind === 'ok' ? '#2DBD80' : '#F2495C' }}>
              {notice.text}
            </div>
          )}
          <button
            onClick={save}
            disabled={!dirty || saving}
            style={{
              width: '100%', padding: '8px 0', borderRadius: 6, fontSize: 11, fontWeight: 700,
              letterSpacing: '0.08em', cursor: dirty ? 'pointer' : 'default',
              background: dirty ? '#0094FB' : '#1C1F25',
              color: dirty ? '#06070A' : '#4A4F57',
              border: 'none', transition: 'background 0.15s, color 0.15s',
            }}
          >
            {saving ? 'SAVING…' : 'SAVE CHANGES'}
          </button>
        </div>
      </aside>
    </>
  )
}
