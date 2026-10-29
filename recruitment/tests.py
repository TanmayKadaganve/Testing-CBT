"""
recruitment/tests.py
=====================
Automated tests for the PyForgeLabs Recruitment & Placement Simulator.
Tests use the real database and real business logic — no mocked outcomes.

Coverage:
- Drive creation and state transitions
- Round configuration
- Candidate enrollment (no duplicates)
- Promotion algorithm (pass / fail / threshold boundary)
- Idempotency of promotion
- Manual override (requires reason and actor)
- Integrity events
- AuditLog immutability
- Analytics helpers
- Retention / archival
"""

from datetime import date, timedelta
from decimal import Decimal

from django.contrib.auth.models import User
from django.test import TestCase, Client
from django.utils import timezone

from portal.models import (
    Exam, Section, Student, Question, Option, Attempt, Answer
)
from recruitment.models import (
    AuditLog,
    CandidateEnrollment,
    IntegrityEvent,
    InterviewAssignment,
    InterviewEvaluation,
    InterviewTemplate,
    RecruitmentDrive,
    Round,
    RoundResult,
    RubricCriterion,
)
from recruitment.services.progression import (
    apply_manual_override,
    process_round_results,
)
from recruitment.services.retention import archive_enrollment, bulk_archive_failed


# ─────────────────────────────────────────────────────────────
#  Helpers
# ─────────────────────────────────────────────────────────────

def make_admin():
    return User.objects.create_superuser(
        username="admin_test", email="admin@test.com", password="adminpass"
    )


def make_staff():
    return User.objects.create_user(
        username="staff_test", password="staffpass", is_staff=True
    )


def make_student(usn="1RV21CS001", name="Test Student"):
    return Student.objects.create(
        usn=usn, name=name, dob=date(2002, 1, 1), is_active=True
    )


def make_exam(title="Test Exam"):
    now = timezone.now()
    exam = Exam.objects.create(title=title, min_stay_minutes=5)
    Section.objects.create(
        exam=exam, title="MCQ", order=1, kind="MCQ",
        start_time=now - timedelta(hours=1),
        end_time=now + timedelta(hours=2),
    )
    return exam


def make_drive(admin, name="Test Drive", status="DRAFT"):
    drive = RecruitmentDrive.objects.create(
        name=name,
        company_name="TestCorp",
        role="SWE",
        start_date=date.today(),
        end_date=date.today() + timedelta(days=30),
        created_by=admin,
        status=status,
    )
    return drive


def make_mcq_round(drive, exam, order=1):
    return Round.objects.create(
        drive=drive, name="Aptitude", round_type="APTITUDE",
        order=order, pass_threshold_percent=Decimal("40.00"),
        is_mandatory=True, exam=exam,
    )


def make_round(drive, order=1, round_type="APTITUDE", pass_threshold=40):
    exam = make_exam(f"Exam for Round {order}") if round_type in ("APTITUDE", "CODING") else None
    return Round.objects.create(
        drive=drive,
        name=f"Round {order}",
        round_type=round_type,
        order=order,
        pass_threshold_percent=Decimal(str(pass_threshold)),
        is_mandatory=True,
        exam=exam,
    )


# ─────────────────────────────────────────────────────────────
#  Drive & Round Tests
# ─────────────────────────────────────────────────────────────

