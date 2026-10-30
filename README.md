# PropertyFlow Revenue Dashboard — Bug Investigation & Fixes

## Overview of Reported Issues & Root Causes

### 1. Cross-Tenant Data Leakage (Client B — Ocean Rentals)
- **Symptom:** Ocean Rentals (`tenant-b`) intermittently saw revenue figures belonging to Sunset Properties (`tenant-a`) when refreshing or viewing `prop-001`, and could see all 5 properties across both tenants in the property selector.
- **Root Causes:**
  1. **Unscoped Redis Cache Key (`backend/app/services/cache.py`):** Revenue summaries were cached under `revenue:{property_id}` without `tenant_id`. Because `properties` uses a composite primary key `(id, tenant_id)` and both `tenant-a` (*Beach House Alpha*) and `tenant-b` (*Mountain Lodge Beta*) have a property with ID `prop-001`, whichever tenant queried `prop-001` first poisoned the cache for the other tenant.
  2. **Broken DB Connection Pool Falling Back to Unscoped Mock Data (`backend/app/core/database_pool.py` & `backend/app/services/reservations.py`):**
     - `requirements.txt` was missing `greenlet` (`sqlalchemy[asyncio]`), causing `from app.core.database_pool import DatabasePool` to fail at import time.
     - `DatabasePool.initialize()` referenced non-existent `settings.supabase_db_*` attributes instead of `settings.database_url`, passed synchronous `QueuePool` to `create_async_engine`, and defined `get_session` as `async def` instead of returning the `AsyncSession` context manager.
     - On exception, `calculate_total_revenue()` caught the error and returned hardcoded, tenant-agnostic `mock_data`.
  3. **Hardcoded Property List & Client-Side Tenant Cache Validation (`frontend/src/components/Dashboard.tsx` & `frontend/src/lib/secureApi.ts`):**
     - `Dashboard.tsx` hardcoded `prop-001`..`prop-005` instead of loading the authenticated tenant's properties.
     - `SecureAPI.isValidTenantId()` only accepted UUIDs (`^[0-9a-f]{8}-...`), rejecting slug tenant IDs (`tenant-a`, `tenant-b`) and clearing the cached auth token.

### 2. March Revenue Discrepancy Across Timezones (Client A — Sunset Properties)
- **Symptom:** Sunset Properties (`tenant-a`) saw `$1,000.00` (3 bookings) instead of `$2,250.00` (4 bookings) for `prop-001` (*Beach House Alpha*) in March 2024.
- **Root Cause:**
  - Reservation `res-tz-1` (`$1,250.000`) has `check_in_date = 2024-02-29 23:30:00+00` (UTC).
  - However, `prop-001` (*Beach House Alpha*) is located in `Europe/Paris` (`UTC+1` in winter), where `2024-02-29 23:30:00+00` is **`2024-03-01 00:30:00` (March 1st, 2024)**.
  - Filtering monthly boundaries in UTC (and falling back to `mock_data`) excluded `res-tz-1` from March 2024.

### 3. Sub-Cent Precision & Rounding Discrepancies (Finance Team)
- **Symptom:** Totals were occasionally off by a cent or triggered precision mismatch warnings.
- **Root Cause:**
  - `reservations.total_amount` is stored as `NUMERIC(10, 3)` (`333.333`, `333.333`, `333.334` for `res-dec-1..3`).
  - Rounding individual bookings prior to aggregation (`333.33 * 3 = 999.99`) loses `$0.01`, and converting unquantized 3-decimal strings directly via `float()` leaks sub-cent precision to the client.

---

## Summary of Fixes

1. **Database Connection Pool (`backend/requirements.txt`, `backend/app/core/database_pool.py`):**
   - Added `sqlalchemy[asyncio]` / `greenlet`.
   - Configured `DatabasePool` to build the `postgresql+asyncpg://` URL from `settings.database_url` and reuse the shared pool instance.
2. **Tenant-Scoped Caching (`backend/app/services/cache.py`):**
   - Scoped Redis keys by tenant, property, and period: `revenue:{tenant_id}:{property_id}:{year}-{month:02d}`.
   - Verified `tenant_id` ownership before serving or storing cached entries.
3. **Timezone-Aware Aggregation & Decimal Rounding (`backend/app/services/reservations.py`, `backend/app/api/v1/dashboard.py`):**
   - Joined `properties` and evaluated monthly boundaries in each property's local timezone using `(r.check_in_date AT TIME ZONE p.timezone) >= :start_date AND (r.check_in_date AT TIME ZONE p.timezone) < :end_date`.
   - Enforced strict tenant ownership (`WHERE p.id = :property_id AND p.tenant_id = :tenant_id`), returning `404 Not Found` if a tenant queries another organization's property.
   - Removed the unscoped `mock_data` fallback.
   - Aggregated full `NUMERIC(10, 3)` precision in PostgreSQL (`SUM(r.total_amount)`) and quantized once to 2 decimal places in Python using `Decimal.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)`.
4. **Frontend Tenant Isolation (`frontend/src/components/Dashboard.tsx`, `frontend/src/components/RevenueSummary.tsx`, `frontend/src/lib/secureApi.ts`):**
   - Added `GET /api/v1/dashboard/properties` and updated `Dashboard.tsx` to dynamically load only the logged-in tenant's properties.
   - Updated `SecureAPI` and `AuthContext` to properly extract and validate `tenant_id` (`tenant-a`, `tenant-b`, or UUID) and flush client cache on account switch.

---

## Verification Results

| Tenant | Property ID | Property Name | Timezone | March 2024 Bookings | March 2024 Total Revenue |
|---|---|---|---|---|---|
| `tenant-a` (Sunset Properties) | `prop-001` | Beach House Alpha | `Europe/Paris` | 4 (includes `res-tz-1` & `res-dec-1..3`) | **USD 2,250.00** |
| `tenant-a` (Sunset Properties) | `prop-002` | City Apartment Downtown | `Europe/Paris` | 4 | **USD 4,975.50** |
| `tenant-a` (Sunset Properties) | `prop-003` | Country Villa Estate | `Europe/Paris` | 2 | **USD 6,100.50** |
| `tenant-b` (Ocean Rentals) | `prop-001` | Mountain Lodge Beta | `America/New_York` | 0 | **USD 0.00** |
| `tenant-b` (Ocean Rentals) | `prop-004` | Lakeside Cottage | `America/New_York` | 4 | **USD 1,776.50** |
| `tenant-b` (Ocean Rentals) | `prop-005` | Urban Loft Modern | `America/New_York` | 3 | **USD 3,256.00** |

## Running & Testing

```bash
docker compose up -d --build
pytest backend/test_dashboard_fixes.py -v
```
- Frontend: `http://localhost:3000`
- Backend API Docs: `http://localhost:8000/docs`
