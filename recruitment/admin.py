"""
recruitment/admin.py
====================
Django admin registrations for all recruitment models.
Provides full CRUD for drive management, round configuration,
candidate enrollment, interview templates, and audit review.
"""

from django.contrib import admin, messages
from django.db import transaction
from django.http import HttpResponse
from django.utils import timezone
from django.utils.html import format_html
import openpyxl

from .models import (
    RecruitmentDrive,
    Round,
    CandidateEnrollment,
    CandidatePresence,
    RoundResult,
    InterviewTemplate,
    RubricCriterion,
    InterviewAssignment,
    InterviewEvaluation,
    IntegrityEvent,
    AuditLog,
)
from portal.services.spreadsheet import escape_formula_cells


# ─────────────────────────────────────────────────────────────
#  Inline classes
# ─────────────────────────────────────────────────────────────

class RoundInline(admin.TabularInline):
    model = Round
    extra = 1
    fields = (
        "order", "name", "round_type", "start_time", "end_time",
        "pass_threshold_percent", "is_mandatory", "exam",
    )
    ordering = ["order"]
    show_change_link = True


class RubricCriterionInline(admin.TabularInline):
    model = RubricCriterion
    extra = 2
    fields = ("order", "name", "max_score", "weight", "description")
    ordering = ["order"]


class InterviewEvaluationInline(admin.TabularInline):
    model = InterviewEvaluation
    extra = 0
    readonly_fields = ("criterion", "score", "notes", "submitted_at", "submitted_by")
    can_delete = False

    def has_add_permission(self, request, obj=None):
        return False


# ─────────────────────────────────────────────────────────────
#  Admin actions
# ─────────────────────────────────────────────────────────────

@admin.action(description="Publish selected drives (Draft → Published)")
def publish_drives(modeladmin, request, queryset):
    count = 0
    errors = []
    for drive in queryset:
        try:
            drive.transition_to(
                RecruitmentDrive.STATUS_PUBLISHED,
                actor=request.user,
                reason="Bulk published via admin action",
            )
            count += 1
        except ValueError as e:
            errors.append(f"{drive.name}: {e}")
    if count:
        modeladmin.message_user(request, f"{count} drive(s) published.", messages.SUCCESS)
    for err in errors:
        modeladmin.message_user(request, err, messages.ERROR)


@admin.action(description="Activate selected drives (Published → Active)")
def activate_drives(modeladmin, request, queryset):
    count = 0
    errors = []
    for drive in queryset:
        try:
            drive.transition_to(
                RecruitmentDrive.STATUS_ACTIVE,
                actor=request.user,
                reason="Bulk activated via admin action",
            )
            count += 1
        except ValueError as e:
            errors.append(f"{drive.name}: {e}")
    if count:
        modeladmin.message_user(request, f"{count} drive(s) activated.", messages.SUCCESS)
    for err in errors:
        modeladmin.message_user(request, err, messages.ERROR)


@admin.action(description="Close selected drives (Active/Paused → Closed)")
def close_drives(modeladmin, request, queryset):
    count = 0
    errors = []
    for drive in queryset:
        try:
            drive.transition_to(
                RecruitmentDrive.STATUS_CLOSED,
                actor=request.user,
                reason="Bulk closed via admin action",
            )
            count += 1
        except ValueError as e:
            errors.append(f"{drive.name}: {e}")
    if count:
        modeladmin.message_user(request, f"{count} drive(s) closed.", messages.SUCCESS)
    for err in errors:
        modeladmin.message_user(request, err, messages.ERROR)


