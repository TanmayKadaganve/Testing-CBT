import json
import random
import time
from datetime import timedelta
import secrets
from django.conf import settings
from django.db import transaction, IntegrityError, OperationalError
from django.views.decorators.cache import never_cache
from django.http import HttpResponse, JsonResponse
from django.shortcuts import render, redirect
from django.utils import timezone
from django.utils.dateparse import parse_date
from django.views.decorators.http import require_POST
from .runner import run_code, LANGUAGES
from portal.services.language_registry import LanguageRegistry
from portal.services.code_draft import CodeDraftService
from .judge import judge
from .models import (
    Student, Attempt, Question, Option, Answer, Feedback, CodingQuestion,
    CodingQuestionAssignment, CodeDraft, CodeSubmission, ExecutionJob,
)
from .services.execution_queue import enqueue_job, get_queue_metrics


def parse_positive_id(value):
    if isinstance(value, bool):
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return parsed if 1 <= parsed <= 2**63 - 1 and str(parsed) == str(value).strip() else None


def parse_optional_id(value):
    return None if value in (None, "") else parse_positive_id(value)


def get_student(request):
    student_id = request.session.get("student_id")
    token = request.session.get("token")
    if not student_id or not token:
        return None
    return Student.objects.filter(id=student_id, is_active=True, active_token=token).first()


def release_student(student):
    student.active_token = ""
    student.save(update_fields=["active_token"])


def recruitment_deadline(student, exam):
    from recruitment.services.round_sessions import round_deadline_for
    return round_deadline_for(student, exam)


def recruitment_round_block(student, exam):
    """Prevent linked exam URLs from bypassing recruitment round controls."""
    from recruitment.models import CandidateEnrollment, RecruitmentDrive
    from recruitment.models import CandidateRoundSession
    linked_enrollments = CandidateEnrollment.objects.filter(
        student=student, drive__rounds__exam=exam
    ).select_related("drive", "current_round").distinct()
    if not linked_enrollments.exists():
        return None
    for enrollment in linked_enrollments:
        if enrollment.current_round_id and enrollment.current_round.exam_id == exam.id:
            if enrollment.drive.status != RecruitmentDrive.STATUS_ACTIVE:
                return "This recruitment drive is not active."
            if enrollment.status not in CandidateEnrollment.ACTIVE_STATUSES:
                return "Your enrollment is not eligible to enter this round."
            session = CandidateRoundSession.objects.filter(
                enrollment=enrollment, round=enrollment.current_round
            ).first()
            if not session:
                return "Please enter through the assigned recruitment round instructions."
            if timezone.now() >= session.deadline_at:
                return "Your time for this recruitment round has ended."
            return None
    return "This exam is not your currently assigned recruitment round."


def pick_exam(student):
    """The exam this student is registered for: the soonest one not yet over."""
    now = timezone.now()
    exams = [e for e in student.exam_set.all() if e.start_time]
    running_or_upcoming = sorted(
        [e for e in exams if e.end_time >= now], key=lambda e: e.start_time
    )
    if running_or_upcoming:
        return running_or_upcoming[0]
    if exams:
        return max(exams, key=lambda e: e.end_time)

    try:
        from recruitment.models import CandidateEnrollment, RecruitmentDrive
        active_enrollments = CandidateEnrollment.objects.filter(
            student=student,
            status__in=[CandidateEnrollment.STATUS_ENROLLED, CandidateEnrollment.STATUS_IN_PROGRESS],
            drive__status__in=[RecruitmentDrive.STATUS_PUBLISHED, RecruitmentDrive.STATUS_ACTIVE],
        ).select_related("current_round__exam", "drive")
        for enrollment in active_enrollments:
            round_obj = enrollment.current_round or enrollment.drive.ordered_rounds.first()
            if round_obj and round_obj.exam:
                round_obj.exam.students.add(student)
                return round_obj.exam
    except Exception:
        pass

    return None

