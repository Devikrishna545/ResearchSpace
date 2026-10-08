import re
from functools import lru_cache

import httpx
from email_validator import EmailNotValidError, validate_email

from app.core.config import Settings


@lru_cache(maxsize=1)
def get_source_client() -> httpx.AsyncClient:
    return httpx.AsyncClient(
        limits=httpx.Limits(max_connections=30, max_keepalive_connections=15, keepalive_expiry=30),
        follow_redirects=False,
    )


async def close_shared_source_client() -> None:
    if not get_source_client.cache_info().currsize:
        return
    try:
        await get_source_client().aclose()
    finally:
        get_source_client.cache_clear()


def source_timeout(settings: Settings) -> httpx.Timeout:
    budget = settings.source_timeout_s
    return httpx.Timeout(
        connect=min(3.0, budget * 0.5),
        read=min(5.0, budget * 0.75),
        write=min(3.0, budget * 0.5),
        pool=min(2.0, budget * 0.4),
    )


def _validated_contact(supplied: str | None, *, explicit: bool) -> str | None:
    if not supplied:
        return None
    try:
        address = validate_email(supplied, check_deliverability=False)
    except EmailNotValidError as exc:
        if not explicit:
            return None
        raise ValueError("Configure a valid, genuine, non-placeholder contact email for OpenAlex") from exc
    domain = address.domain.lower()
    if domain in {"example.com", "example.net", "example.org", "localhost"} or domain.endswith((".invalid", ".test", ".example", ".localhost")):
        if not explicit:
            return None
        raise ValueError("Configure a genuine, non-placeholder contact email for OpenAlex")
    return address.normalized


def source_contact_email(settings: Settings) -> str | None:
    supplied = settings.source_contact_email or settings.unpaywall_email
    if supplied:
        return _validated_contact(supplied, explicit=True)
    match = re.search(r"mailto:([^\s)]+)", settings.source_user_agent, flags=re.IGNORECASE)
    return _validated_contact(match.group(1), explicit=False) if match else None


def validate_openalex_contact(email: str) -> str:
    contact = _validated_contact(email, explicit=True)
    if not contact:
        raise ValueError("Enter a working OpenAlex contact address")
    return contact


def source_headers(settings: Settings, *, contact: str | None = None, allow_configured_contact: bool = True) -> dict[str, str]:
    user_agent = re.sub(r"\s*\(mailto:[^)]*\)", "", settings.source_user_agent, flags=re.IGNORECASE).strip()
    user_agent = user_agent or "research-assistant/0.1"
    contact = contact or (source_contact_email(settings) if allow_configured_contact else None)
    if contact:
        user_agent = f"{user_agent} (mailto:{contact})"
    return {"User-Agent": user_agent}
