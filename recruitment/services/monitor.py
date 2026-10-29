"""
recruitment/services/monitor.py
===============================
Service powering the Live Invigilator Console.
Implements bounded, highly aggregated queries and incremental polling updates.
Never executes per-candidate N+1 loops.
"""

from datetime import timedelta
from django.utils import timezone
from django.db.models import Count, Q, Max, Min
from django.core.paginator import Paginator

from recruitment.models import (
    RecruitmentDrive,
    Round,
    CandidateEnrollment,
    CandidatePresence,
    IntegrityEvent,
    RoundResult,
)
from portal.models import (
    Attempt,
    Answer,
    CodeSubmission,
    CodeDraft,
    ExecutionJob,
    Question,
)


class InvigilatorMonitorService:
    STALE_THRESHOLD_SECONDS = 45
    DISCONNECTED_THRESHOLD_SECONDS = 120

    @classmethod
    def get_live_overview(cls, drive_id):
        """
        Aggregate top-level operational metrics for a drive in bounded queries.
        """
        now = timezone.now()
        drive = RecruitmentDrive.objects.get(pk=drive_id)
        enrollments = CandidateEnrollment.objects.filter(drive=drive)
        total_enrolled = enrollments.count()

        # Status counts
        scheduled_count = enrollments.filter(
            status=CandidateEnrollment.STATUS_SCHEDULED
        ).count()
        in_progress_count = enrollments.filter(
            status=CandidateEnrollment.STATUS_IN_PROGRESS
        ).count()
        awaiting_eval_count = enrollments.filter(
            status=CandidateEnrollment.STATUS_AWAITING
        ).count()
        completed_count = enrollments.filter(
            status__in=[
                CandidateEnrollment.STATUS_PASSED,
                CandidateEnrollment.STATUS_PROMOTED,
            ]
        ).count()

        # Connectivity breakdown via CandidatePresence
        stale_cutoff = now - timedelta(seconds=cls.STALE_THRESHOLD_SECONDS)
        disconnected_cutoff = now - timedelta(seconds=cls.DISCONNECTED_THRESHOLD_SECONDS)

        active_enrollment_ids = enrollments.exclude(
            status__in=CandidateEnrollment.TERMINAL_STATUSES
        ).values_list("id", flat=True)

        presences = CandidatePresence.objects.filter(enrollment_id__in=active_enrollment_ids)
        total_tracked = presences.count()

        connected_count = presences.filter(last_heartbeat__gte=stale_cutoff).count()
        stale_count = presences.filter(
            last_heartbeat__lt=stale_cutoff,
            last_heartbeat__gte=disconnected_cutoff,
        ).count()
        disconnected_count = (
            presences.filter(last_heartbeat__lt=disconnected_cutoff).count()
            + (len(active_enrollment_ids) - total_tracked)
        )

        # Code queue health
        pending_jobs = ExecutionJob.objects.filter(
            status__in=["QUEUED", "RUNNING"]
        ).count()

        # Unresolved warnings (WARNING or CRITICAL)
        unresolved_warnings = IntegrityEvent.objects.filter(
            enrollment__drive=drive,
            reviewed=False,
            severity__in=[IntegrityEvent.SEVERITY_WARNING, IntegrityEvent.SEVERITY_CRITICAL],
        ).count()

        # Deadline approaching (< 10 minutes remaining on active attempts)
        ten_mins_from_now = now + timedelta(minutes=10)
        approaching_deadline = 0
        active_attempts = Attempt.objects.filter(
            student__enrollments__drive=drive,
            submitted_at__isnull=True,
        ).select_related("exam")
        for att in active_attempts:
            if att.exam.end_time and now <= att.exam.end_time <= ten_mins_from_now:
                approaching_deadline += 1

        return {
            "drive_id": drive.id,
            "drive_name": drive.name,
            "total_enrolled": total_enrolled,
            "scheduled": scheduled_count,
            "active_sessions": in_progress_count,
            "connected_count": connected_count,
            "stale_count": stale_count,
            "disconnected_count": disconnected_count,
            "awaiting_evaluation": awaiting_eval_count,
            "completed_submissions": completed_count,
            "pending_code_jobs": pending_jobs,
            "unresolved_warnings": unresolved_warnings,
            "approaching_deadline": approaching_deadline,
            "last_updated": now.isoformat(),
        }

    @classmethod
    def get_candidate_monitor_roster(
        cls,
        drive_id,
        round_id=None,
        connection_filter=None,
        severity_filter=None,
        search=None,
        page=1,
        page_size=50,
    ):
        """
        Builds the candidate monitoring roster with bounded queries.
        Pre-aggregates answers and code progress to avoid N+1 queries.
        """
        now = timezone.now()
        qs = CandidateEnrollment.objects.filter(
            drive_id=drive_id
        ).select_related(
            "student",
            "current_round",
            "presence",
            "presence__attempt",
        )

        if round_id:
            qs = qs.filter(current_round_id=round_id)

        if search:
            search = search.strip()
            qs = qs.filter(
                Q(student__usn__icontains=search) | Q(student__name__icontains=search)
            )

        # Prefetch unreviewed warnings per enrollment
        warning_counts = dict(
            IntegrityEvent.objects.filter(
                enrollment__drive_id=drive_id,
                reviewed=False,
            )
            .values("enrollment_id")
            .annotate(cnt=Count("id"))
            .values_list("enrollment_id", "cnt")
        )

        max_severities = dict(
            IntegrityEvent.objects.filter(
                enrollment__drive_id=drive_id,
                reviewed=False,
            )
            .values("enrollment_id")
            .annotate(max_sev=Max("severity"))
            .values_list("enrollment_id", "max_sev")
        )

        # Batch-fetch active attempts
        candidate_list = list(qs.order_by("student__usn"))
        student_ids = [c.student_id for c in candidate_list]

        active_attempts = {
            a.student_id: a
            for a in Attempt.objects.filter(
                student_id__in=student_ids,
            ).select_related("exam").order_by("-started_at")
        }

        attempt_ids = [a.id for a in active_attempts.values()]

        # MCQ answers count per attempt
        mcq_answer_counts = dict(
            Answer.objects.filter(
                attempt_id__in=attempt_ids,
                selected_option__isnull=False,
            )
            .values("attempt_id")
            .annotate(cnt=Count("id"))
            .values_list("attempt_id", "cnt")
        )

        # Latest code submission per attempt
        latest_submissions = {}
        for sub in (
            CodeSubmission.objects.filter(attempt_id__in=attempt_ids)
            .order_by("attempt_id", "-created_at")
        ):
            if sub.attempt_id not in latest_submissions:
                latest_submissions[sub.attempt_id] = sub

        items = []
        for c in candidate_list:
            presence = getattr(c, "presence", None)
            conn_status = presence.connection_status if presence else "DISCONNECTED"

            if connection_filter and conn_status != connection_filter:
                continue

            unresolved_cnt = warning_counts.get(c.id, 0)
            highest_sev = max_severities.get(c.id, "NONE")

            if severity_filter and highest_sev != severity_filter:
                continue

            att = active_attempts.get(c.student_id)
            attempt_state = "Not Started"
            time_remaining_str = "—"
            start_time_str = "—"
            elapsed_mins = 0

            if att:
                if att.submitted_at:
                    attempt_state = "Submitted"
                else:
                    attempt_state = "Active"

                start_time_str = att.started_at.strftime("%H:%M:%S")
                elapsed_seconds = (now - att.started_at).total_seconds()
                elapsed_mins = int(elapsed_seconds // 60)

                if att.exam and att.exam.end_time:
                    rem_secs = max(0, (att.exam.end_time - now).total_seconds())
                    rem_mins = int(rem_secs // 60)
                    time_remaining_str = f"{rem_mins}m"
                elif c.current_round:
                    rem_secs = max(0, (c.current_round.duration_minutes * 60) - elapsed_seconds)
                    rem_mins = int(rem_secs // 60)
                    time_remaining_str = f"{rem_mins}m"

            # MCQ stats
            mcq_answered = mcq_answer_counts.get(att.id, 0) if att else 0
            mcq_total = 0
            if c.current_round and c.current_round.exam:
                mcq_total = Question.objects.filter(section__exam=c.current_round.exam).count()

            # Coding stats
            code_sub = latest_submissions.get(att.id) if att else None
            code_summary = "—"
            if code_sub:
                code_summary = f"{code_sub.verdict or 'Submitted'} ({code_sub.passed}/{code_sub.total})"

            # Last persisted
            last_persisted = presence.last_persisted_at if presence else None
            last_heartbeat = presence.last_heartbeat if presence else None

            # Next action
            next_action = "Monitor"
            if c.status == CandidateEnrollment.STATUS_AWAITING:
                next_action = "Evaluate"
            elif c.status == CandidateEnrollment.STATUS_SCHEDULED:
                next_action = "Admit"
            elif unresolved_cnt > 0:
                next_action = "Review Warnings"

            items.append({
                "enrollment_id": c.id,
                "student_usn": c.student.usn,
                "student_name": c.student.name,
                "current_round": c.current_round.name if c.current_round else "—",
                "round_type": c.current_round.round_type if c.current_round else "—",
                "enrollment_status": c.status,
                "attempt_state": attempt_state,
                "start_time": start_time_str,
                "elapsed_mins": elapsed_mins,
                "time_remaining": time_remaining_str,
                "mcq_answered": mcq_answered,
                "mcq_total": mcq_total,
                "code_summary": code_summary,
                "last_persisted_at": last_persisted.strftime("%H:%M:%S") if last_persisted else "—",
                "last_heartbeat": last_heartbeat.strftime("%H:%M:%S") if last_heartbeat else "—",
                "connection_status": conn_status,
                "unresolved_warnings": unresolved_cnt,
                "highest_severity": highest_sev,
                "next_action": next_action,
            })

        paginator = Paginator(items, page_size)
        paginated_items = paginator.get_page(page)

        return {
            "items": paginated_items,
            "total_count": len(items),
            "paginator": paginator,
        }

    @classmethod
    def get_incremental_updates(cls, drive_id, since_event_id=0, since_ts=None):
        """
        Lightweight endpoint response for live dashboard polling (every 5-10s).
        Returns new events and refreshed overview metrics without heavy DOM reloads.
        """
        now = timezone.now()
        overview = cls.get_live_overview(drive_id)

        # Fetch events created since since_event_id
        new_events_qs = IntegrityEvent.objects.filter(
            enrollment__drive_id=drive_id,
            id__gt=since_event_id,
        ).select_related("enrollment__student").order_by("id")[:50]

        events_data = []
        max_id = since_event_id
        for ev in new_events_qs:
            max_id = max(max_id, ev.id)
            events_data.append({
                "id": ev.id,
                "usn": ev.enrollment.student.usn if ev.enrollment else "unknown",
                "event_type": ev.get_event_type_display(),
                "severity": ev.severity,
                "occurred_at": ev.occurred_at.strftime("%H:%M:%S"),
                "context": ev.context,
                "reviewed": ev.reviewed,
                "acknowledged": ev.acknowledged,
            })

        return {
            "metrics": overview,
            "new_events": events_data,
            "max_event_id": max_id,
            "timestamp": now.isoformat(),
        }