@never_cache
def login_view(request):
    error = None
    if request.method == "POST":
        usn = request.POST.get("usn", "").strip().upper()
        try:
            dob = parse_date(request.POST.get("dob", ""))
        except ValueError:
            dob = None

        if usn and dob:
            for attempt_i in range(5):
                try:
                    with transaction.atomic():
                        student = (
                            Student.objects.select_for_update()
                            .filter(usn=usn, dob=dob, is_active=True)
                            .first()
                        )
                        if not student:
                            error = "Invalid USN or date of birth."
                            break
                        elif not pick_exam(student):
                            error = "You are not registered for any exam. Please contact the coordinator."
                            break
                        elif student.active_token and request.session.get("token") != student.active_token:
                            error = "This USN is already logged in on another computer. Please call the invigilator."
                            break
                        else:
                            old_id = request.session.get("student_id")
                            if old_id and old_id != student.id:
                                Student.objects.filter(id=old_id).update(active_token="")

                            token = secrets.token_hex(16)
                            student.active_token = token
                            student.last_login_ip = request.META.get("REMOTE_ADDR")
                            student.last_login_at = timezone.now()
                            student.save(update_fields=["active_token", "last_login_ip", "last_login_at"])

                            request.session.flush()
                            request.session["student_id"] = student.id
                            request.session["token"] = token
                            return redirect("instructions")
                except OperationalError:
                    if attempt_i == 4:
                        error = "Server busy under high concurrent load. Please retry."
                    else:
                        time.sleep(0.015 * (1.3 ** attempt_i) + random.uniform(0.005, 0.02))
        else:
            error = "Invalid USN or date of birth."

    return render(request, "portal/login.html", {"error": error})

@never_cache
def instructions(request):
    student = get_student(request)
    if not student:
        return redirect("login")
    exam = pick_exam(student)
    if not exam:
        return redirect("login")

    from recruitment.services.round_sessions import round_session_context
    round_enrollment, round_session = round_session_context(student, exam)
    if round_enrollment and round_enrollment.drive.status != "ACTIVE":
        return redirect("recruitment:candidate_dashboard")
    if round_enrollment and not round_session and round_enrollment.drive.status == "ACTIVE":
        return redirect("recruitment:round_instructions",
                        drive_id=round_enrollment.drive_id,
                        round_id=round_enrollment.current_round_id)
    round_block = recruitment_round_block(student, exam)
    if round_block and not round_block.endswith("time for this recruitment round has ended."):
        return redirect("recruitment:candidate_dashboard")

    now = timezone.now()
    seconds_to_start = max(0, int((exam.start_time - now).total_seconds()))
    deadline = recruitment_deadline(student, exam)
    exam_over = now > exam.end_time or (deadline is not None and now >= deadline)
    error = None

    if request.method == "POST":
        if exam_over:
            error = "This exam or recruitment round has ended."
        elif seconds_to_start > 0:
            error = "The exam has not started yet."
        elif not request.POST.get("agree"):
            error = "Please accept the terms to continue."
        else:
            created = False
            for attempt_i in range(5):
                try:
                    with transaction.atomic():
                        Attempt.objects.get_or_create(student=student, exam=exam)
                    created = True
                    break
                except IntegrityError:
                    created = Attempt.objects.filter(student=student, exam=exam).exists()
                    break
                except OperationalError:
                    if attempt_i < 4:
                        time.sleep(0.015 * (1.3 ** attempt_i) + random.uniform(0.005, 0.02))
            if created:
                return redirect("exam")
            error = "Server busy. Please retry entering the exam."

    return render(request, "portal/instructions.html", {
        "student": student,
        "exam": exam,
        "seconds_to_start": seconds_to_start,
        "exam_over": exam_over,
        "error": error,
    })


def current_section(exam):
    now = timezone.now()
    return exam.sections.filter(start_time__lte=now, end_time__gt=now).first()


