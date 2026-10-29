"""
recruitment/services/integrity.py
=================================
Service for recording, evaluating, deduplicating, and reviewing exam integrity events.
Key principles:
- Events are browser-observable signals, never definitive proof of misconduct.
- Automatic escalation from INFO to WARNING based on configurable Round thresholds.
- Deduplication within a rolling 10-second window to prevent alert flooding.
- Rate limiting to protect against malicious client loops.
"""

from datetime import timedelta
from django.utils import timezone
from django.core.cache import cache
from django.db import transaction

from recruitment.models import (
    CandidateEnrollment,
    IntegrityEvent,
    Round,
    AuditLog,
)
from portal.models import Attempt


class IntegrityEventService:
    DEDUPLICATION_WINDOW_SECONDS = 10
    RATE_LIMIT_WINDOW_SECONDS = 60
    MAX_EVENTS_PER_WINDOW = 30
    RATE_LIMIT_PREFIX = "integrity_rate_limit"

    @classmethod
    def record_event(
        cls,
        student,
        event_type,
        context=None,
        attempt_id=None,
        ip_address=None,
    ):
        """
        Record a browser or system integrity event.
        Validates event type, rate-limits, deduplicates within rolling window,
        and determines appropriate severity level based on round thresholds.
        """
        if context is None:
            context = {}

        now = timezone.now()

        # 1. Rate limiting per student
        rate_key = f"{cls.RATE_LIMIT_PREFIX}:{student.id}"
        event_count = cache.get(rate_key, 0)
        if event_count >= cls.MAX_EVENTS_PER_WINDOW:
            return {
                "status": "rate_limited",
                "message": "Too many integrity events reported in short interval.",
            }
        cache.set(rate_key, event_count + 1, timeout=cls.RATE_LIMIT_WINDOW_SECONDS)

        # 2. Resolve active enrollment & round
        enrollment = (
            CandidateEnrollment.objects.filter(
                student=student,
                drive__status="ACTIVE",
            )
            .select_related("current_round", "drive")
            .first()
        )
        if not enrollment:
            enrollment = (
                CandidateEnrollment.objects.filter(student=student)
                .exclude(status__in=CandidateEnrollment.TERMINAL_STATUSES)
                .select_related("current_round", "drive")
                .first()
            )

        current_round = enrollment.current_round if enrollment else None

        # 3. Resolve attempt
        attempt = None
        if attempt_id:
            attempt = Attempt.objects.filter(id=attempt_id, student=student).first()
        elif current_round and current_round.exam:
            attempt = Attempt.objects.filter(
                student=student,
                exam=current_round.exam,
                submitted_at__isnull=True,
            ).first()

        # 4. Deduplication Check:
        # If an unreviewed event of the same type for this enrollment occurred within 10s, merge it.
        window_start = now - timedelta(seconds=cls.DEDUPLICATION_WINDOW_SECONDS)
        recent_event = (
            IntegrityEvent.objects.filter(
                enrollment=enrollment,
                event_type=event_type,
                occurred_at__gte=window_start,
                reviewed=False,
            )
            .order_by("-occurred_at")
            .first()
        )

        if recent_event:
            # Increment repetition count in context instead of inserting new row
            repeat_count = recent_event.context.get("repeat_count", 1) + 1
            recent_event.context["repeat_count"] = repeat_count
            recent_event.context.update(context)
            recent_event.save(update_fields=["context"])
            return {
                "status": "deduplicated",
                "event_id": recent_event.id,
                "severity": recent_event.severity,
                "repeat_count": repeat_count,
            }

        # 5. Determine Severity
        severity = IntegrityEvent.SEVERITY_INFO

        if event_type == IntegrityEvent.EVENT_TAB_HIDDEN:
            # Count past tab switches in current round
            tab_switches = (
                IntegrityEvent.objects.filter(
                    enrollment=enrollment,
                    round=current_round,
                    event_type=IntegrityEvent.EVENT_TAB_HIDDEN,
                ).count()
                + 1
            )
            context["tab_switch_count"] = tab_switches
            threshold = (
                current_round.tab_switch_warning_threshold
                if current_round
                else 3
            )
            if tab_switches >= threshold:
                severity = IntegrityEvent.SEVERITY_WARNING

        elif event_type == IntegrityEvent.EVENT_FULLSCREEN_EXIT:
            fs_exits = (
                IntegrityEvent.objects.filter(
                    enrollment=enrollment,
                    round=current_round,
                    event_type=IntegrityEvent.EVENT_FULLSCREEN_EXIT,
                ).count()
                + 1
            )
            context["fullscreen_exit_count"] = fs_exits
            threshold = (
                current_round.fullscreen_exit_warning_threshold
                if current_round
                else 2
            )
            if fs_exits >= threshold:
                severity = IntegrityEvent.SEVERITY_WARNING

        elif event_type in (
            IntegrityEvent.EVENT_UNSAVED_DRAFT,
            IntegrityEvent.EVENT_JOB_TIMEOUT,
            IntegrityEvent.EVENT_DUPLICATE_LOGIN,
            IntegrityEvent.EVENT_SUBMIT_RATE,
        ):
            severity = IntegrityEvent.SEVERITY_WARNING

        # The client can fabricate these reports. Preserve threshold calculations as
        # triage context, but never assign disciplinary warning severity from a browser.
        context["threshold_indicator"] = severity
        severity = IntegrityEvent.SEVERITY_INFO
        context["evidence_source"] = "candidate_browser_report"
        context["review_required"] = True

        # 6. Insert new event record
        event = IntegrityEvent.objects.create(
            enrollment=enrollment,
            attempt=attempt,
            round=current_round,
            event_type=event_type,
            severity=severity,
            client_ip=ip_address,
            context=context,
        )

        return {
            "status": "recorded",
            "event_id": event.id,
            "severity": event.severity,
            "occurred_at": event.occurred_at.isoformat(),
        }

    @classmethod
    def acknowledge_event(cls, event_id, user):
        """Acknowledge a warning event without concluding disciplinary review."""
        now = timezone.now()
        event = IntegrityEvent.objects.get(pk=event_id)
        event.acknowledged = True
        event.acknowledged_by = user
        event.acknowledged_at = now
        event.save(update_fields=["acknowledged", "acknowledged_by", "acknowledged_at"])

        AuditLog.objects.create(
            action=AuditLog.WARNING_ACKNOWLEDGED,
            actor=user,
            target_model="IntegrityEvent",
            target_id=str(event.id),
            reason=f"Acknowledged {event.get_event_type_display()} for {event.enrollment.student.usn if event.enrollment else 'unknown'}",
        )
        return event

    @classmethod
    def review_event(cls, event_id, user, review_note):
        """Conclude human review of an integrity event with an authorized finding note."""
        now = timezone.now()
        event = IntegrityEvent.objects.get(pk=event_id)
        event.reviewed = True
        event.reviewed_by = user
        event.reviewed_at = now
        event.review_note = review_note
        event.save(update_fields=["reviewed", "reviewed_by", "reviewed_at", "review_note"])

        AuditLog.objects.create(
            action=AuditLog.INTEGRITY_REVIEW,
            actor=user,
            target_model="IntegrityEvent",
            target_id=str(event.id),
            reason=f"Reviewed event {event.id}: {review_note[:100]}",
        )
        return event

    @classmethod
    def add_invigilator_note(cls, enrollment_id, user, note, ip_address=None):
        """Record an explicit human invigilator observation into candidate audit history."""
        enrollment = CandidateEnrollment.objects.get(pk=enrollment_id)
        event = IntegrityEvent.objects.create(
            enrollment=enrollment,
            round=enrollment.current_round,
            event_type=IntegrityEvent.EVENT_INVIGILATOR_NOTE,
            severity=IntegrityEvent.SEVERITY_INFO,
            context={"note": note, "author": user.get_full_name() or user.username},
            reviewed=True,
            reviewed_by=user,
            reviewed_at=timezone.now(),
            review_note=note,
            client_ip=ip_address,
        )

        AuditLog.objects.create(
            action=AuditLog.INVIGILATOR_NOTE,
            actor=user,
            target_model="CandidateEnrollment",
            target_id=str(enrollment.id),
            reason=f"Invigilator note added: {note[:100]}",
            ip_address=ip_address,
        )
        return event

