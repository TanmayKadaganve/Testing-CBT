from django.db.models import Count, Avg, Q
from django.utils import timezone
from portal.models import (
    Student, Exam, Section, Question, Option, Attempt, Answer,
    Feedback, CodingQuestion, TestCase, CodeSubmission, ExecutionJob
)


def get_overview_metrics():
    """
    Returns real database-derived summary counts and metrics.
    No mock data or fabricated numbers.
    """
    total_students = Student.objects.count()
    active_students = Student.objects.filter(is_active=True).count()
    logged_in_students = Student.objects.filter(is_active=True).exclude(active_token="").count()

    total_exams = Exam.objects.count()
    total_sections = Section.objects.count()
    mcq_sections = Section.objects.filter(kind="MCQ").count()
    coding_sections = Section.objects.filter(kind="CODING").count()

    total_mcq_questions = Question.objects.count()
    total_coding_questions = CodingQuestion.objects.count()

    total_attempts = Attempt.objects.count()
    submitted_attempts = Attempt.objects.filter(submitted_at__isnull=False).count()
    in_progress_attempts = Attempt.objects.filter(submitted_at__isnull=True).count()

    total_submissions = CodeSubmission.objects.count()
    accepted_submissions = CodeSubmission.objects.filter(verdict="Accepted").count()

    queued_jobs = ExecutionJob.objects.filter(status="QUEUED").count()
    running_jobs = ExecutionJob.objects.filter(status="RUNNING").count()

    feedback_count = Feedback.objects.count()
    feedback_avg = Feedback.objects.aggregate(
        avg_exp=Avg("experience_rating"),
        avg_real=Avg("realism_rating")
    )

    return {
        "total_students": total_students,
        "active_students": active_students,
        "logged_in_students": logged_in_students,
        "total_exams": total_exams,
        "total_sections": total_sections,
        "mcq_sections": mcq_sections,
        "coding_sections": coding_sections,
        "total_mcq_questions": total_mcq_questions,
        "total_coding_questions": total_coding_questions,
        "total_attempts": total_attempts,
        "submitted_attempts": submitted_attempts,
        "in_progress_attempts": in_progress_attempts,
        "total_submissions": total_submissions,
        "accepted_submissions": accepted_submissions,
        "queued_jobs": queued_jobs,
        "running_jobs": running_jobs,
        "feedback_count": feedback_count,
        "avg_experience": round(feedback_avg["avg_exp"], 1) if feedback_avg["avg_exp"] else None,
        "avg_realism": round(feedback_avg["avg_real"], 1) if feedback_avg["avg_real"] else None,
    }


def get_charts_data():
    """
    Prepares real aggregated distributions for accessible pure-SVG rendering.
    """
    # 1. Attempt Status
    submitted = Attempt.objects.filter(submitted_at__isnull=False).count()
    in_progress = Attempt.objects.filter(submitted_at__isnull=True).count()
    attempt_status = {
        "Submitted": submitted,
        "In Progress": in_progress,
        "total": submitted + in_progress,
    }

    # 2. Question Types
    mcq_count = Question.objects.count()
    coding_count = CodingQuestion.objects.count()
    question_types = {
        "MCQ Questions": mcq_count,
        "Coding Questions": coding_count,
        "total": mcq_count + coding_count,
    }

    # 3. Code Submission Verdicts
    verdicts_qs = (
        CodeSubmission.objects.values("verdict")
        .annotate(count=Count("id"))
        .order_by("-count")
    )
    verdict_counts = {item["verdict"] or "Pending": item["count"] for item in verdicts_qs}
    verdict_total = sum(verdict_counts.values())

    # 4. Exam Participation (Attempts per Exam, max 6)
    exam_attempts = []
    exams = Exam.objects.annotate(attempt_count=Count("attempt")).order_by("-attempt_count")[:6]
    max_exam_attempts = max([e.attempt_count for e in exams], default=1) or 1
    for e in exams:
        pct = round((e.attempt_count / max_exam_attempts) * 100) if max_exam_attempts > 0 else 0
        exam_attempts.append({
            "title": e.title[:20],
            "count": e.attempt_count,
            "pct": max(pct, 4) if e.attempt_count > 0 else 0,
        })

    # 5. Feedback Ratings Distribution (1-5)
    feedback_ratings = {1: 0, 2: 0, 3: 0, 4: 0, 5: 0}
    for row in Feedback.objects.values("experience_rating").annotate(c=Count("id")):
        r = row["experience_rating"]
        if r in feedback_ratings:
            feedback_ratings[r] = row["c"]

    return {
        "attempt_status": attempt_status,
        "question_types": question_types,
        "verdict_counts": verdict_counts,
        "verdict_total": verdict_total,
        "exam_attempts": exam_attempts,
        "feedback_ratings": feedback_ratings,
    }


