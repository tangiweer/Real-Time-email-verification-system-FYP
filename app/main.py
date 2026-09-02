
import asyncio
import hashlib
import secrets
import time
import logging
from contextlib import asynccontextmanager
import uuid
import shutil
from typing import Optional, List
import os
from datetime import datetime, timedelta
from fastapi import FastAPI, Request, HTTPException, Depends, Body, UploadFile, File, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, FileResponse, RedirectResponse, Response
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

import sys
import os
from pathlib import Path

# Automatically load .env file if present
try:
    from dotenv import load_dotenv
    env_path = Path(__file__).resolve().parent.parent / ".env"
    if env_path.exists():
        load_dotenv(dotenv_path=env_path)
except ImportError:
    pass

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app.services.database import init_db, get_db_session, UPLOAD_DIR
from app.db_models import BulkJob, VerificationLog, User
from app.services.worker import BulkJobWorker
from fastapi.staticfiles import StaticFiles
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

from app.models import (
    EmailVerifyRequest, EmailVerifyResponse,
    PipelineContext, VerificationStatus, FailedLayer,
    RegistrationRequest, RegistrationResponse,
)
from app.pipeline.syntax_handler import SyntaxHandler
from app.pipeline.dns_handler import DNSHandler
from app.pipeline.ml_handler import MLHandler
from app.pipeline.smtp_handler import SMTPHandler
from app.services.disposable_cache import DisposableDomainsCache, REFRESH_INTERVAL_SECONDS
from app.core.auth import require_api_key, startup_log_message, issue_browser_token, validate_browser_token
from app.services.confirmation_service import send_confirmation_email

import json

class JSONFormatter(logging.Formatter):
    def format(self, record):
        log_record = {
            "time": self.formatTime(record, self.datefmt),
            "level": record.levelname,
            "message": record.getMessage(),
        }
        if hasattr(record, "audit_data"):
            log_record.update(record.audit_data)
        return json.dumps(log_record)

logger = logging.getLogger("email_verifier")
logger.setLevel(logging.INFO)
handler = logging.StreamHandler()
handler.setFormatter(JSONFormatter())
logger.addHandler(handler)


# Wire up the CoR chain once — order matters: syntax → dns → ml → smtp

def _build_pipeline(disposable_cache: Optional[DisposableDomainsCache] = None) -> SyntaxHandler:

    syntax = SyntaxHandler()
    dns    = DNSHandler()
    ml     = MLHandler(disposable_cache=disposable_cache)
    smtp   = SMTPHandler()
    syntax.set_next(dns).set_next(ml).set_next(smtp)
    return syntax


# Keep the disposable-domain blocklist fresh in the background

async def _disposable_cache_refresh_loop(cache: DisposableDomainsCache) -> None:

    while True:

        try:
            await asyncio.sleep(REFRESH_INTERVAL_SECONDS)
            logger.info("[background] Starting disposable domain cache refresh...")
            await cache.refresh()
            logger.info(
                f"[background] Cache refresh complete — "
                f"{cache.domain_count} domains cached."
            )
        except asyncio.CancelledError:
            logger.info("[background] Cache refresh task cancelled.")
            break
        except Exception as e:
            logger.error(f"[background] Cache refresh failed: {e}")
            # Don't let one bad refresh kill the whole loop


# Startup / shutdown orchestration