class DriveLifecycleTest(TestCase):
    def setUp(self):
        self.admin = make_admin()
        self.drive = make_drive(self.admin)

    def test_initial_status_is_draft(self):
        self.assertEqual(self.drive.status, "DRAFT")

    def test_valid_transition_draft_to_published(self):
        self.drive.transition_to("PUBLISHED", actor=self.admin, reason="test")
        self.drive.refresh_from_db()
        self.assertEqual(self.drive.status, "PUBLISHED")

    def test_invalid_transition_raises_value_error(self):
        with self.assertRaises(ValueError):
            self.drive.transition_to("ACTIVE", actor=self.admin, reason="skip step")

    def test_transition_writes_audit_log(self):
        before = AuditLog.objects.count()
        self.drive.transition_to("PUBLISHED", actor=self.admin, reason="audit test")
        self.assertEqual(AuditLog.objects.count(), before + 1)
        entry = AuditLog.objects.latest("timestamp")
        self.assertEqual(entry.action, AuditLog.DRIVE_STATUS_CHANGE)
        self.assertEqual(entry.old_value, "DRAFT")
        self.assertEqual(entry.new_value, "PUBLISHED")

    def test_full_lifecycle(self):
        self.drive.transition_to("PUBLISHED", actor=self.admin)
        self.drive.transition_to("ACTIVE", actor=self.admin)
        self.drive.transition_to("PAUSED", actor=self.admin)
        self.drive.transition_to("ACTIVE", actor=self.admin)
        self.drive.transition_to("CLOSED", actor=self.admin)
        self.drive.transition_to("ARCHIVED", actor=self.admin)
        self.drive.refresh_from_db()
        self.assertEqual(self.drive.status, "ARCHIVED")

    def test_archived_drive_cannot_transition(self):
        self.drive.transition_to("PUBLISHED", actor=self.admin)
        self.drive.transition_to("ACTIVE", actor=self.admin)
        self.drive.transition_to("CLOSED", actor=self.admin)
        self.drive.transition_to("ARCHIVED", actor=self.admin)
        with self.assertRaises(ValueError):
            self.drive.transition_to("DRAFT", actor=self.admin)

    def test_round_ordering(self):
        exam = make_exam()
        r1 = Round.objects.create(
            drive=self.drive, name="R1", round_type="APTITUDE", order=1, exam=exam
        )
        r2 = Round.objects.create(
            drive=self.drive, name="R2", round_type="CODING", order=2, exam=exam
        )
        ordered = list(self.drive.ordered_rounds)
        self.assertEqual(ordered[0].pk, r1.pk)
        self.assertEqual(ordered[1].pk, r2.pk)

    def test_round_unique_order_per_drive(self):
        from django.db import IntegrityError
        exam = make_exam()
        Round.objects.create(
            drive=self.drive, name="R1", round_type="APTITUDE", order=1, exam=exam
        )
        with self.assertRaises(IntegrityError):
            Round.objects.create(
                drive=self.drive, name="Dup", round_type="CODING", order=1, exam=exam
            )


# ─────────────────────────────────────────────────────────────
#  Enrollment Tests
# ─────────────────────────────────────────────────────────────

class EnrollmentTest(TestCase):
    def setUp(self):
        self.admin = make_admin()
        self.drive = make_drive(self.admin, status="DRAFT")
        self.student = make_student()

    def test_enroll_student(self):
        e, created = CandidateEnrollment.objects.get_or_create(
            drive=self.drive, student=self.student,
            defaults={"status": "ENROLLED"},
        )
        self.assertTrue(created)
        self.assertEqual(e.status, "ENROLLED")

    def test_no_duplicate_enrollment(self):
        CandidateEnrollment.objects.create(
            drive=self.drive, student=self.student, status="ENROLLED"
        )
        # Second enrollment for same student-drive should raise IntegrityError
        from django.db import IntegrityError
        with self.assertRaises(IntegrityError):
            CandidateEnrollment.objects.create(
                drive=self.drive, student=self.student, status="ENROLLED"
            )

    def test_set_status_writes_audit_log(self):
        enrollment = CandidateEnrollment.objects.create(
            drive=self.drive, student=self.student, status="ENROLLED"
        )
        before = AuditLog.objects.count()
        enrollment.set_status("IN_PROGRESS", actor=self.admin, reason="test")
        self.assertEqual(AuditLog.objects.count(), before + 1)
        enrollment.refresh_from_db()
        self.assertEqual(enrollment.status, "IN_PROGRESS")

    def test_active_statuses_set(self):
        """ENROLLED and IN_PROGRESS are active; FAILED and ARCHIVED are terminal."""
        self.assertIn("ENROLLED", CandidateEnrollment.ACTIVE_STATUSES)
        self.assertIn("IN_PROGRESS", CandidateEnrollment.ACTIVE_STATUSES)
        self.assertIn("FAILED", CandidateEnrollment.TERMINAL_STATUSES)
        self.assertIn("ARCHIVED", CandidateEnrollment.TERMINAL_STATUSES)


# ─────────────────────────────────────────────────────────────
#  Promotion Algorithm Tests
# ─────────────────────────────────────────────────────────────

