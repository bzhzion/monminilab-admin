from fastapi import Request
from slowapi import Limiter


def _get_real_ip(request: Request) -> str:
    # CF-Connecting-IP est injecté par Cloudflare et reflète l'IP réelle du client.
    # Fallback sur l'IP directe si hors tunnel (dev local).
    return request.headers.get("CF-Connecting-IP") or (request.client.host if request.client else "unknown")


limiter = Limiter(key_func=_get_real_ip)
