import datetime
from django.contrib.auth.models import User
from django.test import TestCase, Client
from django.urls import reverse
from django.utils import timezone

from portal.models import (
    Student, Exam, Section, Question, Option, Attempt, Answer,
    Feedback, CodingQuestion, TestCase as CodingTestCase, CodeSubmission,
    CodeDraft, CodingQuestionAssignment, ExecutionJob
)
from portal.runner import run_code
from portal.judge import judge, normalize
from portal.services.dashboard_analytics import get_overview_metrics, get_data_integrity_report
from portal.services.system_health import check_system_health
from portal.middleware import get_performance_metrics


class ExistingWorkflowTests(TestCase):
    """Verifies that existing core CBT workflows are preserved without regression."""

    def setUp(self):
        self.student = Student.objects.create(
            usn="1MS21CS001",
            name="Alice Candidate",
            dob=datetime.date(2003, 5, 14),
            email="alice@example.com",
            is_active=True,
        )
        self.exam = Exam.objects.create(
            title="Placement Assessment 2026",
            instructions="Standard rules apply.",
            min_stay_minutes=90,
        )
        self.exam.students.add(self.student)

        self.section = Section.objects.create(
            exam=self.exam,
            title="Core Python",
            order=1,
            kind="MCQ",
            start_time=timezone.now() - datetime.timedelta(minutes=10),
            end_time=timezone.now() + datetime.timedelta(minutes=50),
        )

    def test_student_usn_uppercased(self):
        student = Student.objects.create(
            usn="1ms21cs999",
            name="Bob",
            dob=datetime.date(2003, 1, 1),
        )
        self.assertEqual(student.usn, "1MS21CS999")

    def test_student_login_success_and_active_token(self):
        client = Client()
        response = client.post(reverse("login"), {
            "usn": "1MS21CS001",
            "dob": "2003-05-14",
        })
        self.assertEqual(response.status_code, 302)
        self.assertIn("instructions", response.url)

        self.student.refresh_from_db()
        self.assertTrue(len(self.student.active_token) > 0)
        self.assertIsNotNone(self.student.last_login_at)

    def test_concurrent_login_blocked(self):
        self.student.active_token = "existing_device_token"
        self.student.save()

        client = Client()
        response = client.post(reverse("login"), {
            "usn": "1MS21CS001",
            "dob": "2003-05-14",
        })
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "already logged in on another computer")

    def test_code_runner_and_judge(self):
        cq = CodingQuestion.objects.create(
            section=self.section,
            order=1,
            title="Sum Two Numbers",
            statement="Read two integers and print their sum.",
            sample_input="2 3\n",
            sample_output="5\n",
            time_limit_seconds=2,
            marks=10,
        )
        CodingTestCase.objects.create(
            question=cq,
            input_data="2 3\n",
            expected_output="5\n",
            is_sample=True,
            marks=5,
        )
        CodingTestCase.objects.create(
            question=cq,
            input_data="10 20\n",
            expected_output="30\n",
            is_sample=False,
            marks=5,
        )

        code = "import sys\na, b = map(int, sys.stdin.read().split())\nprint(a + b)"
        res = judge(cq, "python", code)

        self.assertEqual(res["verdict"], "Accepted")
        self.assertEqual(res["passed"], 2)
        self.assertEqual(res["total"], 2)
        self.assertEqual(res["score"], 10)


