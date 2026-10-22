import type { GatewayHostTranslations } from './types_gateway_host'

// Settings → Gateways copy where the connection cannot change, spread into ja.ts.
export const jaGatewayHost: GatewayHostTranslations = {
  unavailableTitle: 'ゲートウェイ設定は利用できません',
  unavailableDesc: 'デスクトップ IPC ブリッジはゲートウェイ設定を公開していません。',
  webappHostTitle: 'Hermes ホスト',
  webappHostDesc:
    'Webapp は常に配信元の Hermes ホストを使用します。ゲートウェイの切り替え、Hermes Cloud へのサインイン、保存済み接続の管理は Hermes Desktop アプリで行ってください。',
  webAccess: {
    title: 'Web アクセス',
    intro: 'スマートフォンや別のコンピューターから、Nous アカウントでサインインしてこのコンピューターの Hermes を開きます。サインインした人はこのコンピューターでコマンドを実行できます。',
    failed: 'Web アクセスを変更できませんでした',
    running: '実行中',
    stopped: '停止中',
    starting: '起動中',
    restartNeeded: '再起動が必要',
    unavailable: '利用できません',
    notRunningDetail: '起動すると、別のデバイスから Hermes を開けます。',
    needsNous: '先に「プロバイダー」で Nous アカウントにサインインしてください。',
    runningLan: '同じネットワーク上のデバイスでこのアドレスを開いてください。',
    runningPublic: 'あなたの URL 経由で提供中です。',
    pendingOn: '保存しました。ゲートウェイの再起動後に Web アプリが提供されます。',
    pendingOff: 'オフにしましたが、ゲートウェイは再起動するまで Web アプリを提供し続けます。',
    unavailableDetail: reason => `ゲートウェイが Web アプリを提供できませんでした: ${reason}`,
    restartRefused: reason => `保存しました。適用するにはゲートウェイを再起動してください: ${reason}`,
    startTimedOut: 'ゲートウェイが 90 秒以内に Web アプリを提供しませんでした。',
    start: '開始',
    stop: '停止',
    restartGateway: 'ゲートウェイを再起動',
    modeLan: 'このネットワーク',
    modeLanDetail: url => `Wi-Fi 上のデバイスで ${url} を開きます。信頼できるネットワークでのみ使用してください。`,
    noLan: 'このコンピューターには、他のデバイスから到達できるネットワークアドレスがありません。',
    modePublic: '独自の URL',
    modePublicDetail: port => `Tailscale Serve やトンネルなど、すでに運用している HTTPS アドレスで、http://127.0.0.1:${port} に転送するもの。`
  }
}
