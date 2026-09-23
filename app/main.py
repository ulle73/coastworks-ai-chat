import asyncio
import contextlib
import logging
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

import aiohttp
from bs4 import BeautifulSoup
from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, EmailStr, Field

from app.config import settings
from app.core.crawl_target import CrawlTargetValidationError, validate_crawl_target
from app.crawl import CrawlFailure, Fetcher
from app.db import one, pool, transaction
from app.email import send_claim
from app.knowledge import answer
from app.security import (
    client_key,
    digest,
    normalize_url,
    origin,
    rate_limit,
    require_first_party,
    require_owner,
    require_preview,
    secret,
    signer,
    widget_identity,
)

log = logging.getLogger("coastworks.api")


@asynccontextmanager
async def lifespan(app):
    await pool.open(wait=True)
    worker_task = None
    if settings.EMBEDDED_WORKER:
        from app.worker import run_loop

        worker_task = asyncio.create_task(run_loop(), name="embedded-worker")
        log.info("embedded_worker_started")
    try:
        yield
    finally:
        if worker_task is not None:
            worker_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await worker_task
        await pool.close()


app = FastAPI(
    title="Coastworks", lifespan=lifespan, docs_url=None if settings.ENVIRONMENT == "production" else "/docs"
)


@app.middleware("http")
async def boundaries(request: Request, call_next):
    request_id = str(uuid.uuid4())
    try:
        content_length = int(request.headers.get("content-length", "0") or 0)
    except ValueError:
        return JSONResponse({"detail": "Ogiltig begäran."}, status_code=400)
    if content_length > 16000:
        return JSONResponse({"detail": "För mycket innehåll."}, status_code=413)
    # Bound chunked request bodies as well, before JSON decoding.
    if request.method in {"POST", "PUT", "PATCH"}:
        body = bytearray()
        async for part in request.stream():
            body.extend(part)
            if len(body) > 16000:
                return JSONResponse({"detail": "För mycket innehåll."}, status_code=413)
        request._body = bytes(body)
    cors_origin = None
    if request.url.path.startswith("/api/widget/"):
        caller = request.headers.get("origin")
        try:
            bot_id = uuid.UUID(request.url.path.split("/")[3])
            async with transaction() as db:
                bot = await one(db, "SELECT origin,published FROM bots WHERE id=%s", (bot_id,))
            if bot and bot["published"] and caller == bot["origin"]:
                cors_origin = caller
        except ValueError:
            pass
        if request.method == "OPTIONS":
            response = Response(status_code=204 if cors_origin else 403)
        else:
            response = await call_next(request)
    else:
        response = await call_next(request)
    if cors_origin:
        response.headers.update(
            {
                "Access-Control-Allow-Origin": cors_origin,
                "Vary": "Origin",
                "Access-Control-Allow-Methods": "POST, OPTIONS",
                "Access-Control-Allow-Headers": "Content-Type, Authorization",
            }
        )
    response.headers["X-Request-ID"] = request_id
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    if request.url.path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-store"
    ancestors = "https: http:" if request.url.path.startswith("/embed/") else "'none'"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
        "img-src 'self' data:; connect-src 'self'; font-src 'self'; object-src 'none'; "
        f"base-uri 'none'; form-action 'self'; frame-ancestors {ancestors}"
    )
    if settings.ENVIRONMENT == "production":
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    return response


class URLInput(BaseModel):
    url: str = Field(min_length=3, max_length=2048)


class Question(BaseModel):
    message: str = Field(min_length=1, max_length=2000)


class ClaimInput(BaseModel):
    email: EmailStr


class ConfirmInput(BaseModel):
    token: str = Field(min_length=32, max_length=200)


class ManagedInput(ClaimInput):
    website: str = Field(min_length=3, max_length=2048)
    message: str = Field(min_length=10, max_length=4000)


def cookie(response, name, token, age):
    response.set_cookie(
        name,
        token,
        httponly=True,
        secure=settings.ENVIRONMENT == "production",
        samesite="lax",
        max_age=age,
        path="/",
    )


