import { Handle, Position, type NodeProps } from '@xyflow/react'
import type { DagNode } from '../types'
import { isTerminated, locality, localityIcon, statusColor } from '../status'

// Data attached to each React Flow node by Graph.tsx.
export interface CardData extends Record<string, unknown> {
  node: DagNode
  actionable: boolean
}

export default function NodeCard({ data, selected }: NodeProps) {
  const { node: n, actionable } = data as CardData
  const color = statusColor(n.status)
  const loc = locality(n)
  const timing = n.running_time
    ? `run ${n.running_time}`
    : n.elapsed_time
      ? `elapsed ${n.elapsed_time}`
      : n.request_time
        ? `req ${n.request_time}`
        : ''

  return (
    <div
      className={
        'node-card' +
        (selected ? ' selected' : '') +
        (actionable ? ' actionable' : '') +
        (isTerminated(n) ? ' terminated' : '')
      }
      style={{ borderLeftColor: color }}
    >
      <Handle type="target" position={Position.Top} />
      <div className="nc-head">
        <span className="nc-name" title={n.name}>
          {n.name}
        </span>
        <span className="nc-status" style={{ background: color }}>
          {n.status}
        </span>
      </div>
      <div className="nc-meta">
        <span className={`nc-badge loc-${loc.kind}`}>
          {localityIcon(loc)} {loc.label}
        </span>
        {n.partition ? <span className="nc-badge">{n.partition}</span> : null}
        {n.num_nodes ? <span className="nc-badge">×{n.num_nodes}</span> : null}
        {n.allocation && n.allocation !== '-' ? (
          <span className="nc-badge">{n.allocation}</span>
        ) : null}
        {n.job_id ? <span className="nc-badge">#{n.job_id}</span> : null}
      </div>
      {timing ? <div className="nc-time">{timing}</div> : null}
      {n.blocked_on ? <div className="nc-blocked">⚠ {n.blocked_on}</div> : null}
      {n.terminated_reason ? (
        <div className="nc-terminated">✕ {n.terminated_reason}</div>
      ) : null}
      <Handle type="source" position={Position.Bottom} />
    </div>
  )
}
