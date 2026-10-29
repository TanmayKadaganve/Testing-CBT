"""
portal/tests_multilang.py
=========================
Comprehensive test suite verifying:
- Model and migration integrity (CodingQuestionStarterCode, CodeDraft uniqueness)
- Starter code resolution precedence (Override -> Generic Scaffold -> Draft restore)
- Independent multi-language drafts per (attempt, question, language)
- Version-controlled optimistic concurrency (preventing outdated autosave overwrite)
- Multi-language compilation and execution (Python, C, C++)
- Compilation and runtime error verdicts
- LanguageRegistry diagnostics and unavailability handling
"""

import datetime
from decimal import Decimal
import json

from django.contrib.auth.models import User
from django.db import IntegrityError
from django.test import TestCase, Client
from django.urls import reverse
from django.utils import timezone

from portal.models import (
    Student, Exam, Section, CodingQuestion, TestCase as CodingTestCase,
    Attempt, CodeDraft, CodeSubmission, ExecutionJob, CodingQuestionStarterCode
)
from portal.services.language_registry import LanguageRegistry
from portal.services.starter_code import StarterCodeService
from portal.services.code_draft import CodeDraftService
from portal.runner import run_code
from portal.judge import judge


class MultiLanguageArchitectureTests(TestCase):
    """Verifies schema, registry, starter code, and independent draft persistence."""

    def setUp(self):
        self.student1 = Student.objects.create(
            usn="1MS21CS101",
            name="Aarav Patel",
            dob=datetime.date(2003, 3, 15),
            email="aarav@college.edu",
            is_active=True,
        )
        self.student2 = Student.objects.create(
            usn="1MS21CS102",
            name="Diya Sen",
            dob=datetime.date(2003, 7, 22),
            email="diya@college.edu",
            is_active=True,
        )

        now = timezone.now()
        self.exam = Exam.objects.create(
            title="Multi-Language Assessment 2026",
            instructions="Standard examination rules apply.",
            min_stay_minutes=0,
        )
        self.exam.students.add(self.student1, self.student2)

        self.section = Section.objects.create(
            exam=self.exam,
            title="Algorithms & Problem Solving",
            order=1,
            kind="CODING",
            start_time=now - datetime.timedelta(minutes=10),
            end_time=now + datetime.timedelta(hours=2),
        )

        self.question = CodingQuestion.objects.create(
            section=self.section,
            order=1,
            title="Multiply Two Integers",
            statement="Read integers a and b from stdin and print their product a * b.",
            input_format="Two space-separated integers a and b.",
            output_format="A single integer representing the product.",
            sample_input="4 5\n",
            sample_output="20\n",
            marks=10,
            time_limit_seconds=2,
        )

        self.tc_sample = CodingTestCase.objects.create(
            question=self.question,
            input_data="4 5\n",
            expected_output="20\n",
            marks=5,
            is_sample=True,
        )
        self.tc_hidden = CodingTestCase.objects.create(
            question=self.question,
            input_data="12 12\n",
            expected_output="144\n",
            marks=5,
            is_sample=False,
        )

        self.attempt1 = Attempt.objects.create(student=self.student1, exam=self.exam)
        self.attempt2 = Attempt.objects.create(student=self.student2, exam=self.exam)

    # ─────────────────────────────────────────────────────────────
    #  1. Language Registry Tests
    # ─────────────────────────────────────────────────────────────

    def test_language_registry_supported_languages(self):
        supported = LanguageRegistry.get_supported_language_ids()
        self.assertIn("python", supported)
        self.assertIn("c", supported)
        self.assertIn("cpp", supported)
        # Java is not installed on this host and should be unavailable
        self.assertNotIn("java", supported)

    def test_language_registry_diagnostics(self):
        diag = LanguageRegistry.get_diagnostics()
        diag_map = {d["id"]: d for d in diag}

        self.assertTrue(diag_map["python"]["available"])
        self.assertTrue(diag_map["c"]["available"])
        self.assertTrue(diag_map["cpp"]["available"])
        self.assertFalse(diag_map["java"]["available"])
        self.assertIn("Java Runtime", diag_map["java"]["reason"])

    # ─────────────────────────────────────────────────────────────
    #  2. Starter Code Precedence Tests
    # ─────────────────────────────────────────────────────────────

    def test_starter_code_generic_fallback(self):
        # Question has no custom starter code configured
        py_starter = StarterCodeService.get_starter_code(self.question, "python")
        c_starter = StarterCodeService.get_starter_code(self.question, "c")
        cpp_starter = StarterCodeService.get_starter_code(self.question, "cpp")

        self.assertIn("def solve():", py_starter)
        self.assertIn("int main(void)", c_starter)
        self.assertIn("using namespace std;", cpp_starter)

    def test_starter_code_custom_override(self):
        # Configure a custom override for Python
        custom_py = "# Custom Python Template for Multiply\na, b = map(int, input().split())\n"
        CodingQuestionStarterCode.objects.create(
            coding_question=self.question,
            language="python",
            code=custom_py,
        )

        resolved_py = StarterCodeService.get_starter_code(self.question, "python")
        resolved_c = StarterCodeService.get_starter_code(self.question, "c")

        self.assertEqual(resolved_py, custom_py)
        # C should still fallback to generic C starter scaffold
        self.assertIn("int main(void)", resolved_c)

    def test_starter_code_uniqueness_constraint(self):
        CodingQuestionStarterCode.objects.create(
            coding_question=self.question,
            language="python",
            code="print(1)",
        )
        with self.assertRaises(IntegrityError):
            CodingQuestionStarterCode.objects.create(
                coding_question=self.question,
                language="python",
                code="print(2)",
            )

    # ─────────────────────────────────────────────────────────────
    #  3. Independent Multi-Language Drafts Tests
    # ─────────────────────────────────────────────────────────────

    def test_independent_drafts_coexist_per_language(self):
        """
        Verify that a student can have independent drafts in Python, C, and C++
        for the exact same attempt and question without clobbering each other.
        """
        py_code = "# Python solution\nprint(20)\n"
        c_code = "/* C solution */\n#include <stdio.h>\nint main() { printf(\"20\\n\"); return 0; }\n"
        cpp_code = "// C++ solution\n#include <iostream>\nint main() { std::cout << 20 << std::endl; return 0; }\n"

        draft_py, err1 = CodeDraftService.save_draft(self.attempt1, self.question, "python", py_code, version=1)
        draft_c, err2 = CodeDraftService.save_draft(self.attempt1, self.question, "c", c_code, version=1)
        draft_cpp, err3 = CodeDraftService.save_draft(self.attempt1, self.question, "cpp", cpp_code, version=1)

        self.assertIsNone(err1)
        self.assertIsNone(err2)
        self.assertIsNone(err3)

        # Verify all 3 drafts exist in database
        drafts = CodeDraft.objects.filter(attempt=self.attempt1, question=self.question)
        self.assertEqual(drafts.count(), 3)

        # Verify exact code preservation per language
        fetch_py = CodeDraftService.get_draft(self.attempt1, self.question, "python")
        fetch_c = CodeDraftService.get_draft(self.attempt1, self.question, "c")
        fetch_cpp = CodeDraftService.get_draft(self.attempt1, self.question, "cpp")

        self.assertEqual(fetch_py.code, py_code)
        self.assertEqual(fetch_c.code, c_code)
        self.assertEqual(fetch_cpp.code, cpp_code)

    def test_out_of_order_autosave_prevention(self):
        """
        Ensure delayed, out-of-order network autosaves with older versions
        cannot overwrite newer code.
        """
        # Save version 2
        CodeDraftService.save_draft(self.attempt1, self.question, "python", "version 2 code", version=2)

        # Attempt to save delayed version 1
        draft, err = CodeDraftService.save_draft(self.attempt1, self.question, "python", "stale version 1 code", version=1)
        self.assertIsNone(err)

        current = CodeDraftService.get_draft(self.attempt1, self.question, "python")
        self.assertEqual(current.code, "version 2 code")
        self.assertEqual(current.version, 2)

    def test_unsupported_language_draft_rejected(self):
        draft, err = CodeDraftService.save_draft(self.attempt1, self.question, "rust", "fn main() {}", version=1)
        self.assertIsNone(draft)
        self.assertIn("Unsupported language", err)

    def test_resolve_question_state_with_and_without_drafts(self):
        # 1. Initially without drafts: loads starter codes, active_lang is python
        q_state = CodeDraftService.resolve_question_state(self.attempt1, self.question)
        self.assertEqual(q_state["active_language"], "python")
        self.assertIn("def solve():", q_state["code"])
        self.assertIn("python", q_state["starter_codes"])
        self.assertIn("c", q_state["starter_codes"])
        self.assertIn("cpp", q_state["starter_codes"])

        # 2. Student writes in C and saves
        c_code = "#include <stdio.h>\nint main(void) { return 0; }\n"
        CodeDraftService.save_draft(self.attempt1, self.question, "c", c_code, version=1)

        # Now resolve question state: active language should be C because it's the latest updated draft
        q_state_updated = CodeDraftService.resolve_question_state(self.attempt1, self.question)
        self.assertEqual(q_state_updated["active_language"], "c")
        self.assertEqual(q_state_updated["code"], c_code)
        self.assertIn("c", q_state_updated["drafts"])

    # ─────────────────────────────────────────────────────────────
    #  4. Multi-Language Execution & Grading Tests
    # ─────────────────────────────────────────────────────────────

    def test_python_run_and_judge(self):
        py_sol = (
            "import sys\n"
            "a, b = map(int, sys.stdin.read().split())\n"
            "print(a * b)\n"
        )
        # Run code against sample
        res_run = run_code("python", py_sol, stdin_text="4 5\n", time_limit=2)
        self.assertEqual(res_run["status"], "ok")
        self.assertEqual(res_run["stdout"].strip(), "20")

        # Judge against all testcases
        judge_res = judge(self.question, "python", py_sol)
        self.assertEqual(judge_res["verdict"], "Accepted")
        self.assertEqual(judge_res["passed"], 2)
        self.assertEqual(judge_res["score"], 10)

    def test_c_run_and_judge(self):
        c_sol = (
            "#include <stdio.h>\n"
            "int main(void) {\n"
            "    int a, b;\n"
            "    if (scanf(\"%d %d\", &a, &b) == 2) {\n"
            "        printf(\"%d\\n\", a * b);\n"
            "    }\n"
            "    return 0;\n"
            "}\n"
        )
        res_run = run_code("c", c_sol, stdin_text="4 5\n", time_limit=2)
        self.assertEqual(res_run["status"], "ok")
        self.assertEqual(res_run["stdout"].strip(), "20")

        judge_res = judge(self.question, "c", c_sol)
        self.assertEqual(judge_res["verdict"], "Accepted")
        self.assertEqual(judge_res["passed"], 2)
        self.assertEqual(judge_res["score"], 10)

    def test_cpp_run_and_judge(self):
        cpp_sol = (
            "#include <iostream>\n"
            "using namespace std;\n"
            "int main() {\n"
            "    int a, b;\n"
            "    if (cin >> a >> b) {\n"
            "        cout << a * b << endl;\n"
            "    }\n"
            "    return 0;\n"
            "}\n"
        )
        res_run = run_code("cpp", cpp_sol, stdin_text="4 5\n", time_limit=2)
        self.assertEqual(res_run["status"], "ok")
        self.assertEqual(res_run["stdout"].strip(), "20")

        judge_res = judge(self.question, "cpp", cpp_sol)
        self.assertEqual(judge_res["verdict"], "Accepted")
        self.assertEqual(judge_res["passed"], 2)
        self.assertEqual(judge_res["score"], 10)

    def test_c_compilation_error_handling(self):
        c_broken = "#include <stdio.h>\nint main(void) { syntax_error; }\n"
        res_run = run_code("c", c_broken, time_limit=2)
        self.assertEqual(res_run["status"], "compile_error")
        self.assertIn("error:", res_run["stderr"])

        judge_res = judge(self.question, "c", c_broken)
        self.assertEqual(judge_res["verdict"], "Compilation Error")
        self.assertEqual(judge_res["passed"], 0)
        self.assertEqual(judge_res["score"], 0)

    def test_runtime_error_handling(self):
        py_divzero = "print(10 / 0)\n"
        res_run = run_code("python", py_divzero, time_limit=2)
        self.assertEqual(res_run["status"], "runtime_error")
        self.assertIn("ZeroDivisionError", res_run["stderr"])

        judge_res = judge(self.question, "python", py_divzero)
        self.assertEqual(judge_res["verdict"], "Runtime Error")
        self.assertEqual(judge_res["passed"], 0)

    def test_timeout_handling(self):
        py_infinite = "while True: pass\n"
        res_run = run_code("python", py_infinite, time_limit=1)
        self.assertEqual(res_run["status"], "timeout")

        judge_res = judge(self.question, "python", py_infinite)
        self.assertEqual(judge_res["verdict"], "Time Limit Exceeded")
        self.assertEqual(judge_res["passed"], 0)

    # ─────────────────────────────────────────────────────────────
    #  5. Student Flow & View Endpoints Tests
    # ─────────────────────────────────────────────────────────────

    def _login(self, student):
        client = Client()
        client.post(
            reverse("login"),
            {"usn": student.usn, "dob": student.dob.strftime("%Y-%m-%d")},
            follow=True,
        )
        return client

    def test_candidate_switching_languages_autosaves_and_restores(self):
        client = self._login(self.student1)
        client.post(reverse("instructions"), {"agree": "on"})

        # Step 1: Save a Python draft
        resp1 = client.post(
            reverse("save_code"),
            data=json.dumps({
                "question_id": self.question.id,
                "language": "python",
                "code": "# Student Python draft\nprint('PY')",
                "version": 1,
            }),
            content_type="application/json",
        )
        self.assertEqual(resp1.status_code, 200)

        # Step 2: Switch to C and save a C draft
        resp2 = client.post(
            reverse("save_code"),
            data=json.dumps({
                "question_id": self.question.id,
                "language": "c",
                "code": "/* Student C draft */\n#include <stdio.h>",
                "version": 1,
            }),
            content_type="application/json",
        )
        self.assertEqual(resp2.status_code, 200)

        # Step 3: Fetch coding page and verify both drafts are in context
        page_resp = client.get(reverse("coding"))
        self.assertEqual(page_resp.status_code, 200)
        self.assertContains(page_resp, "Student Python draft")
        self.assertContains(page_resp, "Student C draft")

        # Step 4: Verify in database that both drafts are intact
        py_draft = CodeDraftService.get_draft(self.attempt1, self.question, "python")
        c_draft = CodeDraftService.get_draft(self.attempt1, self.question, "c")
        self.assertIsNotNone(py_draft)
        self.assertIsNotNone(c_draft)
        self.assertIn("Student Python draft", py_draft.code)
        self.assertIn("Student C draft", c_draft.code)

