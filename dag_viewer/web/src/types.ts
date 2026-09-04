// Mirrors the workflow_dag.json schema (templates/dag_template.json).
export interface DagNode {
  name: string
  description?: string
  status: string
  id?: number
  stage?: number // legacy identity (legacy_bandoffset)
  level?: number
  cluster?: string
  allocation?: string
  partition?: string
  num_nodes?: string
  expected_start?: string
  request_time?: string
  job_id?: string
  job_name?: string
  elapsed_time?: string
  running_time?: string
  blocked_on?: string
  terminated_reason?: string
  prev?: number[]
  next?: number[]
  [k: string]: unknown
}

export interface Dag {
  exploration: string
  description?: string
  status_legend?: string[]
  nodes: DagNode[]
}

export interface ExplorationSummary {
  exploration: string
  dir: string
  description: string
  node_count: number
  status_counts: Record<string, number>
  legacy: boolean
}

// From GET /api/config -- the backend's authoritative editing rules.
export interface Config {
  statuses: string[]
  required: Record<string, string[]>
  clear: Record<string, string[]>
  plain_fields: string[]
  lifecycle_fields: string[]
  readonly_fields: string[]
}