@asynccontextmanager
async def lifespan(app: FastAPI):

    # Spin up the DB before anything else touches it
    await init_db()

    # Stand up the disposable-domain cache
    disposable_cache = DisposableDomainsCache()
    app.state.disposable_cache = disposable_cache

    # Eagerly load domains so the first request isn't cold
    try:
        await disposable_cache.refresh()
        logger.info(
            f"[startup] Disposable domain cache loaded — "
            f"{disposable_cache.domain_count} domains."
        )
    except Exception as e:
        logger.warning(
            f"[startup] Initial cache refresh failed ({e}). "
            f"Using {disposable_cache.domain_count} seeded domains."
        )

    # Assemble the pipeline now that the cache is warm
    app.state.pipeline = _build_pipeline(disposable_cache=disposable_cache)

    # Force-load the RF model so the first request doesn't pay the cost
    app.state.pipeline.warmup()
    print("[startup] Email verification pipeline ready.")
    print(startup_log_message())

    # Fire off the background refresh loop
    refresh_task = asyncio.create_task(
        _disposable_cache_refresh_loop(disposable_cache)
    )

    # Start the bulk-CSV worker polling loop
    app.state.worker = BulkJobWorker(
        app.state.pipeline,
        on_verification=lambda context: manager.broadcast_verification(
            _live_event(_build_response(context), source="bulk")
        ),
    )
    await app.state.worker.start()

    yield

    # Teardown — cancel background work gracefully
    await app.state.worker.stop()
    
    refresh_task.cancel()
    try:
        await refresh_task
    except asyncio.CancelledError:
        pass
    print("[shutdown] Pipeline and workers cleaned up.")


# NOTE: API-key holders get their own bucket; everyone else is keyed by IP
def _rate_limit_key(request: Request) -> str:

    try:
        api_key = request.headers.get("x-api-key")
    except Exception:
        api_key = None
    configured = os.getenv("API_KEYS", "")
    if api_key and api_key in [k.strip() for k in configured.split(",") if k.strip()]:
        return f"api_key:{api_key}"
    return get_remote_address(request)

# Global burst cap — tight enough to discourage abuse, loose enough not to annoy legit users
limiter = Limiter(key_func=_rate_limit_key, default_limits=["300/minute", "20/second"])

# --- App bootstrap ---

app = FastAPI(
    title="Email Existence Verification Framework",
    description=(
        "A 4-layer Chain of Responsibility pipeline combining Syntax Analysis, "
        "DNS/MX Verification, Machine Learning Classification, and SMTP Diagnostics "
        "for real-time email verification during user onboarding.  "
        "Final Year Project — Staffordshire University."
    ),
    version="1.0.0",
    lifespan=lifespan,
)

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# Thin WS manager — keeps live-dashboard connections alive and fans out results
class ConnectionManager:
    def __init__(self):
        self.active_connections: List[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)

    async def broadcast_verification(self, data: dict):
        for connection in self.active_connections:
            try:
                await connection.send_json(data)
            except Exception:
                self.disconnect(connection)

manager = ConnectionManager()

# CORS — default to typical dev ports; override with ALLOWED_ORIGINS in prod
allowed_origins_env = os.getenv("ALLOWED_ORIGINS")
if allowed_origins_env:
    allow_origins = [o.strip() for o in allowed_origins_env.split(",") if o.strip()]
else:
    # Dev defaults — Vite on 3000, uvicorn on 8000
    allow_origins = [
        "http://localhost:8000",
        "http://127.0.0.1:8000",
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    ]

app.add_middleware(
    CORSMiddleware,
    allow_origins=allow_origins,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)

# Mount the Vite build output so the SPA just works™
FRONTEND_DIR = os.path.join(os.path.dirname(__file__), "../frontend/dist")
if os.path.isdir(FRONTEND_DIR):
    # Vite hashes asset filenames, so /assets/* needs its own mount
    app.mount("/assets", StaticFiles(directory=os.path.join(FRONTEND_DIR, "assets")), name="assets")

# ──────────────── API ────────────────


def _build_response(ctx: PipelineContext) -> EmailVerifyResponse:
    """Build an EmailVerifyResponse from a completed PipelineContext."""
    return EmailVerifyResponse(
        email=ctx.email,
        status=ctx.status,
        confidence=ctx.confidence,
        failed_layer=ctx.failed_layer,
        reasons=ctx.reasons if ctx.reasons else ["No issues detected."],
        suggestion=ctx.suggestion or "No action required.",
        execution_times=ctx.execution_times,
        ml_score=ctx.ml_score,
        syntax_valid=ctx.syntax_valid,
        mx_records=ctx.mx_records,
        is_disposable=ctx.is_disposable,
        smtp_deliverable=ctx.smtp_reachable,
        is_catchall=ctx.is_catchall,
        spf_present=getattr(ctx, "spf_present", False),
        dmarc_present=getattr(ctx, "dmarc_present", False),
        is_role_address=getattr(ctx, "is_role_address", False),
        domain_known_provider=getattr(ctx, "domain_known_provider", False),
        domain_tld_suspicious=getattr(ctx, "domain_tld_suspicious", False),
    )


