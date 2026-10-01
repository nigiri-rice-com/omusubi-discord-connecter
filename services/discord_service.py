import logging
import discord
from config import settings

logger = logging.getLogger('OmusuBI.DiscordService')

class DiscordService:
    def __init__(self, bot: discord.Client | None = None):
        self.bot = bot
        self.server_id = settings.DISCORD_SERVER_ID
        self.channel_ids = settings.DISCORD_CHANNEL_IDS
        self.role_id = settings.DISCORD_ROLE_ID

    def set_bot(self, bot: discord.Client):
        self.bot = bot

    def get_guild(self) -> discord.Guild | None:
        if not self.bot:
            return None
        return self.bot.get_guild(self.server_id)

    async def fetch_member(self, user_id: int | str) -> discord.Member | None:
        guild = self.get_guild()
        if not guild:
            return None
        uid = int(user_id)
        member = guild.get_member(uid)
        if member:
            return member
        try:
            return await guild.fetch_member(uid)
        except (discord.NotFound, discord.HTTPException):
            return None

    async def check_channel_view_permission(self, member: discord.Member, channel_id: int) -> bool:
        channel = member.guild.get_channel(channel_id)
        if not channel:
            try:
                channel = await member.guild.fetch_channel(channel_id)
            except Exception:
                return False
        if not channel:
            return False

        perms = channel.permissions_for(member)
        return perms.view_channel

    async def evaluate_member_access(self, user_id: int | str) -> dict:
        member = await self.fetch_member(user_id)
        if not member:
            return {
                'in_guild': False,
                'has_target_role': False,
                'channel_permissions': {},
                'can_view_any_channel': False,
                'can_view_all_channels': False,
                'eligible_for_developer_role': False,
                'member_name': None,
                'avatar_url': None
            }

        # Check target role
        has_role = any(r.id == self.role_id for r in member.roles)

        # Check target channels
        channel_perms = {}
        for cid in self.channel_ids:
            can_view = await self.check_channel_view_permission(member, cid)
            channel_perms[str(cid)] = can_view

        can_view_any = any(channel_perms.values()) if channel_perms else False
        can_view_all = all(channel_perms.values()) if channel_perms else False

        # Eligible if member has specific role OR has viewing permissions to target channels
        eligible = has_role or can_view_any

        return {
            'in_guild': True,
            'has_target_role': has_role,
            'channel_permissions': channel_perms,
            'can_view_any_channel': can_view_any,
            'can_view_all_channels': can_view_all,
            'eligible_for_developer_role': eligible,
            'member_name': str(member),
            'display_name': member.display_name,
            'avatar_url': str(member.display_avatar.url) if member.display_avatar else None
        }

    async def create_invite(self, max_age: int = 86400 * 7) -> str:
        guild = self.get_guild()
        if not guild:
            return settings.DISCORD_INVITE_URL

        # Find a public text channel
        target_channel = None
        for ch in guild.text_channels:
            if ch.permissions_for(guild.default_role).view_channel:
                target_channel = ch
                break
        if not target_channel and guild.text_channels:
            target_channel = guild.text_channels[0]

        if target_channel:
            try:
                invite = await target_channel.create_invite(max_age=max_age, unique=False, reason='OmusuBI Onboarding')
                return invite.url
            except Exception as e:
                logger.warning(f'Failed to create invite: {e}')

        return settings.DISCORD_INVITE_URL

    async def send_dm_invite(self, user_id: int | str, invite_url: str, custom_message: str | None = None) -> bool:
        if not self.bot:
            return False
        uid = int(user_id)
        user = self.bot.get_user(uid)
        if not user:
            try:
                user = await self.bot.fetch_user(uid)
            except Exception as e:
                logger.warning(f'Failed to fetch user {uid} for DM: {e}')
                return False

        msg = custom_message or (
            f'こんにちは！**OmusuBI (Boundless Identity)** 運営チームです。\n\n'
            f'あなたのアカウントに開発者ロールが付与されました！\n'
            f'開発者用 Discord サーバーへ以下のリンクよりご参加ください：\n'
            f'👉 **{invite_url}**\n\n'
            f'※ 参加後、自動的に権限が同期されます。'
        )

        try:
            dm_channel = await user.create_dm()
            await dm_channel.send(msg)
            logger.info(f'Sent Discord DM invite to user {uid}')
            return True
        except discord.Forbidden:
            logger.warning(f'Cannot send DM to user {uid} (DMs disabled by user)')
            return False
        except Exception as e:
            logger.error(f'Error sending DM to {uid}: {e}')
            return False

discord_service = DiscordService()
