"""
recruitment/services/analytics.py
===================================
Real DB-backed analytics for the recruitment dashboard.
No invented statistics — all metrics query actual rows.
"""

from django.db.models import Count, Q, Avg
from django.utils import timezone

from recruitment.models import (
    RecruitmentDrive,
    Round,
    CandidateEnrollment,
    RoundResult,
    IntegrityEvent,
    InterviewAssignment,
)


def get_drive_overview(drive_id):
    """Returns enrollment/round summary metrics for a single drive."""
    drive = RecruitmentDrive.objects.get(pk=drive_id)
    enrollments = CandidateEnrollment.objects.filter(drive=drive)

    status_counts = dict(
        enrollments.values_list("status")
        .annotate(n=Count("id"))
        .values_list("status", "n")
    )

    rounds = list(drive.ordered_rounds)
    round_stats = []
    for r in rounds:
        results = RoundResult.objects.filter(round=r)
        round_stats.append({
            "round": r,
            "total": results.count(),
            "passed": results.filter(decision=RoundResult.DECISION_PASS).count(),
            "failed": results.filter(decision=RoundResult.DECISION_FAIL).count(),
            "pending": results.filter(decision=RoundResult.DECISION_PENDING).count(),
            "absent": results.filter(decision=RoundResult.DECISION_ABSENT).count(),
            "avg_percentage": results.filter(
                percentage__isnull=False
            ).aggregate(avg=Avg("percentage"))["avg"],
        })

    pending_evaluations = InterviewAssignment.objects.filter(
        round__drive=drive,
        status__in=[
            InterviewAssignment.STATUS_SCHEDULED,
            InterviewAssignment.STATUS_IN_PROGRESS,
        ],
    ).count()

    unreviewed_integrity = IntegrityEvent.objects.filter(
        enrollment__drive=drive,
        reviewed=False,
    ).count()

    return {
        "drive": drive,
        "status_counts": status_counts,
        "total_enrolled": enrollments.count(),
        "total_selected": enrollments.filter(final_selected=True).count(),
        "in_progress": enrollments.filter(
            status=CandidateEnrollment.STATUS_IN_PROGRESS
        ).count(),
        "awaiting_evaluation": enrollments.filter(
            status=CandidateEnrollment.STATUS_AWAITING
        ).count(),
        "round_stats": round_stats,
        "pending_evaluations": pending_evaluations,
        "unreviewed_integrity": unreviewed_integrity,
    }


def get_all_drives_summary():
    """Lightweight summary of all drives for the top-level admin overview."""
    return list(
        RecruitmentDrive.objects.annotate(
            enrolled_count=Count("enrollments", distinct=True),
            selected_count=Count(
                "enrollments",
                filter=Q(enrollments__final_selected=True),
                distinct=True,
            ),
        ).order_by("-created_at")
    )


def get_candidate_timeline(enrollment_id):
    """
    Returns the complete event timeline for one candidate enrollment:
    round results, integrity events, audit log entries.
    """
    from recruitment.models import AuditLog

    enrollment = CandidateEnrollment.objects.select_related(
        "student", "drive", "current_round"
    ).get(pk=enrollment_id)

    round_results = list(
        RoundResult.objects.filter(enrollment=enrollment)
        .select_related("round", "attempt", "decided_by")
        .order_by("round__order")
    )

    integrity_events = list(
        IntegrityEvent.objects.filter(enrollment=enrollment)
        .order_by("-occurred_at")[:50]
    )

    audit_entries = list(
        AuditLog.objects.filter(
            target_model="CandidateEnrollment",
            target_id=str(enrollment_id),
        ).order_by("-timestamp")[:50]
    )

    assignments = list(
        InterviewAssignment.objects.filter(enrollment=enrollment)
        .select_related("round", "interviewer", "template")
        .prefetch_related("evaluations__criterion")
        .order_by("round__order")
    )

    return {
        "enrollment": enrollment,
        "round_results": round_results,
        "integrity_events": integrity_events,
        "audit_entries": audit_entries,
        "assignments": assignments,
    }