def _hash_password(password: str) -> str:
    """Hash a password with a per-user salt using Python's memory-hard scrypt, or pbkdf2 if scrypt is unavailable."""
    salt = secrets.token_bytes(16)
    if hasattr(hashlib, "scrypt"):
        try:
            derived = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=2**14, r=8, p=1)
            return f"scrypt$16384$8$1${salt.hex()}${derived.hex()}"
        except (AttributeError, ValueError):
            pass
    derived = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 100000)
    return f"pbkdf2_sha256$100000${salt.hex()}${derived.hex()}"


def _registration_allowed(context: PipelineContext) -> bool:
    """A no-click registration needs an explicit mailbox acceptance, not a guess."""
    return context.status == VerificationStatus.VALID and context.smtp_reachable is True


@app.post("/admin/session", status_code=204, tags=["Administration"])
async def create_admin_session(api_key: str = Depends(require_api_key)):
    response = Response(status_code=204)
    response.set_cookie("ev_session", issue_browser_token(api_key, "session", 8 * 60 * 60),
                        max_age=8 * 60 * 60, httponly=True, samesite="strict",
                        secure=os.getenv("COOKIE_SECURE", "false").lower() == "true")
    return response


@app.delete("/admin/session", status_code=204, tags=["Administration"])
async def delete_admin_session():
    response = Response(status_code=204)
    response.delete_cookie("ev_session")
    return response


@app.get("/admin/ws-token", tags=["Administration"])
async def create_ws_token(api_key: str = Depends(require_api_key)):
    return {"token": issue_browser_token(api_key, "ws", 60)}


@app.websocket("/ws/live-pipeline")
async def websocket_endpoint(websocket: WebSocket):
    # A short-lived signed token avoids exposing the long-lived API key in URLs.
    if not validate_browser_token(websocket.query_params.get("token"), "ws"):
        await websocket.close(code=1008, reason="Missing or invalid API key")
        return
    await manager.connect(websocket)
    try:
        while True:
            # Hold the socket open — we only push data, never read
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(websocket)


def _live_event(response: EmailVerifyResponse, source: str = "verification") -> dict:
    """Publish an admin-only operational event without exposing the full address."""
    local, _, domain = response.email.partition("@")
    masked = f"{local[:1]}***@{domain}" if domain else "redacted"
    return {
        "email": masked,
        "email_hash": hashlib.sha256(response.email.encode()).hexdigest()[:12],
        "status": response.status.value,
        "confidence": response.confidence,
        "failed_layer": response.failed_layer.value,
        "reasons": response.reasons,
        "source": source,
        # These are operational measurements, not personal data. They allow
        # the live dashboard to explain which pipeline layers ran and where
        # time was spent for each masked verification event.
        "execution_times": response.execution_times,
        "ml_score": response.ml_score,
        "mx_record_count": len(response.mx_records),
        "smtp_deliverable": response.smtp_deliverable,
    }


async def _store_verification_log(db: AsyncSession, ctx: PipelineContext, elapsed_ms: float, owner_key: str) -> None:
    db.add(VerificationLog(
        owner_key=owner_key,
        email_hash=hashlib.sha256(ctx.email.encode()).hexdigest()[:16],
        status=ctx.status.value, confidence=ctx.confidence,
        failed_layer=ctx.failed_layer.value,
        ml_score=ctx.ml_score, smtp_attempted="smtp" in ctx.execution_times,
        ml_short_circuited=ctx.stop_processing and ctx.failed_layer == FailedLayer.ML,
        total_latency_ms=elapsed_ms,
    ))
    await db.commit()

@app.get("/health", tags=["Utilities"])
@limiter.limit("60/minute")
async def health(request: Request):

    return {
        "status": "healthy",
        "service": "Email Existence Verification Framework",
        "version": "1.0.0",
        "timestamp": time.time(),
    }


