"""
recruitment/admin_views.py
===========================
Staff-only management views for recruitment drives, rounds,
candidate lifecycle, interview panels, analytics, and overrides.
All views require staff login.
"""

import logging

from django.contrib import messages
from django.contrib.admin.views.decorators import staff_member_required
from django.contrib.auth.decorators import permission_required
from django.core.paginator import Paginator
from django.db.models import Count, Q
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_POST

import openpyxl
from openpyxl.styles import Font, PatternFill

from recruitment.models import (
    AuditLog,
    CandidateEnrollment,
    CandidatePresence,
    IntegrityEvent,
    InterviewAssignment,
    InterviewEvaluation,
    RecruitmentDrive,
    Round,
    RoundResult,
)
from recruitment.services.analytics import (
    get_all_drives_summary,
    get_candidate_timeline,
    get_drive_overview,
)
from recruitment.services.progression import apply_manual_override, process_round_results
from recruitment.services.retention import archive_enrollment, bulk_archive_failed
from recruitment.services.integrity import IntegrityEventService
from recruitment.services.monitor import InvigilatorMonitorService
from portal.services.spreadsheet import escape_formula_cells

logger = logging.getLogger(__name__)


def action_permission(codename):
    """Require staff login and the model permission for this specific operation."""
    return permission_required(f"recruitment.{codename}", login_url="/admin/login/")


# ─────────────────────────────────────────────────────────────
#  Drive list / overview
# ─────────────────────────────────────────────────────────────

@staff_member_required(login_url="/admin/login/")
@action_permission("view_recruitmentdrive")
@never_cache
def drive_list(request):
    drives = get_all_drives_summary()
    return render(
        request,
        "recruitment/drive_list.html",
        {"drives": drives, "active_nav": "recruitment"},
    )


@staff_member_required(login_url="/admin/login/")
@action_permission("view_recruitmentdrive")
@never_cache
def drive_detail(request, drive_id):
    overview = get_drive_overview(drive_id)
    return render(
        request,
        "recruitment/drive_detail.html",
        {"overview": overview, "active_nav": "recruitment"},
    )


# ─────────────────────────────────────────────────────────────
#  Drive state transitions
# ─────────────────────────────────────────────────────────────

@require_POST
@staff_member_required(login_url="/admin/login/")
@action_permission("change_recruitmentdrive")
def drive_transition(request, drive_id):
    drive = get_object_or_404(RecruitmentDrive, pk=drive_id)
    new_status = request.POST.get("new_status", "")
    reason = request.POST.get("reason", "").strip()
    try:
        drive.transition_to(new_status, actor=request.user, reason=reason)
        messages.success(
            request,
            f"Drive '{drive.name}' transitioned to {drive.get_status_display()}.",
        )
    except ValueError as exc:
        messages.error(request, str(exc))
    return redirect("recruitment:drive_detail", drive_id=drive_id)


# ─────────────────────────────────────────────────────────────
#  Candidate roster
# ─────────────────────────────────────────────────────────────

@staff_member_required(login_url="/admin/login/")
@action_permission("view_candidateenrollment")
@never_cache
def candidate_roster(request, drive_id):
    drive = get_object_or_404(RecruitmentDrive, pk=drive_id)
    search = request.GET.get("q", "").strip()
    status_filter = request.GET.get("status", "").strip()
    round_filter = request.GET.get("round_id", "").strip()

    qs = CandidateEnrollment.objects.filter(drive=drive).select_related(
        "student", "current_round"
    )

    if search:
        qs = qs.filter(
            Q(student__usn__icontains=search) | Q(student__name__icontains=search)
        )
    if status_filter:
        qs = qs.filter(status=status_filter)
    if round_filter.isdigit():
        qs = qs.filter(current_round_id=int(round_filter))

    paginator = Paginator(qs.order_by("student__usn"), 25)
    page = paginator.get_page(request.GET.get("page"))

    return render(
        request,
        "recruitment/candidate_roster.html",
        {
            "drive": drive,
            "page": page,
            "search": search,
            "status_filter": status_filter,
            "round_filter": round_filter,
            "status_choices": CandidateEnrollment.STATUS_CHOICES,
            "rounds": drive.ordered_rounds,
            "total_count": paginator.count,
            "active_nav": "recruitment",
        },
    )


