"""
recruitment/services/presence.py
================================
Service for managing candidate connectivity, heartbeats, and presence status.
Follows strict performance and isolation principles:
- Updates existing CandidatePresence in-place; NEVER inserts a row per heartbeat.
- Derives student and attempt from authenticated server-side context.
- Rate limits heartbeats to prevent LAN saturation.
"""

from datetime import timedelta
from django.utils import timezone
from django.core.cache import cache
from django.db import transaction

from recruitment.models import (
    CandidateEnrollment,
    CandidatePresence,
    Round,
)
from portal.models import Attempt


class CandidatePresenceService:
    MIN_HEARTBEAT_INTERVAL_SECONDS = 5
    RATE_LIMIT_CACHE_PREFIX = "hb_rate_limit"

    @classmethod
    def record_heartbeat(
        cls,
        student,
        attempt_id=None,
        ip_address=None,
        user_agent="",
        activity_type="HEARTBEAT",
    ):
        """
        Record an authenticated heartbeat for a student.
        Enforces rate-limiting and updates or creates CandidatePresence.
        Returns a dict: {'status': 'ok'|'rate_limited', 'connection_status': 'CONNECTED', ...}
        """
        now = timezone.now()

        # 1. Rate limiting check (in-memory cache or fast check)
        rate_key = f"{cls.RATE_LIMIT_CACHE_PREFIX}:{student.id}"
        last_req = cache.get(rate_key)
        if last_req:
            # Client sent heartbeats faster than minimum interval
            return {
                "status": "rate_limited",
                "message": f"Heartbeat interval too fast (<{cls.MIN_HEARTBEAT_INTERVAL_SECONDS}s)",
                "server_time": now.isoformat(),
            }
        cache.set(rate_key, now.timestamp(), timeout=cls.MIN_HEARTBEAT_INTERVAL_SECONDS)

        # 2. Find student's active enrollment
        enrollment = (
            CandidateEnrollment.objects.filter(
                student=student,
                drive__status="ACTIVE",
            )
            .select_related("current_round", "drive")
            .first()
        )

        if not enrollment:
            # Fall back to any non-terminal enrollment
            enrollment = (
                CandidateEnrollment.objects.filter(student=student)
                .exclude(status__in=CandidateEnrollment.TERMINAL_STATUSES)
                .select_related("current_round", "drive")
                .first()
            )

        if not enrollment:
            return {
                "status": "no_active_enrollment",
                "message": "Candidate is not actively enrolled in an active drive.",
                "server_time": now.isoformat(),
            }

        # 3. Resolve attempt if provided or lookup active attempt
        attempt = None
        if attempt_id:
            attempt = Attempt.objects.filter(id=attempt_id, student=student).first()
        elif enrollment.current_round and enrollment.current_round.exam:
            attempt = Attempt.objects.filter(
                student=student,
                exam=enrollment.current_round.exam,
                submitted_at__isnull=True,
            ).first()

        # 4. Atomic upsert of CandidatePresence
        with transaction.atomic():
            presence, created = CandidatePresence.objects.select_for_update().get_or_create(
                enrollment=enrollment,
                defaults={
                    "attempt": attempt,
                    "last_heartbeat": now,
                    "last_activity_type": activity_type,
                    "client_ip": ip_address,
                    "user_agent": (user_agent or "")[:255],
                },
            )
            if not created:
                presence.last_heartbeat = now
                presence.last_activity_type = activity_type
                if attempt:
                    presence.attempt = attempt
                if ip_address:
                    presence.client_ip = ip_address
                if user_agent:
                    presence.user_agent = user_agent[:255]
                presence.save(
                    update_fields=[
                        "last_heartbeat",
                        "last_activity_type",
                        "attempt",
                        "client_ip",
                        "user_agent",
                    ]
                )

        return {
            "status": "ok",
            "connection_status": presence.connection_status,
            "seconds_since_heartbeat": 0,
            "server_time": now.isoformat(),
        }

    @classmethod
    def record_activity(cls, student, activity_type, attempt=None, ip_address=None):
        """
        Record that a candidate persisted meaningful data (e.g. answer save, code draft, submission).
        Updates last_persisted_at and last_heartbeat.
        """
        now = timezone.now()
        enrollment = CandidateEnrollment.objects.filter(
            student=student,
        ).exclude(status__in=CandidateEnrollment.TERMINAL_STATUSES).first()

        if not enrollment:
            return

        with transaction.atomic():
            presence, created = CandidatePresence.objects.select_for_update().get_or_create(
                enrollment=enrollment,
                defaults={
                    "attempt": attempt,
                    "last_heartbeat": now,
                    "last_activity_type": activity_type,
                    "last_persisted_at": now,
                    "client_ip": ip_address,
                },
            )
            if not created:
                presence.last_heartbeat = now
                presence.last_persisted_at = now
                presence.last_activity_type = activity_type
                if attempt:
                    presence.attempt = attempt
                if ip_address:
                    presence.client_ip = ip_address
                presence.save(
                    update_fields=[
                        "last_heartbeat",
                        "last_persisted_at",
                        "last_activity_type",
                        "attempt",
                        "client_ip",
                    ]
                )

