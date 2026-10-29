from datetime import timedelta

from django.db import IntegrityError, transaction
from django.utils import timezone

from recruitment.models import CandidateEnrollment, CandidateRoundSession, RecruitmentDrive


def start_or_get_round_session(enrollment, round_obj):
    """Create the one authoritative start/deadline record for this round."""
    if round_obj.max_attempts != 1:
        raise ValueError("This round is configured for retries, but candidate round sessions support one entry. Set max attempts to 1.")
    now = timezone.now()
    starts_at = now
    if round_obj.exam and round_obj.exam.start_time and round_obj.exam.start_time > now:
        starts_at = round_obj.exam.start_time
    deadline = starts_at + timedelta(minutes=max(1, round_obj.duration_minutes))
    if round_obj.end_time:
        deadline = min(deadline, round_obj.end_time)
    try:
        with transaction.atomic():
            session, _ = CandidateRoundSession.objects.get_or_create(
                enrollment=enrollment,
                round=round_obj,
                defaults={"started_at": starts_at, "deadline_at": deadline},
            )
            return session
    except IntegrityError:
        return CandidateRoundSession.objects.get(enrollment=enrollment, round=round_obj)


def round_deadline_for(student, exam):
    enrollment = CandidateEnrollment.objects.filter(
        student=student,
        drive__status=RecruitmentDrive.STATUS_ACTIVE,
        current_round__exam=exam,
        status__in=CandidateEnrollment.ACTIVE_STATUSES,
    ).select_related("current_round").first()
    if not enrollment:
        return None
    session = CandidateRoundSession.objects.filter(
        enrollment=enrollment, round=enrollment.current_round
    ).first()
    return session.deadline_at if session else None


def round_session_context(student, exam):
    enrollment = CandidateEnrollment.objects.filter(
        student=student, current_round__exam=exam
    ).select_related("drive", "current_round").first()
    if not enrollment:
        return None, None
    session = CandidateRoundSession.objects.filter(
        enrollment=enrollment, round=enrollment.current_round
    ).first()
    return enrollment, session
