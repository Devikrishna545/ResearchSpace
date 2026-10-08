from fastapi import APIRouter, Depends
from sqlalchemy import select
from app.core.auth import current_user
from app.core.config import Settings
from app.db.session import SessionLocal, get_config
from app.modules.discovery.orm import OpenAlexConsent
from app.modules.auth.orm.user import User
from app.modules.discovery.schemas import SearchQuery
from app.modules.discovery.service import DiscoveryService
from app.modules.discovery.providers.arxiv import ArxivAdapter
from app.modules.discovery.providers.core import COREAdapter
from app.modules.discovery.providers.crossref import CrossrefAdapter
from app.modules.discovery.providers.openalex import OpenAlexAdapter
from app.modules.discovery.providers.pubmed import PubMedAdapter
from app.modules.discovery.providers.registry import SourceRegistry
from app.modules.discovery.providers.semantic_scholar import SemanticScholarAdapter
from app.modules.discovery.providers.taxonomy import serializable_tags
from app.modules.discovery.providers.web_search import WebSearchAdapter

router = APIRouter()


def source_adapters(settings: Settings, include_web: bool = False, *, openalex_contact: str | None = None):
    adapters = [ArxivAdapter(settings), OpenAlexAdapter(settings, contact_email=openalex_contact), CrossrefAdapter(settings), PubMedAdapter(settings), SemanticScholarAdapter(settings)]
    if settings.core_api_key:
        adapters.append(COREAdapter(settings))
    if include_web:
        adapters.append(WebSearchAdapter(settings))
    return adapters


@router.get("/search/tags")
async def search_tags():
    return serializable_tags()


@router.post("/spaces/{space_id}/search")
async def search(space_id: str, body: SearchQuery, settings: Settings = Depends(get_config), user: User = Depends(current_user)):
    async with SessionLocal() as session:
        consent = await session.scalar(select(OpenAlexConsent).where(OpenAlexConsent.user_id == user.id))
    contact = consent.contact_email if consent and consent.state == "granted" else None
    return await DiscoveryService(SourceRegistry(
        source_adapters(settings, include_web=body.include_web, openalex_contact=contact),
        owner_id=user.id,
    )).discover(body)
