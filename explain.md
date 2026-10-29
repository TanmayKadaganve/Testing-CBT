# Project Explanation and Source Code Review

## 1. Project at a glance

This repository contains a Django application for computer-based testing (CBT) and recruitment simulations. It has two connected Django apps:

- **`portal`** manages student access, exams, MCQ answers, coding exercises, grading, feedback, and staff dashboards.
- **`recruitment`** manages recruitment drives, candidate enrollment, rounds, interview scoring, presence monitoring, integrity events, and progression decisions.

Recruitment rounds can link to exams in the portal. The recruitment progression service reads the portal's stored answers and code submissions to calculate round results.

The project does not define a separate public REST API or rely on a third-party web API. Its JSON endpoints are internal HTTP routes used by its own pages. Code execution invokes local compiler/runtime subprocesses.

## 2. How the project starts and routes requests

- `manage.py` sets `DJANGO_SETTINGS_MODULE=config.settings` and starts Django management commands.
- `config/settings.py` configures apps, middleware, templates, database, timezone, logging, static files, and security options.
- `config/urls.py` mounts the custom staff dashboard at `/admin/dashboard/`, Django Admin at `/admin/`, recruitment routes at `/recruitment/`, and candidate portal routes at `/`.
- `config/wsgi.py` and `config/asgi.py` expose Django entry points for application servers.
- `portal/apps.py` enables SQLite connection tuning (WAL, synchronous mode, busy timeout, temporary storage, and memory mapping) when SQLite is used.

Installed applications include Django's admin, authentication, content type, session, message, and static-file apps, plus `portal` and `recruitment`.

## 3. Database model map

There are **26 project models**: 15 in `portal` and 11 in `recruitment`.

### Portal models

| Model | Purpose |
|---|---|
| `Student` | Candidate profile, USN, date of birth, active state, single-login token, and last-login metadata |
| `Exam` | Exam title/instructions, minimum-stay configuration, and registered students |
| `Section` | Ordered MCQ or coding section with start/end times |
| `Question` | MCQ prompt, order, and marks |
| `Option` | MCQ answer option and correctness flag |
| `Attempt` | A student's unique attempt at an exam, including start and submission times |
| `Answer` | Selected option and review flag per attempt/question |
| `Feedback` | Post-exam ratings and comments |
| `CodingQuestion` | Coding prompt, constraints, sample I/O, runtime limit, and marks |
| `TestCase` | Input, expected output, sample/hidden flag, and scoring weight |
| `CodingQuestionStarterCode` | Per-question starter code for a language |
| `CodeDraft` | Candidate's saved code per attempt, question, and language |
| `CodeSubmission` | Official coding submission and final test/score summary |
| `CodingQuestionAssignment` | Coding questions assigned to an attempt within a section |
| `ExecutionJob` | Queued/running/completed code run or submit, output, verdict, and timing |

### Recruitment models

| Model | Purpose |
|---|---|
| `RecruitmentDrive` | Placement simulation and its lifecycle status |
| `Round` | Ordered stage in a drive; may link to a portal exam or interview template |
| `CandidateEnrollment` | Student's participation and current state/round in a drive |
| `RoundResult` | Score, percentage, decision, and scoring configuration snapshot for a candidate/round |
| `InterviewTemplate` | Interview structure and reusable rubric |
| `RubricCriterion` | Scored interview criterion with weight and maximum score |
| `InterviewAssignment` | Interviewer assignment, schedule, status, notes, and lock state |
| `InterviewEvaluation` | Interviewer's score and notes for one criterion |
| `CandidatePresence` | Latest heartbeat/activity information for an enrollment |
| `IntegrityEvent` | Browser-observable signal, severity, context, acknowledgment, and review data |
| `AuditLog` | Record of important recruitment/admin actions |

Important relationships: exams own sections; sections own MCQ or coding questions; attempts own answers, drafts, submissions, and jobs. Drives own rounds; enrollments link students to drives; round results and interview assignments link enrollments to rounds. Recruitment reuses portal `Student`, `Exam`, and `Attempt` records instead of creating duplicate candidate/exam models.

## 4. Candidate exam lifecycle

1. Candidate submits USN and date of birth on the login page. The application finds an active student and exam, rejects a different active login token, creates a token, and stores the student ID/token in the session.
2. `pick_exam()` chooses the soonest relevant exam. It can also find an exam from an active recruitment enrollment if the student has no direct exam registration.
3. On the instructions page, the candidate agrees to continue. The application creates or resumes the unique `Attempt` for that student/exam.
4. `exam_page()` finds the section whose scheduled time includes the current time. It renders MCQ questions or, for a coding section, assigns up to two coding questions and prepares language-specific starter/draft state.
5. MCQ answers are saved to `Answer`. The view checks that the question is in the active section and that the option belongs to that question.
6. Coding drafts are saved independently per question and language. Candidates can run code against input or submit it for grading.
7. Submission locks the attempt. The candidate can provide feedback and see a score page. The completion page clears the active login token and session.

