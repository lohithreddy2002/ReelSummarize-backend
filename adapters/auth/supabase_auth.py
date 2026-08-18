"""
Supabase auth adapter that resolves user identity from bearer tokens.
"""
from typing import Optional

import httpx

from ports.auth import AuthContext, AuthPort


class SupabaseAuthAdapter(AuthPort):
    def __init__(
        self,
        supabase_url: str,
        supabase_api_key: str,
        *,
        allow_header_fallback: bool = True,
    ) -> None:
        self._user_endpoint = f"{supabase_url.rstrip('/')}/auth/v1/user"
        self._api_key = supabase_api_key
        self._allow_header_fallback = allow_header_fallback

    async def resolve_context(self, authorization: Optional[str], x_user_id: Optional[str]) -> AuthContext:
        token = self._extract_bearer_token(authorization)
        if token:
            user_id = await self._resolve_user_id_from_token(token)
            if user_id:
                return AuthContext(user_id=user_id, raw_token=token)

        if self._allow_header_fallback:
            user_id = (x_user_id or "anonymous").strip() or "anonymous"
            return AuthContext(user_id=user_id, raw_token=token)

        return AuthContext(user_id="anonymous", raw_token=token)

    async def _resolve_user_id_from_token(self, token: str) -> Optional[str]:
        headers = {
            "Authorization": f"Bearer {token}",
            "apikey": self._api_key,
        }
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(self._user_endpoint, headers=headers)
            if response.status_code != 200:
                return None
            payload = response.json()
            user_id = payload.get("id")
            if isinstance(user_id, str) and user_id.strip():
                return user_id.strip()
            return None
        except Exception:
            return None

    @staticmethod
    def _extract_bearer_token(authorization: Optional[str]) -> Optional[str]:
        if not authorization:
            return None
        value = authorization.strip()
        if not value:
            return None
        if value.lower().startswith("bearer "):
            token = value[7:].strip()
            return token or None
        return None