@transaction.atomic
def assigned_coding_questions(attempt, section):
    try:
        assignment, _ = CodingQuestionAssignment.objects.get_or_create(
            attempt=attempt,
            section=section,
        )
    except IntegrityError:
        assignment = CodingQuestionAssignment.objects.get(attempt=attempt, section=section)

    assignment = CodingQuestionAssignment.objects.select_for_update().get(pk=assignment.pk)

    pool = list(CodingQuestion.objects.filter(section=section).order_by("order", "id"))
    target_count = min(2, len(pool))
    pool_by_id = {question.id: question for question in pool}

    stale_ids = list(
        assignment.questions.exclude(section=section).values_list("id", flat=True)
    )
    if stale_ids:
        assignment.questions.remove(*stale_ids)

    assigned = list(
        assignment.questions.filter(section=section).order_by("order", "id")
    )
    if len(assigned) > target_count:
        assignment.questions.remove(*(question.id for question in assigned[target_count:]))
        assigned = assigned[:target_count]

    selected_ids = {question.id for question in assigned}
    if len(assigned) < target_count:
        prior_work_ids = list(
            CodeDraft.objects.filter(attempt=attempt, question__section=section)
            .order_by("-updated_at")
            .values_list("question_id", flat=True)
        )
        prior_work_ids += list(
            CodeSubmission.objects.filter(attempt=attempt, question__section=section)
            .order_by("-created_at")
            .values_list("question_id", flat=True)
        )
        preferred = []
        for question_id in prior_work_ids:
            if question_id in pool_by_id and question_id not in selected_ids:
                preferred.append(pool_by_id[question_id])
                selected_ids.add(question_id)
                if len(assigned) + len(preferred) == target_count:
                    break

        remaining_count = target_count - len(assigned) - len(preferred)
        random_questions = []
        if remaining_count:
            random_questions = list(
                CodingQuestion.objects.filter(section=section)
                .exclude(id__in=selected_ids)
                .order_by("?")[:remaining_count]
            )

        additions = preferred + random_questions
        if additions:
            assignment.questions.add(*additions)

    return list(assignment.questions.filter(section=section).order_by("order", "id")[:2])

@never_cache
def exam_page(request):
    student = get_student(request)
    if not student:
        return redirect("login")
    exam = pick_exam(student)
    if exam:
        round_block = recruitment_round_block(student, exam)
        if round_block and round_block.startswith("Please enter through"):
            from recruitment.services.round_sessions import round_session_context
            enrollment, _session = round_session_context(student, exam)
            return redirect("recruitment:round_instructions",
                            drive_id=enrollment.drive_id, round_id=enrollment.current_round_id)
        if round_block and not round_block.endswith("time for this recruitment round has ended."):
            return redirect("recruitment:candidate_dashboard")
    attempt = Attempt.objects.filter(student=student, exam=exam).first() if exam else None
    if not attempt:
        return redirect("instructions")
    if attempt.submitted_at:
        return redirect("feedback")

    now = timezone.now()
    if now >= exam.end_time:
        attempt.submitted_at = now
        attempt.save()
        return redirect("feedback")

    deadline = recruitment_deadline(student, exam)
    if deadline is not None and now >= deadline:
        attempt.submitted_at = now
        attempt.save(update_fields=["submitted_at"])
        return redirect("feedback")

    section = current_section(exam)
    effective_deadline = min(exam.end_time, deadline) if deadline else exam.end_time
    unlock_at = exam.start_time + timedelta(minutes=exam.min_stay_minutes)
    context = {
        "student": student,
        "exam": exam,
        "section": section,
        "seconds_to_submit": max(0, int((unlock_at - now).total_seconds())),
    }

    if not section:
        context["next_section"] = (
            exam.sections.filter(start_time__gt=now).order_by("start_time").first()
        )
        return render(request, "portal/exam.html", context)

    if section.kind == "CODING":
        assigned_questions = assigned_coding_questions(attempt, section)
        supported_langs = LanguageRegistry.get_supported_languages()
        supported_ids = list(supported_langs.keys())

        coding = []
        for q in assigned_questions:
            q_state = CodeDraftService.resolve_question_state(attempt, q, supported_ids)
            coding.append(q_state)

        context["questions"] = coding
        context["languages"] = [
            {"id": spec.id, "name": spec.name, "highlight_mode": spec.highlight_mode}
            for spec in supported_langs.values()
        ]
        context["seconds_left"] = max(0, int((min(section.end_time, effective_deadline) - now).total_seconds()))
        return render(request, "portal/coding.html", context)

    questions = section.questions.prefetch_related("options")
    answers = {a.question_id: a for a in attempt.answers.filter(question__in=questions)}
    data = []
    for q in questions:
        a = answers.get(q.id)
        data.append({
            "id": q.id,
            "text": q.text,
            "marks": q.marks,
            "options": [{"id": o.id, "text": o.text} for o in q.options.all()],
            "selected": a.selected_option_id if a else None,
            "review": a.marked_for_review if a else False,
        })

    context["questions"] = data
    context["seconds_left"] = max(0, int((min(section.end_time, effective_deadline) - now).total_seconds()))
    return render(request, "portal/exam.html", context)

