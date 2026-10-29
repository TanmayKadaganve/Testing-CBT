"""
recruitment/views.py
====================
Candidate-facing views for the recruitment portal.
Admin/staff views are in admin_views.py.
"""

import logging

from django.contrib import messages
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_POST

from portal.views import get_student
from recruitment.models import (
    AuditLog,
    CandidateEnrollment,
    CandidatePresence,
    IntegrityEvent,
    RecruitmentDrive,
    Round,
    RoundResult,
    CandidateRoundSession,
)
from recruitment.services.presence import CandidatePresenceService
from recruitment.services.integrity import IntegrityEventService

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────
#  Candidate dashboard
# ─────────────────────────────────────────────────────────────

@never_cache
def candidate_dashboard(request):
    """
    Shows the student's active recruitment drives, current round, and status.
    Only shows drives where the student is enrolled and the drive is ACTIVE.
    """
    student = get_student(request)
    if not student:
        return redirect("login")

    enrollments = (
        CandidateEnrollment.objects.filter(
            student=student,
            drive__status__in=[
                RecruitmentDrive.STATUS_ACTIVE,
                RecruitmentDrive.STATUS_CLOSED,
            ],
        )
        .select_related("drive", "current_round")
        .prefetch_related("round_results__round")
        .order_by("-drive__start_date")
    )

    return render(
        request,
        "recruitment/candidate_dashboard.html",
        {
            "student": student,
            "enrollments": enrollments,
        },
    )


@never_cache
def round_instructions(request, drive_id, round_id):
    """
    Pre-round instructions page. Candidate must confirm before entering.
    Validates eligibility, availability, and enrollment status.
    """
    student = get_student(request)
    if not student:
        return redirect("login")

    enrollment = get_object_or_404(
        CandidateEnrollment,
        student=student,
        drive_id=drive_id,
    )
    round_obj = get_object_or_404(Round, pk=round_id, drive_id=drive_id)

    now = timezone.now()
    error = None

    # Eligibility checks
    if enrollment.drive.status != RecruitmentDrive.STATUS_ACTIVE:
        error = "This recruitment drive is not active. You cannot enter a round."
    elif enrollment.status not in CandidateEnrollment.ACTIVE_STATUSES:
        error = (
            f"Your status for this drive is '{enrollment.get_status_display()}'. "
            "You cannot enter this round."
        )
    elif not enrollment.current_round_id:
        error = "No current round is assigned to your enrollment. Please contact the coordinator."
    elif enrollment.current_round_id != round_obj.pk:
        error = (
            f"You are not assigned to this round. "
            f"Your current round is: {enrollment.current_round.name}."
        )
    elif round_obj.start_time and now < round_obj.start_time:
        secs = int((round_obj.start_time - now).total_seconds())
        error = f"This round has not started yet. It begins in {secs // 60}m {secs % 60}s."
    elif round_obj.end_time and now >= round_obj.end_time:
        error = "This round has ended."
    elif round_obj.max_attempts != 1:
        error = "This round has an unsupported retry setting. Please contact the coordinator."
    else:
        round_session = CandidateRoundSession.objects.filter(
            enrollment=enrollment, round=round_obj
        ).first()
        if round_session and now >= round_session.deadline_at:
            error = "Your time for this round has ended."

    if request.method == "POST" and not error:
        if not request.POST.get("agree"):
            error = "Please read and accept the examination rules to continue."
        else:
            from recruitment.services.round_sessions import start_or_get_round_session
            try:
                round_session = start_or_get_round_session(enrollment, round_obj)
            except ValueError as exc:
                error = str(exc)
                round_session = None
            if error:
                return render(request, "recruitment/round_instructions.html", {
                    "enrollment": enrollment, "round": round_obj, "drive": enrollment.drive,
                    "error": error, "now": now,
                }, status=400)
            # Mark candidate as in-progress for this round
            if enrollment.status != CandidateEnrollment.STATUS_IN_PROGRESS:
                enrollment.set_status(
                    CandidateEnrollment.STATUS_IN_PROGRESS,
                    reason=f"Started round: {round_obj.name}",
                )
            # For automated rounds: redirect to the linked exam
            if round_obj.is_automated and round_obj.exam:
                round_obj.exam.students.add(student)
                return redirect("instructions")  # Portal exam instructions page
            # For human-evaluated rounds: show the interview waiting page
            return redirect("recruitment:interview_waiting", pk=round_obj.pk)

    return render(
        request,
        "recruitment/round_instructions.html",
        {
            "enrollment": enrollment,
            "round": round_obj,
            "drive": enrollment.drive,
            "error": error,
            "now": now,
        },
    )


@never_cache
def interview_waiting(request, pk):
    """
    Candidate waiting room for human-evaluated rounds.
    Shows interview schedule and confirms check-in.
    """
    student = get_student(request)
    if not student:
        return redirect("login")

    round_obj = get_object_or_404(Round, pk=pk)
    enrollment = get_object_or_404(
        CandidateEnrollment,
        student=student,
        drive=round_obj.drive,
    )

    session = CandidateRoundSession.objects.filter(enrollment=enrollment, round=round_obj).first()
    if (enrollment.drive.status != RecruitmentDrive.STATUS_ACTIVE
            or enrollment.status not in CandidateEnrollment.ACTIVE_STATUSES
            or enrollment.current_round_id != round_obj.pk
            or not session
            or timezone.now() >= session.deadline_at):
        return redirect("recruitment:candidate_dashboard")

    from recruitment.models import InterviewAssignment
    assignment = InterviewAssignment.objects.filter(
        enrollment=enrollment, round=round_obj
    ).first()

    return render(
        request,
        "recruitment/interview_waiting.html",
        {
            "enrollment": enrollment,
            "round": round_obj,
            "assignment": assignment,
        },
    )


