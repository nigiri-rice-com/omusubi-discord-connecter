import time
import logging
from pathlib import Path
from fastapi import FastAPI, Request, Response, HTTPException, Depends
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel

from config import settings
from services.keycloak_service import keycloak_service
from services.discord_service import discord_service
from services.invitation_service import invitation_service
from bot.discord_bot import LINKING_CODES
from web.auth import (
    create_session_token,
    get_current_user_optional,
    get_current_user,
    require_admin_user
)

logger = logging.getLogger("OmusuBI.WebApp")

BASE_DIR = Path(__file__).resolve().parent

app = FastAPI(title="OmusuBI Discord Connecter Portal")
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

class LoginRequest(BaseModel):
    username: str
    password: str

class CodeOnlyRequest(BaseModel):
    code: str

@app.api_route("/", methods=["GET", "HEAD"], response_class=HTMLResponse)
async def index_page(request: Request):
    user_session = get_current_user_optional(request)
    if not user_session:
        # Show login page
        return templates.TemplateResponse(
            request=request,
            name="login.html",
            context={
                "base_url": settings.WEB_BASE_URL
            }
        )

    # User is logged in: fetch fresh attributes from Keycloak
    user_id = user_session["user_id"]
    kc_user = await keycloak_service.get_user(user_id)
    if not kc_user:
        # User not found in Keycloak anymore, reset session
        resp = templates.TemplateResponse(request=request, name="login.html", context={"base_url": settings.WEB_BASE_URL})
        resp.delete_cookie("omusubi_session")
        return resp

    d_info = await keycloak_service.get_user_discord_info(kc_user)
    discord_id = d_info.get("discord_id")
    discord_username = d_info.get("discord_username")

    is_admin = await keycloak_service.is_user_admin(user_id)
    # Refresh is_admin in session if changed
    user_session["is_admin"] = is_admin

    is_linked = bool(discord_id)
    eval_res = None
    has_role = False

    if is_linked:
        eval_res = await discord_service.evaluate_member_access(discord_id)
        has_role = await keycloak_service.user_has_role(user_id, settings.KEYCLOAK_TARGET_ROLE)

    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={
            "user": user_session,
            "username": kc_user["username"],
            "email": kc_user.get("email", ""),
            "is_admin": is_admin,
            "is_linked": is_linked,
            "discord_user_id": discord_id,
            "discord_username": discord_username,
            "eval_res": eval_res,
            "has_developer_role": has_role,
            "base_url": settings.WEB_BASE_URL,
            "guild_id": settings.DISCORD_SERVER_ID
        }
    )

@app.post("/api/auth/login")
async def api_login(req: LoginRequest, response: Response):
    username = req.username.strip()
    password = req.password.strip()

    user = await keycloak_service.verify_user_credentials(username, password)
    if not user:
        return {"success": False, "detail": "OmusuBI のユーザー名またはパスワードが正しくありません。"}

    user_id = user["id"]
    is_admin = await keycloak_service.is_user_admin(user_id)

    session_token = create_session_token({
        "user_id": user_id,
        "username": user["username"],
        "email": user.get("email", ""),
        "is_admin": is_admin
    })

    response.set_cookie(
        key="omusubi_session",
        value=session_token,
        max_age=86400 * 7,
        httponly=True,
        samesite="lax",
        secure=True
    )

    return {
        "success": True,
        "username": user["username"],
        "is_admin": is_admin
    }

@app.post("/api/auth/logout")
async def api_logout(response: Response):
    response.delete_cookie("omusubi_session")
    return {"success": True}

@app.post("/api/link")
async def api_link(req: CodeOnlyRequest, request: Request):
    user_session = get_current_user_optional(request)
    if not user_session:
        return {"success": False, "detail": "ログインセッションが切断されました。再ログインしてください。"}
    user_id = user_session["user_id"]

    code = req.code.strip().upper()
    now = time.time()
    code_data = LINKING_CODES.get(code)
    if not code_data or code_data["expires_at"] < now:
        return {"success": False, "detail": "認証コードが無効または有効期限切れです。Discord で /link を再実行してください。"}

    discord_user_id = code_data["discord_user_id"]
    discord_username = code_data["discord_username"]

    # Update user attributes in Keycloak
    await keycloak_service.update_user_attributes(user_id, {
        "discord_id": discord_user_id,
        "discord_username": discord_username,
        "discord_linked_at": str(now)
    })

    # Remove used code
    LINKING_CODES.pop(code, None)

    # Evaluate Discord permissions
    eval_res = await discord_service.evaluate_member_access(discord_user_id)
    has_role = False
    if eval_res["eligible_for_developer_role"]:
        await keycloak_service.assign_role(user_id, settings.KEYCLOAK_TARGET_ROLE)
        has_role = True
    else:
        has_role = await keycloak_service.user_has_role(user_id, settings.KEYCLOAK_TARGET_ROLE)

    return {
        "success": True,
        "username": user_session["username"],
        "discord_user_id": discord_user_id,
        "discord_username": discord_username,
        "in_guild": eval_res["in_guild"],
        "eligible": eval_res["eligible_for_developer_role"],
        "has_developer_role": has_role,
        "channel_permissions": eval_res["channel_permissions"]
    }

