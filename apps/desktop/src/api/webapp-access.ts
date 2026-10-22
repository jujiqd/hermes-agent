import { hermesApi, profileScoped } from './client'

// Web access: turn on the Webapp the gateway on THIS machine serves, for other devices, behind Nous
// sign-in. The backend owns every fact here; the pane renders /status and asks for changes.

export type WebAccessMode = 'lan' | 'public'

export interface WebAccessStatus {
  /** `webapp.enabled` in the serving gateway's config: what it serves from its next start. */
  enabled: boolean
  /** What the gateway serves now; `stopped` when none answers. */
  gateway: { reason: null | string; state: 'off' | 'serving' | 'stopped' | 'unavailable'; url: null | string }
  lan_address: null | string
  mode: null | WebAccessMode
  nous_signed_in: boolean
  port: number
  public_url: string
}

/** Start/stop save the config and restart the gateway; a refused restart keeps the config. */
export interface WebAccessChange extends WebAccessStatus {
  restart_error?: string
  restart_started: boolean
}

export function getWebAccessStatus(): Promise<WebAccessStatus> {
  return hermesApi<WebAccessStatus>({ ...profileScoped(), path: '/api/webapp-access/status' })
}

export function startWebAccess(mode: WebAccessMode, publicUrl?: string): Promise<WebAccessChange> {
  return hermesApi<WebAccessChange>({
    ...profileScoped(),
    body: { mode, public_url: publicUrl },
    method: 'POST',
    path: '/api/webapp-access/start'
  })
}

export function stopWebAccess(): Promise<WebAccessChange> {
  return hermesApi<WebAccessChange>({ ...profileScoped(), method: 'POST', path: '/api/webapp-access/stop' })
}