async def load_bot(db, bot_id):
    bot = await one(
        db, "SELECT * FROM bots WHERE id=%s AND (owner_email IS NOT NULL OR expires_at>now())", (bot_id,)
    )
    if not bot:
        raise HTTPException(404, "Assistenten finns inte eller har löpt ut.")
    return bot


def public_bot(bot):
    return {
        "id": str(bot["id"]),
        "url": bot["url"],
        "state": bot["state"],
        "quality": bot["quality"],
        "published": bot["published"],
        "message": "Vi kunde inte läsa tillräckligt av hemsidan. Försök med en annan adress eller låt oss hjälpa dig."
        if bot["state"] == "failed"
        else None,
    }


@app.get("/health/live")
async def live():
    return {"status": "ok"}


@app.get("/health/ready")
async def ready():
    async with transaction() as db:
        await db.execute("SELECT 1 FROM schema_migrations LIMIT 1")
    return {"status": "ok"}


@app.post("/api/previews", status_code=202)
async def create_preview(body: URLInput, request: Request, response: Response):
    require_first_party(request)
    # Spend admission is committed even when subsequent URL validation fails.
    async with transaction() as db:
        await rate_limit(db, "create:" + client_key(request), 5, 3600)
        await rate_limit(db, "global:crawls", settings.GLOBAL_CRAWLS_PER_DAY, 86400)
    try:
        url = normalize_url(body.url)
        await validate_crawl_target(url)
    except (ValueError, CrawlTargetValidationError):
        raise HTTPException(422, "Vi behöver en publik hemsida som går att nå.")
    token = request.cookies.get("cw_preview") or secret()
    bot_id, job_id = uuid.uuid4(), uuid.uuid4()
    async with transaction() as db:
        await rate_limit(db, "domain:" + digest(origin(url)), 10, 86400)
        await db.execute(
            "INSERT INTO bots(id,url,origin,preview_hash,install_nonce,expires_at) VALUES(%s,%s,%s,%s,%s,now()+(%s * interval '1 hour'))",
            (bot_id, url, origin(url), digest(token), secret(), settings.PREVIEW_HOURS),
        )
        await db.execute("INSERT INTO jobs(id,bot_id) VALUES(%s,%s)", (job_id, bot_id))
    cookie(response, "cw_preview", token, settings.PREVIEW_HOURS * 3600)
    return {"id": str(bot_id), "state": "queued"}


@app.get("/api/bots/{bot_id}")
async def status(bot_id: uuid.UUID, request: Request):
    async with transaction() as db:
        bot = await load_bot(db, bot_id)
        try:
            require_preview(request, bot)
        except HTTPException:
            require_owner(request, bot)
    return public_bot(bot)


@app.post("/api/bots/{bot_id}/chat")
async def preview_chat(bot_id: uuid.UUID, body: Question, request: Request):
    require_first_party(request)
    async with transaction() as db:
        bot = await load_bot(db, bot_id)
        try:
            require_preview(request, bot)
        except HTTPException:
            require_owner(request, bot)
        await rate_limit(db, "preview:chat:" + str(bot_id), 30, 86400)
        await rate_limit(db, "global:messages", settings.GLOBAL_MESSAGES_PER_DAY, 86400)
    if not bot["active_version"]:
        raise HTTPException(409, "Vi förbereder fortfarande din assistent.")
    return await safe_answer(
        bot, body.message, digest(request.cookies.get("cw_preview") or request.cookies.get("cw_owner", ""))
    )


async def safe_answer(bot, message, session):
    try:
        return await answer(bot, message, session)
    except Exception as exc:
        log.warning("chat_failed bot=%s type=%s", bot["id"], type(exc).__name__)
        raise HTTPException(503, "Det gick inte att svara just nu. Försök igen om en stund.")