@require_POST
def save_answer(request):
    student = get_student(request)
    if not student:
        return JsonResponse({"ok": False, "error": "Not logged in"}, status=403)
    exam = pick_exam(student)
    attempt = Attempt.objects.filter(student=student, exam=exam).first() if exam else None
    if not attempt:
        return JsonResponse({"ok": False, "error": "No attempt"}, status=403)
    round_block = recruitment_round_block(student, exam)
    if round_block:
        return JsonResponse({"ok": False, "error": round_block}, status=403)
    if attempt.submitted_at:
        return JsonResponse({"ok": False, "error": "Already submitted"}, status=403)

    deadline = recruitment_deadline(student, exam)
    if deadline is not None and timezone.now() >= deadline:
        return JsonResponse({"ok": False, "error": "Round time has ended"}, status=403)

    section = current_section(exam)
    if not section:
        return JsonResponse({"ok": False, "error": "Section is locked"}, status=403)

    try:
        data = json.loads(request.body)
    except ValueError:
        return JsonResponse({"ok": False, "error": "Bad data"}, status=400)
    if not isinstance(data, dict):
        return JsonResponse({"ok": False, "error": "Expected a JSON object"}, status=400)

    question_id = parse_positive_id(data.get("question_id"))
    if question_id is None:
        return JsonResponse({"ok": False, "error": "Invalid question_id"}, status=400)
    question = Question.objects.filter(id=question_id, section=section).first()
    if not question:
        return JsonResponse({"ok": False, "error": "Question not in this section"}, status=400)

    option_id = data.get("option_id")
    if option_id:
        option_id = parse_positive_id(option_id)
        if option_id is None:
            return JsonResponse({"ok": False, "error": "Invalid option_id"}, status=400)
        option = Option.objects.filter(id=option_id, question=question).first()
        if not option:
            return JsonResponse({"ok": False, "error": "Invalid option for this question"}, status=400)
    else:
        option = None

    saved = False
    for attempt_i in range(5):
        try:
            with transaction.atomic():
                Answer.objects.update_or_create(
                    attempt=attempt,
                    question=question,
                    defaults={"selected_option": option, "marked_for_review": bool(data.get("review"))},
                )
            saved = True
            break
        except IntegrityError:
            with transaction.atomic():
                answer = Answer.objects.select_for_update().filter(attempt=attempt, question=question).first()
                if answer:
                    answer.selected_option = option
                    answer.marked_for_review = bool(data.get("review"))
                    answer.save(update_fields=["selected_option", "marked_for_review", "updated_at"])
            saved = Answer.objects.filter(attempt=attempt, question=question).exists()
            break
        except OperationalError:
            if attempt_i == 4:
                return JsonResponse({"ok": False, "error": "Database busy, please retry"}, status=503)
            time.sleep(0.015 * (1.3 ** attempt_i) + random.uniform(0.005, 0.02))

    if not saved:
        return JsonResponse({"ok": False, "error": "Answer was not saved; please retry"}, status=503)

    try:
        from recruitment.services.presence import CandidatePresenceService
        CandidatePresenceService.record_activity(
            student=student,
            activity_type="MCQ_ANSWER_SAVED",
            attempt=attempt,
            ip_address=request.META.get("REMOTE_ADDR"),
        )
    except Exception:
        pass

    return JsonResponse({"ok": True})