@staff_member_required(login_url="/admin/login/")
@action_permission("view_candidateenrollment")
@action_permission("view_roundresult")
@action_permission("view_integrityevent")
@action_permission("view_interviewevaluation")
@never_cache
def candidate_detail_view(request, enrollment_id):
    """Full candidate timeline — all rounds, results, events, evaluations."""
    enrollment = get_object_or_404(CandidateEnrollment, pk=enrollment_id)
    timeline = get_candidate_timeline(enrollment_id)
    return render(
        request,
        "recruitment/candidate_timeline.html",
        {"timeline": timeline, "active_nav": "recruitment"},
    )


# ─────────────────────────────────────────────────────────────
#  Enrollment bulk actions
# ─────────────────────────────────────────────────────────────

@require_POST
@staff_member_required(login_url="/admin/login/")
@action_permission("add_candidateenrollment")
def enroll_students(request, drive_id):
    """
    Bulk-enroll students (by USN list) into a drive.
    Reuses existing portal.Student records — no duplicate accounts created.
    """
    from portal.models import Student
    drive = get_object_or_404(RecruitmentDrive, pk=drive_id)
    raw = request.POST.get("usn_list", "")
    usns = [u.strip().upper() for u in raw.replace(",", "\n").split() if u.strip()]

    first_round = drive.ordered_rounds.first()
    enrolled = skipped = not_found = 0
    for usn in usns:
        student = Student.objects.filter(usn=usn, is_active=True).first()
        if not student:
            not_found += 1
            continue
        enrollment, created = CandidateEnrollment.objects.get_or_create(
            drive=drive,
            student=student,
            defaults={
                "status": CandidateEnrollment.STATUS_ENROLLED,
                "current_round": first_round,
            },
        )
        if not created and not enrollment.current_round and first_round:
            enrollment.current_round = first_round
            enrollment.save(update_fields=["current_round"])

        if first_round and first_round.exam:
            first_round.exam.students.add(student)

        if created:
            AuditLog.objects.create(
                action=AuditLog.CANDIDATE_ENROLLED,
                actor=request.user,
                target_model="CandidateEnrollment",
                target_id=usn,
                new_value=drive.name,
                ip_address=request.META.get("REMOTE_ADDR"),
            )
            enrolled += 1
        else:
            skipped += 1

    messages.success(
        request,
        f"Enrolled: {enrolled} | Already enrolled: {skipped} | USN not found: {not_found}",
    )
    return redirect("recruitment:candidate_roster", drive_id=drive_id)


@require_POST
@staff_member_required(login_url="/admin/login/")
@action_permission("change_candidateenrollment")
def archive_candidate(request, enrollment_id):
    reason = request.POST.get("reason", "Archived by administrator")
    enrollment = get_object_or_404(CandidateEnrollment, pk=enrollment_id)
    drive_id = enrollment.drive_id
    archive_enrollment(enrollment_id, actor=request.user, reason=reason)
    messages.success(
        request, f"Candidate {enrollment.student.usn} archived successfully."
    )
    return redirect("recruitment:candidate_roster", drive_id=drive_id)


@require_POST
@staff_member_required(login_url="/admin/login/")
@action_permission("change_candidateenrollment")
def bulk_archive_failed_view(request, drive_id):
    count = bulk_archive_failed(drive_id, actor=request.user, reason="Bulk archive by admin")
    messages.success(request, f"{count} failed candidate(s) archived.")
    return redirect("recruitment:candidate_roster", drive_id=drive_id)


# ─────────────────────────────────────────────────────────────
#  Round processing
# ─────────────────────────────────────────────────────────────

@require_POST
@staff_member_required(login_url="/admin/login/")
@action_permission("change_roundresult")
def process_round(request, round_id):
    """Trigger the server-side promotion algorithm for a round."""
    round_obj = get_object_or_404(Round, pk=round_id)
    try:
        summary = process_round_results(round_id, triggered_by=request.user)
        messages.success(
            request,
            f"Round '{round_obj.name}' processed: "
            f"{summary['passed']} passed, {summary['failed']} failed, "
            f"{summary['skipped_already_decided']} already decided.",
        )
        if summary["errors"]:
            for err in summary["errors"]:
                messages.warning(request, f"Error: {err}")
    except Exception as exc:
        logger.exception("Error processing round %s: %s", round_id, exc)
        messages.error(request, f"Processing failed: {exc}")
    return redirect("recruitment:drive_detail", drive_id=round_obj.drive_id)


# ─────────────────────────────────────────────────────────────
#  Manual override
# ─────────────────────────────────────────────────────────────

