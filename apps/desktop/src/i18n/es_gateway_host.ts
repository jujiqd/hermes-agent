import type { GatewayHostTranslations } from './types_gateway_host'

// Settings → Gateways copy where the connection cannot change, spread into es.ts.
export const esGatewayHost: GatewayHostTranslations = {
  unavailableTitle: 'Ajustes del gateway no disponibles',
  unavailableDesc:
    'Los ajustes de conexión solo se pueden cambiar desde la app Hermes Desktop en el equipo que la ejecuta.',
  webappHostTitle: 'Host de Hermes',
  webappHostDesc:
    'La Webapp siempre usa el host de Hermes que la sirve. Para cambiar de gateway, iniciar sesión en Hermes Cloud o gestionar conexiones guardadas, usa la app Hermes Desktop.',
  webAccess: {
    title: 'Acceso web',
    intro: 'Abre Hermes de este ordenador desde tu teléfono u otro ordenador, con tu cuenta de Nous. Quien inicie sesión puede ejecutar comandos en este ordenador.',
    failed: 'No se pudo cambiar el acceso web',
    running: 'En ejecución',
    stopped: 'Detenido',
    starting: 'Iniciando',
    restartNeeded: 'Reinicio necesario',
    unavailable: 'No disponible',
    notRunningDetail: 'Inícialo para abrir Hermes desde otro dispositivo.',
    needsNous: 'Primero inicia sesión en tu cuenta de Nous en Proveedores.',
    runningLan: 'Abre esta dirección en un dispositivo de la misma red.',
    runningPublic: 'Servido a través de tu URL.',
    pendingOn: 'Guardado. El gateway servirá la aplicación web cuando se reinicie.',
    pendingOff: 'Desactivado, pero el gateway sigue sirviendo la aplicación web hasta que se reinicie.',
    unavailableDetail: reason => `El gateway no pudo servir la aplicación web: ${reason}`,
    restartRefused: reason => `Guardado. Reinicia el gateway para aplicarlo: ${reason}`,
    startTimedOut: 'El gateway no sirvió la aplicación web en 90 segundos.',
    start: 'Iniciar',
    stop: 'Detener',
    restartGateway: 'Reiniciar gateway',
    modeLan: 'Esta red',
    modeLanDetail: url => `Los dispositivos de tu wifi abren ${url}. Úsalo solo en una red de confianza.`,
    noLan: 'Este ordenador no tiene una dirección de red a la que puedan llegar otros dispositivos.',
    modePublic: 'Mi propia URL',
    modePublicDetail: port => `Una dirección HTTPS que ya tengas, como Tailscale Serve o un túnel, que reenvíe a http://127.0.0.1:${port}.`
  }
}
