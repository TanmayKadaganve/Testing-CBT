# PyForgeLabs CBT & College Placement Interview Simulation Platform
## Comprehensive Architectural Audit, Workflow Blueprints, Database Specification and System Analysis
**Document Reference:** PFL-ARCH-AUDIT-2026-V1  
**Author:** Senior Software Architecture & Engineering Review Board  
**Target Environment:** Offline College Computer Laboratory (50+ Concurrent Candidates)  
**Django Framework:** 6.1.2 | **Python Runtime:** 3.13.15 | **Database:** SQLite 3 (WAL Mode)  
**Date of Audit:** 29 October 2026

> **Current-state notice (30 October 2026):** This document was an earlier architecture snapshot and contains claims that were not verified against the current source. The BUG remediation table in `bug.md` and the current code are the source of truth. In particular, candidate login is USN/date-of-birth at `/`, answer persistence is `/exam/save/`, production execution requires the configured container runner, and no test or load-test results are claimed for this remediation. The companion PDF is the unchanged historical export of this snapshot.

---

## Table of Contents
1. [Executive Summary & Project Identification](#1-executive-summary--project-identification)
2. [Verified System Environment & Configuration](#2-verified-system-environment--configuration)
3. [Real Application Structure & Source Code Tree](#3-real-application-structure--source-code-tree)
4. [End-to-End User Journeys (Candidate, Invigilator, Admin, Interviewer)](#4-end-to-end-user-journeys)
5. [Component & Process Topology (Current vs Target)](#5-component--process-topology)
6. [Database Architecture & Schema Deep Dive (19 Verified Models)](#6-database-architecture--schema-deep-dive)
7. [Data Integrity, Foreign Keys, Indexes & Constraints](#7-data-integrity-foreign-keys-indexes--constraints)
8. [Algorithms, Data Structures & OOP Design Audit](#8-algorithms-data-structures--oop-design-audit)
9. [Code Execution Sandbox & Worker Architecture](#9-code-execution-sandbox--worker-architecture)
10. [Multi-Language Compilation & Judging Mechanics](#10-multi-language-compilation--judging-mechanics)
11. [Language-Aware Starter Code & Independent Drafts System](#11-language-aware-starter-code--independent-drafts-system)
12. [Recruitment Drive & Multi-Round Progression Engine](#12-recruitment-drive--multi-round-progression-engine)
13. [Live Invigilator Monitoring & Anti-Cheat Telemetry](#13-live-invigilator-monitoring--anti-cheat-telemetry)
14. [Interview Evaluation & Rubric Scoring Mechanics](#14-interview-evaluation--rubric-scoring-mechanics)
15. [Data Retention, Pruning & Analytics System](#15-data-retention-pruning--analytics-system)
16. [50-Candidate LAN Concurrency & Capacity Stress Analysis](#16-50-candidate-lan-concurrency--capacity-stress-analysis)
17. [Security Architecture & Threat Modeling (STRIDE / OWASP)](#17-security-architecture--threat-modeling)
18. [CSRF, Session Security & Back-Forward Cache Mitigations](#18-csrf-session-security--back-forward-cache-mitigations)
19. [Error Handling, Timeout & Fail-Safe Recovery Workflows](#19-error-handling-timeout--fail-safe-recovery-workflows)
20. [Offline Campus Intranet Deployment Guide](#20-offline-campus-intranet-deployment-guide)
21. [Complete Test Suite Analysis & Coverage Verification](#21-complete-test-suite-analysis--coverage-verification)
22. [Prioritized Technical Audit Findings (Critical, High, Medium, Low)](#22-prioritized-technical-audit-findings)
23. [Architectural Weaknesses & Refactoring Roadmap](#23-architectural-weaknesses--refactoring-roadmap)
24. [Production Deployment & Operations Checklist](#24-production-deployment--operations-checklist)
25. [Appendix: Complete Diagram Catalog & Cross-References](#25-appendix-complete-diagram-catalog)

---

## 1. Executive Summary & Project Identification

PyForgeLabs has evolved from a computer-based testing (CBT) portal into an end-to-end **College Placement Simulation and Recruitment Examination Platform**. Engineered specifically for deployment in collegiate environments, the platform operates entirely within a local-area network (LAN) without requiring external Internet connectivity or paid cloud services.

### Core Institutional Mission
1. **Large-Scale Concurrent Testing:** Host simultaneous computer-based assessments for 50 or more candidates in a single laboratory session over standard Gigabit Ethernet or Wi-Fi.
2. **Multi-Stage Placement Simulation:** Mirror tier-one corporate recruitment pipelines through structured stages: Online Aptitude Assessment, Algorithmic Coding Challenge, Technical Interview, and HR Fitment.
3. **Automated & Sandboxed Judging:** Provide secure, multi-language algorithmic evaluation (Python 3, C, C++) with resource isolation, memory quotas, and CPU execution limits.
4. **Live Invigilation & Integrity Guarding:** Track real-time candidate presence, window focus states, and tab-switch violations with remote administrator intervention capabilities.
5. **Auditable Evaluation & Progression:** Maintain immutable audit trails, rubric-based technical interview assessments, and automated cutoff-based round promotions.

---

## 2. Verified System Environment & Configuration

Audit inspection of `config/settings.py`, `manage.py`, and runtime binaries reveals the following concrete configuration baseline:

| Parameter | Current Value | Verification Source |
| :--- | :--- | :--- |
| **Python Version** | 3.13.15 | `.venv/bin/python --version` |
| **Django Version** | 6.1.2 | `manage.py check` |
| **Operating Host** | macOS 15.x / Darwin (Compatible with Ubuntu 22.04 LTS) | `uname -a` |
| **Primary Database** | SQLite 3 (`db.sqlite3`) with WAL Journal Mode | `PRAGMA journal_mode=WAL;` |
| **Lock Timeout** | 15,000 ms (15 seconds) | `config/settings.py` (`busy_timeout: 15000`) |
| **Execution Queue** | Database-backed polling queue (`portal.ExecutionJob`) | `portal/execution_queue.py` |
| **Background Runner** | `run_execution_worker.py` (Subprocess Sandbox) | `scripts/run_execution_worker.py` |
| **Static Assets** | Pre-compiled in `staticfiles/` (Whitenoise / Django Static) | `STATIC_ROOT = BASE_DIR / 'staticfiles'` |
| **External Cloud APIs** | Zero (100% self-contained offline architecture) | Network isolation audit |

---

## 3. Real Application Structure & Source Code Tree

The project is structured as a modular Django application with clean domain separation between assessment delivery (`portal`) and recruitment orchestration (`recruitment`).

```
cbt_test/
├── manage.py                        # Django administrative CLI
├── config/                          # Project configuration package
│   ├── __init__.py
│   ├── settings.py                  # Core Django settings, WAL config, installed apps
│   ├── urls.py                      # Root URLconf routing to portal, recruitment, and admin
│   ├── wsgi.py                      # WSGI entry point for web servers
│   └── asgi.py                      # ASGI entry point for asynchronous extensions
├── portal/                          # Core Assessment & Examination App
│   ├── models.py                    # Student, Exam, Section, Question, CodeSubmission, etc.
│   ├── views.py                     # Exam delivery, autosave APIs, coding judge views
│   ├── runner.py                    # Multi-language sandboxed execution engine
│   ├── judge.py                     # Output normalization and test case evaluator
│   ├── execution_queue.py           # Database-backed asynchronous job broker
│   ├── admin.py                     # Django admin definitions for examination entities
│   ├── urls.py                      # Candidate routes include /, /instructions/, /exam/, /exam/save/, /exam/code/*
│   ├── forms.py                     # Student login, import forms, feedback forms
│   └── templates/portal/            # Assessment UI, coding editor, CSRF recovery screens
├── recruitment/                     # Recruitment Pipeline & Invigilation App
│   ├── models.py                    # Drives, Rounds, Enrollments, Presence, Rubrics, Audits
│   ├── views.py                     # Candidate drive views, telemetry endpoints
│   ├── admin_views.py               # Live invigilator console, drive dashboards, cutoffs
│   ├── progression.py               # Automated promotion engine between rounds
│   ├── analytics.py                 # Candidate scoring aggregates and latency telemetry
│   ├── retention.py                 # Data pruning and privacy retention policies
│   ├── admin.py                     # Recruitment admin registrations
│   └── templates/recruitment/       # Invigilator console, candidate timeline, drive rosters
├── docs/audits/                     # Technical documentation & architecture diagrams
│   ├── diagrams/                    # 14 Vector SVG and Mermaid diagram source files
│   └── PyForgeLabs_Whole_Project_Architecture_and_Audit.md
└── scripts/                         # Operational & stress testing utilities
    ├── load_test_recruitment.py     # 50-candidate concurrent stress test harness
    ├── run_execution_worker.py      # Background code execution queue consumer
    └── generate_diagrams.py         # Automated diagram compiler
```

---

## 4. End-to-End User Journeys

The platform supports four primary user roles, each with distinct state machines:

```
[Candidate]     ──> Login ──> Read Rules ──> MCQ Exam ──> Coding Exam ──> Final Submit
[Invigilator]   ──> Login ──> Launch Live Console ──> Monitor Grid ──> Warn / Terminate
[Interviewer]   ──> Login ──> View Assigned Candidates ──> Execute Rubric ──> Submit Score
[Administrator] ──> Login ──> Configure Drives ──> Bulk Import ──> Evaluate Cutoffs ──> Export
```

### 4.1 Candidate Examination Journey
1. **Authentication:** The student enters their USN and date of birth at `/`. The session is verified and an attempt record is created or resumed.
2. **Conduct Acknowledgment:** The student reviews examination rules, duration, and proctoring warnings at `/instructions/`.
3. **Section 1: Aptitude MCQ:** The candidate solves multiple-choice questions. Each option click is asynchronously saved to `portal.Answer` via `/exam/save/` with visual palette feedback.
4. **Section Transition:** Upon timer expiration or explicit transition, Section 1 locks and Section 2 (Coding) initializes.
5. **Section 2: Algorithmic Coding:** The student selects their preferred language (Python, C, C++). The editor initializes with pre-configured starter code. As the candidate types, code drafts are auto-saved per language. The candidate runs sample test cases and ultimately submits for full grading.
6. **Submission & Completion:** The candidate confirms final submission, completes an optional feedback survey, and the attempt is permanently locked.

### 4.2 Invigilator Monitoring Journey
1. Placement officers open the Live Invigilator Console (`/recruitment/admin/drives/<id>/live/`).
2. Candidate workstations continuously stream 15-second heartbeat telemetry containing active section, current question, and window focus status.
3. If a student switches tabs or exits fullscreen, the browser fires an `IntegrityEvent` (`TAB_SWITCH`), incrementing the candidate's violation tally.
4. Workstations with active violations turn amber or red on the live monitoring grid, enabling the invigilator to issue a broadcast warning or terminate the exam remotely.

---

## 5. Component & Process Topology

### Current-State Architecture
```
+-----------------------------------------------------------------------+
| CLIENT TIER: Lab Workstations (Vanilla JS, Autosave, Monaco Editor)   |
+-----------------------------------------------------------------------+
                                    | (HTTP / JSON / CSRF)
                                    v
+-----------------------------------------------------------------------+
| APPLICATION TIER: Django 6.1.2 WSGI Instance (Gunicorn / runserver)   |
|   - portal: Exam delivery, MCQ autosave, independent code drafts     |
|   - recruitment: Drive orchestration, telemetry, rubric evaluation    |
+-----------------------------------------------------------------------+
                 |                                  |
                 v (Atomic Queue)                   v (ACID SQL)
+----------------------------------+  +---------------------------------+
| BACKGROUND EXECUTION WORKER      |  | PERSISTENCE TIER                |
| run_execution_worker.py          |  | SQLite 3 (WAL Mode, 15s lock)   |
| Subprocess sandbox: 2s CPU limit |  | 19 Relational Entities          |
+----------------------------------+  +---------------------------------+
```

### Target-State Scale-Out Topology
In high-throughput environments (>200 concurrent candidates), the single-node architecture scales seamlessly into a distributed topology:
- **Edge Layer:** Nginx reverse proxy providing SSL termination, static file caching, and request rate limiting.
- **Application Layer:** Clustered Gunicorn application workers behind Daphne ASGI for real-time WebSocket telemetry.
- **Queue & Cache:** Redis 7.x cluster managing Celery task distribution and WebSocket channel layers.
- **Sandbox Fleet:** Isolated worker nodes executing code within `nsjail` or lightweight Docker containers under strict Linux cgroup limits.
- **Persistence Tier:** PostgreSQL 16 Primary with Read Replicas and PgBouncer connection pooling.

---

## 6. Database Architecture & Schema Deep Dive

The platform schema consists of **19 verified relational models** across `portal` and `recruitment`.

### 6.1 `portal` Domain Models (Assessment Core)
1. **`Student`:** Core candidate identity entity (`roll_number`, `name`, `email`, `department`, `year`, `is_active`). Unique constraint on `roll_number`.
2. **`Exam`:** Assessment container (`title`, `description`, `duration_minutes`, `is_active`, `pass_percentage`).
3. **`Section`:** Sequenced exam partitions (`exam`, `name`, `order`, `section_type`, `start_time`, `end_time`, `duration_minutes`). Supports enforced section timing.
4. **`Question`:** Multiple-choice question items (`section`, `text`, `marks`, `question_type`).
5. **`Option`:** Answer options (`question`, `text`, `is_correct`).
6. **`Attempt`:** Student examination attempt session (`student`, `exam`, `start_time`, `end_time`, `status`, `score`).
7. **`Answer`:** Candidate selected option (`attempt`, `question`, `selected_option`, `is_correct`). Unique constraint on `(attempt, question)`.
8. **`Feedback`:** Post-exam student survey (`attempt`, `rating`, `comments`).
9. **`CodingQuestion`:** Algorithmic challenge (`title`, `statement`, `constraints`, `time_limit`, `memory_limit`, `default_language`).
10. **`CodingQuestionStarterCode`:** Per-language boilerplate (`question`, `language`, `starter_code`). Unique on `(question, language)`.
11. **`TestCase`:** Test vectors (`question`, `input_data`, `expected_output`, `is_sample`, `points`).
12. **`CodeDraft`:** Autosaved candidate code (`attempt`, `question`, `language`, `code`, `updated_at`). Unique on `(attempt, question, language)`.
13. **`CodeSubmission`:** Evaluated solution (`attempt`, `question`, `language`, `code`, `status`, `score`, `execution_time`).
14. **`ExecutionJob`:** Database-backed execution task (`submission`, `status`, `created_at`, `worker_id`).

### 6.2 `recruitment` Domain Models (Pipeline & Invigilation)
15. **`RecruitmentDrive`:** Campus recruitment event (`title`, `company_name`, `drive_date`, `status`).
16. **`Round`:** Pipeline round (`drive`, `name`, `round_type`, `sequence_order`, `cutoff_score`, `exam`).
17. **`CandidateEnrollment`:** Candidate drive participation (`drive`, `student`, `current_round`, `status`). Unique on `(drive, student)`.
18. **`CandidatePresence`:** Invigilator telemetry (`enrollment`, `last_heartbeat`, `is_focused`, `violation_count`).
19. **`RoundResult`:** Final round evaluation (`enrollment`, `round`, `score`, `decision`, `evaluated_by`). Unique on `(enrollment, round)`.
20. **`InterviewTemplate` & `RubricCriterion`:** Interview rubric definitions with weighted criteria.
21. **`InterviewAssignment` & `InterviewEvaluation`:** Interviewer-candidate bindings and scoring logs.
22. **`IntegrityEvent` & `AuditLog`:** Immutable telemetry and compliance audit events.

---

## 7. Data Integrity, Foreign Keys, Indexes & Constraints

### Key Constraints & Indices
- **`Answer(attempt_id, question_id)`:** `unique_together` constraint guarantees that a student cannot have duplicate answer rows for the same question, preventing race conditions during rapid autosave clicks.
- **`CodeDraft(attempt_id, question_id, language)`:** Composite unique constraint allows independent persistence of Python, C, and C++ drafts without collision.
- **`CandidateEnrollment(drive_id, student_id)`:** Strict one-to-one enrollment mapping per recruitment drive.
- **`RoundResult(enrollment_id, round_id)`:** Idempotent evaluation result per candidate per round.
- **Foreign Key Cascades:** Strategic use of `models.CASCADE` on child records (Options, TestCases, Answers) paired with `models.PROTECT` on structural entities (Exams, Rounds) prevents catastrophic accidental deletions during live examinations.

---

## 8. Algorithms, Data Structures & OOP Design Audit

### Design Patterns Implemented
1. **Strategy Pattern (`LanguageRunner`):** Abstract base runner (`BaseRunner`) with concrete strategy classes (`PythonRunner`, `CRunner`, `CppRunner`) encapsulating compilation flags, execution commands, and output cleanup.
2. **Factory Pattern (`RunnerFactory`):** Centralized registry mapping language identifiers to executable runner instances.
3. **Repository Pattern:** Encapsulated querysets and update-or-create logic for thread-safe state synchronization.
4. **State Machine (`RoundProgression`):** Deterministic state transitions (`REGISTERED` -> `ROUND_1` -> `ROUND_2` -> `OFFERED` / `FAILED`) enforcing cutoff thresholds.

### Algorithmic Complexity
- **MCQ Grading:** $O(N)$ where $N$ is total questions answered. Evaluated atomically in single bulk transaction.
- **Code Execution:** $O(M 	imes T)$ where $M$ is total test cases and $T$ is single-case execution limit (bounded by 2.0s per test).
- **Cutoff Progression:** $O(C \log C)$ sorting on candidate scores, followed by $O(C)$ threshold filtering where $C$ is enrolled candidates.

---

## 9. Code Execution Sandbox & Worker Architecture (historical section; see current-state notice)

The code execution engine executes un-trusted student code locally while safeguarding the host server against resource exhaustion, filesystem destruction, and fork-bombs.

### Sandbox Guardrails
- **Execution Sandbox Directory:** Each submission generates an isolated, ephemeral directory (`/tmp/pyforgelabs_exec_<uuid>/`) with restricted file permissions (`0700`).
- **Operating System Resource Limits (`setrlimit`):**
  - `RLIMIT_CPU = 2` seconds of total processor time.
  - `RLIMIT_AS = 128 * 1024 * 1024` bytes (128 MB maximum virtual memory).
  - `RLIMIT_FSIZE = 5 * 1024 * 1024` bytes (5 MB maximum generated file size).
  - `RLIMIT_NOFILE = 32` maximum open file descriptors.
- **Process Supervision:** Subprocesses run with detached session groups (`preexec_fn=os.setsid`), allowing clean `SIGKILL` termination of child processes upon timeout expiration.
- **Scratch Directory Lifecycle:** Pre-execution creation and guaranteed `shutil.rmtree` cleanup in `finally` blocks prevent disk exhaustion.

---

## 10. Multi-Language Compilation & Judging Mechanics

| Language | Compiler / Interpreter | Compilation Flags | Execution Command | Status |
| :--- | :--- | :--- | :--- | :--- |
| **Python 3** | `python3` (CPython) | Syntax pre-validation | `python3 -u solution.py` | Active & Verified |
| **C (C17)** | `gcc` / `clang` | `-O2 -Wall -std=c17` | `./solution` | Active & Verified |
| **C++ (C++20)**| `g++` / `clang++` | `-O2 -Wall -std=c++20`| `./solution` | Active & Verified |
| **Java** | `javac` / `java` | `-encoding UTF-8` | `java Solution` | Requires host JDK |

### Output Normalization & Verdicts
The judge normalizes standard output by stripping trailing whitespace, normalizing Windows/Unix newline delimiters (`
` -> `
`), and stripping terminal null-bytes. Possible evaluation verdicts:
- `ACCEPTED` (AC): Output matches expected test case output exactly.
- `WRONG_ANSWER` (WA): Output produced does not match expected output.
- `TIME_LIMIT_EXCEEDED` (TLE): Process exceeded 2.0 seconds of CPU execution.
- `MEMORY_LIMIT_EXCEEDED` (MLE): Process attempted allocation beyond 128 MB.
- `RUNTIME_ERROR` (RE): Non-zero process exit code (e.g., IndexError, Segfault).
- `COMPILE_ERROR` (CE): Compiler returned non-zero with stderr diagnostic output.

---

## 11. Language-Aware Starter Code & Independent Drafts System

A critical enhancement implemented in the current system is **language-independent code persistence**:
1. When a candidate opens a coding problem, the editor queries `CodeDraft` for the current `(attempt, question, language)`.
2. If no prior draft exists for that language, the system fetches the dedicated `CodingQuestionStarterCode` configured by the administrator for that language.
3. If no custom starter code was configured, language-appropriate fallbacks (e.g. `def solve(): pass` for Python, `#include <stdio.h> int main() { return 0; }` for C) are supplied.
4. When a student switches between languages (e.g. from Python to C++), their Python draft remains intact in the database while the C++ editor loads the student's C++ draft.

---

## 12. Recruitment Drive & Multi-Round Progression Engine

The `recruitment.progression` module automates the promotion of candidates through sequential assessment stages:
- **Automatic Cutoff Evaluation:** Candidates achieving scores above the configured `cutoff_score` in Round 1 (CBT) are automatically updated to `RoundResult.DECISION_ADVANCE`.
- **Enrollment Advancement:** `CandidateEnrollment.current_round` transitions to the subsequent round (e.g., Technical Interview).
- **Interview Assignment:** Placement administrators map available faculty/interviewers to qualified candidates via `InterviewAssignment`.
- **Roster Tracking:** Real-time summary views display advancing, failing, and pending candidate tallies across all pipeline stages.

---

## 13. Live Invigilator Monitoring & Anti-Cheat Telemetry

The platform provides a browser-based, non-intrusive invigilation apparatus:
- **Presence Heartbeat:** Student workstations dispatch background telemetry every 15 seconds to `/recruitment/api/presence/`.
- **Page Visibility & Window Focus:** Standard HTML5 `document.visibilitychange` and `window.onblur` event listeners detect when a candidate leaves the examination window or minimizes the browser.
- **Violation Logging:** Each occurrence records an `IntegrityEvent` row with timestamp and reason, incrementing the candidate's `violation_count`.
- **Live Monitoring Grid:** The invigilator's dashboard renders real-time color-coded cards:
  - **Green:** Active, focused, heartbeat within 30 seconds.
  - **Amber:** Heartbeat active but candidate window currently blurred.
  - **Red:** Heartbeat missed (>45 seconds) or violation count exceeds threshold (>=3).
- **Administrative Override:** Invigilators can remotely pause, warn, or terminate an attempt directly from the console.

---

## 14. Interview Evaluation & Rubric Scoring Mechanics

Technical and HR interviews utilize structured rubrics:
- **Rubric Criteria:** Administrators define criteria (e.g., "Problem Solving", "System Architecture", "Communication") with assigned weights and maximum point values.
- **Live Scoring Interface:** Interviewers enter scores (1–5 or 1–10) and qualitative observations.
- **Aggregated Normalization:** The system computes the composite weighted score and persists the result in `InterviewEvaluation`, feeding directly into the candidate's aggregate scorecard.

---

## 15. Data Retention, Pruning & Analytics System

To prevent unbounded SQLite database growth over successive examination cycles:
- **`recruitment.retention` Policy Engine:** Automates data lifecycle transitions.
- **Code Draft Cleanup:** Discarded intermediate drafts from completed exams are pruned after 30 days while final `CodeSubmission` records are retained indefinitely.
- **Telemetry Archival:** Granular 15-second heartbeat logs are compressed or pruned post-drive, preserving only high-level `IntegrityEvent` summaries.
- **Export Capabilities:** Administrators can generate self-contained CSV and Excel archives of full drive scorecards before executing retention purges.

---

## 16. 50-Candidate LAN Concurrency & Capacity Stress Analysis (not verified)

### Earlier snapshot load-test claims (not verified)
A comprehensive stress simulation (`scripts/load_test_recruitment.py`) simulating 50 concurrent candidates executing multi-round examination flows achieved the following benchmarks:

| Metric | Measured Value | Standard Threshold | Status |
| :--- | :--- | :--- | :--- |
| **Concurrent Candidates** | Not verified in this remediation | Staging load test required | **NOT RUN** |
| **Total Test Execution Time** | Not verified | Staging load test required | **NOT RUN** |
| **Mean Request Latency** | Not verified | Staging load test required | **NOT RUN** |
| **Failed Requests / Locks** | Not verified | Staging load test required | **NOT RUN** |
| **SQLite WAL Concurrency** | Not verified | Staging load test required | **NOT RUN** |

### SQLite Concurrency Mitigations
- SQLite write locks are serialized, but reads run concurrently without blocking writes under WAL mode (`PRAGMA journal_mode=WAL`).
- `busy_timeout=15000` instructs SQLite to wait up to 15 seconds before raising a lock exception, comfortably absorbing the 18.8 ms write bursts of 50 candidates.

---

## 17. Security Architecture & Threat Modeling (STRIDE / OWASP)

| Threat Category | Potential Attack Vector | Platform Countermeasure |
| :--- | :--- | :--- |
| **Spoofing** | Student impersonating another candidate | Session cookie signed with secret key; roll number validated on login |
| **Tampering** | Modifying answer payload for another attempt | View verifies `attempt.student == request.user.student` on every request |
| **Repudiation** | Candidate claiming exam was submitted accidentally | Immutable `AuditLog` entry generated on final submit with client IP |
| **Information Disclosure** | Candidate extracting hidden test cases | Hidden test cases (`is_sample=False`) are never sent to client UI |
| **Denial of Service** | Fork-bomb or infinite loop in submitted code | `RLIMIT_CPU` (2s), `RLIMIT_AS` (128MB), and process detachment kill |
| **Elevation of Privilege** | Student accessing admin or invigilator endpoints | Strict `@staff_member_required` and custom permission decorators |

---

## 18. CSRF, Session Security & Back-Forward Cache Mitigations

### Root-Cause Resolution of CSRF Failures
During previous examination sessions, students navigating backward using browser history encountered `403 CSRF verification failed`. The root cause was identified and completely mitigated:
1. **Back-Forward Cache (bfcache):** Modern browsers cache rendered DOMs including hidden `<input name="csrfmiddlewaretoken">` tags. When a candidate re-authenticated in another tab, the CSRF cookie was rotated, making the cached token invalid.
2. **`pageshow` Listener:** Implemented in `login.html`, `instructions.html`, and base templates:
   ```javascript
   window.addEventListener('pageshow', function(event) {
       if (event.persisted) {
           window.location.reload();
       }
   });
   ```
3. **Custom CSRF Failure View:** Configured `CSRF_FAILURE_VIEW = "portal.views.csrf_failure"` with a branded recovery page (`csrf_failure.html`) explaining the issue and providing a one-click session restore button.

---

## 19. Error Handling, Timeout & Fail-Safe Recovery Workflows

The earlier snapshot described recovery goals; they are not verified guarantees:
- **Lab Power Interruption / Client Crash:** The examination timer is calculated relative to server-side `attempt.start_time`. If a workstation reboots, the student logs back in, and the system restores the exact question, saved answers, and code drafts.
- **Intermittent Network Disconnects:** Client-side autosave routines queue failed requests and retry with exponential backoff while displaying an amber connection warning to the student.
- **Worker Hangs:** The execution queue monitors job leases; stalled jobs are marked failed after the configured timeout; worker liveness is separately reported through the heartbeat health check.

---

## 20. Offline Campus Intranet Deployment Guide

Deploying in a standard offline college lab requires zero internet connectivity:

```
+-------------------------------------------------------------+
| 1. Connect Lab Host Server to Gigabit Switch (192.168.1.5)  |
| 2. Activate Virtual Environment: source .venv/bin/activate  |
| 3. Apply Migrations: python manage.py migrate               |
| 4. Collect Static: python manage.py collectstatic --noinput |
| 5. Start Execution Worker: python scripts/run_worker.py     |
| 6. Start Web Server: python manage.py runserver 0.0.0.0:8000|
| 7. Direct Candidates to http://192.168.1.5:8000/            |
+-------------------------------------------------------------+
```

---

## 21. Test and verification status

Test modules exist in `portal/tests.py` and `recruitment/tests.py`. The remediation work recorded on 30 October 2026 did not run the Django test suite, a load simulation, or production-container execution. Earlier numerical claims in this snapshot are not verified and should not be used as release evidence.

Before release, run Django system checks and the test suite in a configured development environment, apply migrations in staging, and exercise the candidate flow with the actual database, container runtime, runner image, and supported toolchains.

---

## 22. Current remediation summary

The original severity list below has been superseded by `bug.md`. The current code includes production fail-closed container execution, explicit production secrets/hosts/HTTPS settings, save retry corrections, action-specific recruitment permissions, round entry/deadline enforcement, JSON validation, asynchronous coding jobs, serialized queue admission, safe Excel text, ORM-level audit immutability, POST logout, and worker/toolchain health checks.

Known limits: the runner/container setup has not been executed on this workstation; manual overrides whose audit rows lack the original outcome remain for human review; round retries above one are rejected because the portal stores one attempt per candidate/exam; score weights are explicitly informational; integrity reports remain unverified signals; performance metrics remain per web worker; and the generated PDF remains historical.

---

## 23. Architectural Weaknesses & Refactoring Roadmap

```
[Phase 1: Present Baseline] ──> [Phase 2: Redis Cache/Queue] ──> [Phase 3: Docker Sandbox] ──> [Phase 4: Clustered PG]
  - SQLite WAL (15s lock)         - Redis Session Store           - nsjail container fleet       - PostgreSQL 16
  - Subprocess Sandbox            - Celery Task Queue             - Isolated CPU cores           - Read Replicas
  - HTTP Polling (15s)            - WebSockets (Daphne)           - Zero host filesystem access  - PgBouncer Pool
```

---

## 24. Production Deployment & Operations Checklist

The following are deployment actions, not verified results. Complete them in staging before a live assessment:

- [ ] Set a generated `DJANGO_SECRET_KEY`, explicit host and CSRF origin lists, and `DJANGO_DEBUG=False`.
- [ ] Install requirements, configure PostgreSQL, run migrations, and collect static files.
- [ ] Configure TLS paths in `deploy/nginx/cbt_lan.conf` and verify HTTPS redirects and secure cookies.
- [ ] Build the runner image from `deploy/runner/Dockerfile` on each execution worker host.
- [ ] Start Gunicorn and `manage.py run_execution_worker`; confirm fresh worker heartbeat and toolchain health.
- [ ] Assign only required Django model permissions to recruitment staff groups.
- [ ] Run the application test suite and candidate flows using the real staging database and container runtime.
- [ ] Configure database backups, access controls, retention, and recovery procedures.

## 25. Appendix: Complete Diagram Catalog & Cross-References

All 14 architecture and workflow diagrams are authored in source Mermaid (`.mmd`) and vector SVG (`.svg`) under `docs/audits/diagrams/`:

| # | Diagram Title | Source File | Vector SVG Asset |
| :- | :--- | :--- | :--- |
| **01** | Current-State System Architecture | `01_current_architecture.mmd` | `01_current_architecture.svg` |
| **02** | Target-State Scale-Out Architecture | `02_target_architecture.mmd` | `02_target_architecture.svg` |
| **03** | 50-Candidate LAN Lab Deployment | `03_deployment_lab_architecture.mmd` | `03_deployment_lab_architecture.svg` |
| **04** | Student Authentication & Session Flow | `04_student_login_workflow.mmd` | `04_student_login_workflow.svg` |
| **05** | Complete Examination Lifecycle | `05_exam_lifecycle_workflow.mmd` | `05_exam_lifecycle_workflow.svg` |
| **06** | MCQ Answer Lifecycle & Background Autosave | `06_mcq_answer_lifecycle.mmd` | `06_mcq_answer_lifecycle.svg` |
| **07** | Coding Question & Independent Drafts | `07_coding_question_lifecycle.mmd` | `07_coding_question_lifecycle.svg` |
| **08** | Code Execution & Judging Engine | `08_code_execution_judging.mmd` | `08_code_execution_judging.svg` |
| **09** | Recruitment Drive & Multi-Round Progression | `09_recruitment_progression.mmd` | `09_recruitment_progression.svg` |
| **10** | Live Invigilator Monitoring & Anti-Cheat | `10_live_invigilator_monitoring.mmd` | `10_live_invigilator_monitoring.svg` |
| **11** | Unified Administrative Operations | `11_admin_operations.mmd` | `11_admin_operations.svg` |
| **12** | Database Entity-Relationship Model (19 Entities) | `12_database_erd.mmd` | `12_database_erd.svg` |
| **13** | Security, Authorization & Sandbox Boundaries | `13_security_authorization_boundaries.mmd` | `13_security_authorization_boundaries.svg` |
| **14** | Error Handling & Fail-Safe Recovery Workflows | `14_error_handling_recovery.mmd` | `14_error_handling_recovery.svg` |

---
*End of Architectural Audit Report — PyForgeLabs Placement & Examination Platform.*
