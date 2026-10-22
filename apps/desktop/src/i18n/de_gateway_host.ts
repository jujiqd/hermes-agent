import type { GatewayHostTranslations } from './types_gateway_host'

// Settings → Gateways copy where the connection cannot change, spread into de.ts.
export const deGatewayHost: GatewayHostTranslations = {
  unavailableTitle: 'Gateway-Einstellungen nicht verfügbar',
  unavailableDesc: 'Die Desktop-IPC-Brücke stellt keine Gateway-Einstellungen bereit.',
  webappHostTitle: 'Hermes-Host',
  webappHostDesc:
    'Die Webapp nutzt immer den Hermes-Host, der sie ausliefert. Um das Gateway zu wechseln, sich bei Hermes Cloud anzumelden oder gespeicherte Verbindungen zu verwalten, verwenden Sie die Hermes-Desktop-App.',
  webAccess: {
    title: 'Webzugriff',
    intro: 'Öffne Hermes auf diesem Computer vom Handy oder einem anderen Computer aus, angemeldet mit deinem Nous-Konto. Wer sich anmeldet, kann Befehle auf diesem Computer ausführen.',
    failed: 'Der Webzugriff konnte nicht geändert werden',
    running: 'Läuft',
    stopped: 'Gestoppt',
    starting: 'Wird gestartet',
    restartNeeded: 'Neustart nötig',
    unavailable: 'Nicht verfügbar',
    notRunningDetail: 'Starte ihn, um Hermes von einem anderen Gerät aus zu öffnen.',
    needsNous: 'Melde dich zuerst unter Anbieter bei deinem Nous-Konto an.',
    runningLan: 'Öffne diese Adresse auf einem Gerät im selben Netzwerk.',
    runningPublic: 'Über deine URL bereitgestellt.',
    pendingOn: 'Gespeichert. Das Gateway stellt die Web-App nach seinem Neustart bereit.',
    pendingOff: 'Ausgeschaltet, aber das Gateway stellt die Web-App bis zu seinem Neustart weiter bereit.',
    unavailableDetail: reason => `Das Gateway konnte die Web-App nicht bereitstellen: ${reason}`,
    restartRefused: reason => `Gespeichert. Starte das Gateway neu, um es anzuwenden: ${reason}`,
    startTimedOut: 'Das Gateway hat die Web-App nicht innerhalb von 90 Sekunden bereitgestellt.',
    start: 'Starten',
    stop: 'Stoppen',
    restartGateway: 'Gateway neu starten',
    modeLan: 'Dieses Netzwerk',
    modeLanDetail: url => `Geräte in deinem WLAN öffnen ${url}. Nur in einem vertrauenswürdigen Netzwerk verwenden.`,
    noLan: 'Dieser Computer hat keine Netzwerkadresse, die andere Geräte erreichen können.',
    modePublic: 'Eigene URL',
    modePublicDetail: port => `Eine HTTPS-Adresse, die du bereits betreibst, etwa Tailscale Serve oder ein Tunnel, die an http://127.0.0.1:${port} weiterleitet.`
  }
}
