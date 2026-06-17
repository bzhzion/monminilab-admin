import httpx

from app.config import settings

FE_API = "https://api.forwardemail.net/v1"


def _auth() -> tuple[str, str]:
    return (settings.FE_API_KEY, "")


def create_alias(slug: str, recipient_email: str) -> None:
    resp = httpx.post(
        f"{FE_API}/domains/{settings.BASE_DOMAIN}/aliases",
        auth=_auth(),
        json={"name": slug, "recipients": [recipient_email], "is_enabled": True},
        timeout=15,
    )
    resp.raise_for_status()


def generate_smtp_password(slug: str) -> str:
    resp = httpx.post(
        f"{FE_API}/domains/{settings.BASE_DOMAIN}/aliases/{slug}/generate-password",
        auth=_auth(),
        timeout=30,
    )
    resp.raise_for_status()
    data = resp.json()
    return data.get("password", data.get("generated_token", ""))


def delete_alias(slug: str) -> None:
    try:
        resp = httpx.delete(
            f"{FE_API}/domains/{settings.BASE_DOMAIN}/aliases/{slug}",
            auth=_auth(),
            timeout=15,
        )
        resp.raise_for_status()
    except Exception:
        pass
