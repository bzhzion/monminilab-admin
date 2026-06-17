from fastapi import Request
from slowapi import Limiter


def _get_real_ip(request: Request) -> str:
    # SECURITE : CF-Connecting-IP n'est fiable QUE si la requête passe par le tunnel
    # Cloudflare (Cloudflare l'injecte et écrase toute valeur cliente). En accès direct
    # (hors tunnel), un client pourrait forger ce header — l'application doit donc
    # n'être exposée QUE derrière le tunnel Cloudflare.
    #
    # On utilise CF-Connecting-IP s'il est présent, sinon l'IP directe de la connexion.
    # On ne fait JAMAIS confiance à d'autres headers forgeables (X-Forwarded-For,
    # X-Real-IP, etc.).
    cf_ip = request.headers.get("CF-Connecting-IP")
    if cf_ip:
        return cf_ip
    return request.client.host if request.client else "unknown"


limiter = Limiter(key_func=_get_real_ip)
