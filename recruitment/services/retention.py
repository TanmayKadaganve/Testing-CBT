"""
recruitment/services/retention.py
====================================
Candidate data retention and archival operations.

Retention rules:
- Failing a round ≠ deleting the student record.
- "Archive" sets status ARCHIVED — removes from active roster, preserves history.
- Permanent deletion requires the 'recruitment.can_delete_candidate_records' permission,
  explicit confirmation, and writes an AuditLog entry.
- The portal.Student model is never deleted by recruitment logic.
"""

import logging

from django.db import transaction
from django.utils import timezone

from recruitment.models import AuditLog, CandidateEnrollment

logger = logging.getLogger(__name__)


def archive_enrollment(enrollment_id, actor, reason=""):
    """
    Soft-archive a candidate enrollment.
    The student's portal record and all result history are preserved.
    """
    with transaction.atomic():
        enrollment = CandidateEnrollment.objects.select_for_update().get(pk=enrollment_id)
        if enrollment.status == CandidateEnrollment.STATUS_ARCHIVED:
            return enrollment  # Already archived — idempotent

        enrollment.set_status(
            CandidateEnrollment.STATUS_ARCHIVED,
            actor=actor,
            reason=reason or "Archived by administrator",
            log_action=AuditLog.CANDIDATE_ARCHIVED,
        )
    return enrollment


def bulk_archive_failed(drive_id, actor, reason=""):
    """Archive all FAILED enrollments in a drive."""
    enrollments = CandidateEnrollment.objects.filter(
        drive_id=drive_id,
        status=CandidateEnrollment.STATUS_FAILED,
    )
    count = 0
    for enrollment in enrollments:
        archive_enrollment(enrollment.pk, actor, reason or "Bulk archive of failed candidates")
        count += 1
    logger.info("Archived %d failed candidates from drive %s", count, drive_id)
    return count


@transaction.atomic
def permanent_delete_enrollment(enrollment_id, actor, reason, confirmed=False):
    """
    Permanently delete a candidate enrollment and all associated recruitment data.

    Requirements:
    - actor must have the 'recruitment.can_delete_candidate_records' permission.
    - reason must be non-empty.
    - confirmed must be True (prevents accidental calls).
    - AuditLog entry is written BEFORE deletion.
    - The portal.Student record is NOT deleted.

    Raises:
        PermissionError: if actor lacks the required permission.
        ValueError: if reason is empty or confirmed is False.
    """
    if not confirmed:
        raise ValueError("Set confirmed=True to acknowledge permanent deletion.")
    if not reason or not reason.strip():
        raise ValueError("A reason is mandatory for permanent deletion.")
    if not actor.has_perm("recruitment.can_delete_candidate_records"):
        raise PermissionError(
            f"User '{actor.username}' does not have permission to permanently "
            "delete candidate records."
        )

    enrollment = CandidateEnrollment.objects.select_for_update().get(pk=enrollment_id)
    student_usn = enrollment.student.usn
    drive_name = enrollment.drive.name

    # Write audit entry BEFORE deletion (so it survives even if deletion fails)
    AuditLog.objects.create(
        action=AuditLog.CANDIDATE_DELETED,
        actor=actor,
        target_model="CandidateEnrollment",
        target_id=str(enrollment_id),
        old_value=f"{student_usn} in {drive_name}",
        new_value="PERMANENTLY DELETED",
        reason=reason,
    )

    # Django cascade will remove: RoundResult, InterviewAssignment,
    # InterviewEvaluation, IntegrityEvent linked to this enrollment.
    # portal.Student is NOT touched.
    enrollment.delete()

    logger.warning(
        "Permanent deletion: enrollment %s (%s / %s) deleted by %s. Reason: %s",
        enrollment_id, student_usn, drive_name, actor.username, reason,
    )

