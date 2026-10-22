import type { GatewayHostTranslations } from './types_gateway_host'

// Settings → Gateways copy where the connection cannot change, spread into ru.ts.
export const ruGatewayHost: GatewayHostTranslations = {
  unavailableTitle: 'Настройки шлюза недоступны',
  unavailableDesc: 'IPC-мост приложения не предоставляет настройки шлюза.',
  webappHostTitle: 'Хост Hermes',
  webappHostDesc:
    'Webapp всегда использует хост Hermes, который его обслуживает. Чтобы сменить шлюз, войти в Hermes Cloud или управлять сохранёнными подключениями, используйте приложение Hermes Desktop.',
  webAccess: {
    title: 'Веб-доступ',
    intro: 'Откройте Hermes этого компьютера с телефона или другого компьютера, войдя через аккаунт Nous. Вошедший может запускать команды на этом компьютере.',
    failed: 'Не удалось изменить веб-доступ',
    running: 'Работает',
    stopped: 'Остановлен',
    starting: 'Запускается',
    restartNeeded: 'Нужен перезапуск',
    unavailable: 'Недоступен',
    notRunningDetail: 'Запустите его, чтобы открыть Hermes с другого устройства.',
    needsNous: 'Сначала войдите в аккаунт Nous в разделе «Провайдеры».',
    runningLan: 'Откройте этот адрес на устройстве в той же сети.',
    runningPublic: 'Доступен через ваш URL.',
    pendingOn: 'Сохранено. Шлюз откроет веб-приложение после перезапуска.',
    pendingOff: 'Выключено, но шлюз продолжает открывать веб-приложение до перезапуска.',
    unavailableDetail: reason => `Шлюзу не удалось открыть веб-приложение: ${reason}`,
    restartRefused: reason => `Сохранено. Перезапустите шлюз, чтобы применить: ${reason}`,
    startTimedOut: 'Шлюз не открыл веб-приложение за 90 секунд.',
    start: 'Запустить',
    stop: 'Остановить',
    restartGateway: 'Перезапустить шлюз',
    modeLan: 'Эта сеть',
    modeLanDetail: url => `Устройства в вашей сети Wi-Fi открывают ${url}. Используйте только в доверенной сети.`,
    noLan: 'У этого компьютера нет сетевого адреса, доступного другим устройствам.',
    modePublic: 'Мой собственный URL',
    modePublicDetail: port => `Уже работающий HTTPS-адрес, например Tailscale Serve или туннель, который перенаправляет на http://127.0.0.1:${port}.`
  }
}
