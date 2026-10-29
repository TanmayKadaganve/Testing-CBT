from django.contrib.admin.views.decorators import staff_member_required
from django.contrib.auth.decorators import permission_required
from django.contrib import messages
from django.core.paginator import Paginator
from django.db.models import Q, Count
from django.shortcuts import render, redirect, get_object_or_404
from django.views.decorators.http import require_POST
from django.views.decorators.cache import never_cache

from portal.models import (
    Student, Exam, Section, Question, Option, Attempt, Answer,
    Feedback, CodingQuestion, TestCase, CodeSubmission, CodeDraft
)
from portal.services.dashboard_analytics import (
    get_overview_metrics, get_charts_data, get_recent_activity, get_data_integrity_report
)
from portal.services.system_health import check_system_health
from portal.middleware import get_performance_metrics


@staff_member_required(login_url="/admin/login/")
@never_cache
def dashboard_overview(request):
    metrics = get_overview_metrics()
    charts = get_charts_data()
    activity = get_recent_activity()

    context = {
        "active_nav": "overview",
        "metrics": metrics,
        "charts": charts,
        "activity": activity,
    }
    return render(request, "portal/admin_dashboard/overview.html", context)


@staff_member_required(login_url="/admin/login/")
@never_cache
def dashboard_students(request):
    search_query = request.GET.get("q", "").strip()
    status_filter = request.GET.get("status", "").strip()
    exam_filter = request.GET.get("exam_id", "").strip()

    students_qs = Student.objects.all().order_by("usn")

    if search_query:
        students_qs = students_qs.filter(
            Q(usn__icontains=search_query) |
            Q(name__icontains=search_query) |
            Q(email__icontains=search_query)
        )

    if status_filter == "active":
        students_qs = students_qs.filter(is_active=True)
    elif status_filter == "inactive":
        students_qs = students_qs.filter(is_active=False)

    if exam_filter.isdigit():
        students_qs = students_qs.filter(exam__id=int(exam_filter))

    paginator = Paginator(students_qs, 20)
    page_number = request.GET.get("page")
    students_page = paginator.get_page(page_number)

    all_exams = Exam.objects.all().order_by("title")

    context = {
        "active_nav": "students",
        "students": students_page,
        "search_query": search_query,
        "status_filter": status_filter,
        "exam_filter": exam_filter,
        "all_exams": all_exams,
        "total_count": paginator.count,
    }
    return render(request, "portal/admin_dashboard/students.html", context)


@staff_member_required(login_url="/admin/login/")
@never_cache
def student_detail(request, student_id):
    student = get_object_or_404(Student, id=student_id)
    exams = student.exam_set.all()
    attempts = Attempt.objects.filter(student=student).select_related("exam").order_by("-started_at")
    submissions = CodeSubmission.objects.filter(attempt__student=student).select_related("question").order_by("-created_at")
    feedbacks = Feedback.objects.filter(attempt__student=student).select_related("attempt__exam")

    context = {
        "active_nav": "students",
        "student": student,
        "exams": exams,
        "attempts": attempts,
        "submissions": submissions,
        "feedbacks": feedbacks,
    }
    return render(request, "portal/admin_dashboard/student_detail.html", context)


@require_POST
@staff_member_required(login_url="/admin/login/")
@permission_required("portal.change_student", login_url="/admin/login/")
def toggle_student_active(request, student_id):
    student = get_object_or_404(Student, id=student_id)
    student.is_active = not student.is_active
    student.save(update_fields=["is_active"])
    status_str = "activated" if student.is_active else "deactivated"
    messages.success(request, f"Student {student.usn} has been {status_str}.")
    return redirect(request.META.get("HTTP_REFERER", "dashboard_students"))