@app.post("/api/bots/{bot_id}/claim", status_code=202)
async def claim(bot_id: uuid.UUID, body: ClaimInput, request: Request):
    require_first_party(request)
    token = secret()
    email = str(body.email).lower()
    async with transaction() as db:
        bot = await load_bot(db, bot_id)
        require_preview(request, bot)
        if not bot["active_version"]:
            raise HTTPException(409, "Prova assistenten när den är klar först.")
        if bot["owner_email"] and bot["owner_email"] != email:
            raise HTTPException(409, "Assistenten har redan kopplats till en e-postadress.")
        await rate_limit(db, "email:ip:" + client_key(request), 5, 3600)
        await rate_limit(db, "email:" + digest(email), 3, 3600)
        await db.execute(
            "INSERT INTO email_tokens(token_hash,bot_id,email,expires_at) VALUES(%s,%s,%s,now()+interval '15 minutes')",
            (digest(token), bot_id, email),
        )
    try:
        await send_claim(email, token)
    except Exception:
        async with transaction() as db:
            await db.execute("DELETE FROM email_tokens WHERE token_hash=%s", (digest(token),))
        raise HTTPException(503, "Mejlet kunde inte skickas. Försök igen om en stund.")
    return {"message": "Kolla din inkorg. Där finns länken till din installationskod."}


@app.post("/api/confirm")
async def confirm(body: ConfirmInput, request: Request, response: Response):
    require_first_party(request)
    async with transaction() as db:
        await rate_limit(db, "confirm:" + client_key(request), 20, 3600)
        token = await one(
            db,
            "UPDATE email_tokens SET used_at=now() WHERE token_hash=%s AND used_at IS NULL AND expires_at>now() RETURNING *",
            (digest(body.token),),
        )
        if not token:
            raise HTTPException(400, "Länken är redan använd eller har löpt ut.")
        bot = await one(
            db,
            "UPDATE bots SET owner_email=%s WHERE id=%s AND (owner_email IS NULL OR owner_email=%s) RETURNING *",
            (token["email"], token["bot_id"], token["email"]),
        )
        if not bot:
            raise HTTPException(409, "Assistenten tillhör redan ett annat konto.")
    cookie(response, "cw_owner", signer.dumps({"email": token["email"]}, salt="owner-v1"), 86400 * 7)
    return public_bot(bot)


@app.post("/api/access", status_code=202)
async def recover_access(body: ClaimInput, request: Request):
    require_first_party(request)
    email = str(body.email).lower()
    token = secret()
    async with transaction() as db:
        await rate_limit(db, "email:ip:" + client_key(request), 5, 3600)
        await rate_limit(db, "email:" + digest(email), 3, 3600)
        bot = await one(
            db, "SELECT id FROM bots WHERE owner_email=%s ORDER BY created_at DESC LIMIT 1", (email,)
        )
        if bot:
            await db.execute(
                "INSERT INTO email_tokens(token_hash,bot_id,email,expires_at) VALUES(%s,%s,%s,now()+interval '15 minutes')",
                (digest(token), bot["id"], email),
            )
    if bot:
        try:
            await send_claim(email, token)
        except Exception:
            async with transaction() as db:
                await db.execute("DELETE FROM email_tokens WHERE token_hash=%s", (digest(token),))
            log.warning("access_email_failed")
    # Always identical response, including SMTP failure: do not expose customer membership.
    return {"message": "Om adressen har en sparad assistent skickar vi en länk till din inkorg."}


@app.get("/api/bots/{bot_id}/installation")
async def installation(bot_id: uuid.UUID, request: Request):
    async with transaction() as db:
        bot = await load_bot(db, bot_id)
        require_owner(request, bot)
    return {
        "code": f'<script src="{settings.PUBLIC_API_ORIGIN or settings.APP_ORIGIN}/widget.js" data-bot="{bot_id}" data-install="{bot["install_nonce"]}" defer></script>',
        "published": bot["published"],
    }


