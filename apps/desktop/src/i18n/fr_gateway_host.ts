import type { GatewayHostTranslations } from './types_gateway_host'

// Settings → Gateways copy where the connection cannot change, spread into fr.ts.
export const frGatewayHost: GatewayHostTranslations = {
  unavailableTitle: 'Paramètres du gateway indisponibles',
  unavailableDesc: "Le pont IPC du desktop n'expose pas les paramètres du gateway.",
  webappHostTitle: 'Hôte Hermes',
  webappHostDesc:
    "La Webapp utilise toujours l'hôte Hermes qui la sert. Pour changer de gateway, vous connecter à Hermes Cloud ou gérer les connexions enregistrées, utilisez l'application Hermes Desktop.",
  webAccess: {
    title: 'Accès web',
    intro: "Ouvrez Hermes sur cet ordinateur depuis votre téléphone ou un autre ordinateur, avec votre compte Nous. Toute personne connectée peut exécuter des commandes sur cet ordinateur.",
    failed: "Impossible de modifier l'accès web",
    running: 'En cours',
    stopped: 'Arrêté',
    starting: 'Démarrage',
    restartNeeded: 'Redémarrage requis',
    unavailable: 'Indisponible',
    notRunningDetail: 'Démarrez-le pour ouvrir Hermes depuis un autre appareil.',
    needsNous: "Connectez-vous d'abord à votre compte Nous dans Fournisseurs.",
    runningLan: 'Ouvrez cette adresse sur un appareil du même réseau.',
    runningPublic: 'Servi via votre URL.',
    pendingOn: "Enregistré. La passerelle servira l'application web après son redémarrage.",
    pendingOff: "Désactivé, mais la passerelle continue de servir l'application web jusqu'à son redémarrage.",
    unavailableDetail: reason => `La passerelle n'a pas pu servir l'application web : ${reason}`,
    restartRefused: reason => `Enregistré. Redémarrez la passerelle pour l'appliquer : ${reason}`,
    startTimedOut: "La passerelle n'a pas servi l'application web en 90 secondes.",
    start: 'Démarrer',
    stop: 'Arrêter',
    restartGateway: 'Redémarrer la passerelle',
    modeLan: 'Ce réseau',
    modeLanDetail: url => `Les appareils de votre Wi-Fi ouvrent ${url}. À utiliser uniquement sur un réseau de confiance.`,
    noLan: "Cet ordinateur n'a aucune adresse réseau accessible aux autres appareils.",
    modePublic: 'Ma propre URL',
    modePublicDetail: port => `Une adresse HTTPS que vous gérez déjà, comme Tailscale Serve ou un tunnel, redirigée vers http://127.0.0.1:${port}.`
  }
}
