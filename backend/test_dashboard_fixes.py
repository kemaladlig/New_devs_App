import httpx

BASE_URL = "http://localhost:8000"


def login(email: str, password: str) -> str:
    resp = httpx.post(
        f"{BASE_URL}/api/v1/auth/login",
        json={"email": email, "password": password},
        timeout=10.0,
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["access_token"]


def test_tenant_isolation_timezone_and_decimal_precision():
    token_a = login("sunset@propertyflow.com", "client_a_2024")
    token_b = login("ocean@propertyflow.com", "client_b_2024")

    headers_a = {"Authorization": f"Bearer {token_a}"}
    headers_b = {"Authorization": f"Bearer {token_b}"}

    # 1. Verify tenant-scoped property list
    props_a = httpx.get(f"{BASE_URL}/api/v1/dashboard/properties", headers=headers_a).json()["properties"]
    props_b = httpx.get(f"{BASE_URL}/api/v1/dashboard/properties", headers=headers_b).json()["properties"]

    assert [p["id"] for p in props_a] == ["prop-001", "prop-002", "prop-003"]
    assert props_a[0]["name"] == "Beach House Alpha"
    assert [p["id"] for p in props_b] == ["prop-001", "prop-004", "prop-005"]
    assert props_b[0]["name"] == "Mountain Lodge Beta"

    # 2. Client A prop-001: includes res-tz-1 (2024-02-29 23:30 UTC -> 2024-03-01 00:30 Europe/Paris)
    # and sums 333.333 + 333.333 + 333.334 = 1000.000 + 1250.000 = 2250.00
    sum_a_001 = httpx.get(
        f"{BASE_URL}/api/v1/dashboard/summary",
        params={"property_id": "prop-001"},
        headers=headers_a,
    )
    assert sum_a_001.status_code == 200
    data_a_001 = sum_a_001.json()
    assert data_a_001["property_name"] == "Beach House Alpha"
    assert data_a_001["total_revenue"] == 2250.0
    assert data_a_001["reservations_count"] == 4

    # 3. Client B prop-001: shares ID 'prop-001' with Client A, must NOT read Client A's Redis cache
    sum_b_001 = httpx.get(
        f"{BASE_URL}/api/v1/dashboard/summary",
        params={"property_id": "prop-001"},
        headers=headers_b,
    )
    assert sum_b_001.status_code == 200
    data_b_001 = sum_b_001.json()
    assert data_b_001["property_name"] == "Mountain Lodge Beta"
    assert data_b_001["total_revenue"] == 0.0
    assert data_b_001["reservations_count"] == 0

    # 4. Cross-tenant property access must be rejected with 404
    cross_b_to_a = httpx.get(
        f"{BASE_URL}/api/v1/dashboard/summary",
        params={"property_id": "prop-002"},
        headers=headers_b,
    )
    assert cross_b_to_a.status_code == 404

    cross_a_to_b = httpx.get(
        f"{BASE_URL}/api/v1/dashboard/summary",
        params={"property_id": "prop-004"},
        headers=headers_a,
    )
    assert cross_a_to_b.status_code == 404

    print("ALL CHECKS PASSED!")


if __name__ == "__main__":
    test_tenant_isolation_timezone_and_decimal_precision()