@admin.action(description="Export selected enrollments (Excel)")
def export_enrollments(modeladmin, request, queryset):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Enrollments"
    headers = [
        "USN", "Name", "Drive", "Status", "Current Round",
        "Final Selected", "Enrolled At",
    ]
    ws.append(headers)
    for cell in ws[1]:
        cell.font = openpyxl.styles.Font(bold=True)

    for enrollment in queryset.select_related(
        "student", "drive", "current_round"
    ).order_by("drive__name", "student__usn"):
        ws.append([
            enrollment.student.usn,
            enrollment.student.name,
            enrollment.drive.name,
            enrollment.get_status_display(),
            enrollment.current_round.name if enrollment.current_round else "",
            "Yes" if enrollment.final_selected else "No",
            timezone.localtime(enrollment.enrolled_at).strftime("%Y-%m-%d %H:%M"),
        ])

    response = HttpResponse(
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
    response["Content-Disposition"] = 'attachment; filename="enrollments.xlsx"'
    escape_formula_cells(wb).save(response)

    AuditLog.objects.create(
        action=AuditLog.EXPORT,
        actor=request.user,
        target_model="CandidateEnrollment",
        target_id="bulk",
        new_value=f"Exported {queryset.count()} enrollment(s)",
        ip_address=request.META.get("REMOTE_ADDR"),
    )
    return response


@admin.action(description="Archive selected enrollments (remove from active roster)")
def archive_enrollments(modeladmin, request, queryset):
    count = 0
    for enrollment in queryset:
        if enrollment.status not in CandidateEnrollment.TERMINAL_STATUSES:
            enrollment.set_status(
                CandidateEnrollment.STATUS_ARCHIVED,
                actor=request.user,
                reason="Bulk archived via admin action",
                log_action=AuditLog.CANDIDATE_ARCHIVED,
            )
            count += 1
    modeladmin.message_user(
        request,
        f"{count} enrollment(s) archived. Already-terminal records were skipped.",
        messages.SUCCESS,
    )


@admin.action(description="Mark selected integrity events as reviewed")
def mark_integrity_reviewed(modeladmin, request, queryset):
    now = timezone.now()
    updated = queryset.filter(reviewed=False).update(
        reviewed=True,
        reviewed_by=request.user,
        reviewed_at=now,
    )
    AuditLog.objects.create(
        action=AuditLog.INTEGRITY_REVIEW,
        actor=request.user,
        target_model="IntegrityEvent",
        target_id="bulk",
        new_value=f"Marked {updated} event(s) as reviewed",
        ip_address=request.META.get("REMOTE_ADDR"),
    )
    modeladmin.message_user(request, f"{updated} event(s) marked as reviewed.", messages.SUCCESS)


@admin.action(description="Acknowledge selected integrity warnings")
def acknowledge_warnings(modeladmin, request, queryset):
    now = timezone.now()
    updated = queryset.filter(acknowledged=False).update(
        acknowledged=True,
        acknowledged_by=request.user,
        acknowledged_at=now,
    )
    AuditLog.objects.create(
        action=AuditLog.WARNING_ACKNOWLEDGED,
        actor=request.user,
        target_model="IntegrityEvent",
        target_id="bulk",
        new_value=f"Acknowledged {updated} warning(s)",
        ip_address=request.META.get("REMOTE_ADDR"),
    )
    modeladmin.message_user(request, f"{updated} warning(s) acknowledged.", messages.SUCCESS)


# ─────────────────────────────────────────────────────────────
#  RecruitmentDrive admin
# ─────────────────────────────────────────────────────────────

@admin.register(RecruitmentDrive)
class RecruitmentDriveAdmin(admin.ModelAdmin):
    list_display = (
        "name", "company_name", "role", "status_badge",
        "total_enrolled", "total_selected", "start_date", "end_date",
    )
    list_filter = ("status", "start_date")
    search_fields = ("name", "company_name", "role")
    readonly_fields = ("created_by", "created_at", "updated_at", "status")
    inlines = [RoundInline]
    actions = [publish_drives, activate_drives, close_drives]

    fieldsets = (
        ("Drive Identity", {
            "fields": ("name", "company_name", "role"),
        }),
        ("Eligibility & Instructions", {
            "fields": ("eligibility_criteria", "skill_requirements", "instructions"),
        }),
        ("Schedule", {
            "fields": ("start_date", "end_date"),
        }),
        ("Status (read-only — use actions to transition)", {
            "fields": ("status",),
        }),
        ("Metadata", {
            "fields": ("created_by", "created_at", "updated_at"),
            "classes": ("collapse",),
        }),
    )

    def save_model(self, request, obj, form, change):
        if not change:
            obj.created_by = request.user
            AuditLog.objects.create(
                action=AuditLog.DRIVE_CREATED,
                actor=request.user,
                target_model="RecruitmentDrive",
                target_id="",
                new_value=obj.name,
                ip_address=request.META.get("REMOTE_ADDR"),
            )
        super().save_model(request, obj, form, change)

    @admin.display(description="Status", ordering="status")
    def status_badge(self, obj):
        colours = {
            "DRAFT": "#888",
            "PUBLISHED": "#1a73e8",
            "ACTIVE": "#2e7d32",
            "PAUSED": "#e65100",
            "CLOSED": "#b71c1c",
            "ARCHIVED": "#616161",
        }
        colour = colours.get(obj.status, "#333")
        return format_html(
            '<span style="color:{};font-weight:bold">{}</span>',
            colour,
            obj.get_status_display(),
        )


# ─────────────────────────────────────────────────────────────
#  Round admin
# ─────────────────────────────────────────────────────────────

@admin.register(Round)
class RoundAdmin(admin.ModelAdmin):
    list_display = (
        "drive", "order", "name", "round_type",
        "start_time", "end_time", "pass_threshold_percent", "is_mandatory",
    )
    list_filter = ("drive", "round_type", "is_mandatory")
    search_fields = ("name", "drive__name")
    ordering = ["drive", "order"]
    autocomplete_fields = ["drive"]

    fieldsets = (
        ("Round Identity", {
            "fields": ("drive", "order", "name", "round_type"),
        }),
        ("Schedule", {
            "fields": ("start_time", "end_time", "duration_minutes"),
        }),
        ("Assessment Configuration", {
            "fields": (
                "pass_threshold_percent", "score_weight",
                "is_mandatory", "max_attempts",
            ),
        }),
        ("Integrity", {
            "fields": ("tab_switch_warning_threshold",),
        }),
        ("Assessment Links", {
            "fields": ("exam", "interview_template"),
            "description": (
                "For APTITUDE/CODING rounds: link a portal Exam. "
                "For TECHNICAL/HR/BEHAVIORAL rounds: link an Interview Template."
            ),
        }),
        ("Instructions", {
            "fields": ("instructions",),
        }),
    )


# ─────────────────────────────────────────────────────────────
#  CandidateEnrollment admin
# ─────────────────────────────────────────────────────────────

@admin.register(CandidateEnrollment)
class CandidateEnrollmentAdmin(admin.ModelAdmin):
    list_display = (
        "student_usn", "student_name", "drive", "status",
        "current_round", "final_selected", "enrolled_at",
    )
    list_filter = ("drive", "status", "final_selected")
    search_fields = ("student__usn", "student__name", "drive__name")
    readonly_fields = ("enrolled_at", "updated_at")
    actions = [export_enrollments, archive_enrollments]

    @admin.display(description="USN", ordering="student__usn")
    def student_usn(self, obj):
        return obj.student.usn

    @admin.display(description="Name", ordering="student__name")
    def student_name(self, obj):
        return obj.student.name


# ─────────────────────────────────────────────────────────────
#  RoundResult admin
# ─────────────────────────────────────────────────────────────

@admin.register(RoundResult)
class RoundResultAdmin(admin.ModelAdmin):
    list_display = (
        "student_usn", "round", "decision", "percentage",
        "total_score", "max_score", "decided_at", "decided_by",
    )
    list_filter = ("decision", "round__drive", "round")
    search_fields = ("enrollment__student__usn", "enrollment__student__name")
    readonly_fields = (
        "enrollment", "round", "attempt",
        "mcq_score", "coding_score", "interview_score",
        "total_score", "max_score", "percentage",
        "decision", "override_decision", "override_reason", "decided_at", "decided_by",
        "score_rule_snapshot",
    )

    # Manual override form — requires reason
    fieldsets = (
        ("Result (read-only — set by the promotion algorithm)", {
            "fields": (
                "enrollment", "round", "attempt",
                "mcq_score", "coding_score", "interview_score",
                "total_score", "max_score", "percentage",
                "decision", "override_decision", "override_reason", "decided_at", "decided_by",
            ),
        }),
        ("Score Rule Snapshot", {
            "fields": ("score_rule_snapshot",),
            "classes": ("collapse",),
        }),
    )

    def save_model(self, request, obj, form, change):
        if change and "decision" in form.changed_data:
            if not obj.override_reason.strip():
                messages.error(
                    request,
                    "An override reason is required when changing a round decision."
                )
                return
            obj.decision = RoundResult.DECISION_OVERRIDE
            obj.decided_by = request.user
            obj.decided_at = timezone.now()
            super().save_model(request, obj, form, change)
            AuditLog.objects.create(
                action=AuditLog.MANUAL_PROMOTION,
                actor=request.user,
                target_model="RoundResult",
                target_id=str(obj.pk),
                old_value=form.initial.get("decision", ""),
                new_value=obj.decision,
                reason=obj.override_reason,
                ip_address=request.META.get("REMOTE_ADDR"),
            )
        else:
            super().save_model(request, obj, form, change)

    @admin.display(description="USN")
    def student_usn(self, obj):
        return obj.enrollment.student.usn

    def has_add_permission(self, request):
        # Round results are created only by the promotion algorithm
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def has_change_permission(self, request, obj=None):
        # Result changes must use apply_manual_override so enrollment state and audit data stay in sync.
        return False


# ─────────────────────────────────────────────────────────────
#  InterviewTemplate admin
# ─────────────────────────────────────────────────────────────

@admin.register(InterviewTemplate)
class InterviewTemplateAdmin(admin.ModelAdmin):
    list_display = ("name", "round_type", "criterion_count", "is_active", "created_by")
    list_filter = ("round_type", "is_active")
    search_fields = ("name",)
    inlines = [RubricCriterionInline]
    readonly_fields = ("created_by", "created_at")

    def save_model(self, request, obj, form, change):
        if not change:
            obj.created_by = request.user
        super().save_model(request, obj, form, change)

    @admin.display(description="# Criteria")
    def criterion_count(self, obj):
        return obj.criteria.count()


# ─────────────────────────────────────────────────────────────
#  InterviewAssignment admin
# ─────────────────────────────────────────────────────────────

@admin.register(InterviewAssignment)
class InterviewAssignmentAdmin(admin.ModelAdmin):
    list_display = (
        "student_usn", "round", "interviewer",
        "status", "scheduled_at", "is_locked",
    )
    list_filter = ("status", "round__drive", "round", "is_locked")
    search_fields = (
        "enrollment__student__usn",
        "enrollment__student__name",
        "interviewer__username",
        "interviewer__first_name",
    )
    readonly_fields = ("completed_at",)
    inlines = [InterviewEvaluationInline]

    @admin.display(description="USN")
    def student_usn(self, obj):
        return obj.enrollment.student.usn


# ─────────────────────────────────────────────────────────────
#  CandidatePresence admin
# ─────────────────────────────────────────────────────────────

@admin.register(CandidatePresence)
class CandidatePresenceAdmin(admin.ModelAdmin):
    list_display = (
        "student_display",
        "connection_badge",
        "last_heartbeat",
        "last_activity_type",
        "last_persisted_at",
        "client_ip",
    )
    list_filter = ("last_activity_type",)
    search_fields = ("enrollment__student__usn", "enrollment__student__name")
    readonly_fields = (
        "enrollment",
        "attempt",
        "last_heartbeat",
        "last_activity_type",
        "last_persisted_at",
        "client_ip",
        "user_agent",
    )

    @admin.display(description="Student")
    def student_display(self, obj):
        return f"{obj.enrollment.student.usn} — {obj.enrollment.student.name}"

    @admin.display(description="Status")
    def connection_badge(self, obj):
        status = obj.connection_status
        colors = {
            "CONNECTED": "#28a745",
            "STALE": "#ffc107",
            "DISCONNECTED": "#dc3545",
        }
        color = colors.get(status, "#6c757d")
        return format_html(
            '<span style="background:{};color:#fff;padding:2px 8px;border-radius:10px;font-size:11px;font-weight:600">{}</span>',
            color,
            status,
        )

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return request.user.is_superuser


# ─────────────────────────────────────────────────────────────
#  IntegrityEvent admin
# ─────────────────────────────────────────────────────────────

@admin.register(IntegrityEvent)
class IntegrityEventAdmin(admin.ModelAdmin):
    list_display = (
        "student_display",
        "severity_badge",
        "event_type",
        "occurred_at",
        "acknowledged_badge",
        "reviewed_badge",
        "reviewed_by",
    )
    list_filter = ("severity", "event_type", "acknowledged", "reviewed")
    search_fields = ("enrollment__student__usn", "enrollment__student__name")
    readonly_fields = (
        "enrollment",
        "attempt",
        "round",
        "event_type",
        "severity",
        "occurred_at",
        "client_ip",
        "context",
    )
    actions = [acknowledge_warnings, mark_integrity_reviewed]

    fieldsets = (
        ("Event (read-only)", {
            "fields": (
                "enrollment",
                "attempt",
                "round",
                "event_type",
                "severity",
                "occurred_at",
                "client_ip",
                "context",
            ),
        }),
        ("Acknowledgment", {
            "fields": ("acknowledged", "acknowledged_by", "acknowledged_at"),
        }),
        ("Review", {
            "fields": ("reviewed", "reviewed_by", "reviewed_at", "review_note"),
        }),
    )

    @admin.display(description="Student")
    def student_display(self, obj):
        if obj.enrollment:
            return f"{obj.enrollment.student.usn} — {obj.enrollment.student.name}"
        return "—"

    @admin.display(description="Severity")
    def severity_badge(self, obj):
        colors = {
            "INFO": "#17a2b8",
            "WARNING": "#ffc107",
            "CRITICAL": "#dc3545",
        }
        color = colors.get(obj.severity, "#6c757d")
        return format_html(
            '<span style="background:{};color:#fff;padding:2px 6px;border-radius:8px;font-size:10px;font-weight:600">{}</span>',
            color,
            obj.severity,
        )

    @admin.display(description="Ack", boolean=True)
    def acknowledged_badge(self, obj):
        return obj.acknowledged

    @admin.display(description="Reviewed", boolean=True)
    def reviewed_badge(self, obj):
        return obj.reviewed

    def has_add_permission(self, request):
        return False  # Events are recorded programmatically only

    def has_delete_permission(self, request, obj=None):
        return request.user.is_superuser


# ─────────────────────────────────────────────────────────────
#  AuditLog admin — read-only
# ─────────────────────────────────────────────────────────────

@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    list_display = (
        "timestamp", "action", "actor", "target_model",
        "target_id", "reason_snippet",
    )
    list_filter = ("action", "target_model")
    search_fields = ("actor__username", "target_id", "reason", "new_value")
    readonly_fields = (
        "action", "actor", "timestamp", "target_model",
        "target_id", "old_value", "new_value", "reason", "ip_address",
    )

    @admin.display(description="Reason")
    def reason_snippet(self, obj):
        return obj.reason[:60] + "…" if len(obj.reason) > 60 else obj.reason

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

