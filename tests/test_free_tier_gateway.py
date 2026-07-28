from pathlib import Path


def test_free_tier_gateway_routes_operational_endpoints_to_api() -> None:
    config = (Path(__file__).parents[1] / "deploy" / "free-tier" / "nginx.conf").read_text()

    for endpoint in (
        "/health/live",
        "/health/ready",
        "/openapi.json",
        "/metrics",
    ):
        assert f"location = {endpoint} {{" in config
