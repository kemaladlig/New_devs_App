from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP
import logging
from typing import Dict, Any, List, Optional
from sqlalchemy import text
from app.core.database_pool import db_pool

logger = logging.getLogger(__name__)


def _get_month_bounds(year: int, month: int) -> tuple[datetime, datetime]:
    start_date = datetime(year, month, 1)
    if month < 12:
        end_date = datetime(year, month + 1, 1)
    else:
        end_date = datetime(year + 1, 1, 1)
    return start_date, end_date


async def calculate_monthly_revenue(
    property_id: str,
    month: int,
    year: int,
    tenant_id: Optional[str] = None,
    db_session=None,
) -> Decimal:
    """
    Calculates revenue for a specific month in the property's local timezone.
    Sums full NUMERIC(10,3) precision in SQL first, then rounds to 2 decimal places.
    """
    start_date, end_date = _get_month_bounds(year, month)

    query = text("""
        SELECT COALESCE(SUM(r.total_amount), 0) AS total
        FROM properties p
        LEFT JOIN reservations r
            ON r.property_id = p.id
            AND r.tenant_id = p.tenant_id
            AND (r.check_in_date AT TIME ZONE p.timezone) >= :start_date
            AND (r.check_in_date AT TIME ZONE p.timezone) < :end_date
        WHERE p.id = :property_id
          AND (:tenant_id IS NULL OR p.tenant_id = :tenant_id)
    """)

    if db_session is not None:
        result = await db_session.execute(
            query,
            {
                "property_id": property_id,
                "tenant_id": tenant_id,
                "start_date": start_date,
                "end_date": end_date,
            },
        )
        val = result.scalar()
        raw_total = Decimal(str(val if val is not None else "0"))
        return raw_total.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    if not db_pool.session_factory:
        await db_pool.initialize()

    async with db_pool.get_session() as session:
        result = await session.execute(
            query,
            {
                "property_id": property_id,
                "tenant_id": tenant_id,
                "start_date": start_date,
                "end_date": end_date,
            },
        )
        val = result.scalar()
        raw_total = Decimal(str(val if val is not None else "0"))
        return raw_total.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


async def calculate_total_revenue(
    property_id: str,
    tenant_id: str,
    month: int = 3,
    year: int = 2024,
) -> Dict[str, Any]:
    """
    Aggregates monthly revenue from the database for a specific tenant and property,
    evaluating reservation check-in timestamps in the property's local timezone.
    """
    if not db_pool.session_factory:
        await db_pool.initialize()

    if not db_pool.session_factory:
        raise RuntimeError("Database connection pool is not available")

    start_date, end_date = _get_month_bounds(year, month)

    async with db_pool.get_session() as session:
        query = text("""
            SELECT 
                p.id AS property_id,
                p.name AS property_name,
                p.timezone AS timezone,
                COALESCE(SUM(r.total_amount), 0) AS total_revenue,
                COUNT(r.id) AS reservation_count
            FROM properties p
            LEFT JOIN reservations r 
                ON r.property_id = p.id 
                AND r.tenant_id = p.tenant_id
                AND (r.check_in_date AT TIME ZONE p.timezone) >= :start_date
                AND (r.check_in_date AT TIME ZONE p.timezone) < :end_date
            WHERE p.id = :property_id 
              AND p.tenant_id = :tenant_id
            GROUP BY p.id, p.name, p.timezone
        """)

        result = await session.execute(
            query,
            {
                "property_id": property_id,
                "tenant_id": tenant_id,
                "start_date": start_date,
                "end_date": end_date,
            },
        )
        row = result.fetchone()

        if not row:
            return {
                "property_id": property_id,
                "tenant_id": tenant_id,
                "total": "0.00",
                "currency": "USD",
                "count": 0,
                "not_found": True,
            }

        # Sum at full NUMERIC(10,3) precision in SQL, then round once to 2 decimals
        raw_total = Decimal(str(row.total_revenue or "0"))
        rounded_total = raw_total.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

        return {
            "property_id": row.property_id,
            "property_name": row.property_name,
            "timezone": row.timezone,
            "tenant_id": tenant_id,
            "total": str(rounded_total),
            "currency": "USD",
            "count": int(row.reservation_count),
        }


async def get_tenant_properties(tenant_id: str) -> List[Dict[str, Any]]:
    """
    Returns the list of properties belonging to the specified tenant.
    """
    if not db_pool.session_factory:
        await db_pool.initialize()

    if not db_pool.session_factory:
        raise RuntimeError("Database connection pool is not available")

    async with db_pool.get_session() as session:
        query = text("""
            SELECT id, name, timezone
            FROM properties
            WHERE tenant_id = :tenant_id
            ORDER BY id ASC
        """)
        result = await session.execute(query, {"tenant_id": tenant_id})
        rows = result.fetchall()
        return [
            {
                "id": row.id,
                "name": row.name,
                "timezone": row.timezone,
            }
            for row in rows
        ]
