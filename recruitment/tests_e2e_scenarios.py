"""
recruitment/tests_e2e_scenarios.py
==================================
Comprehensive end-to-end verification covering Scenarios A through G:
- Scenario A: Full successful candidate path (Login -> Instructions -> MCQ -> Coding C/Python -> Submit -> Feedback -> Done -> Progression -> Next Round)
- Scenario B: Cutoff failure rejection
- Scenario C: Interrupted session & exam resume
- Scenario D: Academic integrity violation & invigilator monitor
- Scenario F: Cross-student unauthorized attempt isolation
- Scenario G: C & C++ compiler compilation & error reporting
"""

from datetime import date, timedelta
from decimal import Decimal
import json

from django.contrib.auth.models import User
from django.test import TestCase, Client
from django.urls import reverse
from django.utils import timezone

from portal.models import (
    Exam, Section, Student, Question, Option, Attempt, Answer,
    Feedback, CodingQuestion, TestCase as CodingTestCase, CodeSubmission,
    CodeDraft, CodingQuestionAssignment, ExecutionJob
)
from portal.runner import run_code, LANGUAGES
from portal.judge import judge
from recruitment.models import (
    AuditLog,
    CandidateEnrollment,
    CandidatePresence,
    IntegrityEvent,
    RecruitmentDrive,
    Round,
    RoundResult,
)
from recruitment.services.progression import process_round_results


