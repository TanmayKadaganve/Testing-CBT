import os
import signal
import sys
import threading
import time
from pathlib import Path
from django.conf import settings
from django.core.management.base import BaseCommand
from django.utils import timezone
from portal.services.execution_queue import claim_next_job, execute_job, get_queue_metrics


class Command(BaseCommand):
    help = "Runs the isolated CBT Code Execution Worker Daemon for processing queued Run and Submit jobs."

    def add_arguments(self, parser):
        parser.add_argument(
            "--worker-id",
            type=str,
            default=None,
            help="Custom identifier or prefix for this worker node (e.g. worker-01)",
        )
        parser.add_argument(
            "--concurrency",
            type=int,
            default=2,
            help="Number of concurrent worker threads (default: 2, recommended: 2-4)",
        )
        parser.add_argument(
            "--poll-interval",
            type=float,
            default=0.5,
            help="Sleep interval in seconds when no jobs are queued (default: 0.5s)",
        )
        parser.add_argument(
            "--one-shot",
            action="store_true",
            help="Process all currently queued jobs and exit (useful for test suites and cron)",
        )

    def handle(self, *args, **options):
        concurrency = max(1, options["concurrency"])
        poll_interval = options["poll_interval"]
        one_shot = options["one_shot"]
        worker_id_opt = options.get("worker_id")
        base_worker_id = worker_id_opt.strip() if worker_id_opt else f"worker-{os.getpid()}"

        self.stdout.write(
            self.style.SUCCESS(
                f"[{timezone.now().strftime('%Y-%m-%d %H:%M:%S')}] Starting CBT Execution Worker Daemon "
                f"(ID: {base_worker_id}, PID: {os.getpid()}, Concurrency: {concurrency}, Poll: {poll_interval}s)..."
            )
        )

        stop_event = threading.Event()
        heartbeat_dir = Path(settings.EXECUTION_WORKER_HEARTBEAT_DIR)
        heartbeat_dir.mkdir(exist_ok=True)
        heartbeat_file = heartbeat_dir / f"{os.getpid()}.heartbeat"

        def _signal_handler(signum, frame):
            self.stdout.write(self.style.WARNING("\nShutdown signal received. Finishing active jobs..."))
            stop_event.set()

        signal.signal(signal.SIGINT, _signal_handler)
        signal.signal(signal.SIGTERM, _signal_handler)

        def worker_loop(worker_idx):
            worker_id = f"{base_worker_id}-{worker_idx}" if concurrency > 1 else base_worker_id
            while not stop_event.is_set():
                job = claim_next_job(worker_id=worker_id)
                if job:
                    self.stdout.write(
                        f"[{worker_id}] Claimed {job.kind} job {job.id} for {job.attempt.student.usn} (Q: {job.question.id})"
                    )
                    execute_job(job)
                    self.stdout.write(
                        self.style.SUCCESS(
                            f"[{worker_id}] Completed job {job.id}: verdict='{job.verdict}', score={job.score}, duration={job.duration_ms}ms"
                        )
                    )
                else:
                    if one_shot:
                        break
                    time.sleep(poll_interval)

        threads = []
        for i in range(concurrency):
            t = threading.Thread(target=worker_loop, args=(i + 1,), daemon=True)
            t.start()
            threads.append(t)

        try:
            last_heartbeat = 0.0
            while any(t.is_alive() for t in threads) and not stop_event.is_set():
                now = time.monotonic()
                if now - last_heartbeat >= 5:
                    temp_file = heartbeat_file.with_suffix(".tmp")
                    try:
                        temp_file.write_text(timezone.now().isoformat(), encoding="utf-8")
                        os.replace(temp_file, heartbeat_file)
                    except OSError as exc:
                        self.stderr.write(self.style.ERROR(f"Cannot write worker heartbeat: {exc}"))
                    last_heartbeat = now
                time.sleep(1.0)
                if one_shot:
                    metrics = get_queue_metrics()
                    if metrics["queued_count"] == 0 and metrics["running_count"] == 0:
                        break
        except KeyboardInterrupt:
            stop_event.set()

        for t in threads:
            t.join(timeout=5.0)

        try:
            heartbeat_file.unlink(missing_ok=True)
        except OSError:
            pass

        self.stdout.write(self.style.SUCCESS("Execution Worker Daemon stopped cleanly."))
