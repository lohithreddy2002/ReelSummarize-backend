"""
Auth port for resolving request auth context.
"""
from dataclasses import dataclass
from typing import Optional, Protocol


@dataclass
class AuthContext:
    user_id: str
    raw_token: Optional[str] = None


class AuthPort(Protocol):
    async def resolve_context(self, authorization: Optional[str], x_user_id: Optional[str]) -> AuthContext:
        ...
