import hmac
from typing import Literal
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, EmailStr
from sqlalchemy import delete, func, select, text, update
from sqlalchemy.exc import IntegrityError

from app.core.auth import (
    COOKIE, CSRF_COOKIE, _failures, admin_user, allowed_attempt, check_origin,
    clear_session, csrf_protect, digest, failed_attempt, issue_session,
    now, password_hash, revoke_session, setup_token_file,
    verify_password, current_user,
)
from app.core.config import get_settings
from app.db.session import SessionLocal
from app.modules.auth.orm.auth_session import AuthSession
from app.modules.compare.orm.comparison_report import ComparisonReport
from app.db.legacy_claim_audit import LegacyClaimAudit
from app.modules.discovery.orm import OpenAlexConsent
from app.modules.papers.orm.paper import Paper
from app.modules.spaces.orm.pin import Pin
from app.modules.spaces.orm.research_space import ResearchSpace
from app.modules.auth.orm.user import User
from app.platform.retrieval.ingest_store import rehydrate_from_db
from app.platform.http.client import validate_openalex_contact

router = APIRouter()


class Credentials(BaseModel):
    email: EmailStr
    password: str


class Bootstrap(Credentials):
    token: str


class ResetPassword(BaseModel):
    password: str


class OpenAlexChoice(BaseModel):
    choice: Literal["account", "custom", "decline"]
    contact_email: EmailStr | None = None
    consent: bool = False


def consent_dto(record: OpenAlexConsent | None) -> dict:
    return {
        "state": record.state if record else "unset",
        "contact_email": record.contact_email if record and record.state == "granted" else None,
        "updated_at": record.updated_at.isoformat() if record and record.updated_at else None,
    }


def user_dto(user: User) -> dict:
    return {"id": user.id, "email": user.email, "is_admin": user.is_admin}


async def legacy_violation_details(connection, rows):
    details = []
    for table, rowid, parent, fk_index in rows:
        quoted_table = table.replace('"', '""')
        links = (await connection.exec_driver_sql(f'PRAGMA foreign_key_list("{quoted_table}")')).all()
        column = next(link[3] for link in links if link[0] == fk_index)
        quoted_column = column.replace('"', '""')
        target = (await connection.exec_driver_sql(
            f'SELECT "{quoted_column}" FROM "{quoted_table}" WHERE rowid = ?', (rowid,),
        )).scalar_one()
        details.append({"table": table, "rowid": rowid, "parent": parent, "fk_index": fk_index, "column": column, "missing_id": target})
    return details


@router.get("/status")
async def status(request: Request, response: Response):
    check_origin(request)
    csrf = request.cookies.get(CSRF_COOKIE)
    if not csrf:
        import secrets
        csrf = secrets.token_urlsafe(32)
        response.set_cookie(CSRF_COOKIE, csrf, httponly=False, secure=get_settings().cookie_secure, samesite="lax", path="/")
    async with SessionLocal() as db:
        setup_required = not bool(await db.scalar(select(func.count(User.id))))
    try:
        user = await current_user(request)
    except HTTPException as exc:
        if exc.status_code != 401:
            raise
        user = None
    warning = None
    consent = None
    if user:
        async with SessionLocal() as db:
            consent = await db.get(OpenAlexConsent, user.id)
            if user.is_admin:
                audit = await db.get(LegacyClaimAudit, user.id)
                if audit:
                    # The claim audit is an immutable setup snapshot, not current health.
                    violations = (await db.execute(text("PRAGMA foreign_key_check"))).all()
                    paper_ids = set((await db.scalars(select(Paper.id))).all())
                    reports = (await db.scalars(select(ComparisonReport.paper_ids))).all()
                    orphan_count = sum(bool(set(ids or []) - paper_ids) for ids in reports)
                    if violations or orphan_count:
                        warning = {
                            "foreign_key_violations": len(violations),
                            "comparison_orphans": orphan_count,
                            "message": "Current saved-data check: some records reference missing papers or other records. "
                            "Run the local read-only audit for details. No records have been changed.",
                        }
    return {"setup_required": setup_required, "authenticated": user is not None, "user": user_dto(user) if user else None, "csrf_token": csrf, "legacy_warning": warning, "openalex_consent": consent_dto(consent) if user else None}


@router.get("/openalex-consent")
async def get_openalex_consent(user: User = Depends(current_user)):
    async with SessionLocal() as db:
        return consent_dto(await db.get(OpenAlexConsent, user.id))


@router.put("/openalex-consent")
async def update_openalex_consent(body: OpenAlexChoice, user: User = Depends(current_user)):
    if body.choice == "decline":
        if body.contact_email or body.consent:
            raise HTTPException(422, "Declining must not include an address or consent")
        contact = None
        state = "declined"
    else:
        if not body.consent:
            raise HTTPException(422, "Explicit consent is required before sending an address to OpenAlex")
        if body.choice == "account":
            if body.contact_email:
                raise HTTPException(422, "Use the custom option to enter a different address")
            contact = user.email
        else:
            if body.contact_email is None:
                raise HTTPException(422, "Enter an address you control")
            contact = str(body.contact_email)
        try:
            contact = validate_openalex_contact(contact)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        state = "granted"
    async with SessionLocal() as db:
        record = await db.get(OpenAlexConsent, user.id)
        if record is None:
            record = OpenAlexConsent(user_id=user.id, state="unset", updated_at=now())
            db.add(record)
        record.state = state
        record.contact_email = contact
        record.updated_at = now()
        await db.commit()
        return consent_dto(record)