class AdminDashboardSecurityAndViewsTests(TestCase):
    """Verifies security, permissions, and behavior of the new Admin Dashboard."""

    def setUp(self):
        self.staff_user = User.objects.create_user(
            username="admin_user",
            password="StrongPassword123!",
            is_staff=True,
            is_superuser=True,
        )
        self.regular_user = User.objects.create_user(
            username="regular_user",
            password="UserPassword123!",
            is_staff=False,
        )
        self.student = Student.objects.create(
            usn="1MS21IS042",
            name="Charlie Engineer",
            dob=datetime.date(2003, 11, 20),
            is_active=True,
        )

    def test_dashboard_unauthorized_redirects_to_login(self):
        client = Client()
        response = client.get(reverse("dashboard_overview"))
        self.assertEqual(response.status_code, 302)
        self.assertIn("/admin/login/", response.url)

    def test_dashboard_regular_user_denied(self):
        client = Client()
        client.login(username="regular_user", password="UserPassword123!")
        response = client.get(reverse("dashboard_overview"))
        self.assertEqual(response.status_code, 302)
        self.assertIn("/admin/login/", response.url)

    def test_dashboard_staff_user_authorized(self):
        client = Client()
        client.login(username="admin_user", password="StrongPassword123!")
        response = client.get(reverse("dashboard_overview"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Overview Analytics")
        self.assertContains(response, "Total Students")

    def test_student_management_search_and_actions(self):
        client = Client()
        client.login(username="admin_user", password="StrongPassword123!")

        # 1. Search
        response = client.get(reverse("dashboard_students") + "?q=Charlie")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "1MS21IS042")

        # 2. Toggle active
        toggle_url = reverse("toggle_student_active", args=[self.student.id])
        resp_post = client.post(toggle_url)
        self.assertEqual(resp_post.status_code, 302)
        self.student.refresh_from_db()
        self.assertFalse(self.student.is_active)

        # 3. Reset login token
        self.student.active_token = "some_session_token"
        self.student.save()
        reset_url = reverse("reset_student_login", args=[self.student.id])
        resp_reset = client.post(reset_url)
        self.assertEqual(resp_reset.status_code, 302)
        self.student.refresh_from_db()
        self.assertEqual(self.student.active_token, "")

    def test_system_health_check(self):
        health = check_system_health()
        self.assertIn(health["overall_status"], ["Healthy", "Warning"])
        check_names = [c["name"] for c in health["checks"]]
        self.assertIn("Database Connectivity", check_names)
        self.assertIn("Disk Storage", check_names)
        self.assertIn("Code Runner Environment", check_names)

    def test_performance_middleware_records_samples(self):
        client = Client()
        client.login(username="admin_user", password="StrongPassword123!")
        client.get(reverse("dashboard_overview"))

        perf = get_performance_metrics()
        self.assertGreater(perf["sample_count"], 0)
        self.assertIsNotNone(perf["avg_latency_ms"])

    def test_data_integrity_audit(self):
        # Create an exam with 0 sections to verify anomaly detection
        empty_exam = Exam.objects.create(title="Incomplete Exam")
        issues = get_data_integrity_report()
        issue_msgs = [i["message"] for i in issues]
        self.assertTrue(any("Incomplete Exam" in msg for msg in issue_msgs))

    def test_admin_portal_homepage_branding_and_metrics(self):
        client = Client()
        client.login(username="admin_user", password="StrongPassword123!")
        response = client.get(reverse("admin:index"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "PyForgeLabs")
        self.assertContains(response, "CBT Administration Center")
        self.assertContains(response, "Registered Students")
        self.assertContains(response, "Analytics Dashboard")
        self.assertContains(response, "cbt-admin-sidebar")

    def test_admin_portal_subpages_accessible(self):
        client = Client()
        client.login(username="admin_user", password="StrongPassword123!")
        
        # Check student changelist and import page
        resp_students = client.get(reverse("admin:portal_student_changelist"))
        self.assertEqual(resp_students.status_code, 200)
        self.assertContains(resp_students, "cbt-admin-sidebar")

        resp_import = client.get(reverse("admin:portal_student_import"))
        self.assertEqual(resp_import.status_code, 200)

        # Check exam changelist
        resp_exams = client.get(reverse("admin:portal_exam_changelist"))
        self.assertEqual(resp_exams.status_code, 200)

    def test_dashboard_and_student_isolation(self):
        client = Client()
        client.login(username="admin_user", password="StrongPassword123!")

        # 1. /dashboard/ remains intact with its original dashboard CSS and sidebar
        resp_dash = client.get(reverse("dashboard_overview"))
        self.assertEqual(resp_dash.status_code, 200)
        self.assertContains(resp_dash, "dashboard.css")
        self.assertContains(resp_dash, "cbtSidebar")

        # 2. Student-facing login page / remains intact
        resp_login = client.get(reverse("login"))
        self.assertEqual(resp_login.status_code, 200)
        self.assertContains(resp_login, 'name="usn"')
        self.assertContains(resp_login, 'name="dob"')


class AdminUrlMigrationAndLayoutTests(TestCase):
    """Verifies the canonical URL migration to /admin/dashboard/, 302 redirects, and layout repairs."""

    def setUp(self):
        self.staff_user = User.objects.create_user(
            username="admin_staff",
            password="StaffPassword123!",
            is_staff=True,
            is_superuser=True,
        )
        self.regular_user = User.objects.create_user(
            username="regular_user",
            password="RegularPassword123!",
            is_staff=False,
        )

    def test_canonical_dashboard_url_returns_200(self):
        client = Client()
        client.login(username="admin_staff", password="StaffPassword123!")
        
        response = client.get("/admin/dashboard/")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Overview Analytics")
        self.assertContains(response, "PyForgeLabs")

    def test_legacy_dashboard_redirects_to_canonical_with_302(self):
        client = Client()
        client.login(username="admin_staff", password="StaffPassword123!")

        # Root legacy dashboard
        resp_root = client.get("/dashboard/")
        self.assertEqual(resp_root.status_code, 302)
        self.assertEqual(resp_root.url, "/admin/dashboard/")

        # Subpaths
        resp_health = client.get("/dashboard/health/")
        self.assertEqual(resp_health.status_code, 302)
        self.assertEqual(resp_health.url, "/admin/dashboard/health/")

        resp_students = client.get("/dashboard/students/")
        self.assertEqual(resp_students.status_code, 302)
        self.assertEqual(resp_students.url, "/admin/dashboard/students/")

    def test_unauthorized_dashboard_access_denied(self):
        client = Client()

        # Anonymous user
        resp_anon = client.get("/admin/dashboard/")
        self.assertEqual(resp_anon.status_code, 302)
        self.assertIn("/admin/login/", resp_anon.url)

        # Non-staff regular user
        client.login(username="regular_user", password="RegularPassword123!")
        resp_regular = client.get("/admin/dashboard/")
        self.assertEqual(resp_regular.status_code, 302)
        self.assertIn("/admin/login/", resp_regular.url)

    def test_admin_import_pages_render_with_unified_design(self):
        client = Client()
        client.login(username="admin_staff", password="StaffPassword123!")

        # 1. Student Import
        resp_student_import = client.get("/admin/portal/student/import/")
        self.assertEqual(resp_student_import.status_code, 200)
        self.assertContains(resp_student_import, "pf-admin-sidebar")
        self.assertContains(resp_student_import, "Before You Import")
        self.assertContains(resp_student_import, "Download Blank Template (.xlsx)")
        self.assertContains(resp_student_import, "Download 30 Dummy Students (Dry Run)")
        self.assertContains(resp_student_import, "Import Students")

        # 2. Question Import
        resp_q_import = client.get("/admin/portal/question/import/")
        self.assertEqual(resp_q_import.status_code, 200)
        self.assertContains(resp_q_import, "pf-admin-sidebar")
        self.assertContains(resp_q_import, "Before You Import MCQ Questions")
        self.assertContains(resp_q_import, "Download Blank MCQ Template (.xlsx)")
        self.assertContains(resp_q_import, "Import Questions")

        # 3. Coding Question Import
        resp_cq_import = client.get("/admin/portal/codingquestion/import/")
        self.assertEqual(resp_cq_import.status_code, 200)
        self.assertContains(resp_cq_import, "pf-admin-sidebar")
        self.assertContains(resp_cq_import, "Before You Import Coding Questions")
        self.assertContains(resp_cq_import, "Download Coding Questions Workbook Template (.xlsx)")
        self.assertContains(resp_cq_import, "Import Coding Questions")

    def test_admin_index_links_to_canonical_dashboard(self):
        client = Client()
        client.login(username="admin_staff", password="StaffPassword123!")

        resp_index = client.get("/admin/")
        self.assertEqual(resp_index.status_code, 200)
        self.assertContains(resp_index, 'href="/admin/dashboard/"')
        self.assertNotContains(resp_index, 'href="/dashboard/"')

    def test_admin_homepage_duplicate_removal_and_sidebar_categories(self):
        client = Client()
        client.login(username="admin_staff", password="StaffPassword123!")

        resp = client.get("/admin/")
        self.assertEqual(resp.status_code, 200)

        # 1. Verify duplicate model tables were removed
        self.assertNotContains(resp, 'admin-model-table')
        self.assertNotContains(resp, 'admin-app-panel')

        # 2. Verify new overview components exist
        self.assertContains(resp, "CBT Administration Center")
        self.assertContains(resp, "Operational Notices & Integrity Status")
        self.assertContains(resp, "Configured Examinations")
        self.assertContains(resp, "Recent Actions")

        # 3. Verify Sidebar Categories are rendered
        self.assertContains(resp, "MAIN WORKFLOWS")
        self.assertContains(resp, "ASSESSMENT SETUP")
        self.assertContains(resp, "DATA OPERATIONS")
        self.assertContains(resp, "SYSTEM & AUDIT")
        self.assertContains(resp, "ACCESS MANAGEMENT")

        # 4. Verify all essential sidebar navigation entries exist
        self.assertContains(resp, "Overview")
        self.assertContains(resp, "Students / Candidates")
        self.assertContains(resp, "Recruitment Drives")
        self.assertContains(resp, "Interview Panel")
        self.assertContains(resp, "Results & Progression")
        self.assertContains(resp, "Exams & Sections")
        self.assertContains(resp, "MCQ Questions")
        self.assertContains(resp, "Coding Assessments")
        self.assertContains(resp, "Test Cases")
        self.assertContains(resp, "Interview Rubrics")
        self.assertContains(resp, "Feedback & Reports")
        self.assertContains(resp, "Users")
        self.assertContains(resp, "Groups")
        self.assertContains(resp, "System Health")
        self.assertContains(resp, "Performance & Latency")
        self.assertContains(resp, "Data Integrity")
        self.assertContains(resp, "Recruitment Audit Log")
        self.assertContains(resp, "Import Students")
        self.assertContains(resp, "Import MCQ Questions")
        self.assertContains(resp, "Import Coding Questions")

        # 5. Verify redundant items were removed from global navigation
        self.assertNotContains(resp, '<span class="cbt-nav-text">Answers</span>')
        self.assertNotContains(resp, '<span class="cbt-nav-text">Code Drafts</span>')
        self.assertNotContains(resp, '<span class="cbt-nav-text">Sections</span>')

        # 6. Verify administrator still has working navigation back to /admin/ via brand link and breadcrumb
        self.assertContains(resp, 'href="/admin/"')


class UnifiedSidebarArchitectureTests(TestCase):
    """Verifies that the unified PyForgeLabs sidebar is shared across all admin & dashboard views,
    the standalone 'Django Admin' navigation item is completely removed, and all registered models
    remain fully accessible.
    """

    def setUp(self):
        self.admin = User.objects.create_superuser(
            username="super_architect",
            password="ArchPassword123!",
            email="architect@example.com",
        )
        self.exam = Exam.objects.create(
            title="Unified Sidebar Exam",
            instructions="Exam rules",
            min_stay_minutes=60,
        )
        self.section = Section.objects.create(
            exam=self.exam,
            title="General Section",
            order=1,
            kind="MCQ",
            start_time=timezone.now() - datetime.timedelta(minutes=10),
            end_time=timezone.now() + datetime.timedelta(minutes=50),
        )

    def test_dashboard_uses_unified_sidebar_and_has_no_django_admin_item(self):
        client = Client()
        client.login(username="super_architect", password="ArchPassword123!")

        resp = client.get("/admin/dashboard/")
        self.assertEqual(resp.status_code, 200)

        # 1. Verify unified sidebar classes & container
        self.assertContains(resp, "cbt-sidebar")
        self.assertContains(resp, "pf-admin-sidebar")

        # 2. Verify brand links consistently to /admin/dashboard/
        self.assertContains(resp, 'href="/admin/dashboard/"')

        # 3. Verify the standalone "Django Admin" item was removed
        self.assertNotContains(resp, '<span class="cbt-nav-text">Django Admin</span>')
        self.assertNotContains(resp, "Django Admin")

        # 4. Verify brand title and subtitle
        self.assertContains(resp, "PyForgeLabs")
        self.assertContains(resp, "College Placement Simulator")

        # 5. Verify the 5 primary workflows are present
        self.assertContains(resp, "Overview")
        self.assertContains(resp, "Students / Candidates")
        self.assertContains(resp, "Recruitment Drives")
        self.assertContains(resp, "Interview Panel")
        self.assertContains(resp, "Results & Progression")

        # 6. Verify the 4 collapsible groups are present
        self.assertContains(resp, "ASSESSMENT SETUP")
        self.assertContains(resp, "DATA OPERATIONS")
        self.assertContains(resp, "SYSTEM & AUDIT")
        self.assertContains(resp, "ACCESS MANAGEMENT")

        # 7. Verify links inside collapsible groups
        self.assertContains(resp, "Exams & Sections")
        self.assertContains(resp, "MCQ Questions")
        self.assertContains(resp, "Coding Assessments")
        self.assertContains(resp, "Interview Rubrics")
        self.assertContains(resp, "Test Cases")
        self.assertContains(resp, "Import Students")
        self.assertContains(resp, "Import MCQ Questions")
        self.assertContains(resp, "Import Coding Questions")
        self.assertContains(resp, "Feedback & Reports")
        self.assertContains(resp, "System Health")
        self.assertContains(resp, "Performance & Latency")
        self.assertContains(resp, "Data Integrity")
        self.assertContains(resp, "Recruitment Audit Log")
        self.assertContains(resp, "Users")
        self.assertContains(resp, "Groups")

        # 8. Verify redundant top-level items were removed from global menu
        self.assertNotContains(resp, '<span class="cbt-nav-text">Answers</span>')
        self.assertNotContains(resp, '<span class="cbt-nav-text">Code Drafts</span>')
        self.assertNotContains(resp, '<span class="cbt-nav-text">Sections</span>')

    def test_admin_index_and_changelists_use_same_unified_sidebar(self):
        client = Client()
        client.login(username="super_architect", password="ArchPassword123!")

        for url in [
            "/admin/",
            "/admin/portal/student/",
            "/admin/portal/exam/",
            "/admin/portal/section/",
            "/admin/portal/question/",
            "/admin/portal/codingquestion/",
            "/admin/portal/testcase/",
            "/admin/portal/attempt/",
            "/admin/portal/answer/",
            "/admin/portal/codesubmission/",
            "/admin/portal/codedraft/",
            "/admin/portal/feedback/",
            "/admin/auth/user/",
            "/admin/auth/group/",
        ]:
            resp = client.get(url)
            self.assertEqual(resp.status_code, 200, f"Route {url} failed with {resp.status_code}")
            # Verify unified sidebar is rendered
            self.assertContains(resp, "cbt-sidebar")
            self.assertContains(resp, "pf-admin-sidebar")
            # Verify standalone "Django Admin" item is not in sidebar
            self.assertNotContains(resp, '<span class="cbt-nav-text">Django Admin</span>')
            # Verify primary workflows & collapsible groups
            self.assertContains(resp, "MAIN WORKFLOWS")
            self.assertContains(resp, "ASSESSMENT SETUP")
            self.assertContains(resp, "SYSTEM & AUDIT")

    def test_contextual_crud_links_present_on_custom_dashboard_pages(self):
        client = Client()
        client.login(username="super_architect", password="ArchPassword123!")

        # Students page has Admin Table link
        resp_students = client.get("/admin/dashboard/students/")
        self.assertEqual(resp_students.status_code, 200)
        self.assertContains(resp_students, 'href="/admin/portal/student/"')

        # Exams page has Admin Table and Manage Sections links
        resp_exams = client.get("/admin/dashboard/exams/")
        self.assertEqual(resp_exams.status_code, 200)
        self.assertContains(resp_exams, 'href="/admin/portal/exam/"')
        self.assertContains(resp_exams, 'href="/admin/portal/section/"')

        # Questions page has Admin Table link
        resp_questions = client.get("/admin/dashboard/questions/")
        self.assertEqual(resp_questions.status_code, 200)
        self.assertContains(resp_questions, 'href="/admin/portal/question/"')

        # Coding page has Admin Table and All Test Cases links
        resp_coding = client.get("/admin/dashboard/coding/")
        self.assertEqual(resp_coding.status_code, 200)
        self.assertContains(resp_coding, 'href="/admin/portal/codingquestion/"')
        self.assertContains(resp_coding, 'href="/admin/portal/testcase/"')

        # Attempts page has Admin Table link
        resp_attempts = client.get("/admin/dashboard/attempts/")
        self.assertEqual(resp_attempts.status_code, 200)
        self.assertContains(resp_attempts, 'href="/admin/portal/attempt/"')

        # Submissions page has Admin Table link
        resp_subs = client.get("/admin/dashboard/submissions/")
        self.assertEqual(resp_subs.status_code, 200)
        self.assertContains(resp_subs, 'href="/admin/portal/codesubmission/"')

        # Feedback page has Admin Table link
        resp_fb = client.get("/admin/dashboard/feedback/")
        self.assertEqual(resp_fb.status_code, 200)
        self.assertContains(resp_fb, 'href="/admin/portal/feedback/"')


class ConcurrencyAndQueueSafetyTests(TestCase):
    """
    Validates race safety, atomic autosave, versioned drafts, sticky assignments,
    and sandboxed execution queue admission control under high concurrency.
    """

    def setUp(self):
        self.student = Student.objects.create(
            usn="1MS22CS101",
            name="Diana Candidate",
            dob=datetime.date(2004, 3, 10),
            is_active=True,
        )
        self.exam = Exam.objects.create(
            title="LAN Scale Exam",
            instructions="Strict concurrency testing.",
            min_stay_minutes=90,
        )
        self.exam.students.add(self.student)

        # MCQ section runs first (from -60m to -10m by default, activated during MCQ test)
        self.mcq_section = Section.objects.create(
            exam=self.exam,
            title="Aptitude",
            order=1,
            kind="MCQ",
            start_time=timezone.now() - datetime.timedelta(minutes=60),
            end_time=timezone.now() - datetime.timedelta(minutes=10),
        )
        self.question = Question.objects.create(
            section=self.mcq_section,
            order=1,
            text="What is 10 + 20?",
            marks=1,
        )
        self.option_correct = Option.objects.create(
            question=self.question,
            text="30",
            is_correct=True,
        )
        self.option_wrong = Option.objects.create(
            question=self.question,
            text="40",
            is_correct=False,
        )

        # Coding section is currently running (from -10m to +50m)
        self.coding_section = Section.objects.create(
            exam=self.exam,
            title="Programming and Coding",
            order=2,
            kind="CODING",
            start_time=timezone.now() - datetime.timedelta(minutes=10),
            end_time=timezone.now() + datetime.timedelta(minutes=50),
        )
        self.coding_q1 = CodingQuestion.objects.create(
            section=self.coding_section,
            order=1,
            title="Double Integer",
            statement="Read an integer and print 2 * N.",
            sample_input="5\n",
            sample_output="10\n",
            time_limit_seconds=2,
            marks=10,
        )
        CodingTestCase.objects.create(
            question=self.coding_q1,
            input_data="5\n",
            expected_output="10\n",
            is_sample=True,
            marks=5,
        )
        CodingTestCase.objects.create(
            question=self.coding_q1,
            input_data="12\n",
            expected_output="24\n",
            is_sample=False,
            marks=5,
        )

    def _login_student(self):
        client = Client()
        client.post(reverse("login"), {
            "usn": "1MS22CS101",
            "dob": "2004-03-10",
        })
        return client

    def test_atomic_mcq_answer_saving_and_validation(self):
        # Activate MCQ section window for this test
        self.mcq_section.start_time = timezone.now() - datetime.timedelta(minutes=10)
        self.mcq_section.end_time = timezone.now() + datetime.timedelta(minutes=50)
        self.mcq_section.save()
        self.coding_section.start_time = timezone.now() + datetime.timedelta(minutes=60)
        self.coding_section.end_time = timezone.now() + datetime.timedelta(minutes=120)
        self.coding_section.save()

        client = self._login_student()
        # Initialize attempt
        client.post(reverse("instructions"), {"agree": "on"})

        # 1. Invalid option not belonging to question is rejected
        bogus_option = Option.objects.create(
            question=Question.objects.create(section=self.mcq_section, order=2, text="Other Q"),
            text="Bogus",
            is_correct=False,
        )
        resp_bad = client.post(
            reverse("save_answer"),
            data={"question_id": self.question.id, "option_id": bogus_option.id},
            content_type="application/json",
        )
        self.assertEqual(resp_bad.status_code, 400)
        self.assertIn("Invalid option", resp_bad.json()["error"])

        # 2. Valid save succeeds and is idempotent
        resp_ok = client.post(
            reverse("save_answer"),
            data={"question_id": self.question.id, "option_id": self.option_correct.id, "review": True},
            content_type="application/json",
        )
        self.assertEqual(resp_ok.status_code, 200)
        self.assertTrue(resp_ok.json()["ok"])

        # Verify DB
        attempt = Attempt.objects.get(student=self.student, exam=self.exam)
        ans = Answer.objects.get(attempt=attempt, question=self.question)
        self.assertEqual(ans.selected_option, self.option_correct)
        self.assertTrue(ans.marked_for_review)

        # 3. Repeated saves update cleanly without duplicate row errors
        resp_update = client.post(
            reverse("save_answer"),
            data={"question_id": self.question.id, "option_id": self.option_wrong.id, "review": False},
            content_type="application/json",
        )
        self.assertEqual(resp_update.status_code, 200)
        ans.refresh_from_db()
        self.assertEqual(ans.selected_option, self.option_wrong)
        self.assertFalse(ans.marked_for_review)
        self.assertEqual(Answer.objects.filter(attempt=attempt, question=self.question).count(), 1)

    def test_code_draft_versioning_prevents_stale_overwrites(self):
        client = self._login_student()
        client.post(reverse("instructions"), {"agree": "on"})

        # Initial save at version 2
        resp_v2 = client.post(
            reverse("save_code"),
            data={
                "question_id": self.coding_q1.id,
                "language": "python",
                "code": "print('Version 2 - fresh')",
                "version": 2,
            },
            content_type="application/json",
        )
        self.assertEqual(resp_v2.status_code, 200)

        attempt = Attempt.objects.get(student=self.student, exam=self.exam)
        draft = CodeDraft.objects.get(attempt=attempt, question=self.coding_q1)
        self.assertEqual(draft.version, 2)
        self.assertIn("Version 2", draft.code)

        # Stale delayed packet arriving at version 1 must NOT overwrite version 2
        resp_stale = client.post(
            reverse("save_code"),
            data={
                "question_id": self.coding_q1.id,
                "language": "python",
                "code": "print('Version 1 - delayed packet')",
                "version": 1,
            },
            content_type="application/json",
        )
        self.assertEqual(resp_stale.status_code, 200)

        draft.refresh_from_db()
        # Stale code was ignored; fresh code preserved
        self.assertEqual(draft.version, 2)
        self.assertIn("Version 2 - fresh", draft.code)

    def test_sticky_coding_question_assignments(self):
        from portal.views import assigned_coding_questions
        attempt, _ = Attempt.objects.get_or_create(student=self.student, exam=self.exam)

        # First assignment
        assigned_1 = assigned_coding_questions(attempt, self.coding_section)
        self.assertEqual(len(assigned_1), 1)
        self.assertEqual(assigned_1[0].id, self.coding_q1.id)

        # Re-fetch multiple times simulates student refreshes
        for _ in range(5):
            assigned_again = assigned_coding_questions(attempt, self.coding_section)
            self.assertEqual([q.id for q in assigned_again], [q.id for q in assigned_1])

        # Exactly 1 assignment record created in DB
        self.assertEqual(
            CodingQuestionAssignment.objects.filter(attempt=attempt, section=self.coding_section).count(), 1
        )

    def test_execution_job_lifecycle_and_polling(self):
        client = self._login_student()
        client.post(reverse("instructions"), {"agree": "on"})

        # Async run submission
        code = "import sys\nn = int(sys.stdin.read().strip())\nprint(n * 2)"
        resp = client.post(
            reverse("code_run") + "?async=1",
            data={
                "question_id": self.coding_q1.id,
                "language": "python",
                "code": code,
                "stdin": "7\n",
            },
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 200)
        job_data = resp.json()
        self.assertTrue(job_data["ok"])
        job_id = job_data["job_id"]
        self.assertEqual(job_data["status"], "QUEUED")

        # Verify job is queued in DB
        job = ExecutionJob.objects.get(id=job_id)
        self.assertEqual(job.status, "QUEUED")

        # Worker processes job
        from portal.services.execution_queue import claim_next_job, execute_job
        claimed = claim_next_job(worker_id="test-worker")
        self.assertIsNotNone(claimed)
        self.assertEqual(str(claimed.id), job_id)
        execute_job(claimed)

        # Poll status endpoint
        poll_resp = client.get(reverse("code_job_status", args=[job_id]))
        self.assertEqual(poll_resp.status_code, 200)
        poll_data = poll_resp.json()
        self.assertEqual(poll_data["status"], "COMPLETED")
        self.assertEqual(poll_data["stdout"].strip(), "14")
        self.assertGreater(poll_data["duration_ms"], 0)

    def test_per_student_concurrency_admission_limit(self):
        client = self._login_student()
        client.post(reverse("instructions"), {"agree": "on"})

        # 1. Enqueue first job
        resp1 = client.post(
            reverse("code_run") + "?async=1",
            data={
                "question_id": self.coding_q1.id,
                "language": "python",
                "code": "print(1)",
            },
            content_type="application/json",
        )
        self.assertEqual(resp1.status_code, 200)

        # 2. Immediate second submission while first is still QUEUED should be throttled
        resp2 = client.post(
            reverse("code_run") + "?async=1",
            data={
                "question_id": self.coding_q1.id,
                "language": "python",
                "code": "print(2)",
            },
            content_type="application/json",
        )
        self.assertEqual(resp2.status_code, 429)
        self.assertTrue(resp2.json().get("busy"))
        self.assertIn("already have a code execution in progress", resp2.json()["error"])

    def test_run_execution_worker_command_with_worker_id(self):
        from io import StringIO
        from django.core.management import call_command
        out = StringIO()
        call_command("run_execution_worker", worker_id="worker-01", one_shot=True, concurrency=1, stdout=out)
        output = out.getvalue()
        self.assertIn("Starting CBT Execution Worker Daemon (ID: worker-01", output)
        self.assertIn("Execution Worker Daemon stopped cleanly", output)