@require_POST
@staff_member_required(login_url="/admin/login/")
@action_permission("change_roundresult")
def manual_override(request, result_id):
    """Apply an authorized manual override to a round result."""
    result = get_object_or_404(RoundResult, pk=result_id)
    new_decision = request.POST.get("new_decision", "")
    reason = request.POST.get("reason", "").strip()
    try:
        apply_manual_override(
            result_id=result_id,
            new_decision=new_decision,
            reason=reason,
            actor=request.user,
        )
        messages.success(
            request,
            f"Override applied: {result.enrollment.student.usn} "
            f"→ {new_decision}. Logged.",
        )
    except (ValueError, PermissionError) as exc:
        messages.error(request, str(exc))
    return redirect(
        "recruitment:candidate_detail_view",
        enrollment_id=result.enrollment_id,
    )


# ─────────────────────────────────────────────────────────────
#  Interview panel (interviewer-facing)
# ─────────────────────────────────────────────────────────────

@staff_member_required(login_url="/admin/login/")
@action_permission("change_interviewassignment")
@action_permission("add_interviewevaluation")
@action_permission("change_interviewevaluation")
@never_cache
def interview_panel(request, assignment_id):
    """
    Evaluation form for an assigned interviewer.
    Scope-limited: interviewer can only see their own assignments.
    """
    assignment = get_object_or_404(
        InterviewAssignment,
        pk=assignment_id,
        interviewer=request.user,
    )

    if assignment.is_locked:
        messages.warning(request, "This evaluation is locked and cannot be edited.")
        return redirect("recruitment:interview_list")

    template = assignment.template
    criteria = list(template.criteria.order_by("order")) if template else []

    existing_evals = {
        e.criterion_id: e
        for e in assignment.evaluations.select_related("criterion").all()
    }

    if request.method == "POST":
        errors = []
        evaluations_to_save = []

        for criterion in criteria:
            raw = request.POST.get(f"score_{criterion.pk}", "")
            try:
                score = int(raw)
            except (ValueError, TypeError):
                errors.append(f"Score for '{criterion.name}' is required.")
                continue
            if not (0 <= score <= criterion.max_score):
                errors.append(
                    f"Score for '{criterion.name}' must be 0–{criterion.max_score}."
                )
                continue
            notes = request.POST.get(f"notes_{criterion.pk}", "").strip()
            evaluations_to_save.append((criterion, score, notes))

        if errors:
            for err in errors:
                messages.error(request, err)
        else:
            for criterion, score, notes in evaluations_to_save:
                InterviewEvaluation.objects.update_or_create(
                    assignment=assignment,
                    criterion=criterion,
                    defaults={
                        "score": score,
                        "notes": notes,
                        "submitted_by": request.user,
                    },
                )

            # Mark assignment completed and locked
            assignment.status = InterviewAssignment.STATUS_COMPLETED
            assignment.completed_at = timezone.now()
            assignment.is_locked = True
            assignment.interview_notes = request.POST.get("interview_notes", "").strip()
            assignment.save(update_fields=[
                "status", "completed_at", "is_locked", "interview_notes"
            ])

            AuditLog.objects.create(
                action=AuditLog.EVALUATION_LOCKED,
                actor=request.user,
                target_model="InterviewAssignment",
                target_id=str(assignment.pk),
                new_value=f"Completed by {request.user.username}",
                ip_address=request.META.get("REMOTE_ADDR"),
            )

            messages.success(request, "Evaluation submitted and locked successfully.")
            return redirect("recruitment:interview_list")

    return render(
        request,
        "recruitment/interview_panel.html",
        {
            "assignment": assignment,
            "criteria": criteria,
            "existing_evals": existing_evals,
            "active_nav": "recruitment",
        },
    )


@staff_member_required(login_url="/admin/login/")
@action_permission("view_interviewassignment")
@never_cache
def interview_list(request):
    """List of interview assignments for the logged-in interviewer."""
    assignments = (
        InterviewAssignment.objects.filter(interviewer=request.user)
        .select_related(
            "enrollment__student", "round__drive", "template"
        )
        .order_by("status", "scheduled_at")
    )
    return render(
        request,
        "recruitment/interview_assignment_list.html",
        {"assignments": assignments, "active_nav": "recruitment"},
    )


# ─────────────────────────────────────────────────────────────
#  Integrity event review
# ─────────────────────────────────────────────────────────────

