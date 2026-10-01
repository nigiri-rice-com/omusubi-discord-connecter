import time
import logging
import httpx
from config import settings

logger = logging.getLogger('OmusuBI.Keycloak')

class KeycloakService:
    def __init__(self):
        self.base_url = settings.KEYCLOAK_URL.rstrip('/')
        self.realm = settings.KEYCLOAK_REALM
        self.admin_user = settings.KEYCLOAK_ADMIN_USER
        self.admin_password = settings.KEYCLOAK_ADMIN_PASSWORD
        self._token = None
        self._token_expires_at = 0
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) OmusuBI-Discord-Connecter/1.0'
        }

    async def get_admin_token(self) -> str:
        if self._token and time.time() < self._token_expires_at - 30:
            return self._token

        token_url = f'{self.base_url}/realms/master/protocol/openid-connect/token'
        data = {
            'client_id': 'admin-cli',
            'username': self.admin_user,
            'password': self.admin_password,
            'grant_type': 'password'
        }

        async with httpx.AsyncClient(verify=False, headers=self.headers, timeout=15.0) as client:
            resp = await client.post(token_url, data=data)
            if resp.status_code != 200:
                logger.error(f'Failed to obtain admin token: {resp.status_code} {resp.text}')
                raise RuntimeError(f'Keycloak admin auth failed: {resp.status_code}')
            
            payload = resp.json()
            self._token = payload['access_token']
            self._token_expires_at = time.time() + payload.get('expires_in', 60)
            return self._token

    async def verify_user_credentials(self, username: str, password: str) -> dict | None:
        token_url = f'{self.base_url}/realms/{self.realm}/protocol/openid-connect/token'
        data = {
            'client_id': 'admin-cli',
            'username': username,
            'password': password,
            'grant_type': 'password'
        }
        async with httpx.AsyncClient(verify=False, headers=self.headers, timeout=15.0) as client:
            resp = await client.post(token_url, data=data)
            if resp.status_code == 200:
                user = await self.find_user_by_username(username)
                return user
            return None

    async def _auth_headers(self) -> dict:
        token = await self.get_admin_token()
        return {
            **self.headers,
            'Authorization': f'Bearer {token}',
            'Content-Type': 'application/json'
        }

    async def get_user(self, user_id: str) -> dict | None:
        url = f'{self.base_url}/admin/realms/{self.realm}/users/{user_id}'
        headers = await self._auth_headers()
        async with httpx.AsyncClient(verify=False, headers=headers, timeout=15.0) as client:
            resp = await client.get(url)
            if resp.status_code == 200:
                return resp.json()
            return None

    async def find_user_by_username(self, username: str) -> dict | None:
        url = f'{self.base_url}/admin/realms/{self.realm}/users?username={username}&exact=true'
        headers = await self._auth_headers()
        async with httpx.AsyncClient(verify=False, headers=headers, timeout=15.0) as client:
            resp = await client.get(url)
            if resp.status_code == 200:
                users = resp.json()
                if users:
                    return users[0]
            return None

    async def find_user_by_email(self, email: str) -> dict | None:
        url = f'{self.base_url}/admin/realms/{self.realm}/users?email={email}&exact=true'
        headers = await self._auth_headers()
        async with httpx.AsyncClient(verify=False, headers=headers, timeout=15.0) as client:
            resp = await client.get(url)
            if resp.status_code == 200:
                users = resp.json()
                if users:
                    return users[0]
            return None

    async def find_user_by_discord_id(self, discord_id: str | int) -> dict | None:
        url = f'{self.base_url}/admin/realms/{self.realm}/users?q=discord_id:{discord_id}'
        headers = await self._auth_headers()
        async with httpx.AsyncClient(verify=False, headers=headers, timeout=15.0) as client:
            resp = await client.get(url)
            if resp.status_code == 200:
                users = resp.json()
                if users:
                    return users[0]
        # Fallback scan if query filter is not supported by DB backend
        all_users = await self.get_all_users()
        for u in all_users:
            attrs = u.get('attributes', {})
            d_ids = attrs.get('discord_id', [])
            if str(discord_id) in [str(x) for x in d_ids]:
                return u
        return None

    async def get_all_users(self, max_count: int = 500) -> list[dict]:
        url = f'{self.base_url}/admin/realms/{self.realm}/users?max={max_count}'
        headers = await self._auth_headers()
        async with httpx.AsyncClient(verify=False, headers=headers, timeout=20.0) as client:
            resp = await client.get(url)
            if resp.status_code == 200:
                return resp.json()
            return []

    async def get_role_by_name(self, role_name: str) -> dict | None:
        url = f'{self.base_url}/admin/realms/{self.realm}/roles/{role_name}'
        headers = await self._auth_headers()
        async with httpx.AsyncClient(verify=False, headers=headers, timeout=15.0) as client:
            resp = await client.get(url)
            if resp.status_code == 200:
                return resp.json()
            return None

    async def get_user_roles(self, user_id: str) -> list[dict]:
        url = f'{self.base_url}/admin/realms/{self.realm}/users/{user_id}/role-mappings/realm'
        headers = await self._auth_headers()
        async with httpx.AsyncClient(verify=False, headers=headers, timeout=15.0) as client:
            resp = await client.get(url)
            if resp.status_code == 200:
                return resp.json()
            return []

    ADMIN_ROLES = {"admin", "cnt-platform-admin", "iam-admin", "su", "realm-admin"}

    async def is_user_admin(self, user_id: str) -> bool:
        roles = await self.get_user_roles(user_id)
        role_names = {r.get('name') for r in roles}
        return bool(role_names.intersection(self.ADMIN_ROLES))

    async def user_has_role(self, user_id: str, role_name: str) -> bool:
        roles = await self.get_user_roles(user_id)
        return any(r.get('name') == role_name for r in roles)

    async def assign_role(self, user_id: str, role_name: str) -> bool:
        role = await self.get_role_by_name(role_name)
        if not role:
            logger.error(f'Role {role_name} not found in realm {self.realm}')
            return False

        url = f'{self.base_url}/admin/realms/{self.realm}/users/{user_id}/role-mappings/realm'
        headers = await self._auth_headers()
        async with httpx.AsyncClient(verify=False, headers=headers, timeout=15.0) as client:
            resp = await client.post(url, json=[role])
            if resp.status_code in (200, 204):
                logger.info(f'Assigned role {role_name} to user {user_id}')
                return True
            logger.error(f'Failed to assign role {role_name}: {resp.status_code} {resp.text}')
            return False

    async def revoke_role(self, user_id: str, role_name: str) -> bool:
        role = await self.get_role_by_name(role_name)
        if not role:
            return False

        url = f'{self.base_url}/admin/realms/{self.realm}/users/{user_id}/role-mappings/realm'
        headers = await self._auth_headers()
        async with httpx.AsyncClient(verify=False, headers=headers, timeout=15.0) as client:
            resp = await client.request('DELETE', url, json=[role])
            if resp.status_code in (200, 204):
                logger.info(f'Revoked role {role_name} from user {user_id}')
                return True
            return False

    async def update_user_attributes(self, user_id: str, attributes_to_merge: dict) -> bool:
        user = await self.get_user(user_id)
        if not user:
            return False

        current_attrs = user.get('attributes', {})
        for k, v in attributes_to_merge.items():
            if isinstance(v, list):
                current_attrs[k] = v
            else:
                current_attrs[k] = [str(v)]

        user['attributes'] = current_attrs
        url = f'{self.base_url}/admin/realms/{self.realm}/users/{user_id}'
        headers = await self._auth_headers()
        async with httpx.AsyncClient(verify=False, headers=headers, timeout=15.0) as client:
            resp = await client.put(url, json=user)
            return resp.status_code in (200, 204)

    async def get_users_with_role(self, role_name: str) -> list[dict]:
        url = f'{self.base_url}/admin/realms/{self.realm}/roles/{role_name}/users'
        headers = await self._auth_headers()
        async with httpx.AsyncClient(verify=False, headers=headers, timeout=20.0) as client:
            resp = await client.get(url)
            if resp.status_code == 200:
                return resp.json()
            return []

    async def get_user_federated_identities(self, user_id: str) -> list[dict]:
        url = f'{self.base_url}/admin/realms/{self.realm}/users/{user_id}/federated-identity'
        headers = await self._auth_headers()
        async with httpx.AsyncClient(verify=False, headers=headers, timeout=15.0) as client:
            resp = await client.get(url)
            if resp.status_code == 200:
                return resp.json()
            return []

    async def get_user_discord_info(self, user: dict) -> dict:
        attrs = user.get('attributes', {})
        d_ids = attrs.get('discord_id', [])
        d_usernames = attrs.get('discord_username', [])
        d_id = d_ids[0] if d_ids and d_ids[0] else None
        d_username = d_usernames[0] if d_usernames else None

        if d_id:
            return {'discord_id': str(d_id), 'discord_username': d_username, 'via_federated': False}

        feds = await self.get_user_federated_identities(user['id'])
        for fed in feds:
            if fed.get('identityProvider') == 'discord':
                fid = str(fed.get('userId'))
                fuser = fed.get('userName')
                await self.update_user_attributes(user['id'], {
                    'discord_id': fid,
                    'discord_username': fuser or ''
                })
                return {'discord_id': fid, 'discord_username': fuser, 'via_federated': True}

        return {'discord_id': None, 'discord_username': None, 'via_federated': False}

keycloak_service = KeycloakService()