def get_recent_activity(limit=8):
    """
    Returns sanitized recent events from the database.
    Never exposes passwords, tokens, DOBs, or secret test cases.
    """
    recent_attempts = (
        Attempt.objects.select_related("student", "exam")
        .order_by("-started_at")[:limit]
    )
    recent_submissions = (
        CodeSubmission.objects.select_related("attempt__student", "question")
        .order_by("-created_at")[:limit]
    )
    recent_feedback = (
        Feedback.objects.select_related("attempt__student", "attempt__exam")
        .order_by("-created_at")[:limit]
    )

    return {
        "recent_attempts": recent_attempts,
        "recent_submissions": recent_submissions,
        "recent_feedback": recent_feedback,
    }


def get_data_integrity_report():
    """
    Detects actionable configuration anomalies across exams, sections, and questions.
    """
    issues = []

    # 1. Exams without any sections
    exams_without_sections = Exam.objects.annotate(sc=Count("sections")).filter(sc=0)
    for exam in exams_without_sections:
        issues.append({
            "type": "Exam Configuration",
            "severity": "Warning",
            "message": f"Exam '{exam.title}' has 0 sections configured. Students cannot attempt it.",
            "link": f"/admin/portal/exam/{exam.id}/change/",
            "action": "Add Sections",
        })

    # 2. Sections with invalid schedules (start >= end)
    for section in Section.objects.all():
        if section.start_time and section.end_time and section.start_time >= section.end_time:
            issues.append({
                "type": "Section Schedule",
                "severity": "Critical",
                "message": f"Section '{section.title}' (in Exam '{section.exam.title}') has start time >= end time.",
                "link": f"/admin/portal/section/{section.id}/change/",
                "action": "Fix Times",
            })

    # 3. MCQ Questions with no options or no correct option
    for q in Question.objects.annotate(oc=Count("options")).select_related("section__exam"):
        if q.oc == 0:
            issues.append({
                "type": "Question Setup",
                "severity": "Critical",
                "message": f"MCQ Question '{q.text[:40]}...' in Section '{q.section.title}' has no options.",
                "link": f"/admin/portal/question/{q.id}/change/",
                "action": "Add Options",
            })
        elif not q.options.filter(is_correct=True).exists():
            issues.append({
                "type": "Question Setup",
                "severity": "Warning",
                "message": f"MCQ Question '{q.text[:40]}...' has no correct answer selected.",
                "link": f"/admin/portal/question/{q.id}/change/",
                "action": "Set Correct Option",
            })

    # 4. Coding Questions with no test cases
    for cq in CodingQuestion.objects.annotate(tc_count=Count("testcases")).select_related("section__exam"):
        if cq.tc_count == 0:
            issues.append({
                "type": "Coding Question Setup",
                "severity": "Critical",
                "message": f"Coding Question '{cq.title}' in Section '{cq.section.title}' has 0 test cases.",
                "link": f"/admin/portal/codingquestion/{cq.id}/change/",
                "action": "Add Test Cases",
            })

    # 5. Students with active session token older than 24 hours
    cutoff = timezone.now() - timezone.timedelta(hours=24)
    stale_students = Student.objects.filter(last_login_at__lt=cutoff).exclude(active_token="")
    for st in stale_students:
        issues.append({
            "type": "Stale Session",
            "severity": "Info",
            "message": f"Student '{st.usn}' has had an active session token since {st.last_login_at.strftime('%d-%b %H:%M')}.",
            "link": f"/admin/dashboard/students/{st.id}/",
            "action": "Inspect Student",
        })

    return issues