@app.post("/api/bots/{bot_id}/publish")
async def publish(bot_id: uuid.UUID, request: Request):
    require_first_party(request)
    async with transaction() as db:
        bot = await load_bot(db, bot_id)
        require_owner(request, bot)
        await rate_limit(db, "publish:" + str(bot_id), 10, 3600)
    try:
        async with Fetcher() as fetcher:
            status_code, html, _ = await fetcher.get(bot["url"], allowed_origin=bot["origin"])
        soup = BeautifulSoup(html, "html.parser")
        found = soup.find(
            "script",
            attrs={
                "src": (settings.PUBLIC_API_ORIGIN or settings.APP_ORIGIN) + "/widget.js",
                "data-bot": str(bot_id),
                "data-install": bot["install_nonce"],
            },
        )
        if status_code != 200 or not found:
            raise CrawlFailure("INSTALL_NOT_FOUND")
    except (CrawlFailure, ValueError, aiohttp.ClientError, TimeoutError):
        raise HTTPException(
            409, "Vi hittar inte koden på hemsidan ännu. Publicera ändringen och försök igen."
        )
    async with transaction() as db:
        await db.execute(
            "UPDATE bots SET published=true WHERE id=%s AND active_version IS NOT NULL", (bot_id,)
        )
    return {"published": True}


@app.post("/api/widget/{bot_id}/session")
async def widget_session(bot_id: uuid.UUID, request: Request):
    async with transaction() as db:
        bot = await load_bot(db, bot_id)
        if not bot["published"] or request.headers.get("origin") != bot["origin"]:
            raise HTTPException(403, "Chatten är inte tillgänglig här.")
        await rate_limit(db, "widget:session:" + client_key(request), 40, 3600)
    return {"token": signer.dumps({"bot": str(bot_id), "session": secret()})}


@app.post("/api/widget/{bot_id}/chat")
async def widget_chat(bot_id: uuid.UUID, body: Question, request: Request):
    identity = widget_identity(request, str(bot_id))
    async with transaction() as db:
        bot = await load_bot(db, bot_id)
        if not bot["published"]:
            raise HTTPException(403, "Chatten är inte tillgänglig just nu.")
        await rate_limit(db, "widget:ip:" + client_key(request), 60, 3600)
        await rate_limit(db, "widget:bot:" + str(bot_id), 200, 86400)
        await rate_limit(db, "global:messages", settings.GLOBAL_MESSAGES_PER_DAY, 86400)
    return await safe_answer(bot, body.message, digest(identity))


@app.post("/api/managed", status_code=201)
async def managed(body: ManagedInput, request: Request):
    require_first_party(request)
    async with transaction() as db:
        await rate_limit(db, "managed:" + client_key(request), 3, 86400)
        await db.execute(
            "INSERT INTO managed_requests(id,email,website,message) VALUES(%s,%s,%s,%s)",
            (uuid.uuid4(), str(body.email).lower(), body.website, body.message),
        )
    return {"message": "Tack! Din förfrågan är sparad. Vi återkommer via e-post."}


@app.delete("/api/bots/{bot_id}", status_code=204)
async def delete_bot(bot_id: uuid.UUID, request: Request):
    require_first_party(request)
    async with transaction() as db:
        bot = await load_bot(db, bot_id)
        require_owner(request, bot)
        await db.execute("DELETE FROM bots WHERE id=%s", (bot_id,))


dist = Path("web/dist")
if dist.exists():
    app.mount("/assets", StaticFiles(directory=dist / "assets"), name="assets")


@app.get("/widget.js")
async def widget_js():
    return FileResponse(
        "web/public/widget.js",
        media_type="application/javascript",
        headers={"Cache-Control": "public, max-age=300"},
    )


@app.get("/assets-local.css")
async def local_styles():
    return FileResponse("web/public/assets-local.css", media_type="text/css")


@app.get("/")
@app.get("/embed/{bot_id}")
async def frontend(bot_id: uuid.UUID | None = None):
    if not dist.exists():
        raise HTTPException(503, "Gränssnittet behöver byggas först.")
    return FileResponse(dist / "index.html", headers={"Cache-Control": "no-cache"})