@require_POST
def logout_view(request):
    student = get_student(request)
    if student:
        release_student(student)
    request.session.flush()
    return redirect("login")

@require_POST
def submit_exam(request):
    student = get_student(request)
    if not student:
        return redirect("login")
    exam = pick_exam(student)
    attempt = Attempt.objects.filter(student=student, exam=exam).first() if exam else None
    if not attempt:
        return redirect("instructions")

    if not attempt.submitted_at:
        now = timezone.now()
        unlock_at = exam.start_time + timedelta(minutes=exam.min_stay_minutes)
        if now < unlock_at and now < exam.end_time:
            return redirect("exam")
        saved = False
        for attempt_i in range(5):
            try:
                attempt.submitted_at = now
                attempt.save(update_fields=["submitted_at"])
                saved = True
                break
            except OperationalError:
                if attempt_i < 4:
                    time.sleep(0.015 * (1.3 ** attempt_i) + random.uniform(0.005, 0.02))
        if not saved:
            return HttpResponse(
                "The exam could not be submitted because the server is busy. Please retry.",
                status=503,
            )
    return redirect("feedback")


@never_cache
def feedback_page(request):
    student = get_student(request)
    if not student:
        return redirect("login")
    exam = pick_exam(student)
    attempt = Attempt.objects.filter(student=student, exam=exam).first() if exam else None
    if not attempt or not attempt.submitted_at:
        return redirect("exam")
    if Feedback.objects.filter(attempt=attempt).exists():
        return redirect("done")

    error = None
    if request.method == "POST":
        try:
            experience = int(request.POST.get("experience", ""))
            realism = int(request.POST.get("realism", ""))
        except ValueError:
            experience = realism = 0
        if not (1 <= experience <= 5 and 1 <= realism <= 5):
            error = "Please select a rating for both questions."
        else:
            saved = False
            for attempt_i in range(5):
                try:
                    Feedback.objects.get_or_create(
                        attempt=attempt,
                        defaults={"experience_rating": experience,
                                  "realism_rating": realism,
                                  "comments": request.POST.get("comments", "").strip()},
                    )
                    saved = True
                    break
                except OperationalError:
                    if attempt_i < 4:
                        time.sleep(0.015 * (1.3 ** attempt_i) + random.uniform(0.005, 0.02))
            if saved:
                return redirect("done")
            error = "Feedback could not be saved because the server is busy. Please retry."

    return render(request, "portal/feedback.html", {"student": student, "error": error})