class PromotionAlgorithmTest(TestCase):
    def setUp(self):
        self.admin = make_admin()
        self.exam = make_exam()
        self.drive = make_drive(self.admin, status="DRAFT")
        self.round1 = make_mcq_round(self.drive, self.exam, order=1)
        self.round2 = Round.objects.create(
            drive=self.drive, name="Technical", round_type="TECHNICAL", order=2
        )

    def _make_enrollment(self, usn="1RV21CS001"):
        student = make_student(usn=usn)
        self.exam.students.add(student)
        enrollment = CandidateEnrollment.objects.create(
            drive=self.drive, student=student, status="ENROLLED",
            current_round=self.round1,
        )
        return student, enrollment

    def _make_attempt_with_score(self, student, percent_correct=60):
        """Create an attempt and answer all questions with given % correct."""
        section = self.exam.sections.first()
        q1 = Question.objects.create(section=section, order=1, text="Q1", marks=5)
        opt_correct = Option.objects.create(question=q1, text="Correct", is_correct=True)
        opt_wrong = Option.objects.create(question=q1, text="Wrong", is_correct=False)

        attempt = Attempt.objects.create(
            student=student, exam=self.exam,
            submitted_at=timezone.now(),
        )
        # Select correct option based on percent_correct
        selected = opt_correct if percent_correct >= 50 else opt_wrong
        Answer.objects.create(
            attempt=attempt, question=q1, selected_option=selected
        )
        return attempt

    def test_passing_candidate_promoted_to_next_round(self):
        student, enrollment = self._make_enrollment()
        self._make_attempt_with_score(student, percent_correct=100)  # 100% → pass

        summary = process_round_results(self.round1.pk, triggered_by=self.admin)
        self.assertEqual(summary["passed"], 1)
        self.assertEqual(summary["failed"], 0)

        enrollment.refresh_from_db()
        self.assertEqual(enrollment.status, "ENROLLED")
        self.assertEqual(enrollment.current_round_id, self.round2.pk)

        result = RoundResult.objects.get(enrollment=enrollment, round=self.round1)
        self.assertEqual(result.decision, "PASS")

    def test_failing_candidate_not_promoted(self):
        student, enrollment = self._make_enrollment("1RV21CS002")
        self._make_attempt_with_score(student, percent_correct=0)  # 0% → fail

        summary = process_round_results(self.round1.pk, triggered_by=self.admin)
        self.assertEqual(summary["failed"], 1)

        enrollment.refresh_from_db()
        self.assertEqual(enrollment.status, "FAILED")

        result = RoundResult.objects.get(enrollment=enrollment, round=self.round1)
        self.assertEqual(result.decision, "FAIL")

    def test_idempotency_no_duplicate_promotion(self):
        """Calling process_round_results twice must not double-process."""
        student, enrollment = self._make_enrollment("1RV21CS003")
        self._make_attempt_with_score(student, percent_correct=100)

        process_round_results(self.round1.pk, triggered_by=self.admin)
        summary2 = process_round_results(self.round1.pk, triggered_by=self.admin)

        self.assertEqual(summary2["skipped_already_decided"], 1)
        self.assertEqual(RoundResult.objects.filter(
            enrollment=enrollment, round=self.round1
        ).count(), 1)

    def test_absent_candidate_when_no_attempt(self):
        student, enrollment = self._make_enrollment("1RV21CS004")
        # No attempt created

        summary = process_round_results(self.round1.pk, triggered_by=self.admin)
        enrollment.refresh_from_db()
        self.assertEqual(enrollment.status, "ABSENT")
        result = RoundResult.objects.get(enrollment=enrollment, round=self.round1)
        self.assertEqual(result.decision, "ABSENT")

    def test_last_round_pass_marks_selected(self):
        """Passing the final round marks the candidate as finally selected."""
        # Make round2 the only round (no next round)
        self.round2.delete()
        student, enrollment = self._make_enrollment("1RV21CS005")
        self._make_attempt_with_score(student, percent_correct=100)

        process_round_results(self.round1.pk, triggered_by=self.admin)
        enrollment.refresh_from_db()
        self.assertTrue(enrollment.final_selected)
        self.assertEqual(enrollment.status, "PASSED")


# ─────────────────────────────────────────────────────────────
#  Manual Override Tests
# ─────────────────────────────────────────────────────────────

