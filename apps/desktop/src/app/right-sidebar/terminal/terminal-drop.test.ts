import type { Terminal } from '@xterm/xterm'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { $notifications, clearNotifications } from '@/store/notifications'

import { bindTerminalDrop } from './terminal-drop'

const desktopWindow = window as unknown as { hermesDesktop?: Partial<Window['hermesDesktop']> }
const MIB = 1024 * 1024

function file(name: string, size = 4): File {
  const value = new File(['data'], name, { type: 'text/plain' })
  Object.defineProperty(value, 'size', { value: size })

  return value
}

function transfer(files: File[], hermesPaths?: string[]): DataTransfer {
  const list = Object.assign([...files], { item: (index: number) => files[index] ?? null })

  return {
    files: list,
    getData: (type: string) =>
      type === 'application/x-hermes-paths' && hermesPaths ? JSON.stringify(hermesPaths.map(path => ({ path }))) : '',
    items: files.map(entry => ({ getAsFile: () => entry, kind: 'file' })),
    types: [...(hermesPaths ? ['application/x-hermes-paths'] : []), ...(files.length ? ['Files'] : [])]
  } as unknown as DataTransfer
}

function drop(host: HTMLElement, data: DataTransfer): Event {
  const event = new Event('drop', { bubbles: true, cancelable: true })
  Object.defineProperty(event, 'dataTransfer', { value: data })
  host.dispatchEvent(event)

  return event
}

function bind(shellName = 'bash') {
  const host = document.createElement('div')
  const write = vi.fn().mockResolvedValue(undefined)
  const focus = vi.fn()

  const unbind = bindTerminalDrop(host, {
    getSessionId: () => 'term-1',
    getShellName: () => shellName,
    markActivity: () => undefined,
    term: { focus } as unknown as Terminal,
    terminalApi: { write } as unknown as Window['hermesDesktop']['terminal']
  })

  return { focus, host, unbind, write }
}

afterEach(() => {
  Reflect.deleteProperty(desktopWindow, 'hermesDesktop')
  clearNotifications()
  vi.restoreAllMocks()
})

describe('terminal drop in the browser-hosted Desktop', () => {
  function browserBridge(stage: (file: File) => Promise<string>) {
    const stageFileForAttach = vi.fn(stage)
    desktopWindow.hermesDesktop = { getPathForFile: () => '', stageFileForAttach }

    return stageFileForAttach
  }

  it('stages each dropped file on the host and types its quoted host path', async () => {
    const stage = browserBridge(async entry => `/srv/hermes/uploads/${entry.name}`)
    const { host, unbind, write } = bind('bash')

    const event = drop(host, transfer([file("it's.txt"), file('b c.log')]))

    expect(event.defaultPrevented).toBe(true)
    await vi.waitFor(() => expect(write).toHaveBeenCalledTimes(1))
    expect(write).toHaveBeenCalledWith('term-1', "'/srv/hermes/uploads/it'\\''s.txt' '/srv/hermes/uploads/b c.log' ")
    expect(stage).toHaveBeenCalledTimes(2)
    unbind()
  })

  it("quotes staged paths for the terminal's own shell", async () => {
    browserBridge(async () => 'C:\\Users\\me\\.hermes\\uploads\\it\'s.txt')
    const { host, unbind, write } = bind('powershell.exe')

    drop(host, transfer([file("it's.txt")]))

    await vi.waitFor(() => expect(write).toHaveBeenCalledWith('term-1', "'C:\\Users\\me\\.hermes\\uploads\\it''s.txt' "))
    unbind()
  })

  it('keeps in-app paths and staged files in drop order', async () => {
    browserBridge(async entry => `/srv/hermes/uploads/${entry.name}`)
    const { host, unbind, write } = bind('zsh')

    drop(host, transfer([file('notes.md')], ['/work/project/src']))

    await vi.waitFor(() =>
      expect(write).toHaveBeenCalledWith('term-1', "'/work/project/src' '/srv/hermes/uploads/notes.md' ")
    )
    unbind()
  })

  it('never uploads a file over 16 MiB and names it in a warning', async () => {
    const stage = browserBridge(async entry => `/srv/hermes/uploads/${entry.name}`)
    const { host, unbind, write } = bind('bash')

    drop(host, transfer([file('huge.iso', 16 * MIB + 1), file('small.txt', 16 * MIB)]))

    await vi.waitFor(() => expect(write).toHaveBeenCalledWith('term-1', "'/srv/hermes/uploads/small.txt' "))
    expect(stage).toHaveBeenCalledTimes(1)
    expect(stage.mock.calls[0][0].name).toBe('small.txt')
    const [warning] = $notifications.get()
    expect(warning?.kind).toBe('warning')
    expect(`${warning?.title} ${warning?.message}`).toContain('huge.iso')
    expect(`${warning?.title} ${warning?.message}`).toContain('16 MiB')
    unbind()
  })

  it("reports a failed upload with the host's reason and types nothing for it", async () => {
    browserBridge(async () => {
      throw new Error('File upload failed (502)')
    })
    const { focus, host, unbind, write } = bind('bash')

    drop(host, transfer([file('report.pdf')]))

    await vi.waitFor(() => expect($notifications.get()).toHaveLength(1))
    const [error] = $notifications.get()
    expect(error?.kind).toBe('error')
    expect(`${error?.title} ${error?.message}`).toContain('report.pdf')
    expect(`${error?.title} ${error?.message}`).toContain('502')
    expect(write).not.toHaveBeenCalled()
    expect(focus).not.toHaveBeenCalled()
    unbind()
  })
})

describe('terminal drop in Electron Desktop', () => {
  it('types the native path of each dropped file without uploading it', async () => {
    const getPathForFile = vi.fn((entry: File) => `/home/me/${entry.name}`)
    desktopWindow.hermesDesktop = { getPathForFile }
    const { focus, host, unbind, write } = bind('bash')

    drop(host, transfer([file('a.txt'), file('b c.txt')]))

    expect(write).toHaveBeenCalledWith('term-1', "'/home/me/a.txt' '/home/me/b c.txt' ")
    expect(focus).toHaveBeenCalled()
    unbind()
  })

  it('ignores a dropped file Electron cannot resolve to a path', async () => {
    desktopWindow.hermesDesktop = { getPathForFile: () => '' }
    const { host, unbind, write } = bind('bash')

    drop(host, transfer([file('from-a-web-page.png')]))
    await Promise.resolve()

    expect(write).not.toHaveBeenCalled()
    expect($notifications.get()).toHaveLength(0)
    unbind()
  })
})
