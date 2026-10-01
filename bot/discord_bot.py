import time
import asyncio
import random
import string
import logging
import discord
from discord import app_commands
from discord.ext import commands, tasks

from config import settings
from services.keycloak_service import keycloak_service
from services.discord_service import discord_service
from services.invitation_service import invitation_service
from services.dev_chat_service import dev_chat_service

logger = logging.getLogger("OmusuBI.Bot")

# In-memory code store: code -> {discord_user_id, discord_username, expires_at}
LINKING_CODES: dict[str, dict] = {}

class OmusuBIBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True
        super().__init__(command_prefix="!omusu ", intents=intents)
        discord_service.set_bot(self)

    async def setup_hook(self):
        if settings.DISCORD_SERVER_ID:
            guild = discord.Object(id=settings.DISCORD_SERVER_ID)
            self.tree.copy_global_to(guild=guild)
            await self.tree.sync(guild=guild)
            logger.info(f"Slash commands synced to guild {settings.DISCORD_SERVER_ID}")

        if settings.DEV_SERVER_ID and settings.DEV_SERVER_ID != settings.DISCORD_SERVER_ID:
            dev_guild = discord.Object(id=settings.DEV_SERVER_ID)
            self.tree.copy_global_to(guild=dev_guild)
            await self.tree.sync(guild=dev_guild)
            logger.info(f"Slash commands synced to dev guild {settings.DEV_SERVER_ID}")

        self.periodic_sync_task.start()

    async def on_ready(self):
        logger.info(f"Logged in as {self.user} (ID: {self.user.id})")
        guild = self.get_guild(settings.DISCORD_SERVER_ID)
        if guild:
            logger.info(f"Connected to guild: {guild.name} (Member count: {guild.member_count})")
        else:
            logger.warning(f"Guild {settings.DISCORD_SERVER_ID} not found. Please invite the bot.")

    async def on_message(self, message: discord.Message):
        # Ignore bot's own messages
        if message.author.bot:
            return

        # Strict Category Isolation Guard: Only process messages in DEV category / forum
        if not dev_chat_service.is_allowed_channel(message.channel):
            await self.process_commands(message)
            return

        content = message.content.strip()
        if not content:
            return

        # 1. 📝・メモ Channel: Automatic dev memo record without commands
        if message.channel.id == settings.DEV_MEMO_CHANNEL_ID:
            await dev_chat_service.handle_memo_channel_message(message)
            return

        # 2. 🧠・メモリー Channel: Automatic memory store without commands
        if message.channel.id == settings.DEV_MEMORY_CHANNEL_ID:
            await dev_chat_service.handle_memory_channel_message(message)
            return

        # 3. 🔐・シークレット Channel: Automatic secret store & message purge
        if message.channel.id == settings.DEV_SECRET_CHANNEL_ID:
            await dev_chat_service.handle_secret_channel_message(message)
            return

        # 4. In Forum Thread or other channels in Category -> Direct Automatic Prompt Response!
        try:
            async with message.channel.typing():
                res = await dev_chat_service.handle_prompt(
                    text=content,
                    author_name=message.author.display_name,
                    channel=message.channel,
                    bot=self,
                    message_id=message.id
                )
                if isinstance(res, discord.Embed):
                    await message.reply(embed=res)
                else:
                    await message.reply(res)
        except Exception as e:
            logger.error(f"Error handling automatic prompt: {e}")
            await message.reply(f"⚠️ プロンプト処理中にエラーが発生しました: {e}")

        await self.process_commands(message)

    async def on_thread_create(self, thread: discord.Thread):
        if getattr(thread, "guild", None) and thread.guild.id != settings.DEV_SERVER_ID:
            return
        if thread.parent_id != settings.DEV_FORUM_CHANNEL_ID:
            return

        # Wait briefly for starter message to be indexed
        await asyncio.sleep(2)
        try:
            starter = await thread.fetch_message(thread.id)
            if starter and not starter.author.bot and starter.content:
                async with thread.typing():
                    res = await dev_chat_service.handle_prompt(
                        text=starter.content,
                        author_name=starter.author.display_name,
                        channel=thread,
                        bot=self
                    )
                    if isinstance(res, discord.Embed):
                        await thread.send(embed=res)
                    else:
                        await thread.send(res)
        except Exception as e:
            logger.error(f"Error in on_thread_create: {e}")

    async def on_member_update(self, before: discord.Member, after: discord.Member):
        if before.guild.id != settings.DISCORD_SERVER_ID:
            return
        # If roles changed, evaluate permissions
        if before.roles != after.roles:
            logger.info(f"Roles changed for {after.display_name}. Evaluating OmusuBI Developer role...")
            eval_res = await discord_service.evaluate_member_access(after.id)
            user = await keycloak_service.find_user_by_discord_id(after.id)
            if user:
                user_id = user["id"]
                if eval_res["eligible_for_developer_role"]:
                    await keycloak_service.assign_role(user_id, settings.KEYCLOAK_TARGET_ROLE)
                    logger.info(f"Assigned {settings.KEYCLOAK_TARGET_ROLE} to {user['username']} on role update")
                else:
                    await keycloak_service.revoke_role(user_id, settings.KEYCLOAK_TARGET_ROLE)
                    logger.info(f"Revoked {settings.KEYCLOAK_TARGET_ROLE} from {user['username']} on role update")

    async def on_member_remove(self, member: discord.Member):
        if member.guild.id != settings.DISCORD_SERVER_ID:
            return
        logger.info(f"Member {member.display_name} left guild. Revoking Developer role...")
        user = await keycloak_service.find_user_by_discord_id(member.id)
        if user:
            await keycloak_service.revoke_role(user["id"], settings.KEYCLOAK_TARGET_ROLE)
            logger.info(f"Revoked {settings.KEYCLOAK_TARGET_ROLE} from {user['username']}")

    @tasks.loop(hours=6)
    async def periodic_sync_task(self):
        logger.info("Running periodic unjoined members scan...")
        try:
            res = await invitation_service.scan_and_invite_unjoined_members()
            logger.info(f"Scan complete: {res['invited_count']} invited, {res['already_in_guild']} in guild")
        except Exception as e:
            logger.error(f"Error in periodic scan: {e}")