@require_POST
@staff_member_required(login_url="/admin/login/")
@permission_required("portal.change_student", login_url="/admin/login/")
def reset_student_login(request, student_id):
    student = get_object_or_404(Student, id=student_id)
    from recruitment.models import AuditLog

    student.active_token = ""
    student.save(update_fields=["active_token"])
    AuditLog.objects.create(
        action=AuditLog.INVIGILATOR_NOTE,
        actor=request.user,
        target_model="Student",
        target_id=str(student.pk),
        reason="Active candidate login token reset by an authorized staff member.",
        ip_address=request.META.get("REMOTE_ADDR"),
    )
    messages.success(request, f"Active session cleared for {student.usn}. The student can now log in.")
    return redirect(request.META.get("HTTP_REFERER", "dashboard_students"))


@staff_member_required(login_url="/admin/login/")
@never_cache
def dashboard_exams(request):
    exams_qs = Exam.objects.prefetch_related("sections").annotate(
        student_count=Count("students", distinct=True),
        attempt_count=Count("attempt", distinct=True)
    ).order_by("title")

    context = {
        "active_nav": "exams",
        "exams": exams_qs,
    }
    return render(request, "portal/admin_dashboard/exams.html", context)


@staff_member_required(login_url="/admin/login/")
@never_cache
def dashboard_questions(request):
    search_query = request.GET.get("q", "").strip()
    exam_filter = request.GET.get("exam_id", "").strip()
    section_filter = request.GET.get("section_id", "").strip()

    questions_qs = Question.objects.select_related("section__exam").prefetch_related("options").order_by("section__exam__title", "section__order", "order")

    if search_query:
        questions_qs = questions_qs.filter(text__icontains=search_query)

    if exam_filter.isdigit():
        questions_qs = questions_qs.filter(section__exam__id=int(exam_filter))

    if section_filter.isdigit():
        questions_qs = questions_qs.filter(section__id=int(section_filter))

    paginator = Paginator(questions_qs, 20)
    page_number = request.GET.get("page")
    questions_page = paginator.get_page(page_number)

    all_exams = Exam.objects.all().order_by("title")
    all_sections = Section.objects.filter(kind="MCQ").order_by("title")

    context = {
        "active_nav": "questions",
        "questions": questions_page,
        "search_query": search_query,
        "exam_filter": exam_filter,
        "section_filter": section_filter,
        "all_exams": all_exams,
        "all_sections": all_sections,
        "total_count": paginator.count,
    }
    return render(request, "portal/admin_dashboard/questions.html", context)


@staff_member_required(login_url="/admin/login/")
@never_cache
def dashboard_coding(request):
    search_query = request.GET.get("q", "").strip()
    exam_filter = request.GET.get("exam_id", "").strip()

    coding_qs = CodingQuestion.objects.select_related("section__exam").annotate(
        tc_count=Count("testcases")
    ).order_by("section__exam__title", "order")

    if search_query:
        coding_qs = coding_qs.filter(Q(title__icontains=search_query) | Q(statement__icontains=search_query))

    if exam_filter.isdigit():
        coding_qs = coding_qs.filter(section__exam__id=int(exam_filter))

    paginator = Paginator(coding_qs, 20)
    page_number = request.GET.get("page")
    coding_page = paginator.get_page(page_number)

    all_exams = Exam.objects.all().order_by("title")

    context = {
        "active_nav": "coding",
        "coding_questions": coding_page,
        "search_query": search_query,
        "exam_filter": exam_filter,
        "all_exams": all_exams,
        "total_count": paginator.count,
    }
    return render(request, "portal/admin_dashboard/coding_questions.html", context)