@app.get("/disposable-cache-status", tags=["Utilities"])
@limiter.limit("10/minute")
async def disposable_cache_status(request: Request):

    cache: DisposableDomainsCache = app.state.disposable_cache
    return {
        "domain_count": cache.domain_count,
        "last_refresh": cache.last_refresh,
        "last_refresh_human": (
            time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime(cache.last_refresh))
            if cache.last_refresh > 0
            else "never (using seed data)"
        ),
        "refresh_interval_hours": REFRESH_INTERVAL_SECONDS / 3600,
    }


@app.get("/pipeline-info", tags=["Utilities"])
@limiter.limit("10/minute")
async def pipeline_info(request: Request):

    return {
        "pipeline": "4-Layer Chain of Responsibility",
        "reference": "Weerakotuwa (2026) — BSc FYP, Staffordshire University",
        "layers": [
            {
                "order": 1,
                "name": "Syntax Analysis",
                "module": "syntax_handler.py",
                "description": (
                    "Validates email format against RFC 5322 / RFC 5321 rules using regex. "
                    "Rejects malformed inputs immediately with zero network calls."
                ),
                "outputs": ["pass", "invalid"],
                "latency": "< 1 ms",
            },
            {
                "order": 2,
                "name": "DNS MX Verification",
                "module": "dns_handler.py",
                "description": (
                    "Queries DNS for MX records to confirm the domain can receive email. "
                    "Gracefully handles NXDOMAIN, NoAnswer, and timeout conditions."
                ),
                "outputs": ["pass", "invalid", "uncertain"],
                "latency": "50–300 ms (network dependent)",
            },
            {
                "order": 3,
                "name": "ML Lexical Classification",
                "module": "ml_handler.py",
                "description": (
                    "Random Forest classifier with 18 lexical features detects disposable "
                    "and bot-generated addresses.  Includes QWERTY spatial distance and "
                    "consecutive consonant cluster metrics.  A Domain-Aware Heuristic Engine "
                    "with live disposable domain cache reduces false positives for culturally "
                    "diverse names."
                ),
                "outputs": ["pass", "suspicious", "invalid"],
                "latency": "< 5 ms",
            },
            {
                "order": 4,
                "name": "SMTP Handshake Diagnostics",
                "module": "smtp_handler.py",
                "description": (
                    "Performs a safe SMTP EHLO/RCPT probe (deep SMTP – high-confidence results "
                    "without sending email, SMTP handshake – Mail server accepts the recipient "
                    "(no message sent)). Detects catch-all domains via randomised canary pre-probe "
                    "and greylisted servers. Returns 'uncertain' when results are inconclusive."
                ),
                "outputs": ["valid", "invalid", "uncertain"],
                "latency": "1–8 s (network dependent, timeout-bounded)",
            },
        ],
        "status_meanings": {
            "valid": "Email passed all layers — likely deliverable.",
            "invalid": "Email definitively rejected by one layer.",
            "suspicious": "ML layer flagged as potentially disposable but not conclusive.",
            "uncertain": "SMTP/DNS inconclusive — use fallback confirmation method.",
        },
    }


@app.post(
    "/verify-email",
    response_model=EmailVerifyResponse,
    tags=["Verification"],
    summary="Verify a single email address through the 4-layer pipeline",
)
@limiter.limit("5/minute")
async def verify_email(
    request: Request,
    email_request: EmailVerifyRequest,
    api_key: str = Depends(require_api_key),
    db: AsyncSession = Depends(get_db_session),
):

    # Seed the context and let the chain do its thing
    context = PipelineContext(email=email_request.email)

    # Run through syntax → dns → ml → smtp
    start = time.perf_counter()
    context = await app.state.pipeline.handle(context)
    elapsed_ms = round((time.perf_counter() - start) * 1000, 1)
    await _store_verification_log(db, context, elapsed_ms, api_key)

    email_hash = hashlib.sha256(email_request.email.encode()).hexdigest()[:8]
    logger.info("Verification Complete", extra={"audit_data": {
        "email_hash": email_hash,
        "status": context.status.value,
        "confidence": context.confidence,
        "failed_layer": context.failed_layer.value if context.failed_layer else None,
        "execution_times": context.execution_times,
        "total_latency_ms": elapsed_ms
    }})

    # Pack the context into the response DTO
    response_data = _build_response(context)

    # Push to any connected live-dashboard WS clients
    await manager.broadcast_verification(_live_event(response_data))

    return response_data


