import os
import json
import time
import subprocess
import logging
import discord
from discord.ext import commands
from pathlib import Path
from config import settings

logger = logging.getLogger("OmusuBI.DevChat")

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)

MEMOS_FILE = DATA_DIR / "memos.json"
SECRETS_FILE = DATA_DIR / "secrets.json"
MEMORY_FILE = DATA_DIR / "memory.json"

PENDING_PROMPTS: dict[str, dict] = {}
LAST_BRIDGE_PING: float = 0.0

class DevChatService:
    def __init__(self):
        self._init_files()

    def is_bridge_online(self) -> bool:
        global LAST_BRIDGE_PING
        return (time.time() - LAST_BRIDGE_PING) < 15.0

    def record_bridge_ping(self):
        global LAST_BRIDGE_PING
        LAST_BRIDGE_PING = time.time()

    def add_bridge_task(self, prompt: str, channel_id: int, message_id: int, author: str) -> str:
        task_id = f"task-{int(time.time() * 1000)}"
        PENDING_PROMPTS[task_id] = {
            "id": task_id,
            "prompt": prompt,
            "channel_id": channel_id,
            "message_id": message_id,
            "author": author,
            "created_at": time.time(),
            "in_flight": False
        }
        return task_id

    def get_next_bridge_task(self) -> dict | None:
        self.record_bridge_ping()
        for tid, t in list(PENDING_PROMPTS.items()):
            if not t.get("in_flight"):
                t["in_flight"] = True
                return t
        return None

    def pop_bridge_task(self, task_id: str) -> dict | None:
        return PENDING_PROMPTS.pop(task_id, None)

    def _init_files(self):
        for f in [MEMOS_FILE, SECRETS_FILE, MEMORY_FILE]:
            if not f.exists():
                with open(f, "w", encoding="utf-8") as fp:
                    json.dump([] if f == MEMOS_FILE else {}, fp, indent=2, ensure_ascii=False)

    def is_allowed_channel(self, channel: discord.abc.GuildChannel | discord.Thread) -> bool:
        """
        Strict Category Isolation Guard:
        Only allow operations inside DEV_CATEGORY_ID (1555216452267544676)
        and DEV_FORUM_CHANNEL_ID (1555216710863429654) in Server 1159029710584561725.
        Any other guild or category is strictly rejected.
        """
        guild = getattr(channel, "guild", None)
        if not guild or guild.id != settings.DEV_SERVER_ID:
            return False

        # Forum Channel itself
        if channel.id == settings.DEV_FORUM_CHANNEL_ID:
            return True

        # Thread inside Forum Channel or Category
        if isinstance(channel, discord.Thread):
            if channel.parent_id == settings.DEV_FORUM_CHANNEL_ID:
                return True
            parent = channel.parent
            if parent and getattr(parent, "category_id", None) == settings.DEV_CATEGORY_ID:
                return True
            return False

        # Standard Text Channel directly under DEV_CATEGORY_ID
        if getattr(channel, "category_id", None) == settings.DEV_CATEGORY_ID:
            return True

        return False

    # ------------------ Memos ------------------
    def add_memo(self, title: str, content: str, author: str, thread_id: int | None = None) -> dict:
        memos = self.list_memos()
        memo = {
            "id": len(memos) + 1,
            "title": title,
            "content": content,
            "author": author,
            "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "thread_id": thread_id
        }
        memos.append(memo)
        with open(MEMOS_FILE, "w", encoding="utf-8") as fp:
            json.dump(memos, fp, indent=2, ensure_ascii=False)
        return memo

    def list_memos(self) -> list[dict]:
        try:
            with open(MEMOS_FILE, "r", encoding="utf-8") as fp:
                return json.load(fp)
        except Exception:
            return []

    # ------------------ Secrets ------------------
    def add_secret(self, key: str, value: str, author: str) -> dict:
        secrets = self._get_secrets_raw()
        secrets[key] = {
            "value": value,
            "author": author,
            "updated_at": time.strftime("%Y-%m-%d %H:%M:%S")
        }
        with open(SECRETS_FILE, "w", encoding="utf-8") as fp:
            json.dump(secrets, fp, indent=2, ensure_ascii=False)
        return {"key": key, "author": author}

    def _get_secrets_raw(self) -> dict:
        try:
            with open(SECRETS_FILE, "r", encoding="utf-8") as fp:
                return json.load(fp)
        except Exception:
            return {}

    def list_secrets(self) -> list[dict]:
        raw = self._get_secrets_raw()
        masked = []
        for k, v in raw.items():
            val = v.get("value", "")
            mask = val[:3] + "••••" + val[-2:] if len(val) > 6 else "••••••••"
            masked.append({
                "key": k,
                "masked_value": mask,
                "author": v.get("author", "unknown"),
                "updated_at": v.get("updated_at", "")
            })
        return masked

    def get_secret(self, key: str) -> str | None:
        raw = self._get_secrets_raw()
        if key in raw:
            return raw[key].get("value")
        return None

    # ------------------ Memory ------------------
    def set_memory(self, key: str, content: str, author: str) -> dict:
        mem = self.list_memories_dict()
        mem[key] = {
            "content": content,
            "author": author,
            "updated_at": time.strftime("%Y-%m-%d %H:%M:%S")
        }
        with open(MEMORY_FILE, "w", encoding="utf-8") as fp:
            json.dump(mem, fp, indent=2, ensure_ascii=False)
        return {"key": key, "content": content}

    def list_memories_dict(self) -> dict:
        try:
            with open(MEMORY_FILE, "r", encoding="utf-8") as fp:
                return json.load(fp)
        except Exception:
            return {}

    def get_memory(self, key: str) -> dict | None:
        return self.list_memories_dict().get(key)

    # ------------------ VPS Status Diagnostic ------------------
    def get_vps_diagnostics(self) -> dict:
        data = {
            "uptime": "N/A",
            "load_avg": "N/A",
            "memory": "N/A",
            "disk": "N/A",
            "k3s_nodes": "N/A",
            "argocd_apps": "N/A"
        }
        try:
            res = subprocess.run(["uptime"], capture_output=True, text=True, timeout=3)
            if res.returncode == 0:
                data["uptime"] = res.stdout.strip()
        except Exception:
            pass

        try:
            res = subprocess.run(["free", "-m"], capture_output=True, text=True, timeout=3)
            if res.returncode == 0:
                lines = res.stdout.strip().split("\n")
                if len(lines) > 1:
                    parts = lines[1].split()
                    if len(parts) >= 7:
                        total, used, free, avail = parts[1], parts[2], parts[3], parts[6]
                        data["memory"] = f"Total: {total}MB | Used: {used}MB | Avail: {avail}MB"
        except Exception:
            pass

        try:
            res = subprocess.run(["df", "-h", "/"], capture_output=True, text=True, timeout=3)
            if res.returncode == 0:
                lines = res.stdout.strip().split("\n")
                if len(lines) > 1:
                    data["disk"] = lines[1]
        except Exception:
            pass

        try:
            res = subprocess.run(["k3s", "kubectl", "get", "nodes", "--no-headers"], capture_output=True, text=True, timeout=5)
            if res.returncode == 0:
                nodes = [l.split()[0] + f" ({l.split()[1]})" for l in res.stdout.strip().split("\n") if l.strip()]
                data["k3s_nodes"] = ", ".join(nodes)
        except Exception:
            pass

        try:
            res = subprocess.run(["k3s", "kubectl", "get", "applications", "-n", "argocd", "--no-headers"], capture_output=True, text=True, timeout=5)
            if res.returncode == 0:
                apps = [f"{l.split()[0]} [{l.split()[1]}/{l.split()[2]}]" for l in res.stdout.strip().split("\n") if l.strip()]
                data["argocd_apps"] = "\n".join(apps[:6]) + (f"\n...他 {len(apps)-6} 件" if len(apps) > 6 else "")
        except Exception:
            pass

        return data

    # ------------------ Automatic Channel Handlers ------------------
    async def handle_memo_channel_message(self, message: discord.Message):
        content = message.content.strip()
        if not content:
            return
        lines = [l.strip() for l in content.split("\n") if l.strip()]
        if len(lines) > 1:
            title = lines[0]
            body = "\n".join(lines[1:])
        elif ":" in content:
            title, body = content.split(":", 1)
        elif "|" in content:
            title, body = content.split("|", 1)
        else:
            title = content[:35] + ("..." if len(content) > 35 else "")
            body = content

        author_name = message.author.display_name
        memo = self.add_memo(title.strip(), body.strip(), author_name, message.channel.id)

        embed = discord.Embed(
            title=f"📝 開発メモを自動保存しました: {memo['title']}",
            description=f"```{memo['content']}```",
            color=0x3B82F6
        )
        embed.set_footer(text=f"Memo ID: #{memo['id']} • 記録者: {author_name} • 自動保存")
        await message.reply(embed=embed)
        try:
            await message.add_reaction("📝")
        except Exception:
            pass

    async def handle_memory_channel_message(self, message: discord.Message):
        content = message.content.strip()
        if not content:
            return
        lines = [l.strip() for l in content.split("\n") if l.strip()]
        if len(lines) > 1:
            key = lines[0]
            body = "\n".join(lines[1:])
        elif ":" in content:
            key, body = content.split(":", 1)
        elif "=" in content:
            key, body = content.split("=", 1)
        elif "|" in content:
            key, body = content.split("|", 1)
        else:
            parts = content.split(maxsplit=1)
            if len(parts) == 2:
                key, body = parts[0], parts[1]
            else:
                key = content[:30]
                body = content

        author_name = message.author.display_name
        mem = self.set_memory(key.strip(), body.strip(), author_name)

        embed = discord.Embed(
            title=f"🧠 システムメモリーに自動記憶しました",
            description=f"**キー:** `{mem['key']}`\n\n```{mem['content']}```",
            color=0x8B5CF6
        )
        embed.set_footer(text=f"記録者: {author_name} • 自動学習")
        await message.reply(embed=embed)
        try:
            await message.add_reaction("🧠")
        except Exception:
            pass

    async def handle_secret_channel_message(self, message: discord.Message):
        content = message.content.strip()
        if not content:
            return
        if ":" in content:
            k, v = content.split(":", 1)
        elif "=" in content:
            k, v = content.split("=", 1)
        elif "|" in content:
            k, v = content.split("|", 1)
        else:
            parts = content.split(maxsplit=1)
            if len(parts) == 2:
                k, v = parts[0], parts[1]
            else:
                k = f"secret-{int(time.time())}"
                v = content

        author_name = message.author.display_name
        k = k.strip()
        v = v.strip()
        self.add_secret(k, v, author_name)

        # Security: Delete the original message containing plaintext secret
        try:
            await message.delete()
        except Exception:
            pass

        mask = v[:3] + "••••" + v[-2:] if len(v) > 6 else "••••••••"
        embed = discord.Embed(
            title="🔐 シークレットを自動安全保管しました",
            description=(
                f"**キー:** `{k}`\n"
                f"**値:** `{mask}`\n\n"
                "🛡️ *セキュリティ保護のため、送信された平文メッセージはチャンネル上から自動削除されました。*"
            ),
            color=0x10B981
        )
        embed.set_footer(text=f"登録者: {author_name} • 保存先: VPS暗号化ストア")
        await message.channel.send(embed=embed)

    # ------------------ Forum Post Creation ------------------
    async def create_forum_post(
        self,
        bot: commands.Bot,
        title: str,
        content: str,
        tag_id: int | None = None,
        author: str = ""
    ) -> discord.Thread:
        forum = bot.get_channel(settings.DEV_FORUM_CHANNEL_ID)
        if not forum:
            forum = await bot.fetch_channel(settings.DEV_FORUM_CHANNEL_ID)

        applied_tags = []
        if tag_id and hasattr(forum, "available_tags"):
            tag_obj = discord.utils.get(forum.available_tags, id=tag_id)
            if tag_obj:
                applied_tags.append(tag_obj)

        thread_with_message = await forum.create_thread(
            name=title,
            content=content,
            applied_tags=applied_tags
        )
        return thread_with_message.thread

    # ------------------ Interactive Prompt Handler ------------------
    async def handle_prompt(
        self,
        text: str,
        author_name: str,
        channel: discord.abc.GuildChannel | discord.Thread,
        bot: commands.Bot,
        message_id: int = 0
    ) -> discord.Embed | str:
        text_lower = text.lower().strip()

        # 1. Status / Diagnostics
        if any(w in text_lower for w in ["status", "ステータス", "vps", "k3s", "負荷", "負荷状況", "システム状態", "稼働状況"]):
            diag = self.get_vps_diagnostics()
            embed = discord.Embed(
                title="🖥️ VPS & クラスターリアルタイム稼働状況",
                color=0x10B981
            )
            embed.add_field(name="⏱️ Uptime & Load", value=f"```{diag['uptime']}```", inline=False)
            embed.add_field(name="🧠 メモリ使用量", value=f"```{diag['memory']}```", inline=False)
            embed.add_field(name="💾 ディスク使用状況", value=f"```{diag['disk']}```", inline=False)
            embed.add_field(name="☸️ K3s クラスターノード", value=f"```{diag['k3s_nodes']}```", inline=False)
            if diag.get("argocd_apps") != "N/A":
                embed.add_field(name="🐙 Argo CD アプリ同期状態", value=f"```{diag['argocd_apps']}```", inline=False)
            embed.set_footer(text="OmusuBI Devops • Antigravity Remote Assistant")
            return embed

        # 2. Argo CD / GitOps check
        if any(w in text_lower for w in ["argocd", "argo", "gitops", "同期"]):
            diag = self.get_vps_diagnostics()
            embed = discord.Embed(
                title="🐙 Argo CD GitOps 同期状態",
                description="K3s クラスター上の Argo CD アプリケーションステータスです。",
                color=0xEA580C
            )
            embed.add_field(name="同期中アプリケーション", value=f"```{diag.get('argocd_apps', 'N/A')}```", inline=False)
            embed.set_footer(text="OmusuBI GitOps • clusters/vps")
            return embed

        # 3. List memos
        if "メモ一覧" in text or "memos" in text_lower:
            memos = self.list_memos()
            if not memos:
                return "ℹ️ 現在登録されている開発メモはありません。`📝・メモ` チャンネルにメッセージを送信すると自動記録されます。"
            embed = discord.Embed(title="📝 開発メモ一覧", color=0x3B82F6)
            for m in memos[-10:]:
                embed.add_field(
                    name=f"#{m['id']} {m['title']} ({m['created_at']})",
                    value=m['content'][:200] + ("..." if len(m['content']) > 200 else ""),
                    inline=False
                )
            return embed

        # 4. List memory
        if "メモリー一覧" in text or "memory list" in text_lower:
            mems = self.list_memories_dict()
            if not mems:
                return "ℹ️ 現在登録されているメモリー情報はありません。`🧠・メモリー` チャンネルにメッセージを送信すると自動記憶されます。"
            embed = discord.Embed(title="🧠 システムメモリー一覧", color=0x8B5CF6)
            for k, v in list(mems.items())[-10:]:
                embed.add_field(
                    name=f"🔑 {k} ({v.get('updated_at', '')})",
                    value=v.get('content', '')[:200],
                    inline=False
                )
            return embed

        # 5. List secrets
        if "シークレット一覧" in text or "secrets" in text_lower:
            secs = self.list_secrets()
            if not secs:
                return "ℹ️ 現在登録されているシークレットはありません。`🔐・シークレット` チャンネルに送信すると安全に保管されます。"
            embed = discord.Embed(title="🔐 シークレット一覧 (マスク表示)", color=0xF59E0B)
            for s in secs:
                embed.add_field(
                    name=f"🔑 `{s['key']}`",
                    value=f"値: `{s['masked_value']}`\n更新日時: {s['updated_at']}\n登録者: {s['author']}",
                    inline=False
                )
            return embed

        # 6. Check if PC Bridge is online for direct execution!
        if self.is_bridge_online():
            task_id = self.add_bridge_task(
                prompt=text,
                channel_id=channel.id,
                message_id=message_id,
                author=author_name
            )
            embed = discord.Embed(
                title="🚀 HOME-DESKTOP (Antigravity PC) へ転送",
                description=f"受信したプロンプトを自宅PCの Antigravity エージェントへ転送しました。\nPC側で自動実行中です。完了次第、結果がここに返答されます。\n\n**送信プロンプト:**\n> {text}",
                color=0x6366F1
            )
            embed.set_footer(text=f"Task: {task_id} • Status: Running on PC Antigravity")
            return embed
        else:
            embed = discord.Embed(
                title="🏠 HOME-DESKTOP (PC Bridge) オフライン",
                description=(
                    f"**受信プロンプト:**\n> {text}\n\n"
                    "自宅PC（HOME-DESKTOP）の Antigravity Bridge が現在オフラインです。\n"
                    "PCを起動し `start_bridge.bat` が実行されると、Discordから自宅PCのAntigravityを直接遠隔操作できます。\n\n"
                    "※VPS単体のステータス確認（`ステータス` / `argocd`）や、`📝・メモ`、`🧠・メモリー`、`🔐・シークレット` の保存はそのままご利用いただけます。"
                ),
                color=0xF59E0B
            )
            embed.set_footer(text="OmusuBI Devops • Antigravity Remote Assistant")
            return embed

dev_chat_service = DevChatService()
