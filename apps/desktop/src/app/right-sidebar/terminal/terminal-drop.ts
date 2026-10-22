import type { Terminal } from '@xterm/xterm'

import { translateNow } from '@/i18n'
import { BROWSER_UPLOAD_MAX_BYTES } from '@/lib/browser-uploads'
import { triggerHaptic } from '@/lib/haptics'
import { notify, notifyError } from '@/store/notifications'

type TerminalApi = Window['hermesDesktop']['terminal']

const HERMES_PATHS_MIME = 'application/x-hermes-paths'

/** A host path, or an OS file with no path the browser must upload to get one. */
type DroppedEntry = File | string

function transferHasDropCandidates(t: DataTransfer): boolean {
  if (t.types?.includes(HERMES_PATHS_MIME)) {
    return true
  }

  if ((t.files?.length ?? 0) > 0) {
    return true
  }

  for (let i = 0; i < (t.items?.length ?? 0); i += 1) {
    if (t.items[i]?.kind === 'file') {
      return true
    }
  }

  return false
}

function collectDroppedEntries(t: DataTransfer): DroppedEntry[] {
  const seen = new Set<string>()
  const entries: DroppedEntry[] = []

  const push = (value: unknown) => {
    if (typeof value !== 'string') {
      return
    }

    const path = value.trim()

    if (path && !seen.has(path)) {
      seen.add(path)
      entries.push(path)
    }
  }

  try {
    const raw = t.getData(HERMES_PATHS_MIME)

    if (raw) {
      for (const entry of JSON.parse(raw) as { path?: unknown }[]) {
        push(entry?.path)
      }
    }
  } catch {
    // Malformed in-app drag payload — fall through to OS files.
  }

  const getPath = window.hermesDesktop?.getPathForFile
  // Only the browser-hosted Desktop stages bytes; Electron resolves an OS file to its own path.
  const canStage = Boolean(window.hermesDesktop?.stageFileForAttach)
  const fileCount = t.files?.length ?? 0

  // `items` repeats `files` with fresh File objects, so it supplies files to stage only when
  // `files` is empty.
  const addFile = (file: File | null, stageable: boolean) => {
    if (!file) {
      return
    }

    let path = ''

    try {
      path = getPath?.(file) ?? ''
    } catch {
      // File handle unavailable.
    }

    if (path) {
      push(path)
    } else if (canStage && stageable) {
      entries.push(file)
    }
  }

  for (let i = 0; i < fileCount; i += 1) {
    addFile(t.files.item(i), true)
  }

  for (let i = 0; i < (t.items?.length ?? 0); i += 1) {
    const item = t.items[i]

    if (item?.kind === 'file') {
      addFile(item.getAsFile(), fileCount === 0)
    }
  }

  return entries
}

// The browser uploads each dropped file to the host (the composer's staged upload) and types the
// host path it gets back. A file over the upload limit is never sent; a warning names it.
async function stageDroppedEntries(entries: DroppedEntry[]): Promise<string[]> {
  const stage = window.hermesDesktop?.stageFileForAttach
  const tooLarge: string[] = []

  const paths = await Promise.all(
    entries.map(async entry => {
      if (typeof entry === 'string') {
        return entry
      }

      if (entry.size > BROWSER_UPLOAD_MAX_BYTES) {
        tooLarge.push(entry.name)

        return ''
      }

      try {
        return (await stage?.(entry)) ?? ''
      } catch (error) {
        notifyError(error, translateNow('rightSidebar.terminalDropUploadFailed', entry.name))

        return ''
      }
    })
  )

  if (tooLarge.length) {
    notify({
      kind: 'warning',
      title: translateNow('rightSidebar.terminalDropTooLargeTitle'),
      message: translateNow(
        'rightSidebar.terminalDropTooLarge',
        tooLarge.join(', '),
        `${BROWSER_UPLOAD_MAX_BYTES / (1024 * 1024)} MiB`
      )
    })
  }

  return paths.filter(Boolean)
}

function quotePathForShell(path: string, shellName: string): string {
  const shell = shellName.toLowerCase()

  if (shell.includes('powershell') || shell.includes('pwsh')) {
    return `'${path.replace(/'/g, "''")}'`
  }

  if (shell.includes('cmd')) {
    return `"${path.replace(/"/g, '""')}"`
  }

  return `'${path.replace(/'/g, "'\\''")}'`
}

interface TerminalDropOptions {
  getSessionId: () => string | null
  getShellName: () => string
  markActivity: () => void
  term: Terminal
  terminalApi: TerminalApi
}

// Dropping files (from the OS or the app's file trees) types their shell-quoted
// paths at the prompt, like a native terminal. In the browser-hosted Desktop an
// OS file is uploaded to the host first and its host path is typed. Returns the
// listener teardown.
export function bindTerminalDrop(
  host: HTMLElement,
  { getSessionId, getShellName, markActivity, term, terminalApi }: TerminalDropOptions
): () => void {
  const onDragOver = (e: DragEvent) => {
    if (!e.dataTransfer || !transferHasDropCandidates(e.dataTransfer)) {
      return
    }

    e.preventDefault()
    e.stopPropagation()
    e.dataTransfer.dropEffect = 'copy'
  }

  const onDrop = (e: DragEvent) => {
    const id = getSessionId()

    if (!id || !e.dataTransfer || !transferHasDropCandidates(e.dataTransfer)) {
      return
    }

    e.preventDefault()
    e.stopPropagation()
    const entries = collectDroppedEntries(e.dataTransfer)

    if (!entries.length) {
      return
    }

    const typePaths = (paths: string[]) => {
      if (!paths.length) {
        return
      }

      markActivity()
      void terminalApi.write(id, `${paths.map(p => quotePathForShell(p, getShellName())).join(' ')} `)
      term.focus()
      triggerHaptic('selection')
    }

    if (entries.every((entry): entry is string => typeof entry === 'string')) {
      typePaths(entries)

      return
    }

    void stageDroppedEntries(entries).then(typePaths)
  }

  host.addEventListener('dragenter', onDragOver)
  host.addEventListener('dragover', onDragOver)
  host.addEventListener('drop', onDrop)

  return () => {
    host.removeEventListener('dragenter', onDragOver)
    host.removeEventListener('dragover', onDragOver)
    host.removeEventListener('drop', onDrop)
  }
}