class ManualOverrideTest(TestCase):
    def setUp(self):
        self.admin = make_admin()
        self.exam = make_exam()
        self.drive = make_drive(self.admin)
        self.round1 = make_mcq_round(self.drive, self.exam, order=1)
        self.student = make_student()
        self.exam.students.add(self.student)
        self.enrollment = CandidateEnrollment.objects.create(
            drive=self.drive, student=self.student,
            status="ENROLLED", current_round=self.round1,
        )
        # Create a FAIL result to override
        self.result = RoundResult.objects.create(
            enrollment=self.enrollment,
            round=self.round1,
            decision="FAIL",
            total_score=Decimal("20"),
            max_score=Decimal("100"),
            percentage=Decimal("20.00"),
            decided_at=timezone.now(),
        )

    def test_override_requires_reason(self):
        with self.assertRaises(ValueError):
            apply_manual_override(self.result.pk, "PASS", reason="", actor=self.admin)

    def test_override_requires_actor(self):
        with self.assertRaises(ValueError):
            apply_manual_override(self.result.pk, "PASS", reason="Correction", actor=None)

    def test_valid_override_changes_decision_and_logs(self):
        before = AuditLog.objects.count()
        apply_manual_override(
            self.result.pk, "PASS",
            reason="Student affected by connectivity issue", actor=self.admin
        )
        self.result.refresh_from_db()
        self.assertEqual(self.result.decision, "MANUAL_OVERRIDE")
        self.assertEqual(AuditLog.objects.count(), before + 2)  # status + override

    def test_override_updates_enrollment_status(self):
        apply_manual_override(
            self.result.pk, "PASS",
            reason="Verified by invigilator", actor=self.admin
        )
        self.enrollment.refresh_from_db()
        self.assertEqual(self.enrollment.status, "PROMOTED")


# ─────────────────────────────────────────────────────────────
#  Integrity Event Tests
# ─────────────────────────────────────────────────────────────

class IntegrityEventTest(TestCase):
    def setUp(self):
        self.admin = make_admin()
        self.student = make_student()
        self.drive = make_drive(self.admin)
        self.enrollment = CandidateEnrollment.objects.create(
            drive=self.drive, student=self.student, status="IN_PROGRESS"
        )

    def test_record_tab_hidden_event(self):
        event = IntegrityEvent.objects.create(
            enrollment=self.enrollment,
            event_type="TAB_HIDDEN",
            context={"elapsed_seconds": 1200},
        )
        self.assertEqual(event.reviewed, False)
        self.assertIsNone(event.reviewed_by)

    def test_event_review(self):
        event = IntegrityEvent.objects.create(
            enrollment=self.enrollment,
            event_type="FULLSCREEN_EXIT",
        )
        from django.utils import timezone
        event.reviewed = True
        event.reviewed_by = self.admin
        event.reviewed_at = timezone.now()
        event.review_note = "Accidental fullscreen exit, no action required."
        event.save()

        event.refresh_from_db()
        self.assertTrue(event.reviewed)
        self.assertEqual(event.reviewed_by, self.admin)

    def test_multiple_events_for_same_enrollment(self):
        """Threshold counting works correctly."""
        for _ in range(5):
            IntegrityEvent.objects.create(
                enrollment=self.enrollment, event_type="TAB_HIDDEN"
            )
        count = IntegrityEvent.objects.filter(
            enrollment=self.enrollment, event_type="TAB_HIDDEN"
        ).count()
        self.assertEqual(count, 5)


# ─────────────────────────────────────────────────────────────
#  AuditLog Immutability Test
# ─────────────────────────────────────────────────────────────

class AuditLogImmutabilityTest(TestCase):
    def setUp(self):
        self.admin = make_admin()
        self.entry = AuditLog.objects.create(
            action=AuditLog.DRIVE_CREATED,
            actor=self.admin,
            target_model="RecruitmentDrive",
            target_id="1",
            new_value="Test Drive",
        )

    def test_cannot_modify_audit_log(self):
        self.entry.new_value = "tampered"
        with self.assertRaises(RuntimeError):
            self.entry.save()

    def test_cannot_delete_audit_log(self):
        with self.assertRaises(RuntimeError):
            self.entry.delete()


