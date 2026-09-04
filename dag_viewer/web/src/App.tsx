import { useCallback, useEffect, useState } from 'react'
import * as api from './api'
import type { Config, Dag, DagNode, ExplorationSummary } from './types'
import { nid } from './status'
import Toolbar from './components/Toolbar'
import Graph from './components/Graph'
import DetailDrawer from './components/DetailDrawer'

export default function App() {
  const [config, setConfig] = useState<Config | null>(null)
  const [explorations, setExplorations] = useState<ExplorationSummary[]>([])
  const [dir, setDir] = useState<string>('')
  const [dag, setDag] = useState<Dag | null>(null)
  const [selectedId, setSelectedId] = useState<number | null>(null)
  const [error, setError] = useState<string>('')
  const [loading, setLoading] = useState(false)

  useEffect(() => {
    Promise.all([api.getConfig(), api.getExplorations()])
      .then(([cfg, projs]) => {
        setConfig(cfg)
        setExplorations(projs)
        if (projs.length) setDir(projs[0].dir)
      })
      .catch((e) => setError(e instanceof Error ? e.message : String(e)))
  }, [])

  useEffect(() => {
    if (!dir) return
    setLoading(true)
    setSelectedId(null)
    api
      .getDag(dir)
      .then((d) => {
        setDag(d)
        setError('')
      })
      .catch((e) => setError(e instanceof Error ? e.message : String(e)))
      .finally(() => setLoading(false))
  }, [dir])

  const selectedNode: DagNode | null =
    dag && selectedId != null
      ? dag.nodes.find((n) => nid(n) === selectedId) ?? null
      : null

  const handleSave = useCallback(
    async (fields: Record<string, unknown>) => {
      if (selectedId == null) return
      const updated = await api.saveNode(dir, selectedId, fields)
      setDag(updated)
      // refresh the exploration summary (status counts) after a write
      api.getExplorations().then(setExplorations).catch(() => undefined)
    },
    [dir, selectedId],
  )

  const refresh = useCallback(() => {
    if (dir)
      api
        .getDag(dir)
        .then(setDag)
        .catch((e) => setError(e instanceof Error ? e.message : String(e)))
    api.getExplorations().then(setExplorations).catch(() => undefined)
  }, [dir])

  return (
    <div className="app">
      <Toolbar
        explorations={explorations}
        dir={dir}
        dag={dag}
        onSelect={setDir}
        onRefresh={refresh}
      />
      {error ? <div className="banner error">{error}</div> : null}
      <div className="main">
        {dag ? (
          <Graph dag={dag} selectedId={selectedId} onSelect={setSelectedId} />
        ) : (
          <div className="empty">
            {loading ? 'Loading…' : 'No workflow loaded.'}
          </div>
        )}
        {selectedNode && config && dag ? (
          <DetailDrawer
            key={selectedId}
            node={selectedNode}
            dag={dag}
            config={config}
            onSave={handleSave}
            onClose={() => setSelectedId(null)}
          />
        ) : null}
      </div>
    </div>
  )
}