@never_cache
def candidate_round_result(request, enrollment_id, round_id):
    """
    Shows the candidate's result for a specific round after it has been decided.
    Does NOT expose: passing thresholds (only whether they passed),
    answer keys, other candidates' data, or interviewer notes.
    """
    student = get_student(request)
    if not student:
        return redirect("login")

    enrollment = get_object_or_404(
        CandidateEnrollment,
        pk=enrollment_id,
        student=student,
    )
    result = get_object_or_404(
        RoundResult,
        enrollment=enrollment,
        round_id=round_id,
    )

    # Only show decided results
    if result.decision == RoundResult.DECISION_PENDING:
        return render(
            request,
            "recruitment/result_pending.html",
            {"round": result.round},
        )

    return render(
        request,
        "recruitment/candidate_round_result.html",
        {
            "enrollment": enrollment,
            "result": result,
            "round": result.round,
        },
    )


# ─────────────────────────────────────────────────────────────
#  Heartbeat & Integrity endpoints
# ─────────────────────────────────────────────────────────────

@require_POST
def candidate_heartbeat(request):
    """
    Receives candidate presence heartbeat (recommended every 15 seconds).
    Updates CandidatePresence in-place with rate-limiting and connection state classification.
    """
    student = get_student(request)
    if not student:
        return JsonResponse({"ok": False, "error": "Not logged in"}, status=403)

    import json
    data = {}
    if request.body:
        try:
            data = json.loads(request.body)
        except ValueError:
            return JsonResponse({"ok": False, "error": "Bad payload"}, status=400)
        if not isinstance(data, dict):
            return JsonResponse({"ok": False, "error": "Expected a JSON object"}, status=400)

    attempt_id = data.get("attempt_id")
    if attempt_id not in (None, ""):
        from portal.views import parse_positive_id
        attempt_id = parse_positive_id(attempt_id)
        if attempt_id is None:
            return JsonResponse({"ok": False, "error": "Invalid attempt_id"}, status=400)
    user_agent = request.META.get("HTTP_USER_AGENT", "")
    ip_address = request.META.get("REMOTE_ADDR")

    result = CandidatePresenceService.record_heartbeat(
        student=student,
        attempt_id=attempt_id,
        ip_address=ip_address,
        user_agent=user_agent,
    )
    return JsonResponse({"ok": True, **result})


@require_POST
def record_integrity_event(request):
    """
    Receives browser-observable exam integrity events.
    Enforces deduplication within rolling window and sets severity levels.
    """
    student = get_student(request)
    if not student:
        return JsonResponse({"ok": False, "error": "Not logged in"}, status=403)

    import json
    try:
        data = json.loads(request.body)
    except (ValueError, KeyError):
        return JsonResponse({"ok": False, "error": "Bad payload"}, status=400)
    if not isinstance(data, dict):
        return JsonResponse({"ok": False, "error": "Expected a JSON object"}, status=400)

    event_type = data.get("event_type", "")
    if not isinstance(event_type, str):
        return JsonResponse({"ok": False, "error": "event_type must be a string"}, status=400)
    valid_types = {et for et, _ in IntegrityEvent.EVENT_TYPE_CHOICES}
    if event_type not in valid_types:
        return JsonResponse({"ok": False, "error": "Unknown event type"}, status=400)

    # Non-sensitive context only — never store code, answers, or sensitive data
    try:
        elapsed_raw = data.get("elapsed_seconds", 0) or 0
        count_raw = data.get("event_count", 1) or 1
        if isinstance(elapsed_raw, float) and not elapsed_raw.is_integer():
            raise ValueError
        if isinstance(count_raw, float) and not count_raw.is_integer():
            raise ValueError
        elapsed_seconds = int(elapsed_raw)
        event_count = int(count_raw)
    except (TypeError, ValueError, OverflowError):
        return JsonResponse({"ok": False, "error": "Numeric event fields must be integers"}, status=400)
    if not 0 <= elapsed_seconds <= 86400 or not 1 <= event_count <= 100:
        return JsonResponse({"ok": False, "error": "Numeric event fields are out of range"}, status=400)
    attempt_id = data.get("attempt_id")
    if attempt_id not in (None, ""):
        from portal.views import parse_positive_id
        attempt_id = parse_positive_id(attempt_id)
        if attempt_id is None:
            return JsonResponse({"ok": False, "error": "Invalid attempt_id"}, status=400)
    safe_context = {
        "client_ts": str(data.get("client_ts", ""))[:50],
        "elapsed_seconds": elapsed_seconds,
        "event_count": 1,
        "evidence_source": "candidate_browser_report",
        "review_required": True,
    }

    result = IntegrityEventService.record_event(
        student=student,
        event_type=event_type,
        context=safe_context,
        attempt_id=attempt_id,
        ip_address=request.META.get("REMOTE_ADDR"),
    )

    flagged = result.get("severity") in [
        IntegrityEvent.SEVERITY_WARNING,
        IntegrityEvent.SEVERITY_CRITICAL,
    ]
    return JsonResponse({"ok": True, "flagged": flagged, **result})