@staff_member_required(login_url="/admin/login/")
@action_permission("view_integrityevent")
@never_cache
def integrity_events_view(request, drive_id):
    drive = get_object_or_404(RecruitmentDrive, pk=drive_id)
    event_type_filter = request.GET.get("event_type", "").strip()
    reviewed_filter = request.GET.get("reviewed", "").strip()

    qs = IntegrityEvent.objects.filter(enrollment__drive=drive).select_related(
        "enrollment__student", "round", "reviewed_by"
    )
    if event_type_filter:
        qs = qs.filter(event_type=event_type_filter)
    if reviewed_filter == "no":
        qs = qs.filter(reviewed=False)
    elif reviewed_filter == "yes":
        qs = qs.filter(reviewed=True)

    paginator = Paginator(qs.order_by("-occurred_at"), 30)
    page = paginator.get_page(request.GET.get("page"))

    return render(
        request,
        "recruitment/integrity_events.html",
        {
            "drive": drive,
            "page": page,
            "event_type_choices": IntegrityEvent.EVENT_TYPE_CHOICES,
            "event_type_filter": event_type_filter,
            "reviewed_filter": reviewed_filter,
            "total_count": paginator.count,
            "active_nav": "recruitment",
        },
    )


# ─────────────────────────────────────────────────────────────
#  Export
# ─────────────────────────────────────────────────────────────

