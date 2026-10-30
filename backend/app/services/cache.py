import json
import redis.asyncio as redis
from typing import Dict, Any
import os

# Initialize Redis client (typically configured centrally).
redis_client = redis.Redis.from_url(os.getenv("REDIS_URL", "redis://localhost:6379/0"))


async def get_revenue_summary(
    property_id: str,
    tenant_id: str,
    month: int = 3,
    year: int = 2024,
) -> Dict[str, Any]:
    """
    Fetches revenue summary, utilizing tenant-scoped caching to prevent cross-tenant data leakage.
    """
    cache_key = f"revenue:{tenant_id}:{property_id}:{year}-{month:02d}"

    # Try to get from cache
    cached = await redis_client.get(cache_key)
    if cached:
        data = json.loads(cached)
        if data.get("tenant_id") == tenant_id:
            return data

    # Revenue calculation is delegated to the reservation service.
    from app.services.reservations import calculate_total_revenue

    # Calculate revenue
    result = await calculate_total_revenue(
        property_id=property_id,
        tenant_id=tenant_id,
        month=month,
        year=year,
    )

    # Only cache valid tenant-owned property results
    if not result.get("not_found"):
        await redis_client.setex(cache_key, 300, json.dumps(result))

    return result