# ─────────────────────────────────────────────────────────────
#  Interview Evaluation Tests
# ─────────────────────────────────────────────────────────────

class InterviewEvaluationTest(TestCase):
    def setUp(self):
        self.admin = make_admin()
        self.interviewer = make_staff()
        self.student = make_student()
        self.drive = make_drive(self.admin)
        self.round_obj = Round.objects.create(
            drive=self.drive, name="Technical", round_type="TECHNICAL", order=1
        )
        self.template = InterviewTemplate.objects.create(
            name="Tech Template", round_type="TECHNICAL", created_by=self.admin
        )
        self.criterion = RubricCriterion.objects.create(
            template=self.template, name="Problem Solving",
            max_score=5, weight=Decimal("1.0"), order=1
        )
        self.enrollment = CandidateEnrollment.objects.create(
            drive=self.drive, student=self.student,
            status="ENROLLED", current_round=self.round_obj
        )
        self.assignment = InterviewAssignment.objects.create(
            enrollment=self.enrollment,
            round=self.round_obj,
            interviewer=self.interviewer,
            template=self.template,
            status="SCHEDULED",
        )

    def test_score_within_max(self):
        evaluation = InterviewEvaluation(
            assignment=self.assignment,
            criterion=self.criterion,
            score=4,
            submitted_by=self.interviewer,
        )
        evaluation.clean()  # Should not raise
        evaluation.save()
        self.assertEqual(evaluation.score, 4)

    def test_score_exceeds_max_raises(self):
        from django.core.exceptions import ValidationError
        evaluation = InterviewEvaluation(
            assignment=self.assignment,
            criterion=self.criterion,
            score=10,  # exceeds max_score=5
            submitted_by=self.interviewer,
        )
        with self.assertRaises(ValidationError):
            evaluation.clean()

    def test_weighted_score_single_evaluator(self):
        InterviewEvaluation.objects.create(
            assignment=self.assignment,
            criterion=self.criterion,
            score=4,
            submitted_by=self.interviewer,
        )
        self.assertEqual(self.assignment.weighted_score, 4.0)

    def test_no_evaluations_returns_none(self):
        self.assertIsNone(self.assignment.weighted_score)

    def test_unique_constraint_per_criterion(self):
        from django.db import IntegrityError
        InterviewEvaluation.objects.create(
            assignment=self.assignment,
            criterion=self.criterion,
            score=3,
            submitted_by=self.interviewer,
        )
        with self.assertRaises(IntegrityError):
            InterviewEvaluation.objects.create(
                assignment=self.assignment,
                criterion=self.criterion,
                score=5,
                submitted_by=self.interviewer,
            )


# ─────────────────────────────────────────────────────────────
#  Retention / Archival Tests
# ─────────────────────────────────────────────────────────────

class RetentionTest(TestCase):
    def setUp(self):
        self.admin = make_admin()
        self.drive = make_drive(self.admin)
        self.student = make_student()
        self.enrollment = CandidateEnrollment.objects.create(
            drive=self.drive, student=self.student, status="FAILED"
        )

    def test_archive_sets_status(self):
        archive_enrollment(self.enrollment.pk, actor=self.admin, reason="Test")
        self.enrollment.refresh_from_db()
        self.assertEqual(self.enrollment.status, "ARCHIVED")

    def test_archive_is_idempotent(self):
        archive_enrollment(self.enrollment.pk, actor=self.admin)
        archive_enrollment(self.enrollment.pk, actor=self.admin)
        self.enrollment.refresh_from_db()
        self.assertEqual(self.enrollment.status, "ARCHIVED")

    def test_archive_preserves_student_record(self):
        archive_enrollment(self.enrollment.pk, actor=self.admin)
        self.assertTrue(Student.objects.filter(pk=self.student.pk).exists())

    def test_bulk_archive_failed(self):
        s2 = make_student("1RV21CS099")
        CandidateEnrollment.objects.create(drive=self.drive, student=s2, status="FAILED")
        count = bulk_archive_failed(self.drive.pk, actor=self.admin)
        self.assertEqual(count, 2)

    def test_permanent_delete_requires_permission(self):
        from recruitment.services.retention import permanent_delete_enrollment
        unprivileged = make_staff()
        with self.assertRaises(PermissionError):
            permanent_delete_enrollment(
                self.enrollment.pk, actor=unprivileged,
                reason="test", confirmed=True
            )

    def test_permanent_delete_requires_reason(self):
        from recruitment.services.retention import permanent_delete_enrollment
        self.admin.user_permissions.add(
            *__import__("django.contrib.auth.models", fromlist=["Permission"])
            .Permission.objects.filter(codename="can_delete_candidate_records")
        )
        with self.assertRaises(ValueError):
            permanent_delete_enrollment(
                self.enrollment.pk, actor=self.admin,
                reason="", confirmed=True
            )

    def test_permanent_delete_requires_confirmed(self):
        from recruitment.services.retention import permanent_delete_enrollment
        with self.assertRaises(ValueError):
            permanent_delete_enrollment(
                self.enrollment.pk, actor=self.admin,
                reason="valid reason", confirmed=False
            )