@app.post(
    "/register",
    response_model=RegistrationResponse,
    tags=["Registration"],
    summary="Register only after automated email verification succeeds",
)
@limiter.limit("5/minute")
async def register(
    request: Request,
    registration: RegistrationRequest,
    db: AsyncSession = Depends(get_db_session),
):
    """Create an account without a confirmation link when SMTP verifies its mailbox.

    Intentionally NOT behind require_api_key — this endpoint IS how a caller
    without credentials yet gets an account. It stays open but rate-limited;
    everything downstream of account creation is gated instead.
    """
    existing = await db.execute(
        select(User).where(func.lower(User.email) == registration.email)
    )
    if existing.scalar_one_or_none():
        # Keep this indistinguishable from any other unsuccessful registration
        # so public callers cannot use this endpoint to enumerate accounts.
        return RegistrationResponse(
            registered=False,
            message="Registration could not be completed. Please try again.",
        )

    context = await app.state.pipeline.handle(PipelineContext(email=registration.email))
    verification = _build_response(context)

    # Registration remains deliberately vague to the customer. Detailed
    # diagnostic information is sent only to authenticated live dashboards.
    await manager.broadcast_verification(_live_event(verification, source="registration"))

    if context.status == VerificationStatus.INVALID:
        return RegistrationResponse(
            registered=False,
            message="Registration could not be completed. Please try again.",
        )

    confirmed_by_smtp = _registration_allowed(context)
    confirmation_token = None
    if not confirmed_by_smtp:
        confirmation_token = secrets.token_urlsafe(32)
    user = User(
        name=registration.name,
        email=registration.email,
        password_hash=_hash_password(registration.password),
        account_status="ACTIVE" if confirmed_by_smtp else "PENDING_EMAIL_CONFIRMATION",
        confirmation_token_hash=(hashlib.sha256(confirmation_token.encode()).hexdigest() if confirmation_token else None),
        confirmation_expires_at=(datetime.utcnow() + timedelta(hours=24) if confirmation_token else None),
    )
    db.add(user)
    await db.commit()

    if confirmation_token:
        try:
            await send_confirmation_email(registration.email, confirmation_token)
        except Exception as exc:
            await db.delete(user)
            await db.commit()
            logger.error("Confirmation email delivery failed: %s", exc)
            raise HTTPException(status_code=503, detail="Email confirmation is temporarily unavailable. Please try again later.")

    email_hash = hashlib.sha256(registration.email.encode()).hexdigest()[:16]
    logger.info("Registration Complete", extra={"audit_data": {
        "email_hash": email_hash,
        "status": context.status.value,
        "smtp_deliverable": context.smtp_reachable,
    }})
    return RegistrationResponse(
        registered=True,
        message=("Account created after automated email verification." if confirmed_by_smtp
                 else "Account created. Check your inbox to confirm your email address and activate it."),
        verification=verification,
    )


@app.get("/confirm-email", tags=["Registration"], include_in_schema=False)
async def confirm_email(token: str, db: AsyncSession = Depends(get_db_session)):
    token_hash = hashlib.sha256(token.encode()).hexdigest()
    result = await db.execute(select(User).where(User.confirmation_token_hash == token_hash))
    user = result.scalar_one_or_none()
    if not user or not user.confirmation_expires_at or user.confirmation_expires_at < datetime.utcnow():
        raise HTTPException(status_code=400, detail="This confirmation link is invalid or has expired.")
    user.account_status = "ACTIVE"
    user.confirmation_token_hash = None
    user.confirmation_expires_at = None
    await db.commit()
    return RedirectResponse(url="/?email_confirmed=1", status_code=303)


