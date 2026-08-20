"""
Composition root for selecting provider implementations by environment.
"""
import os

from adapters.persistence.in_memory import InMemoryPersistenceAdapter
from adapters.persistence.supabase import SupabasePersistenceAdapter
from adapters.auth.header_auth import HeaderAuthAdapter
from adapters.auth.supabase_auth import SupabaseAuthAdapter
from adapters.storage.in_memory import InMemoryStorageAdapter
from adapters.storage.supabase_storage import SupabaseStorageAdapter
from ports.auth import AuthPort
from ports.persistence import PersistencePort
from ports.storage import StoragePort


_persistence_singleton: PersistencePort | None = None
_auth_singleton: AuthPort | None = None
_storage_singleton: StoragePort | None = None


def _env_clean(name: str, default: str = "") -> str:
    """Strip whitespace and optional surrounding quotes from env (common .env mistakes)."""
    raw = os.getenv(name, default)
    if not raw:
        return ""
    s = raw.strip()
    if len(s) >= 2 and s[0] == s[-1] and s[0] in "\"'":
        s = s[1:-1].strip()
    return s


def get_persistence() -> PersistencePort:
    global _persistence_singleton
    if _persistence_singleton is not None:
        return _persistence_singleton

    provider = os.getenv("PERSISTENCE_PROVIDER", "inmemory").lower()
    if provider == "supabase":
        supabase_url = _env_clean("SUPABASE_URL")
        supabase_service_key = _env_clean("SUPABASE_SECRET_KEY")
        if supabase_url and supabase_service_key:
            _persistence_singleton = SupabasePersistenceAdapter(supabase_url, supabase_service_key)
            return _persistence_singleton

    _persistence_singleton = InMemoryPersistenceAdapter()
    return _persistence_singleton


def get_auth() -> AuthPort:
    global _auth_singleton
    if _auth_singleton is not None:
        return _auth_singleton

    provider = os.getenv("AUTH_PROVIDER", "header").lower()
    if provider == "supabase":
        supabase_url = _env_clean("SUPABASE_URL")
        supabase_api_key = _env_clean("SUPABASE_PUBLISHABLE_KEY") or _env_clean("SUPABASE_SECRET_KEY")
        allow_fallback = os.getenv("AUTH_ALLOW_HEADER_FALLBACK", "0") == "1"
        if supabase_url and supabase_api_key:
            _auth_singleton = SupabaseAuthAdapter(
                supabase_url=supabase_url,
                supabase_api_key=supabase_api_key,
                allow_header_fallback=allow_fallback,
            )
            return _auth_singleton

    _auth_singleton = HeaderAuthAdapter()
    return _auth_singleton


def get_storage() -> StoragePort:
    global _storage_singleton
    if _storage_singleton is not None:
        return _storage_singleton

    provider = os.getenv("STORAGE_PROVIDER", "memory").lower()
    if provider == "supabase":
        supabase_url = _env_clean("SUPABASE_URL")
        service_key = _env_clean("SUPABASE_SECRET_KEY")
        bucket = _env_clean("SUPABASE_STORAGE_BUCKET", "media") or "media"
        if supabase_url and service_key:
            _storage_singleton = SupabaseStorageAdapter(supabase_url, service_key, bucket)
            return _storage_singleton

    _storage_singleton = InMemoryStorageAdapter()
    return _storage_singleton
