"""
Header-based auth adapter for early Phase 1.
"""
from typing import Optional

from ports.auth import AuthContext, AuthPort


class HeaderAuthAdapter(AuthPort):
    async def resolve_context(self, authorization: Optional[str], x_user_id: Optional[str]) -> AuthContext:
        # Phase 1 placeholder: use explicit x-user-id when present.
        user_id = (x_user_id or "anonymous").strip() or "anonymous"
        token = authorization.strip() if authorization else None
        return AuthContext(user_id=user_id, raw_token=token)
