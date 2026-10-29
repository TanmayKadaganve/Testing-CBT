"""
recruitment/services/progression.py
=====================================
Server-authoritative promotion algorithm.

Rules:
- Scores are computed from DB records only — never from frontend values.
- All transitions are atomic.
- A RoundResult unique constraint prevents duplicate promotions.
- Every decision is logged in AuditLog.
- Idempotent: safe to call multiple times for the same round.
"""

import logging
from decimal import Decimal

from django.db import transaction, IntegrityError
from django.db.models import Q
from django.utils import timezone

from portal.models import Answer, CodeSubmission
from recruitment.models import (
    AuditLog,
    CandidateEnrollment,
    IntegrityEvent,
    Round,
    RoundResult,
)

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────
#  Score computation helpers
# ─────────────────────────────────────────────────────────────

def _compute_mcq_score(attempt, exam):
    """
    Returns (earned, maximum) for MCQ questions in the given attempt's exam.
    Reads from portal.Answer and portal.Question — no scoring formula changes.
    """
    from portal.models import Question
    questions = list(
        Question.objects.filter(section__exam=exam).select_related("section")
    )
    answers = {
        a.question_id: a
        for a in Answer.objects.filter(attempt=attempt).select_related("selected_option")
    }
    earned = Decimal(0)
    maximum = Decimal(0)
    for q in questions:
        maximum += q.marks
        ans = answers.get(q.id)
        if ans and ans.selected_option and ans.selected_option.is_correct:
            earned += q.marks
    return earned, maximum


def _compute_coding_score(attempt, exam):
    """
    Returns (earned, maximum) for coding questions linked to this attempt.
    Uses best (highest) submission score per question — same logic as done_page.
    """
    from portal.models import CodingQuestionAssignment, CodingQuestion
    assigned_ids = set()
    for assignment in attempt.coding_question_assignments.filter(section__exam=exam):
        for q in assignment.questions.all():
            assigned_ids.add(q.id)

    if not assigned_ids:
        return Decimal(0), Decimal(0)

    assigned_questions = list(
        CodingQuestion.objects.filter(id__in=assigned_ids)
    )
    best_scores = {}
    for sub in CodeSubmission.objects.filter(
        attempt=attempt, question__in=assigned_questions
    ):
        best_scores[sub.question_id] = max(
            best_scores.get(sub.question_id, 0), sub.score
        )

    earned = Decimal(sum(best_scores.values()))
    maximum = Decimal(sum(q.marks for q in assigned_questions))
    return earned, maximum


def _compute_interview_score(enrollment, round_obj):
    """
    Returns (earned, maximum) from InterviewEvaluation records.
    Uses weighted average of all evaluators' scores per criterion.
    Discrepancy of >2 points on any criterion is logged as a warning.
    """
    from recruitment.models import InterviewAssignment, InterviewEvaluation

    assignments = list(
        InterviewAssignment.objects.filter(
            enrollment=enrollment,
            round=round_obj,
            status=InterviewAssignment.STATUS_COMPLETED,
        ).prefetch_related("evaluations__criterion")
    )

    if not assignments:
        return None, None

    # Group criterion scores across all evaluators
    criterion_scores: dict[int, list[float]] = {}
    criterion_max: dict[int, float] = {}
    criterion_weight: dict[int, float] = {}

    for assignment in assignments:
        for evaluation in assignment.evaluations.all():
            c_id = evaluation.criterion_id
            criterion_scores.setdefault(c_id, []).append(float(evaluation.score))
            criterion_max[c_id] = float(evaluation.criterion.max_score)
            criterion_weight[c_id] = float(evaluation.criterion.weight)

    earned = Decimal(0)
    maximum = Decimal(0)

    for c_id, scores in criterion_scores.items():
        # Warn on large inter-evaluator discrepancy
        if len(scores) > 1 and (max(scores) - min(scores)) > 2:
            logger.warning(
                "Score discrepancy > 2 for criterion %s in round %s, enrollment %s. "
                "Scores: %s. Human review recommended.",
                c_id, round_obj.pk, enrollment.pk, scores,
            )
        avg_score = sum(scores) / len(scores)
        weight = Decimal(str(criterion_weight[c_id]))
        earned += Decimal(str(avg_score)) * weight
        maximum += Decimal(str(criterion_max[c_id])) * weight

    return earned, maximum


