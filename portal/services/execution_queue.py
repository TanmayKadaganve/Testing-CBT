import logging
import time
from datetime import timedelta
from pathlib import Path
from django.conf import settings
from django.db import transaction, IntegrityError, OperationalError
from django.utils import timezone

from portal.models import ExecutionJob, CodeSubmission, CodeDraft, QueueAdmissionLock
from portal.runner import run_code
from portal.judge import judge

logger = logging.getLogger(__name__)

# Queue configuration limits
MAX_PER_STUDENT_CONCURRENCY = 1
MAX_QUEUE_CAPACITY = 100
ABANDONED_JOB_TIMEOUT_SECONDS = 60


def get_queue_metrics():
    """
    Returns live statistics on queue depth and processing health.
    """
    now = timezone.now()
    queued_count = ExecutionJob.objects.filter(status="QUEUED").count()
    running_count = ExecutionJob.objects.filter(status="RUNNING").count()
    completed_today = ExecutionJob.objects.filter(
        status="COMPLETED", created_at__gte=now - timedelta(hours=24)
    ).count()
    timed_out_today = ExecutionJob.objects.filter(
        status="TIMED_OUT", created_at__gte=now - timedelta(hours=24)
    ).count()
    failed_today = ExecutionJob.objects.filter(
        status="FAILED", created_at__gte=now - timedelta(hours=24)
    ).count()

    oldest_queued = ExecutionJob.objects.filter(status="QUEUED").order_by("created_at").first()
    oldest_wait_seconds = 0
    if oldest_queued:
        oldest_wait_seconds = max(0, int((now - oldest_queued.created_at).total_seconds()))

    return {
        "queued_count": queued_count,
        "running_count": running_count,
        "completed_today": completed_today,
        "timed_out_today": timed_out_today,
        "failed_today": failed_today,
        "oldest_wait_seconds": oldest_wait_seconds,
        "is_saturated": queued_count >= MAX_QUEUE_CAPACITY,
    }


def has_live_execution_worker(max_age_seconds=15):
    heartbeat_dir = Path(settings.EXECUTION_WORKER_HEARTBEAT_DIR)
    if not heartbeat_dir.exists():
        return False
    now = time.time()
    for heartbeat in heartbeat_dir.glob("*.heartbeat"):
        try:
            if now - heartbeat.stat().st_mtime <= max_age_seconds:
                return True
        except OSError:
            continue
    return False


def enqueue_job(attempt, question, kind, language, code, stdin="", run_sync_fallback=False):
    """
    Enqueues a code execution job with admission control and fairness checks.
    Returns (job, None) on success, or (None, error_dict) on admission failure.
    """
    now = timezone.now()

    if not run_sync_fallback and not has_live_execution_worker():
        return None, {
            "error": "The execution worker is not available. Your code was not queued; please contact the invigilator.",
            "busy": True,
            "status_code": 503,
        }

    try:
        with transaction.atomic():
            # Force a write to the shared singleton before reading counts. This serializes
            # admission across PostgreSQL workers and obtains SQLite's database write lock.
            QueueAdmissionLock.objects.get(pk=1)
            QueueAdmissionLock.objects.filter(pk=1).update(updated_at=now)

            queued_count = ExecutionJob.objects.filter(status="QUEUED").count()
            if queued_count >= MAX_QUEUE_CAPACITY:
                return None, {
                    "error": "The execution server is currently at maximum capacity. Please retry in a few moments.",
                    "busy": True,
                    "status_code": 503,
                }

            active_student_jobs = ExecutionJob.objects.filter(
                attempt=attempt, status__in=["QUEUED", "RUNNING"]
            ).count()
            if active_student_jobs >= MAX_PER_STUDENT_CONCURRENCY:
                return None, {
                    "error": "You already have a code execution in progress. Please wait for it to complete.",
                    "busy": True,
                    "status_code": 429,
                }

            recent_dup = ExecutionJob.objects.filter(
                attempt=attempt, question=question, kind=kind, code=code,
                status__in=["QUEUED", "RUNNING"],
                created_at__gte=now - timedelta(seconds=10),
            ).first()
            if recent_dup:
                return recent_dup, None

            job = ExecutionJob.objects.create(
                attempt=attempt, question=question, kind=kind, language=language,
                code=code, stdin=stdin or "", status="QUEUED",
            )
    except OperationalError:
        return None, {"error": "Execution queue is busy. Please retry shortly.", "busy": True, "status_code": 503}

    if run_sync_fallback:
        execute_job_sync(job)

    return job, None


