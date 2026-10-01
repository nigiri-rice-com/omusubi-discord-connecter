import asyncio
import logging
import uvicorn
from config import settings
from bot.discord_bot import bot
from web.app import app

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("OmusuBI.Main")

async def run_web():
    config = uvicorn.Config(app, host=settings.WEB_HOST, port=settings.WEB_PORT, log_level="info")
    server = uvicorn.Server(config)
    logger.info(f"Starting OmusuBI Service Linking Web Portal on {settings.WEB_HOST}:{settings.WEB_PORT}")
    await server.serve()

async def run_bot():
    token = settings.DISCORD_BOT_TOKEN
    if not token:
        logger.error("No DISCORD_BOT_TOKEN configured. Discord bot will not start.")
        return
    logger.info("Starting OmusuBI Discord Bot...")
    try:
        await bot.start(token)
    except Exception as e:
        logger.error(f"Error running Discord Bot: {e}")

from services.keycloak_service import keycloak_service
from services.discord_service import discord_service
from services.invitation_service import invitation_service

async def run_sync_worker():
    logger.info("Starting OmusuBI Discord Role & Invitation Sync Worker...")
    await asyncio.sleep(10)
    while True:
        try:
            users = await keycloak_service.get_all_users(max_count=500)
            for u in users:
                user_id = u["id"]
                d_info = await keycloak_service.get_user_discord_info(u)
                d_id = d_info.get("discord_id")
                if not d_id:
                    continue

                eval_res = await discord_service.evaluate_member_access(d_id)
                has_role = await keycloak_service.user_has_role(user_id, settings.KEYCLOAK_TARGET_ROLE)

                if eval_res["eligible_for_developer_role"] and not has_role:
                    logger.info(f"Auto-granting {settings.KEYCLOAK_TARGET_ROLE} to {u['username']} (Discord ID: {d_id})")
                    await keycloak_service.assign_role(user_id, settings.KEYCLOAK_TARGET_ROLE)
                elif not eval_res["eligible_for_developer_role"] and has_role:
                    logger.info(f"Auto-revoking {settings.KEYCLOAK_TARGET_ROLE} from {u['username']} (Discord ID: {d_id})")
                    await keycloak_service.revoke_role(user_id, settings.KEYCLOAK_TARGET_ROLE)

            await invitation_service.scan_and_invite_unjoined_members()
        except Exception as e:
            logger.error(f"Error in background sync worker: {e}")

        await asyncio.sleep(60)

async def main():
    await asyncio.gather(
        run_web(),
        run_bot(),
        run_sync_worker()
    )

if __name__ == "__main__":
    asyncio.run(main())