# ─────────────────────────────────────────────────────────────
#  Main promotion algorithm
# ─────────────────────────────────────────────────────────────

@transaction.atomic
def process_round_results(round_id, triggered_by=None):
    """
    Compute and record server-authoritative results for all enrolled candidates
    in the given round.

    - Idempotent: skips enrollments that already have a PASS or FAIL decision.
    - Race-safe: wraps the entire computation in a transaction and uses
      select_for_update on CandidateEnrollment rows.
    - Promotes passing candidates to next round automatically.
    - Returns a summary dict for admin reporting.

    Args:
        round_id: pk of the Round to process.
        triggered_by: User who triggered this (for audit log); None = automated.
    """
    round_obj = Round.objects.select_related("drive", "exam", "interview_template").get(
        pk=round_id
    )
    drive = round_obj.drive

    # Fetch all enrollments in this drive that are at this round or already have a result for this round,
    # locking rows to prevent concurrent promotion of the same candidate.
    enrollments = list(
        CandidateEnrollment.objects.select_for_update()
        .filter(
            Q(drive=drive, current_round=round_obj) |
            Q(drive=drive, round_results__round=round_obj)
        )
        .distinct()
    )

    summary = {
        "round": round_obj.name,
        "processed": 0,
        "passed": 0,
        "failed": 0,
        "skipped_already_decided": 0,
        "skipped_no_attempt": 0,
        "errors": [],
    }

    next_round = round_obj.next_round
    threshold = round_obj.pass_threshold_percent  # Decimal

    for enrollment in enrollments:
        try:
            _process_single_enrollment(
                enrollment=enrollment,
                round_obj=round_obj,
                threshold=threshold,
                next_round=next_round,
                triggered_by=triggered_by,
                summary=summary,
            )
        except Exception as exc:
            logger.exception(
                "Error processing enrollment %s in round %s: %s",
                enrollment.pk, round_obj.pk, exc,
            )
            summary["errors"].append(
                f"{enrollment.student.usn}: {exc}"
            )

    logger.info(
        "Round %s processed: %s",
        round_obj.name,
        summary,
    )
    return summary