def claim_next_job(worker_id="worker-default"):
    """
    Claims the next available FIFO job in a race-safe manner.
    Uses select_for_update(skip_locked=True) on PostgreSQL or transaction locking on SQLite.
    Also recovers abandoned jobs exceeding the timeout.
    """
    now = timezone.now()

    # Recovery: Reclaim stalled jobs whose worker crashed
    try:
        stalled_cutoff = now - timedelta(seconds=ABANDONED_JOB_TIMEOUT_SECONDS)
        stalled_jobs = list(ExecutionJob.objects.filter(status="RUNNING", started_at__lt=stalled_cutoff))
        for stalled in stalled_jobs:
            logger.warning("Recovering abandoned job %s (worker: %s)", stalled.id, stalled.worker_id)
            stalled.status = "FAILED"
            stalled.error_message = "Execution worker did not report back within the timeout period."
            stalled.completed_at = now
            stalled.save(update_fields=["status", "error_message", "completed_at"])
    except Exception as e:
        logger.debug("Stalled job cleanup deferred: %s", e)

    # Claim next job
    try:
        with transaction.atomic():
            job_qs = ExecutionJob.objects.filter(status="QUEUED").order_by("created_at")
            # skip_locked is supported in PostgreSQL 9.5+ and ignored on SQLite
            try:
                job = job_qs.select_for_update(skip_locked=True).first()
            except Exception:
                job = job_qs.select_for_update().first()

            if not job:
                return None

            job.status = "RUNNING"
            job.started_at = now
            job.worker_id = worker_id
            job.save(update_fields=["status", "started_at", "worker_id"])
            return job
    except Exception as e:
        logger.exception("Error claiming next job: %s", e)
        return None


def execute_job(job):
    """
    Executes a claimed job using the isolated runner and trusted judge.
    Persists results atomically.
    """
    start_time = time.perf_counter()
    now = timezone.now()

    try:
        if job.kind == "RUN":
            res = run_code(
                job.language,
                job.code,
                job.stdin,
                job.question.time_limit_seconds,
            )
            duration_ms = round((time.perf_counter() - start_time) * 1000, 2)

            job.stdout = res.get("stdout", "")
            job.stderr = res.get("stderr", "")
            job.duration_ms = duration_ms

            if res["status"] == "ok":
                job.status = "COMPLETED"
                job.verdict = "OK"
            elif res["status"] == "timeout":
                job.status = "TIMED_OUT"
                job.verdict = "Time Limit Exceeded"
            elif res["status"] == "runtime_error":
                job.status = "COMPLETED"
                job.verdict = "Runtime Error"
            elif res["status"] == "compile_error":
                job.status = "COMPLETED"
                job.verdict = "Compilation Error"
            else:
                job.status = "FAILED"
                job.verdict = "Execution Error"
                job.error_message = res.get("stderr", "Unknown error")

        elif job.kind == "SUBMIT":
            res = judge(job.question, job.language, job.code)
            duration_ms = round((time.perf_counter() - start_time) * 1000, 2)

            job.verdict = res.get("verdict", "")
            job.passed = res.get("passed", 0)
            job.total = res.get("total", 0)
            job.score = res.get("score", 0)
            job.test_results_json = res.get("results", [])
            job.duration_ms = duration_ms
            job.status = "COMPLETED"

            # Atomically record official CodeSubmission with retry for write contention
            for attempt_i in range(10):
                try:
                    with transaction.atomic():
                        CodeSubmission.objects.create(
                            attempt=job.attempt,
                            question=job.question,
                            language=job.language,
                            code=job.code,
                            verdict=job.verdict,
                            passed=job.passed,
                            total=job.total,
                            score=job.score,
                        )
                    break
                except OperationalError:
                    time.sleep(0.02 * (1.3 ** attempt_i) + 0.01)

        job.completed_at = timezone.now()
        for attempt_i in range(10):
            try:
                job.save()
                break
            except OperationalError:
                time.sleep(0.02 * (1.3 ** attempt_i) + 0.01)
        return job

    except Exception as e:
        logger.exception("Uncaught exception while processing job %s: %s", job.id, e)
        job.status = "FAILED"
        job.verdict = "Internal Error"
        job.error_message = str(e)
        job.completed_at = timezone.now()
        job.save()
        return job


def execute_job_sync(job):
    """
    Executes a newly queued job synchronously within the calling thread,
    used for immediate resolution or local developer testing without worker daemon.
    """
    job.status = "RUNNING"
    job.started_at = timezone.now()
    job.worker_id = "sync-handler"
    job.save(update_fields=["status", "started_at", "worker_id"])
    return execute_job(job)