# ─────────────────────────────────────────────────────────────
#  View / URL Access Tests
# ─────────────────────────────────────────────────────────────

class ViewAccessTest(TestCase):
    def setUp(self):
        self.client = Client()
        self.admin = make_admin()
        self.drive = make_drive(self.admin)

    def test_drive_list_requires_staff(self):
        response = self.client.get("/recruitment/admin/drives/")
        self.assertIn(response.status_code, [302, 403])

    def test_drive_list_accessible_by_staff(self):
        self.client.force_login(self.admin)
        response = self.client.get("/recruitment/admin/drives/")
        self.assertEqual(response.status_code, 200)

    def test_candidate_dashboard_requires_student_session(self):
        response = self.client.get("/recruitment/dashboard/")
        self.assertRedirects(response, "/", fetch_redirect_response=False)

    def test_integrity_event_endpoint_rejects_unauthenticated(self):
        import json
        response = self.client.post(
            "/recruitment/integrity/event/",
            data=json.dumps({"event_type": "TAB_HIDDEN"}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 403)


# ─────────────────────────────────────────────────────────────
#  Candidate Presence & Heartbeat Tests
# ─────────────────────────────────────────────────────────────

class CandidatePresenceTest(TestCase):
    def setUp(self):
        from django.core.cache import cache
        cache.clear()
        self.admin = make_admin()
        self.student = make_student()
        self.drive = make_drive(self.admin)
        self.drive.status = "ACTIVE"
        self.drive.save()
        self.round_obj = make_round(self.drive, 1, "APTITUDE", 50)
        self.enrollment = CandidateEnrollment.objects.create(
            drive=self.drive,
            student=self.student,
            current_round=self.round_obj,
            status=CandidateEnrollment.STATUS_IN_PROGRESS,
        )

    def test_heartbeat_creates_and_updates_in_place(self):
        from recruitment.services.presence import CandidatePresenceService
        from recruitment.models import CandidatePresence

        # First heartbeat
        res1 = CandidatePresenceService.record_heartbeat(
            student=self.student,
            ip_address="192.168.1.10",
        )
        self.assertEqual(res1["status"], "ok")
        self.assertEqual(res1["connection_status"], "CONNECTED")
        self.assertEqual(CandidatePresence.objects.filter(enrollment=self.enrollment).count(), 1)

        # Clear rate limit cache to allow immediate second heartbeat
        from django.core.cache import cache
        cache.clear()

        # Second heartbeat should update existing record, not create a new one
        res2 = CandidatePresenceService.record_heartbeat(
            student=self.student,
            ip_address="192.168.1.10",
            activity_type="EXAM_NAVIGATION",
        )
        self.assertEqual(res2["status"], "ok")
        self.assertEqual(CandidatePresence.objects.filter(enrollment=self.enrollment).count(), 1)

        presence = CandidatePresence.objects.get(enrollment=self.enrollment)
        self.assertEqual(presence.last_activity_type, "EXAM_NAVIGATION")

    def test_heartbeat_rate_limiting(self):
        from recruitment.services.presence import CandidatePresenceService
        from django.core.cache import cache
        cache.clear()

        # 1st heartbeat succeeds
        res1 = CandidatePresenceService.record_heartbeat(student=self.student)
        self.assertEqual(res1["status"], "ok")

        # 2nd immediate heartbeat should be rate-limited
        res2 = CandidatePresenceService.record_heartbeat(student=self.student)
        self.assertEqual(res2["status"], "rate_limited")

    def test_connection_status_classification(self):
        from datetime import timedelta
        from django.utils import timezone
        from recruitment.models import CandidatePresence

        now = timezone.now()
        presence = CandidatePresence.objects.create(
            enrollment=self.enrollment,
            last_heartbeat=now - timedelta(seconds=20),
        )
        self.assertEqual(presence.connection_status, "CONNECTED")
        self.assertTrue(presence.is_online)

        # Stale (> 45s)
        presence.last_heartbeat = now - timedelta(seconds=60)
        presence.save()
        self.assertEqual(presence.connection_status, "STALE")
        self.assertFalse(presence.is_online)

        # Disconnected (> 120s)
        presence.last_heartbeat = now - timedelta(seconds=180)
        presence.save()
        self.assertEqual(presence.connection_status, "DISCONNECTED")
        self.assertFalse(presence.is_online)

    def test_record_activity_updates_presence(self):
        from recruitment.services.presence import CandidatePresenceService
        from recruitment.models import CandidatePresence

        CandidatePresenceService.record_activity(
            student=self.student,
            activity_type="MCQ_ANSWER_SAVED",
            ip_address="192.168.1.25",
        )
        presence = CandidatePresence.objects.filter(enrollment=self.enrollment).first()
        self.assertIsNotNone(presence)
        self.assertEqual(presence.last_activity_type, "MCQ_ANSWER_SAVED")
        self.assertIsNotNone(presence.last_persisted_at)


# ─────────────────────────────────────────────────────────────
#  Integrity Event Service Tests
# ─────────────────────────────────────────────────────────────

class IntegrityEventServiceTest(TestCase):
    def setUp(self):
        from django.core.cache import cache
        cache.clear()
        self.admin = make_admin()
        self.student = make_student()
        self.drive = make_drive(self.admin)
        self.drive.status = "ACTIVE"
        self.drive.save()
        self.round_obj = make_round(self.drive, 1, "APTITUDE", 50)
        self.round_obj.tab_switch_warning_threshold = 2
        self.round_obj.fullscreen_exit_warning_threshold = 2
        self.round_obj.save()
        self.enrollment = CandidateEnrollment.objects.create(
            drive=self.drive,
            student=self.student,
            current_round=self.round_obj,
            status=CandidateEnrollment.STATUS_IN_PROGRESS,
        )

    def test_tab_switch_escalation_to_warning(self):
        from recruitment.services.integrity import IntegrityEventService
        from recruitment.models import IntegrityEvent

        # 1st event: below threshold -> INFO
        r1 = IntegrityEventService.record_event(
            student=self.student,
            event_type=IntegrityEvent.EVENT_TAB_HIDDEN,
        )
        self.assertEqual(r1["status"], "recorded")
        self.assertEqual(r1["severity"], IntegrityEvent.SEVERITY_INFO)

        # Advance time beyond deduplication window
        from django.utils import timezone
        from datetime import timedelta
        IntegrityEvent.objects.filter(id=r1["event_id"]).update(
            occurred_at=timezone.now() - timedelta(seconds=15)
        )

        # 2nd event: reaches threshold (2) -> WARNING
        r2 = IntegrityEventService.record_event(
            student=self.student,
            event_type=IntegrityEvent.EVENT_TAB_HIDDEN,
        )
        self.assertEqual(r2["status"], "recorded")
        self.assertEqual(r2["severity"], IntegrityEvent.SEVERITY_WARNING)

    def test_event_deduplication_within_window(self):
        from recruitment.services.integrity import IntegrityEventService
        from recruitment.models import IntegrityEvent

        r1 = IntegrityEventService.record_event(
            student=self.student,
            event_type=IntegrityEvent.EVENT_FULLSCREEN_EXIT,
        )
        self.assertEqual(r1["status"], "recorded")

        # Second rapid event within window should deduplicate
        r2 = IntegrityEventService.record_event(
            student=self.student,
            event_type=IntegrityEvent.EVENT_FULLSCREEN_EXIT,
        )
        self.assertEqual(r2["status"], "deduplicated")
        self.assertEqual(r2["event_id"], r1["event_id"])
        self.assertEqual(r2["repeat_count"], 2)

        # Only one row created
        self.assertEqual(
            IntegrityEvent.objects.filter(enrollment=self.enrollment).count(), 1
        )

    def test_invigilator_workflow_acknowledge_and_review(self):
        from recruitment.services.integrity import IntegrityEventService
        from recruitment.models import IntegrityEvent, AuditLog

        r = IntegrityEventService.record_event(
            student=self.student,
            event_type=IntegrityEvent.EVENT_TAB_HIDDEN,
        )
        event_id = r["event_id"]

        # Acknowledge
        ev = IntegrityEventService.acknowledge_event(event_id, self.admin)
        self.assertTrue(ev.acknowledged)
        self.assertEqual(ev.acknowledged_by, self.admin)
        self.assertTrue(
            AuditLog.objects.filter(action=AuditLog.WARNING_ACKNOWLEDGED).exists()
        )

        # Review with note
        ev_reviewed = IntegrityEventService.review_event(
            event_id, self.admin, "Permitted system notification tab switch."
        )
        self.assertTrue(ev_reviewed.reviewed)
        self.assertEqual(ev_reviewed.reviewed_by, self.admin)
        self.assertIn("Permitted", ev_reviewed.review_note)
        self.assertTrue(
            AuditLog.objects.filter(action=AuditLog.INTEGRITY_REVIEW).exists()
        )

    def test_add_invigilator_note(self):
        from recruitment.services.integrity import IntegrityEventService
        from recruitment.models import IntegrityEvent, AuditLog

        note_ev = IntegrityEventService.add_invigilator_note(
            enrollment_id=self.enrollment.id,
            user=self.admin,
            note="Candidate requested temporary assistance with network cable.",
            ip_address="192.168.1.100",
        )
        self.assertEqual(note_ev.event_type, IntegrityEvent.EVENT_INVIGILATOR_NOTE)
        self.assertEqual(note_ev.enrollment, self.enrollment)
        self.assertTrue(
            AuditLog.objects.filter(action=AuditLog.INVIGILATOR_NOTE).exists()
        )


# ─────────────────────────────────────────────────────────────
#  Live Invigilator Console Tests
# ─────────────────────────────────────────────────────────────

class LiveInvigilatorConsoleTest(TestCase):
    def setUp(self):
        self.client = Client()
        self.admin = make_admin()
        self.student = make_student()
        self.drive = make_drive(self.admin)
        self.drive.status = "ACTIVE"
        self.drive.save()
        self.round_obj = make_round(self.drive, 1, "APTITUDE", 50)
        self.enrollment = CandidateEnrollment.objects.create(
            drive=self.drive,
            student=self.student,
            current_round=self.round_obj,
            status=CandidateEnrollment.STATUS_IN_PROGRESS,
        )

    def test_console_requires_staff(self):
        resp = self.client.get(f"/recruitment/admin/drives/{self.drive.id}/monitor/")
        self.assertIn(resp.status_code, [302, 403])

    def test_console_accessible_by_staff(self):
        self.client.force_login(self.admin)
        resp = self.client.get(f"/recruitment/admin/drives/{self.drive.id}/monitor/")
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Live Invigilator Console")
        self.assertContains(resp, self.student.usn)

    def test_incremental_updates_endpoint(self):
        self.client.force_login(self.admin)
        resp = self.client.get(
            f"/recruitment/admin/drives/{self.drive.id}/monitor/updates/?since_event_id=0"
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("metrics", data)
        self.assertIn("new_events", data)
        self.assertEqual(data["metrics"]["total_enrolled"], 1)

    def test_candidate_heartbeat_authenticated_session(self):
        # Set active token on student
        self.student.active_token = "test_token_123"
        self.student.save()

        # Log student in via session
        session = self.client.session
        session["student_id"] = self.student.id
        session["token"] = "test_token_123"
        session.save()

        import json
        resp = self.client.post(
            "/recruitment/heartbeat/",
            data=json.dumps({"client_ts": "2026-10-29T18:00:00Z"}),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data.get("ok"))
        self.assertIn(data.get("connection_status"), ["CONNECTED", "STALE", "DISCONNECTED"])


# Import Scenario A-G End-to-End Tests
from .tests_e2e_scenarios import EndToEndRecruitmentWorkflowTests