@never_cache
def done_page(request):
    student = get_student(request)
    if not student:
        return redirect("login")
    name = student.name
    attempt = (
        Attempt.objects.filter(student=student, feedback__isnull=False)
        .select_related("exam")
        .order_by("-submitted_at", "-id")
        .first()
    )
    exam = attempt.exam if attempt else None
    result_rows = []
    total_score = 0
    max_marks = 0

    if attempt:
        score_labels = [
            "Verbal Ability",
            "Logical Reasoning",
            "Quantitative Aptitude",
            "Programming and Coding",
        ]
        section_scores = {label: 0 for label in score_labels}
        label_by_title = {label.casefold(): label for label in score_labels}
        questions = Question.objects.filter(
            section__exam=exam,
            section__kind="MCQ",
        ).select_related("section")
        answers = {
            answer.question_id: answer
            for answer in Answer.objects.filter(attempt=attempt).select_related("selected_option")
        }

        for question in questions:
            max_marks += question.marks
            section = question.section
            label = (
                "Programming and Coding"
                if section.kind == "CODING"
                else label_by_title.get(section.title.strip().casefold())
            )
            answer = answers.get(question.id)
            if answer and answer.selected_option and answer.selected_option.is_correct:
                total_score += question.marks
                if label:
                    section_scores[label] += question.marks

        assigned_coding_questions = set()
        for assignment in attempt.coding_question_assignments.filter(section__kind="CODING"):
            assigned_coding_questions.update(assignment.questions.all())

        best_code_scores = {}
        for submission in CodeSubmission.objects.filter(
            attempt=attempt,
            question__in=assigned_coding_questions,
        ):
            best_code_scores[submission.question_id] = max(
                best_code_scores.get(submission.question_id, 0), submission.score
            )

        for question in assigned_coding_questions:
            max_marks += question.marks
            earned = best_code_scores.get(question.id, 0)
            section_scores["Programming and Coding"] += earned
            total_score += earned

        result_rows = [(label, section_scores[label]) for label in score_labels]

    release_student(student)
    request.session.flush()
    return render(request, "portal/done.html", {
        "name": name,
        "exam_title": exam.title if exam else "",
        "result_rows": result_rows,
        "total_score": total_score,
        "max_marks": max_marks,
    })

def _coding_request(request):
    """Shared checks for the three coding endpoints.

    Returns (info, None) on success or (None, error_response) on failure.
    """
    def fail(msg, status):
        return None, JsonResponse({"ok": False, "error": msg}, status=status)

    student = get_student(request)
    if not student:
        return fail("Not logged in", 403)
    exam = pick_exam(student)
    attempt = Attempt.objects.filter(student=student, exam=exam).first() if exam else None
    if not attempt:
        return fail("No attempt", 403)
    round_block = recruitment_round_block(student, exam)
    if round_block:
        return fail(round_block, 403)
    if attempt.submitted_at:
        return fail("Already submitted", 403)

    deadline = recruitment_deadline(student, exam)
    if deadline is not None and timezone.now() >= deadline:
        return fail("Round time has ended", 403)

    section = current_section(exam)
    if not section or section.kind != "CODING":
        return fail("Section is locked", 403)

    try:
        data = json.loads(request.body)
    except ValueError:
        return fail("Bad data", 400)
    if not isinstance(data, dict):
        return fail("Expected a JSON object", 400)

    assigned_questions = assigned_coding_questions(attempt, section)
    question_id = parse_positive_id(data.get("question_id"))
    if question_id is None:
        return fail("Invalid question_id", 400)
    question = CodingQuestion.objects.filter(
        id=question_id,
        section=section,
        id__in=[q.id for q in assigned_questions],
    ).first()
    if not question:
        return fail("Question not in this section", 400)

    language = data.get("language", "python")
    if not isinstance(language, str):
        return fail("Language must be a string", 400)
    if not LanguageRegistry.is_supported(language):
        return fail(f"Unsupported or unavailable language: {language}", 400)

    code = data.get("code", "")
    if not isinstance(code, str) or len(code) > 50000:
        return fail("Code too long", 400)

    return {"student": student, "attempt": attempt, "question": question,
            "language": language, "code": code, "data": data}, None


def _save_draft(info):
    raw_version = info["data"].get("version", 1) or 1
    incoming_version = parse_positive_id(raw_version)
    if incoming_version is None or incoming_version > 2**31 - 1:
        raise ValueError("Draft version is out of range")
    draft, error = CodeDraftService.save_draft(
        attempt=info["attempt"],
        question=info["question"],
        language=info["language"],
        code=info["code"],
        version=incoming_version,
    )
    if draft is None:
        raise RuntimeError(error or "Draft could not be saved")
    return draft


def _save_draft_or_response(info):
    try:
        return _save_draft(info), None
    except ValueError as exc:
        return None, JsonResponse({"ok": False, "error": str(exc)}, status=400)
    except RuntimeError as exc:
        return None, JsonResponse({"ok": False, "error": str(exc)}, status=503)