bot = OmusuBIBot()

def generate_linking_code(user_id: int, username: str) -> str:
    now = time.time()
    for k in list(LINKING_CODES.keys()):
        if LINKING_CODES[k]["expires_at"] < now:
            del LINKING_CODES[k]

    code = "OMUSU-" + "".join(random.choices(string.digits, k=4))
    LINKING_CODES[code] = {
        "discord_user_id": str(user_id),
        "discord_username": username,
        "expires_at": now + 600  # 10 minutes
    }
    return code

# ----------------- Existing Commands -----------------
@bot.tree.command(name="link", description="OmusuBI (Keycloak) アカウントと連携するための認証コードを発行します")
async def cmd_link(interaction: discord.Interaction):
    code = generate_linking_code(interaction.user.id, str(interaction.user))
    link_url = f"{settings.WEB_BASE_URL}?code={code}"

    embed = discord.Embed(
        title="🍱 OmusuBI サービス連携コード",
        description="OmusuBI アカウントと Discord アカウントを連携します。\n以下の認証コードまたはリンクから連携ポータルを開いてください。",
        color=0x6366F1
    )
    embed.add_field(name="認証コード (有効期限 10分)", value=f"```\n{code}\n```", inline=False)
    embed.add_field(name="連携ページ URL", value=f"[専用連携ポータルを開く]({link_url})", inline=False)
    embed.set_footer(text="OmusuBI (Boundless Identity) • Developer Role Sync")

    view = discord.ui.View()
    view.add_item(discord.ui.Button(label="連携ポータルを開く", url=link_url, style=discord.ButtonStyle.link))

    await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

@bot.tree.command(name="status", description="あなたの OmusuBI 連携およびチャンネル閲覧権限のステータスを確認します")
async def cmd_status(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)
    eval_res = await discord_service.evaluate_member_access(interaction.user.id)
    user = await keycloak_service.find_user_by_discord_id(interaction.user.id)

    embed = discord.Embed(
        title="🍱 OmusuBI 連携ステータス",
        color=0x10B981 if (user and eval_res["eligible_for_developer_role"]) else 0xF59E0B
    )

    if user:
        embed.add_field(name="OmusuBI ユーザー", value=f"**{user['username']}** ({user.get('email', 'No email')})", inline=False)
        has_dev_role = await keycloak_service.user_has_role(user["id"], settings.KEYCLOAK_TARGET_ROLE)
        embed.add_field(
            name="Developer ロール",
            value="🟢 **付与済み (Active)**" if has_dev_role else "⚪ **未付与**",
            inline=True
        )
    else:
        embed.add_field(name="OmusuBI 連携", value="❌ **未連携** (`/link` で連携してください)", inline=False)

    ch_desc = []
    for cid, ok in eval_res["channel_permissions"].items():
        ch_desc.append(f"{'✅' if ok else '❌'} チャンネル `{cid}`")
    
    role_desc = "✅ 対象開発者ロール保有" if eval_res["has_target_role"] else "❌ 対象ロールなし"
    embed.add_field(name="Discord 権限チェック", value="\n".join(ch_desc) + f"\n{role_desc}", inline=False)

    await interaction.followup.send(embed=embed, ephemeral=True)

