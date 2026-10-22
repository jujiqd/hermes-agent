// Settings → Gateways copy for a renderer that cannot change its connection: a Desktop whose
// bridge exposes no gateway settings, and the Webapp, bound to the host that serves it. Plus
// Settings → Web Access, which turns on the Webapp this machine's gateway serves.
// `Translations['settings']['gateway']` spreads this in.
export interface GatewayHostTranslations {
  unavailableTitle: string
  unavailableDesc: string
  webappHostTitle: string
  webappHostDesc: string
  webAccess: WebAccessTranslations
}

export interface WebAccessTranslations {
  title: string
  intro: string
  failed: string
  running: string
  stopped: string
  starting: string
  restartNeeded: string
  unavailable: string
  notRunningDetail: string
  needsNous: string
  runningLan: string
  runningPublic: string
  pendingOn: string
  pendingOff: string
  unavailableDetail: (reason: string) => string
  restartRefused: (reason: string) => string
  startTimedOut: string
  start: string
  stop: string
  restartGateway: string
  modeLan: string
  modeLanDetail: (url: string) => string
  noLan: string
  modePublic: string
  modePublicDetail: (port: number) => string
}
