# プロジェクト永続運用ルール (GEMINI.md)

## 【最重要・永久必須事項】Discord への進捗報告および記録義務

本ワークスペース（`●devop`）を扱うすべての AI エージェント（Antigravity、サブエージェント、後続チャット）は、**以下の Discord 報告・記録ルールを永久の必須事項として厳格に遵守すること**。

---

### 1. 進捗報告のタイミング
いかなるタスク（調査・構築・設定変更・デバッグ・メンテナンス）においても、以下のタイミングで指定スレッドへ進捗報告を自動送信すること：
1. **作業開始時**: タスク内容・着手方針・予定スコープを送信
2. **作業中（1時間ごと）**: 長時間タスク時は 1 時間おきに進捗・現在地・残タスクを送信
3. **作業完了時**: 実施結果・確認ログ・残課題のまとめを送信
4. **障害・アラート検知時**: 異常発生・速度低下・設定不整合を発見した際に即時送信

---

### 2. 送信先スレッドおよび専用チャンネル一覧

サーバーID: `1159029710584561725`（Riceball-Database）
カテゴリID: `1555216452267544676`（`nigiri-rice.com🍙`）

| 担当 / 役割 | チャンネル・スレッドID | 運用用途 |
|---|---|---|
| **VPS 専任スレッド** | `1555227855053652139` | `🌐 [VPS] クラウドインフラ運用・進捗報告`<br>VPS（Xserver / K3s / ArgoCD / SSO）作業の報告先 |
| **PVE 専任スレッド** | `1555227857557520394` | `🏠 [PVE] ホームサーバー・宅内ネットワーク運用・進捗報告`<br>Proxmox / AdGuard / BE450 / 2.5GbE 作業の報告先 |
| **開発メモ** | `1555223941759377438` | `📝・メモ`<br>作業備忘録・仕様変更点を直接送信（自動記録） |
| **システムメモリー** | `1555223943848140873` | `🧠・メモリー`<br>設計思想・IPルール・永続設定方針を直接送信（自動記憶） |
| **シークレット保管** | `1555223945173803068` | `🔐・シークレット`<br>機密情報・APIキーを送信（平文は即座に自動削除され暗号保管） |

> [!CAUTION]
> **カテゴリ隔離の徹底**: 上記カテゴリ（`1555216452267544676`）以外のチャンネルには一切干渉・発言・操作を行わないこと。

---

### 3. 送信用スクリプト・コードスニペット

#### Python から送信する場合:
```python
import os, urllib.request, json

TOKEN = os.getenv("DISCORD_BOT_TOKEN", "YOUR_DISCORD_BOT_TOKEN")
CHANNEL_ID = "1555227855053652139"  # VPS: 1555227855053652139 / PVE: 1555227857557520394

def send_discord_progress(title: str, description: str, color: int = 0x6366F1):
    payload = {
        "embeds": [{
            "title": title,
            "description": description,
            "color": color,
            "footer": {"text": "Antigravity Devops Agent"}
        }]
    }
    req = urllib.request.Request(
        f"https://discord.com/api/v10/channels/{CHANNEL_ID}/messages",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bot {TOKEN}",
            "Content-Type": "application/json",
            "User-Agent": "DiscordBot (OmusuBI, 1.0)"
        }
    )
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read().decode())
```

#### PowerShell から送信する場合:
> [!WARNING]
> Windows PowerShell (5.1) では文字列のままだと日本語が `?` に文字化けするため、必ず UTF-8 バイト配列に変換して送信してください。

```powershell
$token = if ($env:DISCORD_BOT_TOKEN) { $env:DISCORD_BOT_TOKEN } else { "YOUR_DISCORD_BOT_TOKEN" }
$channelId = "1555227857557520394" # PVE専任スレッド
$body = @{
    embeds = @(@{
        title = "進捗タイトル"
        description = "進捗詳細内容"
        color = 0x10B981
        footer = @{ text = "Antigravity PVE Agent" }
    })
}
$jsonBytes = [System.Text.Encoding]::UTF8.GetBytes(($body | ConvertTo-Json -Depth 10))
Invoke-RestMethod -Uri "https://discord.com/api/v10/channels/$channelId/messages" `
    -Method Post -Body $jsonBytes `
    -ContentType "application/json; charset=utf-8" `
    -Headers @{ Authorization = "Bot $token"; "User-Agent" = "DiscordBot (OmusuBI, 1.0)" }
```