class EndToEndRecruitmentWorkflowTests(TestCase):
    """Exhaustive verification of end-to-end student and recruitment flows."""

    def setUp(self):
        self.admin = User.objects.create_superuser(
            username="placement_officer",
            email="po@college.edu",
            password="adminpassword123",
        )
        self.client = Client()

        # Create Student
        self.student = Student.objects.create(
            usn="1RV21CS099",
            name="Rohit Sharma",
            dob=date(2003, 4, 30),
            email="rohit@college.edu",
            is_active=True,
        )

        # Create Exam with 1 MCQ Section and 1 CODING Section
        now = timezone.now()
        self.exam = Exam.objects.create(
            title="Campus Tech Drive 2026 Assessment",
            instructions="Maintain silence and adhere to lab guidelines.",
            min_stay_minutes=0,  # allow immediate submission in tests
        )

        # Initially MCQ section is active, Coding is upcoming
        self.sec_mcq = Section.objects.create(
            exam=self.exam,
            title="Aptitude & Logical",
            order=1,
            kind="MCQ",
            start_time=now - timedelta(minutes=5),
            end_time=now + timedelta(hours=1),
        )

        self.q1 = Question.objects.create(
            section=self.sec_mcq,
            text="What is 15 * 4?",
            marks=5,
        )
        self.opt1_correct = Option.objects.create(
            question=self.q1, text="60", is_correct=True
        )
        self.opt1_wrong = Option.objects.create(
            question=self.q1, text="55", is_correct=False
        )

        self.sec_coding = Section.objects.create(
            exam=self.exam,
            title="Data Structures & Algorithms",
            order=2,
            kind="CODING",
            start_time=now + timedelta(hours=1),
            end_time=now + timedelta(hours=2),
        )

        self.coding_q = CodingQuestion.objects.create(
            section=self.sec_coding,
            title="Sum of Two Numbers",
            statement="Read two integers a and b from stdin and print their sum.",
            sample_input="5 7\n",
            sample_output="12\n",
            marks=10,
            time_limit_seconds=2,
        )
        CodingTestCase.objects.create(
            question=self.coding_q,
            input_data="10 20\n",
            expected_output="30\n",
            marks=5,
            is_sample=True,
        )
        CodingTestCase.objects.create(
            question=self.coding_q,
            input_data="100 250\n",
            expected_output="350\n",
            marks=5,
            is_sample=False,
        )

        # Create Drive with 2 Rounds
        self.drive = RecruitmentDrive.objects.create(
            name="Infosys Campus Placement 2026",
            company_name="Infosys",
            role="Specialist Programmer",
            start_date=date.today(),
            end_date=date.today() + timedelta(days=7),
            created_by=self.admin,
            status=RecruitmentDrive.STATUS_ACTIVE,
        )

        self.round_1 = Round.objects.create(
            drive=self.drive,
            name="Round 1: Online Technical Assessment",
            round_type="CODING",
            order=1,
            pass_threshold_percent=Decimal("50.00"),
            is_mandatory=True,
            exam=self.exam,
        )

        self.round_2 = Round.objects.create(
            drive=self.drive,
            name="Round 2: Technical Interview",
            round_type="TECHNICAL",
            order=2,
            pass_threshold_percent=Decimal("60.00"),
            is_mandatory=True,
        )

    def _login_candidate(self, student=None):
        student = student or self.student
        client = Client()
        login_resp = client.post(
            reverse("login"),
            {"usn": student.usn, "dob": student.dob.strftime("%Y-%m-%d")},
            follow=True,
        )
        self.assertEqual(login_resp.status_code, 200)
        return client

    def test_scenario_a_full_successful_candidate_flow(self):
        """
        Scenario A:
        1. Bulk-enroll student into active drive.
        2. Student logs in via USN+DOB, pick_exam resolves drive round exam.
        3. Accepts instructions.
        4. Answers MCQ correctly.
        5. Writes C code, runs sample, submits code, receives Accepted.
        6. Submits exam, submits feedback.
        7. Results displayed on done_page, session token revoked.
        8. Progression algorithm advances candidate to Round 2.
        """
        # Step 1: Admin bulk-enrolls student
        self.client.force_login(self.admin)
        enroll_resp = self.client.post(
            reverse("recruitment:enroll_students", kwargs={"drive_id": self.drive.id}),
            {"usn_list": self.student.usn},
            follow=True,
        )
        self.assertEqual(enroll_resp.status_code, 200)

        enrollment = CandidateEnrollment.objects.get(drive=self.drive, student=self.student)
        self.assertEqual(enrollment.current_round, self.round_1)
        self.assertTrue(self.exam.students.filter(id=self.student.id).exists())

        # Step 2: Candidate logs in
        student_client = self._login_candidate()

        # Step 3: Instructions & rule agreement
        inst_resp = student_client.post(reverse("instructions"), {"agree": "on"}, follow=True)
        self.assertEqual(inst_resp.status_code, 200)

        attempt = Attempt.objects.get(student=self.student, exam=self.exam)
        self.assertIsNotNone(attempt)

        # Step 4: MCQ Assessment
        save_ans_resp = student_client.post(
            reverse("save_answer"),
            data=json.dumps({"question_id": self.q1.id, "option_id": self.opt1_correct.id}),
            content_type="application/json",
        )
        self.assertEqual(save_ans_resp.status_code, 200)
        self.assertTrue(save_ans_resp.json()["ok"])

        # Transition to Coding Section
        now_ts = timezone.now()
        self.sec_mcq.end_time = now_ts - timedelta(seconds=1)
        self.sec_mcq.save()
        self.sec_coding.start_time = now_ts - timedelta(seconds=1)
        self.sec_coding.end_time = now_ts + timedelta(hours=1)
        self.sec_coding.save()

        # Step 5: Coding Assessment in C
        c_solution = (
            "#include <stdio.h>\n"
            "int main(void) {\n"
            "    int a, b;\n"
            "    if (scanf(\"%d %d\", &a, &b) == 2) {\n"
            "        printf(\"%d\\n\", a + b);\n"
            "    }\n"
            "    return 0;\n"
            "}\n"
        )
        # 5a: Run C code
        run_resp = student_client.post(
            reverse("code_run"),
            data=json.dumps({
                "question_id": self.coding_q.id,
                "language": "c",
                "code": c_solution,
                "stdin": "5 7\n",
            }),
            content_type="application/json",
        )
        self.assertEqual(run_resp.status_code, 200)
        run_data = run_resp.json()
        self.assertTrue(run_data["ok"])
        self.assertEqual(run_data["status"], "ok")
        self.assertEqual(run_data["stdout"].strip(), "12")

        # 5b: Submit C code
        submit_code_resp = student_client.post(
            reverse("code_submit"),
            data=json.dumps({
                "question_id": self.coding_q.id,
                "language": "c",
                "code": c_solution,
            }),
            content_type="application/json",
        )
        self.assertEqual(submit_code_resp.status_code, 200)
        submit_data = submit_code_resp.json()
        self.assertTrue(submit_data["ok"])
        self.assertEqual(submit_data["verdict"], "Accepted")
        self.assertEqual(submit_data["passed"], 2)
        self.assertEqual(submit_data["score"], 10)

        # Step 6: Submit Exam & Feedback
        exam_submit_resp = student_client.post(reverse("submit_exam"), follow=True)
        self.assertEqual(exam_submit_resp.status_code, 200)
        attempt.refresh_from_db()
        self.assertIsNotNone(attempt.submitted_at)

        feedback_resp = student_client.post(
            reverse("feedback"),
            {"experience": 5, "realism": 5, "comments": "Excellent simulation!"},
            follow=True,
        )
        self.assertEqual(feedback_resp.status_code, 200)
        self.assertContains(feedback_resp, "Assessment Complete")

        # Verify session token revoked
        self.student.refresh_from_db()
        self.assertEqual(self.student.active_token, "")

        # Step 7: Server-authoritative promotion
        summary = process_round_results(self.round_1.id, triggered_by=self.admin)
        self.assertEqual(summary["passed"], 1)
        self.assertEqual(summary["failed"], 0)

        enrollment.refresh_from_db()
        self.assertEqual(enrollment.current_round, self.round_2)

        res = RoundResult.objects.get(enrollment=enrollment, round=self.round_1)
        self.assertEqual(res.decision, RoundResult.DECISION_PASS)
        self.assertEqual(res.total_score, Decimal("15.00"))  # 5 MCQ + 10 Coding
        self.assertEqual(res.max_score, Decimal("15.00"))
        self.assertEqual(res.percentage, Decimal("100.00"))

    def test_scenario_b_candidate_failed_cutoff(self):
        """
        Scenario B: Candidate scores 0% (below 50% threshold) and is rejected.
        """
        enrollment = CandidateEnrollment.objects.create(
            drive=self.drive,
            student=self.student,
            current_round=self.round_1,
            status=CandidateEnrollment.STATUS_ENROLLED,
        )
        self.exam.students.add(self.student)

        # Candidate logs in, creates attempt, answers MCQ with wrong answer
        client = self._login_candidate()
        client.post(reverse("instructions"), {"agree": "on"})
        client.post(
            reverse("save_answer"),
            data=json.dumps({"question_id": self.q1.id, "option_id": self.opt1_wrong.id}),
            content_type="application/json",
        )
        client.post(reverse("submit_exam"))

        summary = process_round_results(self.round_1.id, triggered_by=self.admin)
        self.assertEqual(summary["failed"], 1)

        enrollment.refresh_from_db()
        self.assertEqual(enrollment.status, CandidateEnrollment.STATUS_FAILED)

        res = RoundResult.objects.get(enrollment=enrollment, round=self.round_1)
        self.assertEqual(res.decision, RoundResult.DECISION_FAIL)
        self.assertEqual(res.percentage, Decimal("0.00"))

    def test_scenario_c_disconnect_reconnect_resume(self):
        """
        Scenario C: Candidate disconnects mid-exam; re-login restores answers and draft code.
        """
        self.exam.students.add(self.student)
        client1 = self._login_candidate()
        client1.post(reverse("instructions"), {"agree": "on"})

        # Save an answer
        client1.post(
            reverse("save_answer"),
            data=json.dumps({"question_id": self.q1.id, "option_id": self.opt1_correct.id}),
            content_type="application/json",
        )
        # Transition to coding section to save code draft
        now_ts = timezone.now()
        self.sec_mcq.end_time = now_ts - timedelta(seconds=1)
        self.sec_mcq.save()
        self.sec_coding.start_time = now_ts - timedelta(seconds=1)
        self.sec_coding.end_time = now_ts + timedelta(hours=1)
        self.sec_coding.save()

        # Save a code draft
        client1.post(
            reverse("save_code"),
            data=json.dumps({
                "question_id": self.coding_q.id,
                "language": "python",
                "code": "# Draft solution\nprint(10)",
            }),
            content_type="application/json",
        )

        # Simulate disconnect and seat unlock by invigilator
        self.student.active_token = ""
        self.student.save()

        # Candidate logs back in on replacement computer
        client2 = self._login_candidate()
        exam_resp = client2.get(reverse("exam"))
        self.assertEqual(exam_resp.status_code, 200)

        # Check that answer is preserved
        attempt = Attempt.objects.get(student=self.student, exam=self.exam)
        ans = Answer.objects.filter(attempt=attempt, question=self.q1).first()
        self.assertIsNotNone(ans)
        self.assertEqual(ans.selected_option, self.opt1_correct)

        # Check that code draft is preserved
        draft = CodeDraft.objects.filter(attempt=attempt, question=self.coding_q).first()
        self.assertIsNotNone(draft)
        self.assertIn("Draft solution", draft.code)

    def test_scenario_d_academic_integrity_tab_switch(self):
        """
        Scenario D: Integrity events are recorded and reflected in the live monitor.
        """
        enrollment = CandidateEnrollment.objects.create(
            drive=self.drive,
            student=self.student,
            current_round=self.round_1,
            status=CandidateEnrollment.STATUS_IN_PROGRESS,
        )
        self.exam.students.add(self.student)
        client = self._login_candidate()
        client.post(reverse("instructions"), {"agree": "on"})

        # Record tab hidden event
        event_resp = client.post(
            reverse("recruitment:integrity_event"),
            data=json.dumps({
                "event_type": "TAB_HIDDEN",
                "client_ts": "2026-10-29T18:00:00Z",
                "elapsed_seconds": 120,
            }),
            content_type="application/json",
        )
        self.assertEqual(event_resp.status_code, 200)
        self.assertTrue(event_resp.json()["ok"])

        # Check invigilator monitor incremental updates
        staff_client = Client()
        staff_client.force_login(self.admin)
        mon_resp = staff_client.get(
            reverse("recruitment:live_monitor_updates", kwargs={"drive_id": self.drive.id})
            + "?since_event_id=0"
        )
        self.assertEqual(mon_resp.status_code, 200)
        events = mon_resp.json()["new_events"]
        self.assertTrue(any("Hidden" in e["event_type"] or e["event_type"] == "TAB_HIDDEN" for e in events))

    def test_scenario_f_cross_student_tampering_blocked(self):
        """
        Scenario F: Candidate cannot tamper with another candidate's attempt.
        """
        student2 = Student.objects.create(
            usn="1RV21CS100",
            name="Sneha Rao",
            dob=date(2003, 7, 21),
            is_active=True,
        )
        self.exam.students.add(self.student, student2)

        # Student 1 creates attempt
        c1 = self._login_candidate(self.student)
        c1.post(reverse("instructions"), {"agree": "on"})
        attempt1 = Attempt.objects.get(student=self.student, exam=self.exam)

        # Student 2 logs in
        c2 = self._login_candidate(student2)
        c2.post(reverse("instructions"), {"agree": "on"})

        # Transition to coding section
        now_ts = timezone.now()
        self.sec_mcq.end_time = now_ts - timedelta(seconds=1)
        self.sec_mcq.save()
        self.sec_coding.start_time = now_ts - timedelta(seconds=1)
        self.sec_coding.end_time = now_ts + timedelta(hours=1)
        self.sec_coding.save()

        # Student 2 tries to save code for Student 1's question on Student 2's session
        # _coding_request binds to request.session's student attempt, never cross-contaminates
        save_resp = c2.post(
            reverse("save_code"),
            data=json.dumps({
                "question_id": self.coding_q.id,
                "language": "python",
                "code": "print('Malicious')",
            }),
            content_type="application/json",
        )
        self.assertEqual(save_resp.status_code, 200)

        # Verify Student 1's draft is NOT modified
        draft1 = CodeDraft.objects.filter(attempt=attempt1, question=self.coding_q).first()
        self.assertIsNone(draft1)

    def test_scenario_g_c_and_cpp_compilation_and_errors(self):
        """
        Scenario G:
        - C code compiles and runs.
        - C++ code compiles and runs.
        - C compilation failure returns 'Compilation Error' in judge.
        """
        # C execution
        c_code = "#include <stdio.h>\nint main(void) { printf(\"C_OK\\n\"); return 0; }\n"
        res_c = run_code("c", c_code, time_limit=2)
        self.assertEqual(res_c["status"], "ok")
        self.assertEqual(res_c["stdout"].strip(), "C_OK")

        # C++ execution
        cpp_code = "#include <iostream>\nint main(void) { std::cout << \"CPP_OK\" << std::endl; return 0; }\n"
        res_cpp = run_code("cpp", cpp_code, time_limit=2)
        self.assertEqual(res_cpp["status"], "ok")
        self.assertEqual(res_cpp["stdout"].strip(), "CPP_OK")

        # C compilation syntax error
        c_broken = "#include <stdio.h>\nint main(void) { syntax_error; }\n"
        res_err = run_code("c", c_broken, time_limit=2)
        self.assertEqual(res_err["status"], "compile_error")
        self.assertIn("error:", res_err["stderr"])

        # Judge evaluation on compilation failure
        judge_res = judge(self.coding_q, "c", c_broken)
        self.assertEqual(judge_res["verdict"], "Compilation Error")
        self.assertEqual(judge_res["passed"], 0)
        self.assertEqual(judge_res["score"], 0)
