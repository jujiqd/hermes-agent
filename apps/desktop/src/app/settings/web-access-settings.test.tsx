vi.mock('@/store/profile', async (): Promise<object> => {
  const { atom } = await import('nanostores')

  return {
    $activeGatewayProfile: atom<string>('default'),
    $profiles: atom<Array<{ name: string; is_default?: boolean }>>([]),
    normalizeProfileKey: (profile: string | null): string => profile || 'default'
  }
})
vi.mock('@/hermes', () => ({
  getProfiles: vi.fn(async () => ({ profiles: [] })),
  getWebAccessStatus: vi.fn(),
  setApiRequestProfile: vi.fn(),
  startWebAccess: vi.fn(),
  stopWebAccess: vi.fn()
}))

import { QueryClientProvider } from '@tanstack/react-query'
import { cleanup, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import type { WebAccessStatus } from '@/api/webapp-access'
import * as hermes from '@/hermes'
import { I18nProvider } from '@/i18n'
import { queryClient } from '@/lib/query-client'

import { WebAccessSettings } from './web-access-settings'

const mocked = vi.mocked(hermes)

const OFF: WebAccessStatus = {
  enabled: false,
  gateway: { reason: null, state: 'off', url: null },
  lan_address: '192.168.1.50',
  mode: null,
  nous_signed_in: true,
  port: 9120,
  public_url: ''
}

function renderPane(status: WebAccessStatus) {
  mocked.getWebAccessStatus.mockResolvedValue(status)

  return render(
    <QueryClientProvider client={queryClient}>
      <I18nProvider>
        <WebAccessSettings />
      </I18nProvider>
    </QueryClientProvider>
  )
}

beforeEach(() => queryClient.clear())

afterEach(() => {
  cleanup()
  vi.clearAllMocks()
})

describe('WebAccessSettings', () => {
  it('offers Start only with a Nous account to sign in with', async () => {
    const signedOut = renderPane({ ...OFF, nous_signed_in: false })

    expect((await screen.findByRole('button', { name: 'Start' })).hasAttribute('disabled')).toBe(true)
    signedOut.unmount()
    queryClient.clear()
    renderPane(OFF)

    expect((await screen.findByRole('button', { name: 'Start' })).hasAttribute('disabled')).toBe(false)
  })

  it('says why the gateway cannot serve a turned-on web app', async () => {
    renderPane({
      ...OFF,
      enabled: true,
      gateway: { reason: 'port 9120 is in use', state: 'unavailable', url: null },
      mode: 'lan'
    })

    expect(await screen.findByText(/port 9120 is in use/)).toBeTruthy()
  })

  it('never reports a web app the gateway still serves as stopped', async () => {
    // Stop saved `enabled: false`, but the gateway refused to restart: it still serves the web app.
    renderPane({ ...OFF, gateway: { reason: null, state: 'serving', url: 'http://127.0.0.1:9120' } })

    expect(await screen.findByText('Restart needed')).toBeTruthy()
    expect(screen.queryByText('Stopped')).toBeNull()
  })
})