def _process_single_enrollment(
    enrollment, round_obj, threshold, next_round, triggered_by, summary
):
    """Process promotion for one candidate in one round (called inside atomic block)."""
    student = enrollment.student

    # Idempotency check: skip if already decided
    existing = RoundResult.objects.filter(
        enrollment=enrollment, round=round_obj
    ).first()
    if existing and existing.decision in (
        RoundResult.DECISION_PASS,
        RoundResult.DECISION_FAIL,
        RoundResult.DECISION_OVERRIDE,
        RoundResult.DECISION_ABSENT,
    ):
        summary["skipped_already_decided"] += 1
        return

    # Skip candidates who have withdrawn or were archived prior to this round
    if enrollment.status in (
        CandidateEnrollment.STATUS_ARCHIVED,
        CandidateEnrollment.STATUS_WITHDRAWN,
    ):
        return

    # ── Compute scores ────────────────────────────────────────

    mcq_earned = coding_earned = interview_earned = None
    mcq_max = coding_max = interview_max = Decimal(0)
    attempt = None

    if round_obj.is_automated and round_obj.exam:
        attempt = enrollment.student.attempt_set.filter(
            exam=round_obj.exam
        ).order_by("-started_at").first()

        if not attempt or not attempt.submitted_at:
            # Candidate did not submit — mark absent
            _record_result(
                enrollment=enrollment,
                round_obj=round_obj,
                attempt=None,
                total_earned=Decimal(0),
                total_max=Decimal(0),
                decision=RoundResult.DECISION_ABSENT,
                decided_by=triggered_by,
                reason="No submitted attempt found",
            )
            enrollment.set_status(
                CandidateEnrollment.STATUS_ABSENT,
                actor=triggered_by,
                reason=f"No submission found for {round_obj.name}",
            )
            summary["processed"] += 1
            summary["skipped_no_attempt"] += 1
            return

        mcq_earned, mcq_max = _compute_mcq_score(attempt, round_obj.exam)
        coding_earned, coding_max = _compute_coding_score(attempt, round_obj.exam)
        interview_earned, interview_max = None, Decimal(0)

    elif round_obj.is_human_evaluated:
        interview_earned, interview_max = _compute_interview_score(
            enrollment, round_obj
        )
        if interview_earned is None:
            # Evaluations not yet complete
            summary["skipped_no_attempt"] += 1
            return

    # ── Aggregate total ───────────────────────────────────────

    total_earned = Decimal(0)
    total_max = Decimal(0)

    for earned, max_val in [
        (mcq_earned, mcq_max),
        (coding_earned, coding_max),
        (interview_earned, interview_max),
    ]:
        if earned is not None:
            total_earned += earned
            total_max += max_val

    if total_max > 0:
        percentage = (total_earned / total_max * 100).quantize(Decimal("0.01"))
    else:
        percentage = Decimal(0)

    # ── Pass / Fail decision ──────────────────────────────────

    if round_obj.is_mandatory:
        decision = (
            RoundResult.DECISION_PASS
            if percentage >= threshold
            else RoundResult.DECISION_FAIL
        )
    else:
        # Optional round: always advance
        decision = RoundResult.DECISION_PASS

    # ── Record result ─────────────────────────────────────────

    result = _record_result(
        enrollment=enrollment,
        round_obj=round_obj,
        attempt=attempt,
        total_earned=total_earned,
        total_max=total_max,
        decision=decision,
        decided_by=triggered_by,
        reason="Computed by promotion algorithm",
        mcq_earned=mcq_earned,
        mcq_max=mcq_max,
        coding_earned=coding_earned,
        coding_max=coding_max,
        interview_earned=interview_earned,
        interview_max=interview_max,
        percentage=percentage,
    )

    # ── Advance or reject enrollment ──────────────────────────

    if decision == RoundResult.DECISION_PASS:
        summary["passed"] += 1
        if next_round:
            enrollment.current_round = next_round
            enrollment.save(update_fields=["current_round", "updated_at"])
            if next_round.exam:
                next_round.exam.students.add(student)
            enrollment.set_status(
                CandidateEnrollment.STATUS_ENROLLED,
                actor=triggered_by,
                reason=f"Passed {round_obj.name} ({percentage}%). Moved to {next_round.name}.",
                log_action=AuditLog.CANDIDATE_PROMOTED,
            )
        else:
            # Last round: mark selected
            enrollment.final_selected = True
            enrollment.save(update_fields=["final_selected", "updated_at"])
            enrollment.set_status(
                CandidateEnrollment.STATUS_PASSED,
                actor=triggered_by,
                reason=f"Passed all rounds. Drive complete.",
                log_action=AuditLog.CANDIDATE_PROMOTED,
            )
    else:
        summary["failed"] += 1
        enrollment.set_status(
            CandidateEnrollment.STATUS_FAILED,
            actor=triggered_by,
            reason=f"Failed {round_obj.name} ({percentage}% < {threshold}% threshold).",
            log_action=AuditLog.CANDIDATE_REJECTED,
        )

    summary["processed"] += 1


