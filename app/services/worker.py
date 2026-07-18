"""
Asynchronous background worker for processing bulk CSV jobs.
Polls the SQLite database for PENDING jobs and processes them
without blocking the FastAPI event loop.
"""

from __future__ import annotations

import asyncio
import csv
import os
import time
import logging
import hashlib
from datetime import datetime
from typing import Optional
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.database import AsyncSessionLocal, UPLOAD_DIR
from app.db_models import BulkJob, VerificationLog
from app.models import PipelineContext, VerificationStatus
from app.pipeline.base_handler import BaseEmailHandler

logger = logging.getLogger("email_verifier.worker")

class BulkJobWorker:
    def __init__(self, pipeline: BaseEmailHandler):
        self.pipeline = pipeline
        self.is_running = False
        self._task: Optional[asyncio.Task] = None

    async def start(self):
        """Kicks off the background polling loop to watch for new work."""
        self.is_running = True
        self._task = asyncio.create_task(self._loop())
        logger.info("[worker] Bulk job background worker started.")

    async def stop(self):
        """Signals the worker to wind down and waits for the current task to finish."""
        self.is_running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("[worker] Bulk job background worker stopped.")

    async def _loop(self):
        """The heart of the worker—continually scans for pending work."""
        while self.is_running:
            try:
                await self._process_next_job()
            except Exception as e:
                logger.error(f"[worker] Error in worker loop: {e}")
            
            # Pause briefly so we don't hog the CPU; keep the event loop responsive.
            await asyncio.sleep(5)

    async def _process_next_job(self):
        """Finds a single task, updates status, and initiates the pipeline."""
        async with AsyncSessionLocal() as session:
            # Grab the first waiting job; keep it simple and orderly.
            result = await session.execute(
                select(BulkJob).where(BulkJob.status == "PENDING").limit(1)
            )
            job = result.scalar_one_or_none()
            
            if not job:
                return 

            # Lock the job so no other instances pick it up.
            job.status = "PROCESSING"
            await session.commit()
            
            logger.info(f"[worker] Started processing job {job.id} (File: {job.file_path})")

            # Actually run the processing logic.
            try:
                await self._process_csv(session, job)
            except Exception as e:
                logger.error(f"[worker] Job {job.id} failed: {e}")
                job.status = "FAILED"
                job.error_message = str(e)
                job.completed_at = datetime.utcnow()
                await session.commit()
            finally:
                # Security/Privacy: We wipe the raw CSV once we're done.
                # We've already hashed the emails, so keep the disk clean.
                try:
                    if os.path.exists(job.file_path):
                        os.remove(job.file_path)
                        logger.info(f"[worker] Deleted raw input CSV for job {job.id}")
                except OSError as cleanup_err:
                    logger.warning(
                        f"[worker] Could not delete input CSV for job {job.id}: {cleanup_err}"
                    )

    async def _process_csv(self, session: AsyncSession, job: BulkJob):
        """Parses the CSV, coordinates the verification pipeline, and writes output."""
        input_file = job.file_path
        if not os.path.exists(input_file):
            raise FileNotFoundError(f"Input file missing: {input_file}")

        output_filename = f"processed_{job.id}.csv"
        output_file = os.path.join(UPLOAD_DIR, output_filename)
        
        valid_cnt = 0
        invalid_cnt = 0
        susp_cnt = 0
        uncert_cnt = 0
        
        # Load the emails. For our current scope, loading these into memory is fine.
        emails = []
        with open(input_file, mode="r", encoding="utf-8", errors="replace") as f:
            reader = csv.reader(f)
            header = next(reader, None)
            if header:
                email_idx = 0
                for i, col in enumerate(header):
                    if "email" in col.lower():
                        email_idx = i
                        break
                
                # Double check if the 'header' actually contains an email (rare edge case).
                if "@" in header[email_idx] and "." in header[email_idx]:
                    emails.append(header[email_idx].strip())
            else:
                email_idx = 0
                
            for row in reader:
                if row and len(row) > email_idx:
                    email = row[email_idx].strip()
                    if email:
                        emails.append(email)

        job.total_rows = len(emails)
        await session.commit()

        # Prep our output file with clear column names.
        with open(output_file, mode="w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["email", "status", "confidence", "failed_layer", "ml_score", "reason"])

        # Process in chunks; this helps manage system resources better than a huge bulk load.
        CHUNK_SIZE = 20
        for i in range(0, len(emails), CHUNK_SIZE):
            chunk = emails[i:i+CHUNK_SIZE]
            
            # Fire off a chunk of verifications concurrently.
            tasks = [self._verify_single(email) for email in chunk]
            results = await asyncio.gather(*tasks)
            
            db_logs = []
            csv_rows = []
            
            for ctx, elapsed_ms in results:
                if ctx.status == VerificationStatus.VALID:
                    valid_cnt += 1
                elif ctx.status == VerificationStatus.INVALID:
                    invalid_cnt += 1
                elif ctx.status == VerificationStatus.SUSPICIOUS:
                    susp_cnt += 1
                else:
                    uncert_cnt += 1
                
                # Hash the email to keep our DB records anonymous.
                email_hash = hashlib.sha256(ctx.email.encode()).hexdigest()[:16]
                smtp_attempted = "smtp" in ctx.execution_times
                ml_short_circuited = ctx.stop_processing and ctx.failed_layer == "ml"
                
                log = VerificationLog(
                    job_id=job.id,
                    user_id=job.user_id,
                    email_hash=email_hash,
                    status=ctx.status.value,
                    confidence=ctx.confidence,
                    failed_layer=ctx.failed_layer.value if ctx.failed_layer else None,
                    ml_score=ctx.ml_score,
                    smtp_attempted=smtp_attempted,
                    ml_short_circuited=ml_short_circuited,
                    total_latency_ms=elapsed_ms
                )
                db_logs.append(log)
                
                # Pack the results for our CSV row output.
                reason_str = " | ".join(ctx.reasons) if ctx.reasons else ""
                csv_rows.append([
                    ctx.email,
                    ctx.status.value,
                    round(ctx.confidence, 2),
                    ctx.failed_layer.value if ctx.failed_layer else "",
                    round(ctx.ml_score, 2),
                    reason_str
                ])
                
            session.add_all(db_logs)
            
            # Keep the DB in sync with our current progress.
            job.processed_rows += len(chunk)
            job.valid_count = valid_cnt
            job.invalid_count = invalid_cnt
            job.suspicious_count = susp_cnt
            job.uncertain_count = uncert_cnt
            
            await session.commit()
            
            # Write out this batch to the physical file on disk.
            with open(output_file, mode="a", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)
                writer.writerows(csv_rows)
                
            # Let other tasks breathe before processing the next batch.
            await asyncio.sleep(0.1)

        # Job complete
        job.status = "COMPLETED"
        job.output_file_path = output_file
        job.completed_at = datetime.utcnow()
        await session.commit()
        
        logger.info(f"[worker] Job {job.id} completed. Processed {job.processed_rows} emails.")

    async def _verify_single(self, email: str) -> tuple[PipelineContext, float]:
        """Verify a single email and return context and elapsed time."""
        start = time.perf_counter()
        ctx = PipelineContext(email=email)
        try:
            ctx = await self.pipeline.handle(ctx)
        except Exception as e:
            logger.error(f"[worker] Verification failed for {email}: {e}")
            ctx.status = VerificationStatus.UNCERTAIN
            ctx.reasons.append(f"Internal error: {str(e)}")
            
        elapsed_ms = (time.perf_counter() - start) * 1000
        return ctx, elapsed_ms
