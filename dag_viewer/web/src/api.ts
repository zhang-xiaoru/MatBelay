import type { Config, Dag, ExplorationSummary } from './types'

// Small typed fetch client. The backend returns {ok:false,error} on failure;
// surface that message so the UI can show the exact validation/lifecycle error.
async function req<T>(url: string, opts?: RequestInit): Promise<T> {
  const r = await fetch(url, opts)
  let data: unknown = null
  try {
    data = await r.json()
  } catch {
    /* empty / non-JSON body */
  }
  const obj = (data ?? {}) as Record<string, unknown>
  if (!r.ok || obj.ok === false) {
    throw new Error((obj.error as string) || `${r.status} ${r.statusText}`)
  }
  return data as T
}

export const getConfig = () => req<Config>('/api/config')

export const getExplorations = () =>
  req<{ explorations: ExplorationSummary[] }>('/api/explorations').then((d) => d.explorations)

export const getDag = (dir: string) =>
  req<{ dag: Dag }>(`/api/dag?exploration=${encodeURIComponent(dir)}`).then((d) => d.dag)

export const saveNode = (
  exploration: string,
  id: number,
  fields: Record<string, unknown>,
) =>
  req<{ dag: Dag }>('/api/node', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ exploration, id, fields }),
  }).then((d) => d.dag)
