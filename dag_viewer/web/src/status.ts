import type { DagNode } from './types'

// Node identity / depth, matching the Python helpers (id ?? stage, level ?? id).
export const nid = (n: DagNode): number => n.id ?? n.stage ?? 0
export const lvl = (n: DagNode): number => n.level ?? nid(n)

export interface StatusStyle {
  label: string
  color: string
}

// Status -> accent color. Chosen to read on both light and dark backgrounds.
export const STATUS_STYLES: Record<string, StatusStyle> = {
  completed: { label: 'completed', color: '#16a34a' },
  running: { label: 'running', color: '#2563eb' },
  queued: { label: 'queued', color: '#d97706' },
  ready: { label: 'ready', color: '#0891b2' },
  pending: { label: 'pending', color: '#6b7280' },
  failed: { label: 'failed', color: '#dc2626' },
  blocked: { label: 'blocked', color: '#7c3aed' },
  // Retired from the live graph: warm dark grey, deliberately unlike pending's
  // cool grey, and paired with a faded card so a dead branch reads at a glance.
  terminated: { label: 'terminated', color: '#57534e' },
}

// A terminated node is judged invalid: it never reaches 'completed', so every
// node below it is unreachable too.
export const isTerminated = (n: DagNode): boolean => n.status === 'terminated'

export const statusColor = (s: string): string =>
  STATUS_STYLES[s]?.color ?? '#6b7280'

// Locality: cluster == 'local' -> local; a cluster name -> remote; empty -> unset.
export interface Locality {
  kind: 'local' | 'remote' | 'unset'
  label: string
}

export function locality(n: DagNode): Locality {
  const c = (n.cluster ?? '').trim()
  if (!c) return { kind: 'unset', label: 'unset' }
  if (c.toLowerCase() === 'local') return { kind: 'local', label: 'local' }
  return { kind: 'remote', label: c }
}

export const localityIcon = (loc: Locality): string =>
  loc.kind === 'local' ? '🖥' : loc.kind === 'remote' ? '☁' : '•'

// A node is "actionable" when every dependency is completed but it hasn't started.
export function isActionable(n: DagNode, statusById: Map<number, string>): boolean {
  if (n.status !== 'pending' && n.status !== 'ready') return false
  // a terminated parent can never complete, so this node is dead, not actionable
  const prev = n.prev ?? []
  return prev.length > 0 && prev.every((p) => statusById.get(p) === 'completed')
}