@bot.tree.command(name="sync", description="現在の Discord 権限を再判定し OmusuBI のロールを即時更新します")
async def cmd_sync(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)
    user = await keycloak_service.find_user_by_discord_id(interaction.user.id)
    if not user:
        await interaction.followup.send("⚠️ OmusuBI アカウントがまだ連携されていません。先に `/link` を実行してください。", ephemeral=True)
        return

    eval_res = await discord_service.evaluate_member_access(interaction.user.id)
    user_id = user["id"]
    if eval_res["eligible_for_developer_role"]:
        await keycloak_service.assign_role(user_id, settings.KEYCLOAK_TARGET_ROLE)
        msg = "✅ **同期完了**: 条件を満たしているため、OmusuBI に **Developer** ロールを付与しました！"
    else:
        await keycloak_service.revoke_role(user_id, settings.KEYCLOAK_TARGET_ROLE)
        msg = "ℹ️ **同期完了**: 対象チャンネルの閲覧権限がないため、Developer ロールを解除しました。"

    await interaction.followup.send(msg, ephemeral=True)

# ----------------- Dev Forum & Prompt Commands (Category Restricted) -----------------
@bot.tree.command(name="prompt", description="リモート対話プロンプトを送信します（開発カテゴリ専用）")
@app_commands.describe(query="プロンプト内容・質問・操作指示")
async def cmd_prompt(interaction: discord.Interaction, query: str):
    if not dev_chat_service.is_allowed_channel(interaction.channel):
        await interaction.response.send_message(
            f"⚠️ この機能は開発専用カテゴリ（ID: `{settings.DEV_CATEGORY_ID}`）内でのみ利用可能です。",
            ephemeral=True
        )
        return
    await interaction.response.defer()
    res = await dev_chat_service.handle_prompt(
        text=query,
        author_name=interaction.user.display_name,
        channel=interaction.channel,
        bot=bot
    )
    if isinstance(res, discord.Embed):
        await interaction.followup.send(embed=res)
    else:
        await interaction.followup.send(res)

@bot.tree.command(name="topic", description="開発フォーラムに新しいトピック（投稿・チャンネル）を作成します")
@app_commands.describe(
    title="投稿タイトル（自動的にチャンネル名になります）",
    content="初期プロンプトまたはトピック本文",
    tag="付与する分類タグ"
)
@app_commands.choices(tag=[
    app_commands.Choice(name="Development (開発全般)", value="dev"),
    app_commands.Choice(name="System (システム運用)", value="system"),
    app_commands.Choice(name="OmusuBI (おむすび本体)", value="omusubi"),
    app_commands.Choice(name="VPS (仮想専用サーバ)", value="vps"),
    app_commands.Choice(name="PVE (Proxmox/宅内基盤)", value="pve"),
    app_commands.Choice(name="mailcow (メール)", value="mailcow"),
    app_commands.Choice(name="keycloak (認証)", value="keycloak"),
])
async def cmd_topic(interaction: discord.Interaction, title: str, content: str, tag: app_commands.Choice[str] = None):
    if not dev_chat_service.is_allowed_channel(interaction.channel):
        await interaction.response.send_message(
            f"⚠️ この機能は開発専用カテゴリ（ID: `{settings.DEV_CATEGORY_ID}`）内でのみ利用可能です。",
            ephemeral=True
        )
        return
    await interaction.response.defer()
    tag_map = {
        "system": settings.TAG_SYSTEM_ID,
        "dev": settings.TAG_DEV_ID,
        "omusubi": settings.TAG_OMUSUBI_ID,
        "vps": settings.TAG_VPS_ID,
        "pve": settings.TAG_PVE_ID,
        "mailcow": settings.TAG_MAILCOW_ID,
        "keycloak": settings.TAG_KEYCLOAK_ID
    }
    tag_id = tag_map.get(tag.value if tag else "dev", settings.TAG_DEV_ID)

    thread = await dev_chat_service.create_forum_post(
        bot=bot,
        title=title,
        content=f"**投稿者:** {interaction.user.mention}\n\n{content}",
        tag_id=tag_id,
        author=interaction.user.display_name
    )

    # Initial assistant greeting and analysis in new thread
    res = await dev_chat_service.handle_prompt(
        text=content,
        author_name=interaction.user.display_name,
        channel=thread,
        bot=bot
    )
    if isinstance(res, discord.Embed):
        await thread.send(embed=res)
    else:
        await thread.send(res)

    await interaction.followup.send(f"✅ 新規トピックチャンネル `{title}` を作成しました: {thread.jump_url}")