@app.post(
    "/verify-batch",
    response_model=list[EmailVerifyResponse],
    tags=["Verification"],
    summary="Verify a batch of email addresses (up to 50)",
)
@limiter.limit("20/minute")
async def verify_batch(
    request: Request,
    emails: list[str] = Body(...),
    api_key: str = Depends(require_api_key),
    db: AsyncSession = Depends(get_db_session),
):

    if not isinstance(emails, list) or len(emails) == 0:
        raise HTTPException(status_code=400, detail="Request must include a non-empty list of emails.")
    if len(emails) > 50:
        raise HTTPException(status_code=400, detail="Maximum 50 emails allowed per batch request.")

    sem = asyncio.Semaphore(10)

    async def _run(email: str) -> EmailVerifyResponse:
        async with sem:
            ctx = PipelineContext(email=email)
            start = time.perf_counter()
            ctx = await app.state.pipeline.handle(ctx)
            elapsed_ms = round((time.perf_counter() - start) * 1000, 1)

            response_data = _build_response(ctx)
            
            await manager.broadcast_verification(_live_event(response_data))
            return response_data

    tasks = [asyncio.create_task(_run(e)) for e in emails]
    results = await asyncio.gather(*tasks)
    # Persist aggregate evidence for the research metrics without storing emails.
    for response_data in results:
        # Context is not retained by the response; reconstruct only audit fields.
        db.add(VerificationLog(owner_key=api_key, email_hash=hashlib.sha256(response_data.email.encode()).hexdigest()[:16],
               status=response_data.status.value, confidence=response_data.confidence,
               failed_layer=response_data.failed_layer.value, ml_score=response_data.ml_score,
               smtp_attempted="smtp" in response_data.execution_times,
               ml_short_circuited=response_data.failed_layer == FailedLayer.ML,
               total_latency_ms=sum(response_data.execution_times.values())))
    await db.commit()
    return results

@app.post(
    "/jobs/upload",
    tags=["Bulk Verification"],
    summary="Upload a CSV file for bulk email verification"
)
@limiter.limit("5/minute")
async def upload_csv_job(
    request: Request,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db_session),
    api_key: str = Depends(require_api_key),
):
    if not file.filename or not file.filename.lower().endswith(".csv"):
        raise HTTPException(status_code=400, detail="Only CSV files are supported.")
    max_upload_bytes = 10 * 1024 * 1024
    content_length = request.headers.get("content-length")
    if content_length:
        try:
            if int(content_length) > max_upload_bytes:
                raise HTTPException(status_code=413, detail="CSV upload exceeds the 10 MB limit.")
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid Content-Length header.")
        
    job_id = str(uuid.uuid4())
    file_path = os.path.join(UPLOAD_DIR, f"input_{job_id}.csv")
    
    try:
        bytes_written = 0
        with open(file_path, "wb") as buffer:
            while chunk := await file.read(1024 * 1024):
                bytes_written += len(chunk)
                if bytes_written > max_upload_bytes:
                    raise HTTPException(status_code=413, detail="CSV upload exceeds the 10 MB limit.")
                buffer.write(chunk)
    except HTTPException:
        if os.path.exists(file_path):
            os.remove(file_path)
        raise
    except Exception as e:
        if os.path.exists(file_path):
            os.remove(file_path)
        raise HTTPException(status_code=500, detail=f"Failed to save file: {e}")
        
    # Persist the job metadata so the worker can pick it up.
    # owner_key ties this job to the caller so /jobs/{id}* can enforce that
    # only the uploader (or an unauthenticated caller in REQUIRE_AUTH=false
    # mode) can check status or download results.
    new_job = BulkJob(
        id=job_id,
        file_path=file_path,
        status="PENDING",
        owner_key=api_key,
    )
    db.add(new_job)
    await db.commit()
    
    return {"job_id": job_id, "status": "PENDING", "message": "File uploaded successfully and queued for processing."}


def _assert_job_owner(job: BulkJob, api_key: str) -> None:
    """Reject access to a job that wasn't created by this caller.

    Legacy rows created before this migration have owner_key=None; treat
    those as unclaimed rather than silently public or silently locked out.
    """
    if job.owner_key is not None and job.owner_key != api_key:
        raise HTTPException(status_code=403, detail="You do not have access to this job.")