Key functions in `portal/views.py` include `get_student`, `release_student`, `pick_exam`, `login_view`, `instructions`, `current_section`, `assigned_coding_questions`, `exam_page`, `save_answer`, `submit_exam`, `feedback_page`, `done_page`, `_coding_request`, `_save_draft`, `save_code`, `code_run`, `code_submit`, `code_job_status`, and `csrf_failure`.

## 5. Coding and scoring pipeline

- `portal/services/language_registry.py` defines Python, C, C++, and Java configurations and checks whether their runtimes/compilers are available.
- `portal/services/starter_code.py` returns configured per-question starter code or the language's generic scaffold.
- `portal/services/code_draft.py` saves and loads drafts by attempt/question/language; a version check prevents an older autosave from replacing a newer draft.
- `portal/runner.py` writes code to a temporary directory, compiles when needed, executes it with a reduced environment, captures output, and enforces a wall-clock timeout. Unix resource limits are attempted for CPU, memory, file size, file descriptors, and process count.
- `portal/judge.py` runs a submission for each test case, normalizes trailing whitespace, compares output, totals test-case marks, and scales the earned marks to the coding question's configured marks. Hidden test inputs and expected outputs are not returned in the result list.
- `portal/services/execution_queue.py` provides queue admission limits, job claiming/recovery, synchronous execution, and result persistence. `run_execution_worker` is a management command that polls and processes jobs.

The coding template calls `/exam/code/run/` and `/exam/code/submit/` without `?async=1`. Those views default to synchronous execution. Thus, the normal page flow runs the work in the web request, despite the available background worker implementation.

## 6. Recruitment lifecycle and progression

`RecruitmentDrive` has validated status transitions (draft, published, active, paused, closed, archived). A drive contains ordered `Round` records. Candidate enrollment records the candidate's current round and status.

Candidate recruitment views show a drive dashboard, round instructions, interview waiting room, and round results. An automated round can add its linked exam to the student's exam list and redirect to the portal exam flow. A human-evaluated round directs the candidate to the interview waiting page.

The main recruitment services are:

- `recruitment/services/progression.py`: `_compute_mcq_score`, `_compute_coding_score`, `_compute_interview_score`, `process_round_results`, `_process_single_enrollment`, `_record_result`, and `apply_manual_override`.
- `recruitment/services/presence.py`: `CandidatePresenceService.record_heartbeat()` and `record_activity()`.
- `recruitment/services/integrity.py`: records and deduplicates events, determines severity, acknowledges/reviews warnings, and adds invigilator notes.
- `recruitment/services/monitor.py`: produces live overview, roster, and incremental update data.
- `recruitment/services/analytics.py`: calculates drive summaries and candidate timelines.
- `recruitment/services/retention.py`: archives enrollments or permanently deletes an enrollment after a permission check, confirmation, reason, and audit record.

Automated progression uses saved portal answers and the best code submission score per assigned question. Interview progression uses completed interview assignments and weighted criterion scores. Mandatory rounds pass or fail against a percentage threshold; optional rounds advance candidates. Passing can move an enrollment to the next round; passing the final round marks the candidate selected.

Recruitment staff pages support drive transitions, enrollment, rosters, round processing, overrides, interviews, integrity review, monitoring, and Excel exports. The interviewer panel scopes an assignment to `interviewer=request.user` and locks the evaluation after submission. Custom staff views generally use Django's `staff_member_required` decorator.

## 7. HTTP route and API map

These routes are defined in `portal/urls.py`, `portal/dashboard_urls.py`, and `recruitment/urls.py`.

### Candidate portal

| Method | Path | Function |
|---|---|---|
| GET/POST | `/` | `login_view` |
| GET/POST | `/instructions/` | `instructions` |
| GET | `/exam/` or `/coding/` | `exam_page` |
| POST | `/exam/save/` | `save_answer` (JSON) |
| POST | `/exam/submit/` | `submit_exam` |
| GET/POST | `/feedback/` | `feedback_page` |
| GET | `/done/` | `done_page` |
| POST | `/exam/code/save/` | `save_code` (JSON) |
| POST | `/exam/code/run/` | `code_run` (JSON) |
| POST | `/exam/code/submit/` | `code_submit` (JSON) |
| GET | `/exam/code/job/<uuid>/` | `code_job_status` (JSON) |
| GET | `/logout/` | `logout_view` |

### Recruitment candidate routes

