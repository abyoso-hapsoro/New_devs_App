import json
import redis.asyncio as redis
from typing import Dict, Any, Optional
import os
from app.services.reservations import calculate_revenue

# Initialize Redis client (typically configured centrally).
redis_client = redis.Redis.from_url(os.getenv("REDIS_URL", "redis://localhost:6379/0"))
CACHE_VERSION = "v2"
CACHE_TTL_SECONDS = 300


def revenue_cache_key(tenant_id: str, property_id: str, month: Optional[int] = None, year: Optional[int] = None) -> str:
    """
    Build the cache key for a revenue summary.

    BUG FIX: the key used to be `revenue:{property_id}`. Property IDs are only unique
    per tenant (properties PK is (id, tenant_id); both tenants own a 'prop-001'), so
    whichever tenant warmed the cache served its numbers to the other tenant for the
    next 5 minutes. The tenant MUST be part of the key, as must the period.
    """
    if not tenant_id:
        raise ValueError("tenant_id is required for cache isolation")
    period = f"{year:04d}-{month:02d}" if month is not None and year is not None else "all"
    return f"revenue:{CACHE_VERSION}:{tenant_id}:{property_id}:{period}"


async def get_revenue_summary(
    property_id: str,
    tenant_id: str,
    month: Optional[int] = None,
    year: Optional[int] = None,
) -> Optional[Dict[str, Any]]:
    """
    Fetches revenue summary, utilizing caching to improve performance.
    Returns None when the property does not belong to the tenant.
    """
    cache_key = revenue_cache_key(tenant_id, property_id, month, year)

    try:
        cached = await redis_client.get(cache_key)
    except Exception as e:
        cached = None

    if cached:
        data = json.loads(cached)
        if data.get("tenant_id") == tenant_id and data.get("property_id") == property_id:
            return data
        try:
            await redis_client.delete(cache_key)
        except Exception:
            pass

    result = await calculate_revenue(property_id, tenant_id, month=month, year=year)
    if result is None:
        return None

    try:
        await redis_client.setex(cache_key, CACHE_TTL_SECONDS, json.dumps(result))
    except Exception as e:
        pass

    return result
