from decimal import Decimal, ROUND_HALF_UP
from fastapi import APIRouter, Depends, HTTPException, status
from typing import Dict, Any, List
from app.services.cache import get_revenue_summary
from app.services.reservations import get_tenant_properties
from app.core.auth import authenticate_request as get_current_user

router = APIRouter()


@router.get("/dashboard/properties")
async def list_dashboard_properties(
    current_user: Any = Depends(get_current_user),
) -> Dict[str, List[Dict[str, Any]]]:
    tenant_id = getattr(current_user, "tenant_id", None)
    if not tenant_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Tenant context required",
        )
    properties = await get_tenant_properties(tenant_id)
    return {"properties": properties}


@router.get("/dashboard/summary")
async def get_dashboard_summary(
    property_id: str,
    month: int = 3,
    year: int = 2024,
    current_user: Any = Depends(get_current_user),
) -> Dict[str, Any]:
    tenant_id = getattr(current_user, "tenant_id", None)
    if not tenant_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Tenant context required",
        )

    revenue_data = await get_revenue_summary(
        property_id=property_id,
        tenant_id=tenant_id,
        month=month,
        year=year,
    )

    if revenue_data.get("not_found"):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Property '{property_id}' not found for your organization",
        )

    total_decimal = Decimal(str(revenue_data["total"])).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP
    )

    return {
        "property_id": revenue_data["property_id"],
        "property_name": revenue_data.get("property_name"),
        "timezone": revenue_data.get("timezone"),
        "total_revenue": float(total_decimal),
        "currency": revenue_data["currency"],
        "reservations_count": revenue_data["count"],
    }