| Method | Path | Function |
|---|---|---|
| GET | `/recruitment/dashboard/` | `candidate_dashboard` |
| GET/POST | `/recruitment/drive/<drive_id>/round/<round_id>/instructions/` | `round_instructions` |
| GET | `/recruitment/round/<round_id>/waiting/` | `interview_waiting` |
| GET | `/recruitment/enrollment/<enrollment_id>/round/<round_id>/result/` | `candidate_round_result` |
| POST | `/recruitment/heartbeat/` | `candidate_heartbeat` (JSON) |
| POST | `/recruitment/integrity/event/` | `record_integrity_event` (JSON) |

### Staff pages

- `/admin/` is Django Admin.
- `/admin/dashboard/` and its subpaths provide the custom portal dashboard.
- `/recruitment/admin/` and its subpaths provide recruitment staff pages, including drive lists/details, rosters, interviews, exports, integrity review, and monitoring.
- `GET /recruitment/admin/drives/<drive_id>/monitor/updates/` returns JSON for live monitor polling.

Candidate JSON endpoints rely on the active candidate session and CSRF protection for POST requests. Staff operations require staff login; the interviewer views further filter assignments to the logged-in interviewer.

## 8. Main review findings

### Security and deployment

1. **Untrusted code is not isolated from the host.** Temporary directories and a sanitized environment are useful controls, but they do not block filesystem or network access. Unix `setrlimit` controls are skipped on Windows; Windows timeout cleanup kills the direct process only. The compiler phase has a timeout but does not receive the execution resource limits. Do not expose this runner to untrusted users without container/OS-level isolation, network restrictions, and resource controls.
2. **Development security settings are the defaults.** `DEBUG` defaults to true and `SECRET_KEY` has an insecure fallback in `config/settings.py`. Production must override both and set valid allowed hosts. `DJANGO_SECURE_SSL` controls secure cookies and defaults false; the sample environment also sets it false.
3. **Default host patterns are not subnet wildcards.** Entries like `10.*` in Django's `ALLOWED_HOSTS` are not interpreted as IP ranges. Configure exact host/IP entries or another valid arrangement for the deployment.
4. **Candidate authentication uses date of birth.** The candidate login is USN plus DOB rather than a password. Active-login tokens block concurrent sessions, but this is not equivalent to a strong candidate secret or an account password flow.
5. **Production dependencies are incomplete in `requirements.txt`.** The source supports PostgreSQL and deployment files configure Gunicorn, but neither a PostgreSQL adapter nor Gunicorn appears in the pinned requirements. Install/pin the needed deployment packages explicitly.

### Correctness and behavior

1. In `portal/views.py`, several database retry loops compare `attempt_i` with 14 even when the loop is `range(5)`. In `save_answer`, exhausting retries can fall through and return success even though the answer was not saved. `login_view` can also finish retries without setting the intended busy error.
2. `_save_draft()` ignores the `(draft, error)` returned by `CodeDraftService.save_draft()`. A failed draft write can therefore be presented as successful to the browser.
3. `Round.max_attempts` exists as configuration, but the exam attempt model has a unique student/exam constraint and the candidate flow does not enforce a configurable retry count.
4. `Round.score_weight` is stored in the result snapshot but not used in the shown round percentage/progression calculations.
5. `apply_manual_override()` stores `MANUAL_OVERRIDE` for both pass and fail overrides, while `RoundResult.passed` considers every `MANUAL_OVERRIDE` decision passed. A failed override can therefore be represented inconsistently by the result model.
6. The execution queue's admission checks are counts followed by job creation, not a single locked admission transaction, so concurrent requests could race around the configured capacity/concurrency limits.

### Documentation accuracy

The existing audit document under `docs/audits/` does not consistently describe the current source. It refers to password login and paths such as `/api/save-answer/`, but the implementation uses USN/DOB and `/exam/save/`. Its model count and some runner/security descriptions also differ from the code. The README says there are no automated tests, but test modules are present in both apps. Their current pass status has not been verified here.

## 9. Tests and operational utilities

Test files are present in `portal/tests.py`, `portal/tests_multilang.py`, `recruitment/tests.py`, and `recruitment/tests_e2e_scenarios.py`. They were not run as part of this source review.

Other operational files include:

- `scripts/migrate_to_postgres.py` for migration/export/import workflow support.
- `scripts/load_test_suite.py` and `scripts/load_test_recruitment.py` for load-test tooling.
- `deploy/gunicorn.conf.py`, `deploy/systemd/`, and `deploy/nginx/` for deployment configuration.
- `portal/services/system_health.py` for database, migration, disk, runner, static-asset, and execution-queue checks.
- `portal/middleware.py` for in-memory request performance measurements.

## 10. Summary

The repository implements a substantial exam and recruitment workflow with clear app separation, database-backed records, coding drafts, output-based grading, interview rubrics, and staff monitoring tools. The highest-priority concerns are safe execution of student code, production settings/deployment dependencies, retry paths that can report unsaved data as saved, and inconsistencies between manual overrides and result semantics. Treat the existing architecture audit as historical/inaccurate until it is reconciled with the current source.
