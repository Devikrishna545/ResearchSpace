import hmac
import re
import secrets
from datetime import timedelta
from enum import Enum
from urllib.parse import urlencode, urlparse
from uuid import UUID, uuid4

import httpx
from cryptography.fernet import Fernet, InvalidToken
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError

from app.core.auth import COOKIE, current_user, digest, now
from app.core.config import get_settings
from app.db.session import SessionLocal
from app.modules.compare.orm.comparison_report import ComparisonReport
from app.modules.sharing.orm import LinkedInConnection, LinkedInOAuthState, LinkedInPostAttempt
from app.modules.notes.orm import Note
from app.modules.papers.orm.paper import Paper
from app.modules.spaces.orm.research_space import ResearchSpace
from app.modules.auth.orm.user import User

router = APIRouter()


def configuration():
    settings = get_settings()
    if not all((
        settings.linkedin_member_social_enabled, settings.linkedin_client_id,
        settings.linkedin_client_secret, settings.linkedin_redirect_uri,
        settings.linkedin_token_key,
    )):
        raise HTTPException(503, "LinkedIn posting is unavailable: developer credentials, member permission or encryption key are not configured")
    redirect = urlparse(settings.linkedin_redirect_uri)
    if redirect.scheme != "https" or not redirect.netloc or redirect.query or redirect.fragment:
        raise HTTPException(503, "LinkedIn posting requires an absolute registered HTTPS callback")
    if not re.fullmatch(r"\d{6}", settings.linkedin_api_version):
        raise HTTPException(503, "LinkedIn API version must have YYYYMM format")
    try:
        cipher = Fernet(settings.linkedin_token_key.encode())
    except (ValueError, TypeError) as exc:
        raise HTTPException(503, "LinkedIn encryption key is invalid") from exc
    return settings, cipher


@router.get("/status")
async def connection_status(user: User = Depends(current_user)):
    try:
        configuration()
    except HTTPException as exc:
        if exc.status_code != 503:
            raise
        return {"available": False, "connected": False, "reason": exc.detail}
    async with SessionLocal() as db:
        connection = await db.get(LinkedInConnection, user.id)
    return {
        "available": True,
        "connected": bool(connection and connection.expires_at > now()),
        "expires_at": connection.expires_at.isoformat() if connection else None,
    }


@router.post("/connect")
async def connect(request: Request, user: User = Depends(current_user)):
    settings, _ = configuration()
    state = secrets.token_urlsafe(40)
    async with SessionLocal() as db:
        db.add(LinkedInOAuthState(
            state_hash=digest(state), user_id=user.id,
            session_hash=digest(request.cookies[COOKIE]), expires_at=now() + timedelta(minutes=10),
        ))
        await db.commit()
    query = urlencode({
        "response_type": "code", "client_id": settings.linkedin_client_id,
        "redirect_uri": settings.linkedin_redirect_uri, "state": state,
        "scope": "openid profile w_member_social",
    })
    return {"authorization_url": f"https://www.linkedin.com/oauth/v2/authorization?{query}"}