@app.post("/api/sync")
async def api_sync(request: Request):
    user_session = get_current_user_optional(request)
    if not user_session:
        return {"success": False, "detail": "ログインセッションが切断されました。再ログインしてください。"}
    user_id = user_session["user_id"]

    user = await keycloak_service.get_user(user_id)
    if not user:
        return {"success": False, "detail": "ユーザーが見つかりません。"}

    d_info = await keycloak_service.get_user_discord_info(user)
    discord_user_id = d_info.get("discord_id")
    discord_username = d_info.get("discord_username") or ""
    if not discord_user_id:
        return {"success": False, "detail": "Discord アカウントが連携されていません。"}

    eval_res = await discord_service.evaluate_member_access(discord_user_id)

    if eval_res["eligible_for_developer_role"]:
        await keycloak_service.assign_role(user_id, settings.KEYCLOAK_TARGET_ROLE)
        has_role = True
    else:
        await keycloak_service.revoke_role(user_id, settings.KEYCLOAK_TARGET_ROLE)
        has_role = False

    return {
        "success": True,
        "username": user["username"],
        "discord_user_id": discord_user_id,
        "discord_username": discord_username,
        "in_guild": eval_res["in_guild"],
        "eligible": eval_res["eligible_for_developer_role"],
        "has_developer_role": has_role,
        "channel_permissions": eval_res["channel_permissions"]
    }

@app.post("/api/unlink")
async def api_unlink(request: Request):
    user_session = get_current_user_optional(request)
    if not user_session:
        return {"success": False, "detail": "ログインセッションが切断されました。再ログインしてください。"}
    user_id = user_session["user_id"]

    await keycloak_service.revoke_role(user_id, settings.KEYCLOAK_TARGET_ROLE)
    await keycloak_service.update_user_attributes(user_id, {
        "discord_id": "",
        "discord_username": ""
    })
    return {"success": True}

@app.post("/api/admin/invite-unjoined")
async def api_admin_invite_unjoined(request: Request):
    user_session = get_current_user_optional(request)
    if not user_session or not user_session.get("is_admin"):
        return {"success": False, "detail": "この機能の実行には管理者権限が必要です。"}

    res = await invitation_service.scan_and_invite_unjoined_members()
    return {"success": True, **res}

@app.get("/health")
async def health():
    return {"status": "ok"}

from services.dev_chat_service import dev_chat_service
import discord

class BridgeDispatchRequest(BaseModel):
    prompt: str
    channel_id: int
    author: str = "Antigravity Bridge Tester"

@app.post("/api/bridge/dispatch")
async def bridge_dispatch(req: BridgeDispatchRequest):
    task_id = dev_chat_service.add_bridge_task(
        prompt=req.prompt,
        channel_id=req.channel_id,
        message_id=0,
        author=req.author
    )
    return {"status": "ok", "task_id": task_id}

class BridgeResultRequest(BaseModel):
    task_id: str
    output: str
    success: bool = True

@app.get("/api/bridge/poll")
async def bridge_poll():
    task = dev_chat_service.get_next_bridge_task()
    return {"task": task, "online": True}

@app.post("/api/bridge/result")
async def bridge_result(req: BridgeResultRequest):
    task = dev_chat_service.pop_bridge_task(req.task_id)
    if not task:
        return {"status": "not_found"}

    from bot.discord_bot import bot

    channel = bot.get_channel(task["channel_id"])
    if not channel:
        try:
            channel = await bot.fetch_channel(task["channel_id"])
        except Exception:
            pass

    if channel:
        output_text = req.output.strip() if req.output else "（出力なし）"
        try:
            msg = await channel.fetch_message(task["message_id"])
            if msg:
                await msg.add_reaction("✅")
        except Exception:
            pass

        if len(output_text) <= 1900:
            embed = discord.Embed(
                title="💻 HOME-DESKTOP (Antigravity PC) 実行結果",
                description=f"```{output_text}```",
                color=0x10B981
            )
            embed.set_footer(text=f"Task: {task['id']} • Executed on HOME-DESKTOP")
            await channel.send(embed=embed)
        else:
            chunks = [output_text[i:i+1900] for i in range(0, len(output_text), 1900)]
            for idx, c in enumerate(chunks[:5]):
                embed = discord.Embed(
                    title=f"💻 HOME-DESKTOP (Antigravity PC) 実行結果 ({idx+1}/{min(len(chunks), 5)})",
                    description=f"```{c}```",
                    color=0x10B981
                )
                await channel.send(embed=embed)

    return {"status": "ok"}
