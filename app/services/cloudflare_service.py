import httpx

from app.config import settings

CF_API = "https://api.cloudflare.com/client/v4"


def _bearer_headers() -> dict:
    return {"Authorization": f"Bearer {settings.CF_TOKEN}", "Content-Type": "application/json"}


def _global_headers() -> dict:
    # /cfd_tunnel/{id}/configurations ne supporte pas Bearer token — Global API Key requis
    return {
        "X-Auth-Key": settings.CF_GLOBAL_API_KEY,
        "X-Auth-Email": settings.CF_ACCOUNT_EMAIL,
        "Content-Type": "application/json",
    }


def _tunnel_config_url() -> str:
    return f"{CF_API}/accounts/{settings.CF_ACCOUNT_ID}/cfd_tunnel/{settings.CF_TUNNEL_ID}/configurations"


def _get_tunnel_config() -> dict:
    resp = httpx.get(_tunnel_config_url(), headers=_global_headers(), timeout=15)
    resp.raise_for_status()
    return resp.json()["result"]["config"]


def _put_tunnel_config(config: dict) -> None:
    resp = httpx.put(
        _tunnel_config_url(),
        headers=_global_headers(),
        json={"config": config},
        timeout=15,
    )
    resp.raise_for_status()


def add_tunnel_ingress(slug: str, port: int) -> None:
    config = _get_tunnel_config()
    ingress = config.get("ingress", [{"service": "http_status:404"}])

    hostname = f"{slug}.{settings.BASE_DOMAIN}"
    new_rule = {"hostname": hostname, "service": f"http://localhost:{port}"}

    catch_all_idx = next(
        (i for i, r in enumerate(ingress) if not r.get("hostname")),
        len(ingress),
    )
    ingress.insert(catch_all_idx, new_rule)
    config["ingress"] = ingress
    _put_tunnel_config(config)


def remove_tunnel_ingress(slug: str) -> None:
    try:
        config = _get_tunnel_config()
        hostname = f"{slug}.{settings.BASE_DOMAIN}"
        config["ingress"] = [r for r in config.get("ingress", []) if r.get("hostname") != hostname]
        _put_tunnel_config(config)
    except Exception:
        pass


def add_dns_record(slug: str) -> None:
    resp = httpx.post(
        f"{CF_API}/zones/{settings.CF_ZONE_ID}/dns_records",
        headers=_bearer_headers(),
        json={
            "type": "CNAME",
            "name": f"{slug}.{settings.BASE_DOMAIN}",
            "content": f"{settings.CF_TUNNEL_ID}.cfargotunnel.com",
            "proxied": True,
        },
        timeout=15,
    )
    resp.raise_for_status()


def remove_dns_record(slug: str) -> None:
    hostname = f"{slug}.{settings.BASE_DOMAIN}"
    try:
        resp = httpx.get(
            f"{CF_API}/zones/{settings.CF_ZONE_ID}/dns_records",
            headers=_bearer_headers(),
            params={"name": hostname, "type": "CNAME"},
            timeout=15,
        )
        resp.raise_for_status()
        for record in resp.json().get("result", []):
            httpx.delete(
                f"{CF_API}/zones/{settings.CF_ZONE_ID}/dns_records/{record['id']}",
                headers=_bearer_headers(),
                timeout=15,
            )
    except Exception:
        pass