@router.get("/callback")
async def callback(request: Request, state: str, code: str | None = None, error: str | None = None, user: User = Depends(current_user)):
    settings, cipher = configuration()
    async with SessionLocal() as db:
        saved = await db.get(LinkedInOAuthState, digest(state))
        if not saved or saved.user_id != user.id or saved.expires_at <= now() or not hmac.compare_digest(saved.session_hash, digest(request.cookies[COOKIE])):
            raise HTTPException(403, "Invalid or expired LinkedIn OAuth state")
        await db.delete(saved)
        await db.commit()
    if error:
        raise HTTPException(400, "LinkedIn authorization was denied or cancelled")
    if not code:
        raise HTTPException(400, "LinkedIn authorization code is missing")
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            exchange = await client.post(
                "https://www.linkedin.com/oauth/v2/accessToken",
                data={
                    "grant_type": "authorization_code", "code": code,
                    "client_id": settings.linkedin_client_id,
                    "client_secret": settings.linkedin_client_secret,
                    "redirect_uri": settings.linkedin_redirect_uri,
                },
            )
            if exchange.status_code != 200:
                raise HTTPException(502, f"LinkedIn authorization failed (HTTP {exchange.status_code}); reconnect and check app permissions")
            token_data = exchange.json()
            token = token_data.get("access_token")
            scope = token_data.get("scope", "")
            lifetime = token_data.get("expires_in")
            if not isinstance(token, str) or not token or not isinstance(scope, str) or "w_member_social" not in scope.split() or not isinstance(lifetime, int) or lifetime <= 0:
                raise HTTPException(502, "LinkedIn did not grant the required member-posting permission or a valid token")
            identity = await client.get("https://api.linkedin.com/v2/userinfo", headers={"Authorization": "Bearer " + token})
            if identity.status_code != 200:
                raise HTTPException(502, f"LinkedIn identity lookup failed (HTTP {identity.status_code})")
            member_id = identity.json().get("sub")
            if not isinstance(member_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]+", member_id):
                raise HTTPException(502, "LinkedIn did not return a usable member identifier")
    except httpx.HTTPError as exc:
        raise HTTPException(502, "LinkedIn could not be reached; reconnect later") from exc
    async with SessionLocal() as db:
        connection = await db.get(LinkedInConnection, user.id)
        if connection is None:
            connection = LinkedInConnection(user_id=user.id, encrypted_token="", member_id="", expires_at=now())
            db.add(connection)
        connection.encrypted_token = cipher.encrypt(token.encode()).decode()
        connection.member_id = member_id
        connection.expires_at = now() + timedelta(seconds=lifetime)
        await db.commit()
    return RedirectResponse(f"{settings.cors_allow_origins[0]}?linkedin=connected", status_code=303)


@router.post("/disconnect")
async def disconnect(user: User = Depends(current_user)):
    async with SessionLocal() as db:
        await db.execute(delete(LinkedInConnection).where(LinkedInConnection.user_id == user.id))
        await db.execute(delete(LinkedInOAuthState).where(LinkedInOAuthState.user_id == user.id))
        await db.commit()
    return {"connected": False, "external_revocation": "To revoke LinkedIn's grant as well, remove this app in LinkedIn Permitted Services."}


class Visibility(str, Enum):
    PUBLIC = "PUBLIC"
    CONNECTIONS = "CONNECTIONS"


class PublishRequest(BaseModel):
    source_type: str = Field(pattern="^(note|finding)$")
    source_id: str
    finding_kind: str | None = None
    finding_index: int | None = Field(default=None, ge=0)
    text: str = Field(min_length=1, max_length=3000)
    visibility: Visibility
    confirmed: bool
    request_id: UUID


async def check_selected_item(db, user_id: str, body: PublishRequest) -> None:
    if body.source_type == "note":
        note = await db.scalar(
            select(Note).join(ResearchSpace, ResearchSpace.id == Note.space_id)
            .where(Note.id == body.source_id, ResearchSpace.user_id == user_id)
        )
        found = note.id if note else None
        if note and note.paper_id and not await db.scalar(select(Paper.id).where(Paper.id == note.paper_id, Paper.owner_id == user_id)):
            raise HTTPException(409, "Legacy note references missing paper evidence; repair it before publishing")
    else:
        report = await db.scalar(
            select(ComparisonReport).join(ResearchSpace, ResearchSpace.id == ComparisonReport.space_id)
            .where(ComparisonReport.id == body.source_id, ResearchSpace.user_id == user_id)
        )
        # Only shown findings of grounded reports can be shared; retired profile-only reports cannot.
        categories = {"commonality": "commonalities", "contradiction": "contradictions", "gap": "candidate_gaps",
                      "difference": "differences", "numerical": "numerical"}
        grounded = report is not None and report.report_kind == "grounded"
        if not grounded or body.finding_kind not in categories or body.finding_index is None:
            found = None
        else:
            paper_ids = set(report.paper_ids or [])
            available = set((await db.scalars(select(Paper.id).where(Paper.id.in_(paper_ids), Paper.owner_id == user_id))).all())
            if paper_ids - available:
                raise HTTPException(409, "Finding references missing paper evidence; re-run the comparison before publishing")
            items = ((report.report_json or {}).get("sections") or {}).get(categories[body.finding_kind]) or []
            found = report.id if body.finding_index < len(items) else None
    if not found:
        raise HTTPException(404, "Selected item not found")


