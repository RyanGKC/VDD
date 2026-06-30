import json
import logging
from core.models import DDContext
from core.mock import tools as mock_tools
from core import real_tools
from core.cache import PersistentCache

logger = logging.getLogger(__name__)
cache_db = PersistentCache()

async def _run_mock(func, cache_key: str, *args, **kwargs):
    cached = cache_db.get(cache_key, use_mock=True)
    if cached:
        return cached
    res = await func(*args, **kwargs)
    cache_db.set(cache_key, res, use_mock=True)
    return res

async def fetch_corporate_registry(ctx: DDContext, company_name: str, country: str | None) -> str:
    if ctx.use_mock:
        return await _run_mock(mock_tools.fetch_corporate_registry, f"registry|{company_name}|{country}", company_name, country)
    return await real_tools.fetch_corporate_registry(ctx, company_name, country)

async def verify_kyb_records(ctx: DDContext, company_name: str, reg_id: str | None) -> str:
    if ctx.use_mock:
        return await _run_mock(mock_tools.verify_kyb_records, f"kyb|{company_name}|{reg_id}", company_name, reg_id)
    return await real_tools.verify_kyb_records(ctx, company_name, reg_id)

async def screen_sanctions(ctx: DDContext, entities: list[str]) -> str:
    if ctx.use_mock:
        return await _run_mock(mock_tools.screen_sanctions, f"sanctions|{json.dumps(entities)}", entities)
    return await real_tools.screen_sanctions(ctx, entities)

async def verify_licenses(ctx: DDContext, company_name: str, country: str | None) -> str:
    if ctx.use_mock:
        return await _run_mock(mock_tools.verify_licenses, f"licenses|{company_name}|{country}", company_name, country)
    return await real_tools.verify_licenses(ctx, company_name, country)

async def fetch_financials(ctx: DDContext, company_name: str, registration_id: str | None) -> str:
    if ctx.use_mock:
        return await _run_mock(mock_tools.fetch_financials, f"financials|{company_name}|{registration_id}", company_name, registration_id)
    return await real_tools.fetch_financials(ctx, company_name, registration_id)

async def scan_adverse_media(ctx: DDContext, entities: list[str]) -> str:
    if ctx.use_mock:
        return await _run_mock(mock_tools.scan_adverse_media, f"media|{json.dumps(entities)}", entities)
    return await real_tools.scan_adverse_media(ctx, entities)

async def perform_web_search(ctx: DDContext, query: str) -> str:
    if ctx.use_mock:
        import asyncio
        await asyncio.sleep(0.5)
        return await _run_mock(mock_tools.perform_web_search, f"search|{query}", query)
    return await real_tools.perform_web_search(ctx, query)
