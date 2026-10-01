import os
from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent

def _load_secrets_file():
    secrets_path = BASE_DIR / 'Secrets'
    data = {}
    if secrets_path.exists():
        with open(secrets_path, 'r', encoding='utf-8', errors='ignore') as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith('#'):
                    continue
                if ':' in line:
                    k, v = line.split(':', 1)
                    k = k.strip()
                    v = v.strip()
                    if k == 'Token':
                        data['DISCORD_BOT_TOKEN'] = v
                    elif k == 'ServerID':
                        data['DISCORD_SERVER_ID'] = int(v) if v.isdigit() else 0
                    elif k == 'ChannelIDs':
                        data['DISCORD_CHANNEL_IDS'] = [int(x.strip()) for x in v.split(',') if x.strip().isdigit()]
                    elif k == 'roleID':
                        data['DISCORD_ROLE_ID'] = int(v) if v.isdigit() else 0
    return data

_secrets = _load_secrets_file()

class Settings:
    # Discord Configuration
    DISCORD_BOT_TOKEN: str = os.getenv('DISCORD_BOT_TOKEN', _secrets.get('DISCORD_BOT_TOKEN', ''))
    DISCORD_SERVER_ID: int = int(os.getenv('DISCORD_SERVER_ID', _secrets.get('DISCORD_SERVER_ID', 0)))
    DISCORD_CHANNEL_IDS: list[int] = _secrets.get('DISCORD_CHANNEL_IDS', [1498244759079358564, 1545841029088022629, 1543147319069777961])
    DISCORD_ROLE_ID: int = int(os.getenv('DISCORD_ROLE_ID', _secrets.get('DISCORD_ROLE_ID', 1299275926202224661)))
    DISCORD_INVITE_URL: str = os.getenv('DISCORD_INVITE_URL', 'https://discord.gg/nigiri-rice')

    # Restricted Dev Forum & Category Configuration
    DEV_SERVER_ID: int = int(os.getenv('DEV_SERVER_ID', '1159029710584561725'))
    DEV_CATEGORY_ID: int = int(os.getenv('DEV_CATEGORY_ID', '1555216452267544676'))
    DEV_FORUM_CHANNEL_ID: int = int(os.getenv('DEV_FORUM_CHANNEL_ID', '1555216710863429654'))
    DEV_MEMO_CHANNEL_ID: int = int(os.getenv('DEV_MEMO_CHANNEL_ID', '1555223941759377438'))
    DEV_MEMORY_CHANNEL_ID: int = int(os.getenv('DEV_MEMORY_CHANNEL_ID', '1555223943848140873'))
    DEV_SECRET_CHANNEL_ID: int = int(os.getenv('DEV_SECRET_CHANNEL_ID', '1555223945173803068'))

    # Forum Tag IDs
    TAG_SYSTEM_ID: int = 1555217049838559242
    TAG_DEV_ID: int = 1555217076090708028
    TAG_OMUSUBI_ID: int = 1555217119594160198
    TAG_VPS_ID: int = 1555217139978215515
    TAG_PVE_ID: int = 1555217154620522499
    TAG_MAILCOW_ID: int = 1555217186229059644
    TAG_KEYCLOAK_ID: int = 1555217205493506169

    # Keycloak (OmusuBI) Configuration
    KEYCLOAK_URL: str = os.getenv('KEYCLOAK_URL', 'https://sso.nigiri-rice.com')
    KEYCLOAK_REALM: str = os.getenv('KEYCLOAK_REALM', 'master')
    KEYCLOAK_ADMIN_USER: str = os.getenv('KEYCLOAK_ADMIN_USER', 'admin')
    KEYCLOAK_ADMIN_PASSWORD: str = os.getenv('KEYCLOAK_ADMIN_PASSWORD', '')
    KEYCLOAK_TARGET_ROLE: str = os.getenv('KEYCLOAK_TARGET_ROLE', 'Developer')

    # SMTP Configuration for Invitation Emails
    SMTP_HOST: str = os.getenv('SMTP_HOST', '210.131.211.17')
    SMTP_PORT: int = int(os.getenv('SMTP_PORT', '25'))
    SMTP_USER: str = os.getenv('SMTP_USER', '')
    SMTP_PASSWORD: str = os.getenv('SMTP_PASSWORD', '')
    SMTP_FROM: str = os.getenv('SMTP_FROM', 'OmusuBI Support <no-reply@nigiri-rice.com>')
    SMTP_USE_TLS: bool = os.getenv('SMTP_USE_TLS', 'false').lower() in ('true', '1')

    # Web Portal
    WEB_HOST: str = os.getenv('WEB_HOST', '0.0.0.0')
    WEB_PORT: int = int(os.getenv('WEB_PORT', '8080'))
    WEB_BASE_URL: str = os.getenv('WEB_BASE_URL', 'https://id.nigiri-rice.com/connect/discord')

settings = Settings()