@app.get(
    "/jobs/{job_id}",
    tags=["Bulk Verification"],
    summary="Check the status of a bulk verification job"
)
@limiter.limit("30/minute")
async def get_job_status(
    request: Request,
    job_id: str,
    db: AsyncSession = Depends(get_db_session),
    api_key: str = Depends(require_api_key),
):
    result = await db.execute(select(BulkJob).where(BulkJob.id == job_id))
    job = result.scalar_one_or_none()
    
    if not job:
        raise HTTPException(status_code=404, detail="Job not found.")

    _assert_job_owner(job, api_key)

    return {
        "job_id": job.id,
        "status": job.status,
        "total_rows": job.total_rows,
        "processed_rows": job.processed_rows,
        "progress_percent": round((job.processed_rows / job.total_rows * 100), 1) if job.total_rows > 0 else 0,
        "results": {
            "valid": job.valid_count,
            "invalid": job.invalid_count,
            "suspicious": job.suspicious_count,
            "uncertain": job.uncertain_count
        },
        "created_at": job.created_at,
        "completed_at": job.completed_at,
        "error_message": job.error_message
    }

@app.get(
    "/jobs/{job_id}/download",
    tags=["Bulk Verification"],
    summary="Download the processed CSV file"
)
@limiter.limit("10/minute")
async def download_job_results(
    request: Request,
    job_id: str,
    db: AsyncSession = Depends(get_db_session),
    api_key: str = Depends(require_api_key),
):
    result = await db.execute(select(BulkJob).where(BulkJob.id == job_id))
    job = result.scalar_one_or_none()
    
    if not job:
        raise HTTPException(status_code=404, detail="Job not found.")

    _assert_job_owner(job, api_key)

    if job.status != "COMPLETED" or not job.output_file_path:
        raise HTTPException(status_code=400, detail="Job is not completed yet.")
        
    if not os.path.exists(job.output_file_path):
        raise HTTPException(status_code=404, detail="Processed file not found on disk.")
        
    return FileResponse(
        path=job.output_file_path,
        media_type="text/csv",
        filename=f"verified_emails_{job_id}.csv"
    )

@app.get(
    "/analytics/dashboard",
    tags=["Analytics"],
    summary="Get aggregate analytics for the dashboard"
)
@limiter.limit("10/minute")
async def get_dashboard_analytics(
    request: Request,
    db: AsyncSession = Depends(get_db_session),
    api_key: str = Depends(require_api_key),
):
    # Aggregate counts — nothing fancy, just group-by queries
    total_result = await db.execute(select(func.count(VerificationLog.id)).where(VerificationLog.owner_key == api_key))
    total_emails = total_result.scalar() or 0
    
    # Breakdown by status category
    status_result = await db.execute(
        select(VerificationLog.status, func.count(VerificationLog.id))
        .where(VerificationLog.owner_key == api_key)
        .group_by(VerificationLog.status)
    )
    status_counts = {row[0]: row[1] for row in status_result.all()}
    
    # How many SMTP probes did the ML layer save us?
    ml_saved_result = await db.execute(
        select(func.count(VerificationLog.id))
        .where(VerificationLog.ml_short_circuited == True, VerificationLog.owner_key == api_key)
    )
    ml_saved_probes = ml_saved_result.scalar() or 0
    
    return {
        "total_emails_verified": total_emails,
        "status_distribution": {
            "valid": status_counts.get("valid", 0),
            "invalid": status_counts.get("invalid", 0),
            "suspicious": status_counts.get("suspicious", 0),
            "uncertain": status_counts.get("uncertain", 0)
        },
        "ml_contribution": {
            "smtp_probes_saved": ml_saved_probes,
            "saved_percentage": round((ml_saved_probes / total_emails * 100), 1) if total_emails > 0 else 0
        }
    }


# SPA fallback — any route that isn't an API endpoint gets index.html
@app.get("/{full_path:path}", include_in_schema=False)
async def serve_spa(full_path: str):
    index_path = os.path.join(FRONTEND_DIR, "index.html")
    if os.path.exists(index_path):
        with open(index_path, "r") as f:
            return HTMLResponse(content=f.read())
    return HTMLResponse(content="<h2>Frontend not built. Run npm run build in frontend directory.</h2>")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True)
