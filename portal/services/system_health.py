import os
import shutil
import sys
import subprocess
import time
from pathlib import Path
from django.conf import settings
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.utils import timezone


def check_system_health():
    """
    Executes real, lightweight, local system checks.
    No simulated values, no external API calls.
    Returns a dict with overall_status and list of check items.
    """
    checks = []
    overall_status = "Healthy"

    # 1. Database Connectivity & Ping
    db_status = "Healthy"
    db_detail = "Database connection is operational."
    db_latency_ms = None
    try:
        start = time.perf_counter()
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            cursor.fetchone()
        db_latency_ms = round((time.perf_counter() - start) * 1000, 2)
        db_detail = f"Connected to {connection.vendor} in {db_latency_ms} ms."
    except Exception as e:
        db_status = "Critical"
        overall_status = "Critical"
        db_detail = f"Database connection failed: {str(e)}"

    checks.append({
        "name": "Database Connectivity",
        "status": db_status,
        "detail": db_detail,
        "remediation": "Check database file permissions or engine configuration." if db_status != "Healthy" else None,
    })

    # 2. Database Migrations Status
    mig_status = "Healthy"
    mig_detail = "All database migrations are applied."
    try:
        executor = MigrationExecutor(connection)
        targets = executor.loader.graph.leaf_nodes()
        unapplied = executor.migration_plan(targets)
        if unapplied:
            mig_status = "Warning"
            if overall_status == "Healthy":
                overall_status = "Warning"
            mig_detail = f"{len(unapplied)} unapplied migration(s) detected."
    except Exception as e:
        mig_status = "Warning"
        mig_detail = f"Could not check migrations: {str(e)}"

    checks.append({
        "name": "Schema Migrations",
        "status": mig_status,
        "detail": mig_detail,
        "remediation": "Run 'python manage.py migrate' to apply pending migrations." if mig_status != "Healthy" else None,
    })

    # 3. Disk & Storage Space
    disk_status = "Healthy"
    try:
        total, used, free = shutil.disk_usage(settings.BASE_DIR)
        total_gb = round(total / (2**30), 1)
        free_gb = round(free / (2**30), 1)
        used_pct = round((used / total) * 100, 1)

        disk_detail = f"{free_gb} GB free of {total_gb} GB ({used_pct}% used)."
        if used_pct > 95:
            disk_status = "Critical"
            overall_status = "Critical"
        elif used_pct > 85:
            disk_status = "Warning"
            if overall_status == "Healthy":
                overall_status = "Warning"
    except Exception as e:
        disk_status = "Unknown"
        disk_detail = f"Could not determine disk usage: {str(e)}"

    checks.append({
        "name": "Disk Storage",
        "status": disk_status,
        "detail": disk_detail,
        "remediation": "Free up disk space on the host volume." if disk_status != "Healthy" else None,
    })

    # 4. Code execution backend: verify the actual configured isolation runtime.
    runner_status = "Healthy"
    try:
        if settings.CODE_EXECUTION_BACKEND == "container":
            runtime = settings.CODE_EXECUTION_CONTAINER_RUNTIME
            if not shutil.which(runtime):
                runner_status = "Critical"
                runner_detail = f"Configured container runtime '{runtime}' is not installed; code execution is fail-closed."
            else:
                probe = subprocess.run(
                    [runtime, "run", "--rm", "--pull=never", "--network=none",
                     settings.CODE_EXECUTION_CONTAINER_IMAGE, "sh", "-lc",
                     "python3 --version && gcc --version && g++ --version && javac -version"],
                    capture_output=True, timeout=15,
                )
                if probe.returncode:
                    runner_status = "Critical"
                    runner_detail = "Runner image, container runtime permissions, or configured toolchains failed the isolated probe."
                else:
                    runner_detail = "Runner image and Python/C/C++/Java toolchains are available."
        elif settings.CODE_EXECUTION_BACKEND == "local":
            py_path = sys.executable
            if os.path.isfile(py_path) and os.access(py_path, os.X_OK) and settings.DEBUG and settings.CODE_EXECUTION_ALLOW_UNSANDBOXED:
                runner_detail = f"Development-only local runner available at {os.path.basename(py_path)} (Python {sys.version.split()[0]})."
            else:
                runner_status = "Critical"
                runner_detail = "Unsafe or disabled host execution is not permitted by current settings."
        else:
            runner_status = "Critical"
            runner_detail = f"Unknown code execution backend: {settings.CODE_EXECUTION_BACKEND}."
    except Exception as e:
        runner_status = "Warning"
        runner_detail = f"Failed to verify Python interpreter: {str(e)}"

    checks.append({
        "name": "Code Runner Environment",
        "status": runner_status,
        "detail": runner_detail,
        "remediation": "Ensure Python virtual environment is intact." if runner_status != "Healthy" else None,
    })
    if runner_status == "Critical":
        overall_status = "Critical"
    elif runner_status == "Warning" and overall_status == "Healthy":
        overall_status = "Warning"

    # 5. Static Assets Availability
    static_status = "Healthy"
    static_detail = "Core static assets verified."
    key_assets = [
        os.path.join(settings.BASE_DIR, "portal", "static", "portal", "admin_dashboard", "css", "dashboard.css"),
        os.path.join(settings.BASE_DIR, "portal", "static", "portal", "images", "pyforgelabs-logo.png"),
    ]
    missing = [p for p in key_assets if not os.path.exists(p)]
    if missing:
        static_status = "Warning"
        static_detail = f"{len(missing)} static asset(s) missing on disk."

    checks.append({
        "name": "Static Assets",
        "status": static_status,
        "detail": static_detail,
        "remediation": "Verify static asset paths or run collectstatic." if static_status != "Healthy" else None,
    })

    # 6. Execution Job Queue & Worker Health
    queue_status = "Healthy"
    queue_detail = "Execution queue is clear and responsive."
    remediation = None
    try:
        from portal.services.execution_queue import get_queue_metrics
        qm = get_queue_metrics()
        q_cnt = qm["queued_count"]
        r_cnt = qm["running_count"]
        wait_s = qm["oldest_wait_seconds"]
        heartbeat_dir = Path(settings.EXECUTION_WORKER_HEARTBEAT_DIR)
        heartbeat_files = list(heartbeat_dir.glob("*.heartbeat")) if heartbeat_dir.exists() else []
        fresh_workers = []
        for heartbeat in heartbeat_files:
            try:
                if time.time() - heartbeat.stat().st_mtime <= 15:
                    fresh_workers.append(heartbeat)
            except OSError:
                continue
        if settings.CODE_EXECUTION_BACKEND == "container" and not fresh_workers:
            queue_status = "Critical" if q_cnt else "Warning"
            if queue_status == "Critical":
                overall_status = "Critical"
            elif overall_status == "Healthy":
                overall_status = "Warning"
            queue_detail = "No live execution worker heartbeat was found."
            remediation = "Start manage.py run_execution_worker and check its service logs."
        elif qm["is_saturated"]:
            queue_status = "Critical"
            overall_status = "Critical"
            queue_detail = f"Queue saturated: {q_cnt} jobs waiting (max capacity). Longest wait: {wait_s}s."
            remediation = "Start additional execution worker processes (manage.py run_execution_worker)."
        elif q_cnt > 20 or wait_s > 30:
            queue_status = "Warning"
            if overall_status == "Healthy":
                overall_status = "Warning"
            queue_detail = f"Elevated queue load: {q_cnt} queued, {r_cnt} running. Longest wait: {wait_s}s."
            remediation = "Monitor worker throughput or increase worker concurrency."
        else:
            queue_detail = f"Operating normally: {q_cnt} queued, {r_cnt} running, {qm['completed_today']} completed today."
    except Exception as e:
        queue_status = "Warning"
        queue_detail = f"Could not inspect execution queue: {str(e)}"

    checks.append({
        "name": "Execution Queue & Workers",
        "status": queue_status,
        "detail": queue_detail,
        "remediation": remediation,
    })

    return {
        "overall_status": overall_status,
        "checks": checks,
        "checked_at": timezone.now(),
        "python_version": sys.version.split()[0],
        "django_version": "6.1.2",
        "debug_mode": settings.DEBUG,
        "timezone": str(settings.TIME_ZONE),
    }
