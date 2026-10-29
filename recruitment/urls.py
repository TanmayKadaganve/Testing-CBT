"""
recruitment/urls.py
====================
URL configuration for the recruitment module.
- Candidate-facing routes under /recruitment/
- Admin/staff routes under /admin/recruitment/ (mounted separately)
"""

from django.urls import path
from . import views, admin_views

app_name = "recruitment"

urlpatterns = [
    # ── Candidate-facing ─────────────────────────────────────
    path(
        "dashboard/",
        views.candidate_dashboard,
        name="candidate_dashboard",
    ),
    path(
        "drive/<int:drive_id>/round/<int:round_id>/instructions/",
        views.round_instructions,
        name="round_instructions",
    ),
    path(
        "round/<int:pk>/waiting/",
        views.interview_waiting,
        name="interview_waiting",
    ),
    path(
        "enrollment/<int:enrollment_id>/round/<int:round_id>/result/",
        views.candidate_round_result,
        name="candidate_round_result",
    ),

    # ── Heartbeat & Integrity event recording ────────────────
    path(
        "heartbeat/",
        views.candidate_heartbeat,
        name="candidate_heartbeat",
    ),
    path(
        "integrity/event/",
        views.record_integrity_event,
        name="record_integrity_event",
    ),
    path(
        "integrity-event/",
        views.record_integrity_event,
        name="integrity_event",
    ),

    # ── Admin / staff views ───────────────────────────────────
    path(
        "admin/drives/",
        admin_views.drive_list,
        name="drive_list",
    ),
    path(
        "admin/drives/<int:drive_id>/",
        admin_views.drive_detail,
        name="drive_detail",
    ),
    path(
        "admin/drives/<int:drive_id>/transition/",
        admin_views.drive_transition,
        name="drive_transition",
    ),
    path(
        "admin/drives/<int:drive_id>/candidates/",
        admin_views.candidate_roster,
        name="candidate_roster",
    ),
    path(
        "admin/drives/<int:drive_id>/candidates/enroll/",
        admin_views.enroll_students,
        name="enroll_students",
    ),
    path(
        "admin/drives/<int:drive_id>/candidates/archive-failed/",
        admin_views.bulk_archive_failed_view,
        name="bulk_archive_failed",
    ),
    path(
        "admin/drives/<int:drive_id>/export/",
        admin_views.export_results,
        name="export_results",
    ),
    path(
        "admin/drives/<int:drive_id>/integrity/",
        admin_views.integrity_events_view,
        name="integrity_events",
    ),
    path(
        "admin/drives/<int:drive_id>/monitor/",
        admin_views.live_invigilator_console,
        name="live_invigilator_console",
    ),
    path(
        "admin/drives/<int:drive_id>/monitor/updates/",
        admin_views.live_monitor_updates,
        name="live_monitor_updates",
    ),
    path(
        "admin/integrity/<int:event_id>/acknowledge/",
        admin_views.acknowledge_warning_view,
        name="acknowledge_warning",
    ),
    path(
        "admin/integrity/<int:event_id>/review/",
        admin_views.review_warning_view,
        name="review_warning",
    ),
    path(
        "admin/candidates/<int:enrollment_id>/note/",
        admin_views.add_invigilator_note_view,
        name="add_invigilator_note",
    ),
    path(
        "admin/enrollment/<int:enrollment_id>/",
        admin_views.candidate_detail_view,
        name="candidate_detail_view",
    ),
    path(
        "admin/enrollment/<int:enrollment_id>/archive/",
        admin_views.archive_candidate,
        name="archive_candidate",
    ),
    path(
        "admin/round/<int:round_id>/process/",
        admin_views.process_round,
        name="process_round",
    ),
    path(
        "admin/result/<int:result_id>/override/",
        admin_views.manual_override,
        name="manual_override",
    ),
    path(
        "admin/interviews/",
        admin_views.interview_list,
        name="interview_list",
    ),
    path(
        "admin/interviews/<int:assignment_id>/evaluate/",
        admin_views.interview_panel,
        name="interview_panel",
    ),
]

