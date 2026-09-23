import hashlib
import hmac
import secrets
from urllib.parse import urlsplit, urlunsplit

from fastapi import HTTPException, Request
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from app.config import settings
from app.db import one

signer = URLSafeTimedSerializer(settings.SECRET_KEY, salt="widget-session-v1")


def digest(value: str) -> str:
    return hmac.new(settings.SECRET_KEY.encode(), value.encode(), hashlib.sha256).hexdigest()


def secret() -> str:
    return secrets.token_urlsafe(32)


def normalize_url(value: str) -> str:
    value = value.strip()
    if "://" not in value:
        value = "https://" + value
    parsed = urlsplit(value)
    if (
        parsed.scheme not in {"https", "http"}
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.port not in {None, 80, 443}
        or any(ord(c) < 33 or c in "\\<>\"'`" for c in value)
    ):
        raise ValueError("Ange en publik webbadress med http eller https.")
    host = parsed.hostname.encode("idna").decode().lower()
    if ":" in host:
        host = f"[{host}]"
    port = (
        f":{parsed.port}" if parsed.port and parsed.port != (443 if parsed.scheme == "https" else 80) else ""
    )
    return urlunsplit((parsed.scheme, host + port, parsed.path or "/", "", ""))


def origin(url: str) -> str:
    parts = urlsplit(url)
    return f"{parts.scheme}://{parts.netloc}"


def require_first_party(request: Request):
    if request.headers.get("origin") != settings.APP_ORIGIN:
        raise HTTPException(403, "Öppna tjänsten i din webbläsare och försök igen.")


def require_preview(request: Request, bot):
    token = request.cookies.get("cw_preview", "")
    if not token or not hmac.compare_digest(digest(token), bot["preview_hash"]):
        raise HTTPException(404, "Assistenten finns inte eller har löpt ut.")


def require_owner(request: Request, bot):
    token = request.cookies.get("cw_owner", "")
    try:
        data = signer.loads(token, salt="owner-v1", max_age=86400 * 7)
    except (BadSignature, SignatureExpired):
        raise HTTPException(401, "Bekräfta din e-post för att fortsätta.")
    if not bot["owner_email"] or data.get("email") != bot["owner_email"]:
        raise HTTPException(404, "Assistenten finns inte.")


def widget_identity(request: Request, bot_id: str):
    authorization = request.headers.get("authorization", "")
    try:
        data = signer.loads(authorization.removeprefix("Bearer "), max_age=900)
    except (BadSignature, SignatureExpired):
        raise HTTPException(401, "Ladda om chatten för att fortsätta.")
    if data.get("bot") != bot_id or not data.get("session"):
        raise HTTPException(403, "Chatten kunde inte öppnas.")
    return data["session"]


async def rate_limit(connection, key: str, limit: int, seconds: int):
    row = await one(
        connection,
        """
      INSERT INTO rate_limits(key,count,expires_at) VALUES(%s,1,now()+(%s * interval '1 second'))
      ON CONFLICT(key) DO UPDATE SET
        count=CASE WHEN rate_limits.expires_at<=now() THEN 1 ELSE rate_limits.count+1 END,
        expires_at=CASE WHEN rate_limits.expires_at<=now() THEN EXCLUDED.expires_at ELSE rate_limits.expires_at END
      RETURNING count
    """,
        (key, seconds),
    )
    if row["count"] > limit:
        raise HTTPException(
            429, "Lite många försök just nu. Försök igen senare.", headers={"Retry-After": str(seconds)}
        )


def client_key(request: Request):
    # The reverse proxy must replace forwarded headers; uvicorn trusts only explicitly configured peers.
    return digest(request.client.host if request.client else "unknown")