# Memo Group
memo_group = app_commands.Group(name="memo", description="開発メモの登録および一覧照会")

@memo_group.command(name="add", description="新しい開発メモを登録しフォーラムにトピックを作成します")
@app_commands.describe(title="メモタイトル", content="メモの内容")
async def cmd_memo_add(interaction: discord.Interaction, title: str, content: str):
    if not dev_chat_service.is_allowed_channel(interaction.channel):
        await interaction.response.send_message(
            f"⚠️ この機能は開発専用カテゴリ（ID: `{settings.DEV_CATEGORY_ID}`）内でのみ利用可能です。",
            ephemeral=True
        )
        return
    await interaction.response.defer()
    m = dev_chat_service.add_memo(title, content, interaction.user.display_name)
    thread = await dev_chat_service.create_forum_post(
        bot=bot,
        title=f"📝 {title}",
        content=f"**開発メモ登録**\n登録者: {interaction.user.mention}\nID: `#{m['id']}`\n\n```{content}```",
        tag_id=settings.TAG_DEV_ID,
        author=interaction.user.display_name
    )
    m["thread_id"] = thread.id
    await interaction.followup.send(f"✅ 開発メモ `#{m['id']} {title}` を登録しました: {thread.jump_url}")

@memo_group.command(name="list", description="登録されている最新の開発メモ一覧を表示します")
async def cmd_memo_list(interaction: discord.Interaction):
    if not dev_chat_service.is_allowed_channel(interaction.channel):
        await interaction.response.send_message(
            f"⚠️ この機能は開発専用カテゴリ（ID: `{settings.DEV_CATEGORY_ID}`）内でのみ利用可能です。",
            ephemeral=True
        )
        return
    memos = dev_chat_service.list_memos()
    if not memos:
        await interaction.response.send_message("ℹ️ 登録されている開発メモはありません。", ephemeral=True)
        return
    embed = discord.Embed(title="📝 開発メモ一覧", color=0x3B82F6)
    for m in memos[-10:]:
        embed.add_field(name=f"#{m['id']} {m['title']} ({m['created_at']})", value=m['content'][:250], inline=False)
    await interaction.response.send_message(embed=embed)

bot.tree.add_command(memo_group)

# Secret Group
secret_group = app_commands.Group(name="secret", description="シークレット情報の安全保管および監査")

@secret_group.command(name="add", description="シークレットを安全に保管し、フォーラムに監査トピックを作成します")
@app_commands.describe(key="シークレット識別キー", value="秘密値（平文はDiscordに残りません）")
async def cmd_secret_add(interaction: discord.Interaction, key: str, value: str):
    if not dev_chat_service.is_allowed_channel(interaction.channel):
        await interaction.response.send_message(
            f"⚠️ この機能は開発専用カテゴリ（ID: `{settings.DEV_CATEGORY_ID}`）内でのみ利用可能です。",
            ephemeral=True
        )
        return
    await interaction.response.defer(ephemeral=True)
    sec = dev_chat_service.add_secret(key, value, interaction.user.display_name)
    mask = value[:3] + "••••" + value[-2:] if len(value) > 6 else "••••••••"
    thread = await dev_chat_service.create_forum_post(
        bot=bot,
        title=f"🔐 {key}",
        content=f"**シークレット登録監査ログ**\n登録者: {interaction.user.mention}\nキー: `{key}`\n値: `{mask}`\n※実値はVPS安全領域に保管されており平文は漏洩しません。",
        tag_id=settings.TAG_SYSTEM_ID,
        author=interaction.user.display_name
    )
    await interaction.followup.send(f"✅ シークレット `{key}` を安全に保存しました。\n監査トピック: {thread.jump_url}", ephemeral=True)

