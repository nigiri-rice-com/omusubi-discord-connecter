import time
import json
import hmac
import hashlib
import base64
from fastapi import Request, HTTPException
from config import settings

SECRET_KEY = settings.DISCORD_BOT_TOKEN[:32].encode()

def create_session_token(user_data: dict, expires_in: int = 86400 * 7) -> str:
    payload = {
        **user_data,
        "exp": int(time.time()) + expires_in
    }
    raw_bytes = json.dumps(payload, separators=(',', ':')).encode('utf-8')
    b64_payload = base64.urlsafe_b64encode(raw_bytes).decode('utf-8')
    sig = hmac.new(SECRET_KEY, b64_payload.encode('utf-8'), hashlib.sha256).hexdigest()
    return f"{b64_payload}.{sig}"

def verify_session_token(token: str) -> dict | None:
    if not token or "." not in token:
        return None
    try:
        b64_payload, sig = token.split(".", 1)
        expected_sig = hmac.new(SECRET_KEY, b64_payload.encode('utf-8'), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(sig, expected_sig):
            return None
        raw_bytes = base64.urlsafe_b64decode(b64_payload.encode('utf-8'))
        payload = json.loads(raw_bytes.decode('utf-8'))
        if payload.get("exp", 0) < time.time():
            return None
        return payload
    except Exception:
        return None

def get_current_user_optional(request: Request) -> dict | None:
    cookie = request.cookies.get("omusubi_session")
    if not cookie:
        return None
    return verify_session_token(cookie)

def get_current_user(request: Request) -> dict:
    user = get_current_user_optional(request)
    if not user:
        raise HTTPException(status_code=401, detail="ログインが必要です。再度ログインしてください。")
    return user

def require_admin_user(request: Request) -> dict:
    user = get_current_user(request)
    if not user.get("is_admin"):
        raise HTTPException(status_code=403, detail="この機能の実行には管理者権限が必要です。")
    return user