@staff_member_required(login_url="/admin/login/")
@never_cache
def dashboard_attempts(request):
    exam_filter = request.GET.get("exam_id", "").strip()
    status_filter = request.GET.get("status", "").strip()

    attempts_qs = Attempt.objects.select_related("student", "exam").order_by("-started_at")

    if exam_filter.isdigit():
        attempts_qs = attempts_qs.filter(exam__id=int(exam_filter))

    if status_filter == "submitted":
        attempts_qs = attempts_qs.filter(submitted_at__isnull=False)
    elif status_filter == "in_progress":
        attempts_qs = attempts_qs.filter(submitted_at__isnull=True)

    paginator = Paginator(attempts_qs, 20)
    page_number = request.GET.get("page")
    attempts_page = paginator.get_page(page_number)

    # Compute MCQ scores for attempts on current page
    scored_attempts = []
    for att in attempts_page:
        mcq_earned = 0
        mcq_max = 0
        answers = Answer.objects.filter(attempt=att).select_related("question", "selected_option")
        for a in answers:
            mcq_max += a.question.marks
            if a.selected_option and a.selected_option.is_correct:
                mcq_earned += a.question.marks

        # Coding best scores
        code_subs = CodeSubmission.objects.filter(attempt=att)
        best_code = {}
        for sub in code_subs:
            best_code[sub.question_id] = max(best_code.get(sub.question_id, 0), sub.score)
        code_earned = sum(best_code.values())

        scored_attempts.append({
            "attempt": att,
            "mcq_earned": mcq_earned,
            "code_earned": code_earned,
            "total_score": mcq_earned + code_earned,
        })

    all_exams = Exam.objects.all().order_by("title")

    context = {
        "active_nav": "attempts",
        "scored_attempts": scored_attempts,
        "attempts_page": attempts_page,
        "exam_filter": exam_filter,
        "status_filter": status_filter,
        "all_exams": all_exams,
        "total_count": paginator.count,
    }
    return render(request, "portal/admin_dashboard/attempts.html", context)


@staff_member_required(login_url="/admin/login/")
@never_cache
def dashboard_submissions(request):
    verdict_filter = request.GET.get("verdict", "").strip()
    submissions_qs = CodeSubmission.objects.select_related("attempt__student", "question__section__exam").order_by("-created_at")

    if verdict_filter:
        submissions_qs = submissions_qs.filter(verdict=verdict_filter)

    paginator = Paginator(submissions_qs, 25)
    page_number = request.GET.get("page")
    submissions_page = paginator.get_page(page_number)

    verdicts = CodeSubmission.objects.values_list("verdict", flat=True).distinct()

    context = {
        "active_nav": "submissions",
        "submissions": submissions_page,
        "verdict_filter": verdict_filter,
        "verdicts": verdicts,
        "total_count": paginator.count,
    }
    return render(request, "portal/admin_dashboard/submissions.html", context)


@staff_member_required(login_url="/admin/login/")
@never_cache
def dashboard_feedback(request):
    feedbacks_qs = Feedback.objects.select_related("attempt__student", "attempt__exam").order_by("-created_at")
    paginator = Paginator(feedbacks_qs, 20)
    page_number = request.GET.get("page")
    feedbacks_page = paginator.get_page(page_number)

    # Average metrics
    avg_stats = Feedback.objects.aggregate(
        exp_avg=Count("experience_rating"),
        real_avg=Count("realism_rating")
    )

    context = {
        "active_nav": "feedback",
        "feedbacks": feedbacks_page,
        "total_count": paginator.count,
    }
    return render(request, "portal/admin_dashboard/feedback.html", context)


@staff_member_required(login_url="/admin/login/")
@never_cache
def dashboard_health(request):
    health = check_system_health()
    context = {
        "active_nav": "health",
        "health": health,
    }
    return render(request, "portal/admin_dashboard/system_health.html", context)


@staff_member_required(login_url="/admin/login/")
@never_cache
def dashboard_performance(request):
    perf = get_performance_metrics()
    context = {
        "active_nav": "performance",
        "perf": perf,
    }
    return render(request, "portal/admin_dashboard/performance.html", context)


@staff_member_required(login_url="/admin/login/")
@never_cache
def dashboard_integrity(request):
    issues = get_data_integrity_report()
    context = {
        "active_nav": "integrity",
        "issues": issues,
    }
    return render(request, "portal/admin_dashboard/integrity.html", context)