@require_POST
def save_code(request):
    info, err = _coding_request(request)
    if err:
        return err
    _, save_error = _save_draft_or_response(info)
    if save_error:
        return save_error
    try:
        from recruitment.services.presence import CandidatePresenceService
        CandidatePresenceService.record_activity(
            student=info["student"],
            activity_type="CODE_DRAFT_SAVED",
            attempt=info["attempt"],
            ip_address=request.META.get("REMOTE_ADDR"),
        )
    except Exception:
        pass
    return JsonResponse({"ok": True})


@require_POST
def code_run(request):
    info, err = _coding_request(request)
    if err:
        return err
    _, save_error = _save_draft_or_response(info)
    if save_error:
        return save_error

    stdin_text = info["data"].get("stdin")
    if not isinstance(stdin_text, str):
        stdin_text = info["question"].sample_input
    stdin_text = stdin_text[:10000]

    is_async = request.GET.get("async") == "1" or info["data"].get("async") is True or not settings.DEBUG
    job, err_dict = enqueue_job(
        attempt=info["attempt"],
        question=info["question"],
        kind="RUN",
        language=info["language"],
        code=info["code"],
        stdin=stdin_text,
        run_sync_fallback=not is_async,
    )
    if err_dict:
        return JsonResponse(
            {"ok": False, "error": err_dict["error"], "busy": err_dict.get("busy", False)},
            status=err_dict.get("status_code", 400),
        )

    if is_async:
        return JsonResponse({"ok": True, "job_id": str(job.id), "status": job.status})

    status_name = (
        "ok"
        if job.status == "COMPLETED" and job.verdict == "OK"
        else (
            "timeout"
            if job.status == "TIMED_OUT"
            else (
                "runtime_error"
                if job.verdict == "Runtime Error"
                else ("compile_error" if job.verdict == "Compilation Error" else "error")
            )
        )
    )
    return JsonResponse({
        "ok": True,
        "job_id": str(job.id),
        "status": status_name,
        "stdout": job.stdout,
        "stderr": job.stderr,
        "duration_ms": job.duration_ms,
    })


@require_POST
def code_submit(request):
    info, err = _coding_request(request)
    if err:
        return err
    _, save_error = _save_draft_or_response(info)
    if save_error:
        return save_error

    is_async = request.GET.get("async") == "1" or info["data"].get("async") is True or not settings.DEBUG
    job, err_dict = enqueue_job(
        attempt=info["attempt"],
        question=info["question"],
        kind="SUBMIT",
        language=info["language"],
        code=info["code"],
        stdin="",
        run_sync_fallback=not is_async,
    )
    if err_dict:
        return JsonResponse(
            {"ok": False, "error": err_dict["error"], "busy": err_dict.get("busy", False)},
            status=err_dict.get("status_code", 400),
        )

    if is_async:
        return JsonResponse({"ok": True, "job_id": str(job.id), "status": job.status})

    return JsonResponse({
        "ok": True,
        "job_id": str(job.id),
        "verdict": job.verdict,
        "passed": job.passed,
        "total": job.total,
        "score": job.score,
        "results": job.test_results_json or [],
        "duration_ms": job.duration_ms,
    })


def code_job_status(request, job_id):
    student = get_student(request)
    if not student:
        return JsonResponse({"ok": False, "error": "Not logged in"}, status=403)

    job = ExecutionJob.objects.filter(id=job_id, attempt__student=student).first()
    if not job:
        return JsonResponse({"ok": False, "error": "Job not found"}, status=404)

    return JsonResponse({
        "ok": True,
        "job_id": str(job.id),
        "status": job.status,
        "kind": job.kind,
        "verdict": job.verdict,
        "passed": job.passed,
        "total": job.total,
        "score": job.score,
        "stdout": job.stdout,
        "stderr": job.stderr,
        "duration_ms": job.duration_ms,
        "results": job.test_results_json or [],
        "error": job.error_message if job.status == "FAILED" else "",
    })


def csrf_failure(request, reason=""):
    return render(request, "portal/csrf_failure.html", {"reason": reason}, status=403)
