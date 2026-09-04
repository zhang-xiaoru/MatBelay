import type { Dag, ExplorationSummary } from '../types'
import { STATUS_STYLES } from '../status'

export default function Toolbar({
  explorations,
  dir,
  dag,
  onSelect,
  onRefresh,
}: {
  explorations: ExplorationSummary[]
  dir: string
  dag: Dag | null
  onSelect: (dir: string) => void
  onRefresh: () => void
}) {
  return (
    <header className="toolbar">
      <div className="brand">Workflow DAG</div>
      <select value={dir} onChange={(e) => onSelect(e.target.value)}>
        {explorations.length === 0 && <option value="">no explorations found</option>}
        {explorations.map((p) => (
          <option key={p.dir} value={p.dir}>
            {p.exploration} ({p.node_count})
          </option>
        ))}
      </select>
      {dag?.description ? (
        <span className="desc" title={dag.description}>
          {dag.description}
        </span>
      ) : null}
      <div className="spacer" />
      <div className="legend">
        {Object.entries(STATUS_STYLES).map(([k, v]) => (
          <span key={k} className="legend-item">
            <i style={{ background: v.color }} />
            {k}
          </span>
        ))}
      </div>
      <button onClick={onRefresh}>Refresh</button>
    </header>
  )
}
