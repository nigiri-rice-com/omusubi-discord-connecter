import time
import logging
from datetime import datetime
import aiosmtplib
from email.message import EmailMessage

from config import settings
from services.keycloak_service import keycloak_service
from services.discord_service import discord_service

logger = logging.getLogger("OmusuBI.InvitationService")

class InvitationService:
    def __init__(self):
        self.cooldown_seconds = 86400 * 3  # 3 days cooldown

    async def send_invite_email(self, to_email: str, recipient_name: str, invite_url: str) -> bool:
        msg = EmailMessage()
        msg["Subject"] = "【OmusuBI】開発者向け Discord サーバーへのご案内"
        msg["From"] = settings.SMTP_FROM
        msg["To"] = to_email

        plain_text = f"""{recipient_name} 様

いつも OmusuBI をご利用いただきありがとうございます。

あなたのアカウントに開発者権限が付与されました。
つきましては、開発チームの Discord サーバーへご案内いたします。

以下の招待リンクよりサーバーへご参加ください：
{invite_url}

※ 本リンクからご参加いただくと、OmusuBI と連動して各種開発リソースへのアクセス権限が自動付与されます。
※ 本メールにお心当たりがない場合は、お手数ですが本メールを破棄してください。

-----------------------------------------
OmusuBI (Boundless Identity)
https://id.nigiri-rice.com
-----------------------------------------
"""

        html_text = f"""<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <style>
    body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background: #0f172a; color: #e2e8f0; padding: 24px; }}
    .card {{ max-width: 560px; margin: 0 auto; background: #1e293b; border-radius: 12px; padding: 32px; border: 1px solid #334155; }}
    .badge {{ display: inline-block; padding: 4px 12px; background: #6366f1; color: #fff; border-radius: 9999px; font-size: 12px; font-weight: bold; margin-bottom: 16px; }}
    h2 {{ color: #ffffff; margin-top: 0; font-size: 22px; }}
    p {{ line-height: 1.6; color: #94a3b8; font-size: 15px; }}
    .btn {{ display: inline-block; margin: 24px 0; padding: 14px 28px; background: #5865F2; color: #ffffff !important; text-decoration: none; border-radius: 8px; font-weight: bold; font-size: 16px; }}
    .footer {{ margin-top: 32px; border-top: 1px solid #334155; padding-top: 16px; font-size: 12px; color: #64748b; }}
  </style>
</head>
<body>
  <div class="card">
    <div class="badge">🍙 OmusuBI Identity Orchestrator</div>
    <h2>Discord サーバーへのご案内</h2>
    <p>{recipient_name} 様</p>
    <p>あなたのアカウントに <strong>Developer (開発者)</strong> ロールが付与されました。<br>
    開発チーム用の公式 Discord サーバーへ参加し、連携を完了してください。</p>
    
    <div style="text-align: center;">
      <a href="{invite_url}" class="btn" target="_blank">Discord サーバーに参加する</a>
    </div>

    <p style="font-size: 13px; color: #64748b;">
      招待リンク: <a href="{invite_url}" style="color: #818cf8;">{invite_url}</a>
    </p>
    <div class="footer">
      本メールは OmusuBI プラットフォームより自動配信されています。<br>
      © nigiri-rice.com All rights reserved.
    </div>
  </div>
</body>
</html>
"""
        msg.set_content(plain_text)
        msg.add_alternative(html_text, subtype="html")

        try:
            await aiosmtplib.send(
                msg,
                hostname=settings.SMTP_HOST,
                port=settings.SMTP_PORT,
                username=settings.SMTP_USER or None,
                password=settings.SMTP_PASSWORD or None,
                start_tls=settings.SMTP_USE_TLS
            )
            logger.info(f"Sent invite email to {to_email}")
            return True
        except Exception as e:
            logger.error(f"Failed to send email to {to_email}: {e}")
            return False

    async def scan_and_invite_unjoined_members(self, role_name: str | None = None) -> dict:
        target_role = role_name or settings.KEYCLOAK_TARGET_ROLE
        users = await keycloak_service.get_users_with_role(target_role)

        results = {
            "target_role": target_role,
            "total_role_users": len(users),
            "linked_users": 0,
            "already_in_guild": 0,
            "in_cooldown": 0,
            "invited_count": 0,
            "dm_sent": 0,
            "email_sent": 0,
            "details": []
        }

        invite_url = await discord_service.create_invite()
        now = time.time()

        for u in users:
            d_info = await keycloak_service.get_user_discord_info(u)
            discord_id = d_info.get("discord_id")
            if not discord_id:
                continue

            results["linked_users"] += 1
            username = u.get("username")
            email = u.get("email")
            display_name = f"{u.get('firstName', '')} {u.get('lastName', '')}".strip() or username

            # Check if user is in Discord guild
            member = await discord_service.fetch_member(discord_id)
            if member:
                results["already_in_guild"] += 1
                continue

            # Check cooldown
            last_sent_list = attrs.get("discord_invite_last_sent", [])
            if last_sent_list:
                try:
                    last_sent_ts = float(last_sent_list[0])
                    if now - last_sent_ts < self.cooldown_seconds:
                        results["in_cooldown"] += 1
                        continue
                except ValueError:
                    pass

            # User is NOT in guild and NOT in cooldown -> Send Invites!
            dm_ok = await discord_service.send_dm_invite(discord_id, invite_url)
            email_ok = False
            if email:
                email_ok = await self.send_invite_email(email, display_name, invite_url)

            if dm_ok or email_ok:
                results["invited_count"] += 1
                if dm_ok:
                    results["dm_sent"] += 1
                if email_ok:
                    results["email_sent"] += 1

                # Update cooldown timestamp in Keycloak
                await keycloak_service.update_user_attributes(u["id"], {
                    "discord_invite_last_sent": str(now)
                })

                results["details"].append({
                    "username": username,
                    "email": email,
                    "discord_id": discord_id,
                    "dm_sent": dm_ok,
                    "email_sent": email_ok
                })

        return results

invitation_service = InvitationService()