@staff_member_required(login_url="/admin/login/")
@action_permission("view_roundresult")
def export_results(request, drive_id):
    """Download full drive results as an Excel file."""
    drive = get_object_or_404(RecruitmentDrive, pk=drive_id)
    rounds = list(drive.ordered_rounds)

    enrollments = list(
        CandidateEnrollment.objects.filter(drive=drive)
        .select_related("student", "current_round")
        .order_by("student__usn")
    )

    # Pre-fetch all round results for this drive
    results_map: dict[tuple, RoundResult] = {}
    for rr in RoundResult.objects.filter(round__drive=drive).select_related("round"):
        results_map[(rr.enrollment_id, rr.round_id)] = rr

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Results"

    headers = (
        ["USN", "Name", "Drive Status", "Final Selected"]
        + [f"{r.name} Score %" for r in rounds]
        + [f"{r.name} Decision" for r in rounds]
    )
    ws.append(headers)
    for cell in ws[1]:
        cell.font = Font(bold=True)

    green = PatternFill("solid", fgColor="C6EFCE")
    red = PatternFill("solid", fgColor="FFC7CE")
    yellow = PatternFill("solid", fgColor="FFEB9C")

    for enrollment in enrollments:
        row = [
            enrollment.student.usn,
            enrollment.student.name,
            enrollment.get_status_display(),
            "Yes" if enrollment.final_selected else "No",
        ]
        for r in rounds:
            rr = results_map.get((enrollment.pk, r.pk))
            row.append(str(rr.percentage) if rr and rr.percentage is not None else "")
            row.append(rr.display_decision if rr else "Not Attempted")
        ws.append(row)

        # Colour decision cells
        row_num = ws.max_row
        for col_offset, r in enumerate(rounds):
            decision_col = 4 + len(rounds) + col_offset + 1
            rr = results_map.get((enrollment.pk, r.pk))
            if rr:
                cell = ws.cell(row=row_num, column=decision_col)
                if rr.decision == RoundResult.DECISION_PASS:
                    cell.fill = green
                elif rr.decision == RoundResult.DECISION_FAIL:
                    cell.fill = red
                elif rr.decision == RoundResult.DECISION_PENDING:
                    cell.fill = yellow

    # Auto-width
    for col in ws.columns:
        max_len = max(len(str(c.value)) if c.value else 0 for c in col)
        ws.column_dimensions[col[0].column_letter].width = min(max(max_len + 2, 10), 40)

    AuditLog.objects.create(
        action=AuditLog.EXPORT,
        actor=request.user,
        target_model="RecruitmentDrive",
        target_id=str(drive_id),
        new_value=f"Results export for '{drive.name}'",
        ip_address=request.META.get("REMOTE_ADDR"),
    )

    response = HttpResponse(
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
    response["Content-Disposition"] = (
        f'attachment; filename="results_drive_{drive_id}.xlsx"'
    )
    escape_formula_cells(wb).save(response)
    return response


# ─────────────────────────────────────────────────────────────
#  Live Invigilator Console Views
# ─────────────────────────────────────────────────────────────

@staff_member_required(login_url="/admin/login/")
@action_permission("view_recruitmentdrive")
@never_cache
def live_invigilator_console(request, drive_id):
    """
    Main Live Invigilator Console for real-time exam supervision.
    Provides live status metrics, candidate roster with connection/warning indicators,
    and interactive activity timelines.
    """
    drive = get_object_or_404(RecruitmentDrive, pk=drive_id)
    rounds = drive.ordered_rounds

    round_id = request.GET.get("round_id")
    connection = request.GET.get("connection")
    severity = request.GET.get("severity")
    search = request.GET.get("q", "")
    page = request.GET.get("page", 1)

    overview = InvigilatorMonitorService.get_live_overview(drive_id)
    roster = InvigilatorMonitorService.get_candidate_monitor_roster(
        drive_id=drive_id,
        round_id=int(round_id) if round_id and round_id.isdigit() and len(round_id) <= 18 else None,
        connection_filter=connection,
        severity_filter=severity,
        search=search,
        page=page,
        page_size=50,
    )

    return render(
        request,
        "recruitment/live_monitor.html",
        {
            "drive": drive,
            "rounds": rounds,
            "overview": overview,
            "roster": roster,
            "selected_round_id": round_id,
            "selected_connection": connection,
            "selected_severity": severity,
            "search_query": search,
        },
    )


@staff_member_required(login_url="/admin/login/")
@action_permission("view_recruitmentdrive")
def live_monitor_updates(request, drive_id):
    """
    JSON endpoint for lightweight incremental live polling (every 5-10 seconds).
    Returns latest overview metrics and newly created events since given ID/timestamp.
    """
    raw_event_id = request.GET.get("since_event_id", "0") or "0"
    try:
        since_event_id = int(raw_event_id)
    except (TypeError, ValueError, OverflowError):
        return JsonResponse({"ok": False, "error": "since_event_id must be a non-negative integer"}, status=400)
    if not 0 <= since_event_id <= 2**63 - 1:
        return JsonResponse({"ok": False, "error": "since_event_id is out of range"}, status=400)
    since_ts = request.GET.get("since_ts")

    updates = InvigilatorMonitorService.get_incremental_updates(
        drive_id=drive_id,
        since_event_id=since_event_id,
        since_ts=since_ts,
    )
    return JsonResponse(updates)


@staff_member_required(login_url="/admin/login/")
@action_permission("change_integrityevent")
@require_POST
def acknowledge_warning_view(request, event_id):
    """Acknowledge an integrity warning event without concluding review."""
    event = IntegrityEventService.acknowledge_event(event_id, request.user)
    if request.headers.get("x-requested-with") == "XMLHttpRequest" or "application/json" in request.headers.get("accept", ""):
        return JsonResponse({"ok": True, "event_id": event.id, "acknowledged": True})
    messages.success(request, f"Warning #{event_id} acknowledged.")
    return redirect(request.META.get("HTTP_REFERER", f"/recruitment/admin/drives/{event.round.drive_id if event.round else 1}/monitor/"))


@staff_member_required(login_url="/admin/login/")
@action_permission("change_integrityevent")
@require_POST
def review_warning_view(request, event_id):
    """Mark an integrity event as reviewed with an authorized finding note."""
    note = request.POST.get("review_note", "").strip()
    if not note:
        messages.error(request, "A review note is required to conclude review.")
        return redirect(request.META.get("HTTP_REFERER", "/recruitment/admin/drives/"))

    event = IntegrityEventService.review_event(event_id, request.user, note)
    if request.headers.get("x-requested-with") == "XMLHttpRequest" or "application/json" in request.headers.get("accept", ""):
        return JsonResponse({"ok": True, "event_id": event.id, "reviewed": True})
    messages.success(request, f"Event #{event_id} reviewed and updated.")
    return redirect(request.META.get("HTTP_REFERER", f"/recruitment/admin/drives/{event.round.drive_id if event.round else 1}/monitor/"))


@staff_member_required(login_url="/admin/login/")
@action_permission("add_integrityevent")
@require_POST
def add_invigilator_note_view(request, enrollment_id):
    """Record an official invigilator observation note into candidate history."""
    note = request.POST.get("note", "").strip()
    if not note:
        messages.error(request, "Note content cannot be empty.")
        return redirect(request.META.get("HTTP_REFERER", f"/recruitment/admin/candidates/{enrollment_id}/"))

    IntegrityEventService.add_invigilator_note(
        enrollment_id=enrollment_id,
        user=request.user,
        note=note,
        ip_address=request.META.get("REMOTE_ADDR"),
    )
    if request.headers.get("x-requested-with") == "XMLHttpRequest" or "application/json" in request.headers.get("accept", ""):
        return JsonResponse({"ok": True, "enrollment_id": enrollment_id})
    messages.success(request, "Invigilator note recorded.")
    return redirect(request.META.get("HTTP_REFERER", f"/recruitment/admin/candidates/{enrollment_id}/"))