@router.post("/bootstrap")
async def bootstrap(body: Bootstrap, request: Request, response: Response):
    csrf_protect(request)
    key = f"bootstrap:{request.client.host if request.client else 'unknown'}"
    allowed_attempt(key)
    token_file = setup_token_file()
    hashed = password_hash(body.password)
    async with SessionLocal() as db:
        if db.bind.dialect.name == "sqlite":
            await db.execute(text("BEGIN IMMEDIATE"))
        if await db.scalar(select(func.count(User.id))):
            raise HTTPException(409, "Setup is already complete")
        if not token_file.exists() or not hmac.compare_digest(token_file.read_text(encoding="utf-8").strip(), digest(body.token)):
            failed_attempt(key)
            raise HTTPException(403, "Invalid setup token")
        connection = await db.connection()
        if (await connection.exec_driver_sql("PRAGMA integrity_check")).scalar_one() != "ok":
            raise HTTPException(409, "Database integrity check failed; restore the backup before setup")
        broken = (await connection.exec_driver_sql("PRAGMA foreign_key_check")).all()
        violations = await legacy_violation_details(connection, broken)
        existing = await db.scalar(select(ResearchSpace.id).where(ResearchSpace.user_id.is_not(None)).limit(1))
        if existing:
            raise HTTPException(409, "Existing workspace ownership must be reviewed before setup")
        if await db.scalar(select(Paper.id).where(Paper.owner_id.is_not(None)).limit(1)):
            raise HTTPException(409, "Existing paper ownership must be reviewed before setup")
        paper_ids = set((await db.scalars(select(Paper.id))).all())
        comparison_orphans = []
        for report in (await db.scalars(select(ComparisonReport))).all():
            missing = sorted(set(report.paper_ids or []) - paper_ids)
            if missing:
                comparison_orphans.append({"report_id": report.id, "missing_paper_ids": missing})
        unreferenced_ids = (await db.scalars(select(Paper.id).where(~Paper.id.in_(select(Pin.paper_id))))).all()
        user = User(id=str(uuid4()), email=str(body.email).lower(), password_hash=hashed, is_admin=True)
        db.add(user)
        await db.flush()
        db.add(OpenAlexConsent(user_id=user.id, state="unset", updated_at=now()))
        claimed_spaces = await db.execute(update(ResearchSpace).where(ResearchSpace.user_id.is_(None)).values(user_id=user.id))
        claimed_papers = await db.execute(update(Paper).where(Paper.owner_id.is_(None)).values(owner_id=user.id))
        current_violations = (await connection.exec_driver_sql("PRAGMA foreign_key_check")).all()
        if set(map(tuple, current_violations)) != set(map(tuple, broken)):
            raise HTTPException(409, "Ownership claim changed legacy foreign-key violations; no claim was committed")
        db.add(LegacyClaimAudit(
            user_id=user.id, foreign_key_violations=violations,
            comparison_orphans=comparison_orphans,
            unreferenced_paper_ids=unreferenced_ids,
        ))
        await db.commit()
    token_file.unlink(missing_ok=True)
    _failures.pop(key, None)
    await issue_session(response, user.id)
    await rehydrate_from_db()
    return {**user_dto(user), "claim": {
        "spaces": claimed_spaces.rowcount, "papers": claimed_papers.rowcount,
        "unreferenced_papers": len(unreferenced_ids),
        "foreign_key_violations": len(violations), "comparison_orphans": len(comparison_orphans),
    }}


@router.post("/login")
async def login(body: Credentials, request: Request, response: Response):
    csrf_protect(request)
    client = request.client.host if request.client else "unknown"
    ip_key = f"login-ip:{client}"
    allowed_attempt(ip_key)
    key = f"login:{client}:{str(body.email).lower()}"
    allowed_attempt(key)
    async with SessionLocal() as db:
        user = await db.scalar(select(User).where(User.email == str(body.email).lower()))
    if not verify_password(user, body.password):
        failed_attempt(key)
        failed_attempt(ip_key)
        raise HTTPException(401, "Invalid email or password")
    _failures.pop(key, None)
    _failures.pop(ip_key, None)
    await issue_session(response, user.id)
    await revoke_session(request.cookies.get(COOKIE))
    return user_dto(user)


@router.post("/logout")
async def logout(request: Request, response: Response, user: User = Depends(current_user)):
    await revoke_session(request.cookies.get(COOKIE))
    clear_session(response)
    return {"ok": True}


@router.post("/logout-all")
async def logout_all(response: Response, user: User = Depends(current_user)):
    await revoke_session(None, user.id)
    clear_session(response)
    return {"ok": True}


@router.get("/users")
async def list_users(admin: User = Depends(admin_user)):
    async with SessionLocal() as db:
        users = (await db.scalars(select(User).order_by(User.email))).all()
    return [user_dto(user) for user in users]


@router.post("/users")
async def create_user(body: Credentials, admin: User = Depends(admin_user)):
    user = User(id=str(uuid4()), email=str(body.email).lower(), password_hash=password_hash(body.password), is_admin=False)
    async with SessionLocal() as db:
        db.add(user)
        try:
            await db.flush()
            db.add(OpenAlexConsent(user_id=user.id, state="unset", updated_at=now()))
            await db.commit()
        except IntegrityError as exc:
            raise HTTPException(409, "Account already exists") from exc
    return user_dto(user)


@router.post("/users/{user_id}/reset-password")
async def reset_password(user_id: str, body: ResetPassword, admin: User = Depends(admin_user)):
    hashed = password_hash(body.password)
    async with SessionLocal() as db:
        user = await db.get(User, user_id)
        if not user:
            raise HTTPException(404, "Account not found")
        user.password_hash = hashed
        await db.execute(delete(AuthSession).where(AuthSession.user_id == user_id))
        await db.commit()
    return {"ok": True}