async def record_attempt(attempt_id: str, status: str, result_urn: str | None = None) -> None:
    async with SessionLocal() as db:
        saved = await db.get(LinkedInPostAttempt, attempt_id)
        saved.status = status
        saved.result_urn = result_urn
        await db.commit()


@router.post("/publish")
async def publish(body: PublishRequest, user: User = Depends(current_user)):
    if not body.confirmed or not body.text.strip():
        raise HTTPException(422, "Review the text and explicitly confirm this post")
    settings, cipher = configuration()
    async with SessionLocal() as db:
        await check_selected_item(db, user.id, body)
        connection = await db.get(LinkedInConnection, user.id)
        if not connection or connection.expires_at <= now():
            raise HTTPException(409, "LinkedIn connection is missing or expired; reconnect before publishing")
        try:
            token = cipher.decrypt(connection.encrypted_token.encode()).decode()
        except InvalidToken as exc:
            raise HTTPException(503, "Stored LinkedIn token cannot be decrypted; reconnect with the configured encryption key") from exc
        member_id = connection.member_id
        attempt = LinkedInPostAttempt(
            id=str(uuid4()), user_id=user.id, request_id=str(body.request_id),
            source_type=body.source_type, source_id=body.source_id, status="pending",
        )
        db.add(attempt)
        try:
            await db.commit()
        except IntegrityError as exc:
            raise HTTPException(409, "This publication request has already been used; check LinkedIn before trying again") from exc
    payload = {
        "author": f"urn:li:person:{member_id}", "commentary": body.text.strip(),
        "visibility": body.visibility.value,
        "distribution": {"feedDistribution": "MAIN_FEED", "targetEntities": [], "thirdPartyDistributionChannels": []},
        "lifecycleState": "PUBLISHED", "isReshareDisabledByAuthor": False,
    }
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.post(
                "https://api.linkedin.com/rest/posts",
                json=payload,
                headers={
                    "Authorization": "Bearer " + token,
                    "Linkedin-Version": settings.linkedin_api_version,
                    "X-Restli-Protocol-Version": "2.0.0",
                    "Content-Type": "application/json",
                },
            )
    except (httpx.ConnectError, httpx.ConnectTimeout) as exc:
        await record_attempt(attempt.id, "not_sent")
        raise HTTPException(503, "LinkedIn connection failed before posting; reopen the preview and explicitly approve a new request to retry") from exc
    except httpx.HTTPError as exc:
        await record_attempt(attempt.id, "uncertain")
        raise HTTPException(502, "LinkedIn publish outcome is unknown; check your LinkedIn profile before considering a new request") from exc
    if response.status_code != 201:
        await record_attempt(attempt.id, "rejected" if response.status_code < 500 else "uncertain")
        if response.status_code in (401, 403):
            raise HTTPException(409, "LinkedIn token or w_member_social permission was rejected; reconnect")
        if response.status_code == 429:
            raise HTTPException(429, "LinkedIn rate limit reached; do not retry this request automatically")
        raise HTTPException(502, f"LinkedIn publish failed (HTTP {response.status_code}); check LinkedIn before retrying")
    result_id = response.headers.get("x-restli-id")
    if not result_id:
        await record_attempt(attempt.id, "uncertain")
        raise HTTPException(502, "LinkedIn accepted the post but did not return an ID; check your profile before trying again")
    await record_attempt(attempt.id, "published", result_id)
    return {"published": True, "post_id": result_id, "visibility": body.visibility.value}
