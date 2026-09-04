import { useMemo, useState, type ReactNode } from 'react'
import type { Config, Dag, DagNode } from '../types'
import { nid } from '../status'

// Editable fields (topology/identity stay read-only, handled by the CLI scripts).
const ALL_EDIT = [
  'name',
  'description',
  'cluster',
  'allocation',
  'partition',
  'num_nodes',
  'job_id',
  'job_name',
  'expected_start',
  'request_time',
  'elapsed_time',
  'running_time',
  'blocked_on',
  'terminated_reason',
]

export default function DetailDrawer({
  node,
  dag,
  config,
  onSave,
  onClose,
}: {
  node: DagNode
  dag: Dag
  config: Config
  onSave: (fields: Record<string, unknown>) => Promise<void>
  onClose: () => void
}) {
  const legend = dag.status_legend ?? config.statuses
  const initial = useMemo(() => buildForm(node), [node])
  const [form, setForm] = useState<Record<string, string>>(initial)
  const [saving, setSaving] = useState(false)
  const [err, setErr] = useState('')
  const [ok, setOk] = useState(false)

  const set = (k: string, v: string) => {
    setForm((f) => ({ ...f, [k]: v }))
    setOk(false)
  }

  const statusChanged = form.status !== String(node.status ?? '')
  const required = statusChanged ? config.required[form.status] ?? [] : []

  const nameById = new Map<number, string>()
  dag.nodes.forEach((n) => nameById.set(nid(n), n.name))
  const prevNames = (node.prev ?? []).map((p) => nameById.get(p) ?? `#${p}`)
  const nextNames = (node.next ?? []).map((p) => nameById.get(p) ?? `#${p}`)

  async function save() {
    setSaving(true)
    setErr('')
    setOk(false)
    try {
      const fields = diffFields(node, form, config, statusChanged)
      if (Object.keys(fields).length === 0) {
        setErr('No changes to save.')
        return
      }
      await onSave(fields)
      setOk(true)
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e))
    } finally {
      setSaving(false)
    }
  }

  return (
    <aside className="drawer">
      <div className="drawer-head">
        <div>
          <div className="drawer-title">{node.name}</div>
          <div className="drawer-sub">
            id {nid(node)} · level {node.level ?? node.stage ?? '—'}
          </div>
        </div>
        <button className="icon" onClick={onClose} aria-label="close">
          ✕
        </button>
      </div>

      <div className="drawer-body">
        <Field label="Name">
          <input value={form.name} onChange={(e) => set('name', e.target.value)} />
        </Field>
        <Field label="Description">
          <textarea
            rows={4}
            value={form.description}
            onChange={(e) => set('description', e.target.value)}
          />
        </Field>
        <Field label="Status">
          <select value={form.status} onChange={(e) => set('status', e.target.value)}>
            {legend.map((s) => (
              <option key={s} value={s}>
                {s}
              </option>
            ))}
          </select>
        </Field>
        {statusChanged && required.length > 0 ? (
          <div className="hint">
            Status “{form.status}” requires: {required.join(', ')}
          </div>
        ) : null}

        <div className="grid2">
          <Field label="Cluster">
            <input value={form.cluster} onChange={(e) => set('cluster', e.target.value)} />
          </Field>
          <Field label="Allocation">
            <input
              value={form.allocation}
              onChange={(e) => set('allocation', e.target.value)}
            />
          </Field>
          <Field label="Partition">
            <input
              value={form.partition}
              placeholder="normal | development | gpu-a100"
              onChange={(e) => set('partition', e.target.value)}
            />
          </Field>
          <Field label="Nodes (-N)">
            <input
              value={form.num_nodes}
              placeholder="4"
              onChange={(e) => set('num_nodes', e.target.value)}
            />
          </Field>
          <Field label="Job ID" req={required.includes('job_id')}>
            <input value={form.job_id} onChange={(e) => set('job_id', e.target.value)} />
          </Field>
          <Field label="Job name">
            <input
              value={form.job_name}
              onChange={(e) => set('job_name', e.target.value)}
            />
          </Field>
          <Field label="Expected start" req={required.includes('expected_start')}>
            <input
              value={form.expected_start}
              onChange={(e) => set('expected_start', e.target.value)}
            />
          </Field>
          <Field label="Request time">
            <input
              value={form.request_time}
              onChange={(e) => set('request_time', e.target.value)}
            />
          </Field>
          <Field label="Elapsed time" req={required.includes('elapsed_time')}>
            <input
              value={form.elapsed_time}
              onChange={(e) => set('elapsed_time', e.target.value)}
            />
          </Field>
          <Field label="Running time" req={required.includes('running_time')}>
            <input
              value={form.running_time}
              onChange={(e) => set('running_time', e.target.value)}
            />
          </Field>
        </div>
        <Field label="Blocked on" req={required.includes('blocked_on')}>
          <input
            value={form.blocked_on}
            onChange={(e) => set('blocked_on', e.target.value)}
          />
        </Field>
        <Field
          label="Terminated reason"
          req={required.includes('terminated_reason')}
        >
          <input
            value={form.terminated_reason}
            placeholder="why this node was judged invalid"
            onChange={(e) => set('terminated_reason', e.target.value)}
          />
        </Field>

        <div className="readonly">
          <div>
            <b>prev:</b> {prevNames.length ? prevNames.join(', ') : '—'}
          </div>
          <div>
            <b>next:</b> {nextNames.length ? nextNames.join(', ') : '—'}
          </div>
          <div className="note">
            Dependencies &amp; level are edited with the insert/delete CLI scripts,
            not here.
          </div>
        </div>
      </div>

      <div className="drawer-foot">
        {err ? <div className="msg error">{err}</div> : null}
        {ok ? <div className="msg ok">Saved to workflow_dag.json.</div> : null}
        <div className="foot-actions">
          <button onClick={onClose}>Close</button>
          <button className="primary" onClick={save} disabled={saving}>
            {saving ? 'Saving…' : 'Save'}
          </button>
        </div>
      </div>
    </aside>
  )
}

function Field({
  label,
  req,
  children,
}: {
  label: string
  req?: boolean
  children: ReactNode
}) {
  return (
    <label className={'field' + (req ? ' required' : '')}>
      <span>
        {label}
        {req ? ' *' : ''}
      </span>
      {children}
    </label>
  )
}

function buildForm(node: DagNode): Record<string, string> {
  const f: Record<string, string> = { status: String(node.status ?? '') }
  ALL_EDIT.forEach((k) => {
    f[k] = String((node as Record<string, unknown>)[k] ?? '')
  })
  return f
}

// Send only what changed. On a status change also include that status's REQUIRED
// fields (with their current values) so the transition passes, without echoing
// stale fields -- so the backend's lifecycle CLEAR still applies.
function diffFields(
  node: DagNode,
  form: Record<string, string>,
  config: Config,
  statusChanged: boolean,
): Record<string, unknown> {
  const out: Record<string, unknown> = {}
  ALL_EDIT.forEach((k) => {
    const orig = String((node as Record<string, unknown>)[k] ?? '')
    if (form[k] !== orig) out[k] = form[k]
  })
  if (statusChanged) {
    out.status = form.status
    for (const r of config.required[form.status] ?? []) {
      if (!(r in out)) out[r] = form[r]
    }
  }
  return out
}