@secret_group.command(name="list", description="保存されているシークレットのキー一覧を表示します（マスク表示）")
async def cmd_secret_list(interaction: discord.Interaction):
    if not dev_chat_service.is_allowed_channel(interaction.channel):
        await interaction.response.send_message(
            f"⚠️ この機能は開発専用カテゴリ（ID: `{settings.DEV_CATEGORY_ID}`）内でのみ利用可能です。",
            ephemeral=True
        )
        return
    secs = dev_chat_service.list_secrets()
    if not secs:
        await interaction.response.send_message("ℹ️ 登録されているシークレットはありません。", ephemeral=True)
        return
    embed = discord.Embed(title="🔐 シークレット一覧 (マスク表示)", color=0xF59E0B)
    for s in secs:
        embed.add_field(name=f"🔑 `{s['key']}`", value=f"値: `{s['masked_value']}`\n更新: {s['updated_at']}", inline=False)
    await interaction.response.send_message(embed=embed, ephemeral=True)

bot.tree.add_command(secret_group)

# Memory Group
memory_group = app_commands.Group(name="memory", description="システムメモリー（知識ベース）管理")

@memory_group.command(name="add", description="メモリーを記録しフォーラムにトピックを作成します")
@app_commands.describe(key="メモリー識別キー", content="記録する内容")
async def cmd_memory_add(interaction: discord.Interaction, key: str, content: str):
    if not dev_chat_service.is_allowed_channel(interaction.channel):
        await interaction.response.send_message(
            f"⚠️ この機能は開発専用カテゴリ（ID: `{settings.DEV_CATEGORY_ID}`）内でのみ利用可能です。",
            ephemeral=True
        )
        return
    await interaction.response.defer()
    mem = dev_chat_service.set_memory(key, content, interaction.user.display_name)
    thread = await dev_chat_service.create_forum_post(
        bot=bot,
        title=f"🧠 {key}",
        content=f"**システムメモリー記録**\n記録者: {interaction.user.mention}\nキー: `{key}`\n\n```{content}```",
        tag_id=settings.TAG_OMUSUBI_ID,
        author=interaction.user.display_name
    )
    await interaction.followup.send(f"✅ メモリー `{key}` を記録しました: {thread.jump_url}")

@memory_group.command(name="list", description="記録されているメモリー一覧を表示します")
async def cmd_memory_list(interaction: discord.Interaction):
    if not dev_chat_service.is_allowed_channel(interaction.channel):
        await interaction.response.send_message(
            f"⚠️ この機能は開発専用カテゴリ（ID: `{settings.DEV_CATEGORY_ID}`）内でのみ利用可能です。",
            ephemeral=True
        )
        return
    mems = dev_chat_service.list_memories_dict()
    if not mems:
        await interaction.response.send_message("ℹ️ 記録されているメモリーはありません。", ephemeral=True)
        return
    embed = discord.Embed(title="🧠 システムメモリー一覧", color=0x8B5CF6)
    for k, v in list(mems.items())[-15:]:
        embed.add_field(name=f"🔑 `{k}`", value=v.get("content", "")[:200], inline=False)
    await interaction.response.send_message(embed=embed)

bot.tree.add_command(memory_group)

# SysInfo Command
@bot.tree.command(name="sysinfo", description="VPSおよびKubernetesクラスタのリアルタイム稼働状況を表示します")
async def cmd_sysinfo(interaction: discord.Interaction):
    if not dev_chat_service.is_allowed_channel(interaction.channel):
        await interaction.response.send_message(
            f"⚠️ この機能は開発専用カテゴリ（ID: `{settings.DEV_CATEGORY_ID}`）内でのみ利用可能です。",
            ephemeral=True
        )
        return
    await interaction.response.defer()
    diag = dev_chat_service.get_vps_diagnostics()
    embed = discord.Embed(title="🖥️ VPS & クラスター稼働状況", color=0x10B981)
    embed.add_field(name="⏱️ Uptime & Load", value=f"```{diag['uptime']}```", inline=False)
    embed.add_field(name="🧠 メモリ使用量", value=f"```{diag['memory']}```", inline=False)
    embed.add_field(name="💾 ディスク使用状況", value=f"```{diag['disk']}```", inline=False)
    embed.add_field(name="☸️ K3s クラスターノード", value=f"```{diag['k3s_nodes']}```", inline=False)
    embed.set_footer(text="OmusuBI Devops • Antigravity Remote Assistant")
    await interaction.followup.send(embed=embed)