def _record_result(
    enrollment, round_obj, attempt, total_earned, total_max,
    decision, decided_by, reason,
    mcq_earned=None, mcq_max=None,
    coding_earned=None, coding_max=None,
    interview_earned=None, interview_max=None,
    percentage=None,
):
    """
    Create or update a RoundResult.
    If a PENDING result already exists, update it.
    If a PASS/FAIL/OVERRIDE result exists, raise IntegrityError (idempotent guard).
    """
    snapshot = {
        "pass_threshold_percent": str(round_obj.pass_threshold_percent),
        "is_mandatory": round_obj.is_mandatory,
        "score_weight": str(round_obj.score_weight),
    }

    result_defaults = {
        "attempt": attempt,
        "mcq_score": mcq_earned,
        "coding_score": coding_earned,
        "interview_score": interview_earned,
        "total_score": total_earned,
        "max_score": total_max,
        "percentage": percentage,
        "decision": decision,
        "decided_at": timezone.now(),
        "decided_by": decided_by,
        "reason": reason if hasattr(RoundResult, "reason") else None,
        "score_rule_snapshot": snapshot,
    }
    # Remove None-valued fields from defaults to avoid overwriting with null
    result_defaults = {k: v for k, v in result_defaults.items() if v is not None or k in {
        "attempt", "mcq_score", "coding_score", "interview_score",
        "total_score", "max_score", "percentage"
    }}

    try:
        result, created = RoundResult.objects.update_or_create(
            enrollment=enrollment,
            round=round_obj,
            defaults=result_defaults,
        )
    except IntegrityError:
        # Already exists with a final decision — do not overwrite
        result = RoundResult.objects.get(enrollment=enrollment, round=round_obj)

    return result


# ─────────────────────────────────────────────────────────────
#  Manual override
# ─────────────────────────────────────────────────────────────

@transaction.atomic
def apply_manual_override(result_id, new_decision, reason, actor):
    """
    Allows an authorized administrator to override a round result.

    Requirements:
    - reason must be non-empty.
    - actor must be set.
    - Every override is logged in AuditLog with old and new values.

    Raises ValueError if inputs are invalid.
    """
    if not reason or not reason.strip():
        raise ValueError("A reason is mandatory for a manual override.")
    if actor is None:
        raise ValueError("An authenticated actor is required for a manual override.")
    if new_decision not in (
        RoundResult.DECISION_PASS,
        RoundResult.DECISION_FAIL,
        RoundResult.DECISION_ABSENT,
    ):
        raise ValueError(f"Invalid decision for manual override: {new_decision!r}")

    result = RoundResult.objects.select_for_update().get(pk=result_id)
    old_decision = result.decision

    result.decision = RoundResult.DECISION_OVERRIDE
    result.override_decision = new_decision
    result.override_reason = reason
    result.decided_by = actor
    result.decided_at = timezone.now()
    result.save(update_fields=[
        "decision", "override_decision", "override_reason", "decided_by", "decided_at"
    ])

    # Advance or reject enrollment to match override
    enrollment = result.enrollment
    if new_decision == RoundResult.DECISION_PASS:
        next_round = result.round.next_round
        if next_round:
            enrollment.current_round = next_round
            enrollment.final_selected = False
            enrollment.save(update_fields=["current_round", "final_selected", "updated_at"])
            enrollment.set_status(
                CandidateEnrollment.STATUS_PROMOTED,
                actor=actor,
                reason=f"Manual override: {reason}",
                log_action=AuditLog.MANUAL_PROMOTION,
            )
        else:
            enrollment.final_selected = True
            enrollment.save(update_fields=["final_selected", "updated_at"])
            enrollment.set_status(
                CandidateEnrollment.STATUS_PASSED,
                actor=actor,
                reason=f"Manual override: {reason}",
                log_action=AuditLog.MANUAL_PROMOTION,
            )
    elif new_decision == RoundResult.DECISION_ABSENT:
        enrollment.final_selected = False
        enrollment.save(update_fields=["final_selected", "updated_at"])
        enrollment.set_status(
            CandidateEnrollment.STATUS_ABSENT,
            actor=actor,
            reason=f"Manual override: {reason}",
            log_action=AuditLog.CANDIDATE_REJECTED,
        )
    else:
        enrollment.final_selected = False
        enrollment.save(update_fields=["final_selected", "updated_at"])
        enrollment.set_status(
            CandidateEnrollment.STATUS_FAILED,
            actor=actor,
            reason=f"Manual override: {reason}",
            log_action=AuditLog.CANDIDATE_REJECTED,
        )

    AuditLog.objects.create(
        action=AuditLog.MANUAL_PROMOTION,
        actor=actor,
        target_model="RoundResult",
        target_id=str(result.pk),
        old_value=old_decision,
        new_value=new_decision,
        reason=reason,
    )

    return result

