#!/usr/bin/env python3
"""
Generate all 14 architectural and workflow diagrams for PyForgeLabs CBT
in both Mermaid (.mmd) and standalone Vector SVG (.svg) formats.
"""

import os
from pathlib import Path

DIAGRAMS_DIR = Path(__file__).resolve().parent.parent / "docs" / "audits" / "diagrams"
DIAGRAMS_DIR.mkdir(parents=True, exist_ok=True)

# -----------------------------------------------------------------------------
# MERMAID DEFINITIONS
# -----------------------------------------------------------------------------

MERMAID_DIAGRAMS = {
    "01_current_architecture.mmd": """flowchart TB
    subgraph ClientLayer["Client Layer (Lab Workstations)"]
        S_UI["Student Web Client\\n(Vanilla JS, Auto-save, Ace/Monaco, Visibility API)"]
        A_UI["Admin / Invigilator Console\\n(Live Monitoring Dashboard, Audit Log)"]
        I_UI["Interviewer Portal\\n(Rubric Scoring, Candidate Timeline)"]
    end

    subgraph AppServer["Django Application Server (Port 8000)"]
        WSGI["WSGI / Gunicorn / runserver"]
        SEC["Security & Middleware\\n(CSRF, Session, Auth, HostValidation)"]
        
        subgraph PortalApp["portal Application"]
            PV["portal.views\\n(Auth, Exam, Section, MCQ Autosave, Drafts)"]
            PR["portal.runner\\n(Multi-language Sandbox: Python, C, C++)"]
            PJ["portal.judge\\n(Test Case Matcher, Score Engine)"]
            PQ["portal.execution_queue\\n(DB-backed ExecutionJob Queue)"]
        end

        subgraph RecruitmentApp["recruitment Application"]
            RV["recruitment.views & admin_views\\n(Drives, Invigilation, Telemetry)"]
            RP["recruitment.progression\\n(Round Cutoffs & Promotion Engine)"]
            RA["recruitment.analytics & retention\\n(Scores, Latency, Data Pruning)"]
        end
    end

    subgraph DataLayer["Persistence & Storage Layer"]
        DB[("SQLite 3 Database\\n(db.sqlite3 with WAL mode & 15s timeout)")]
        STATIC["Collected Static Assets\\n(staticfiles/)"]
        SANDBOX_TMP["Sandboxed Temp Files\\n(/tmp/pyforgelabs_exec_*)"]
    end

    subgraph WorkerProcess["Background Execution Engine"]
        WORKER["run_execution_worker.py\\n(Polling Loop, Atomic Job Claiming)"]
        SUBPROC["Subprocess Sandbox\\n(ulimit CPU, Memory, Timeout Enforcement)"]
    end

    S_UI -->|"HTTP / REST API (CSRF)"| WSGI
    A_UI -->|"Live Polling (Presence, Alerts)"| WSGI
    I_UI -->|"Rubric Evaluation POST"| WSGI
    WSGI --> SEC --> PV & RV
    PV --> PR & PQ
    PQ --> DB
    WORKER -->|"SELECT FOR UPDATE / Claim"| DB
    WORKER --> SUBPROC
    SUBPROC --> SANDBOX_TMP
    PR --> SUBPROC
    RV --> RP & RA
    PV & RV --> DB
    WSGI -.-> STATIC
""",

    "02_target_architecture.mmd": """flowchart TB
    subgraph EdgeLayer["Edge & Ingress Layer"]
        DNS["Internal College DNS / Router"]
        NGINX["Nginx High-Performance Reverse Proxy\\n(SSL/TLS, Static File Cache, Gzip, Rate Limiting)"]
    end

    subgraph AppCluster["Application Tier (Scale-Out)"]
        GUNICORN1["Gunicorn Instance 1\\n(4 gthread Workers)"]
        GUNICORN2["Gunicorn Instance 2\\n(4 gthread Workers)"]
        ASGI["Daphne / Uvicorn ASGI Server\\n(WebSockets for Real-time Invigilation)"]
    end

    subgraph CacheBroker["In-Memory Cache & Message Broker"]
        REDIS["Redis 7.x Cluster / Standalone\\n(Cache, Channel Layers, Celery Broker, Session Store)"]
    end

    subgraph CoreServices["Django Core Platform (portal + recruitment)"]
        DJ_CORE["Django 6.x Application Server"]
        PROG_SVC["Progression & Evaluation Service"]
        INVIG_SVC["Live Telemetry & Alert Stream"]
    end

    subgraph SandboxFleet["Distributed Execution Fleet"]
        CELERY["Celery Distributed Workers"]
        DOCKER1["Containerized Sandbox 1\\n(nsjail / Docker cgroups)"]
        DOCKER2["Containerized Sandbox 2\\n(nsjail / Docker cgroups)"]
    end

    subgraph StorageLayer["Data & Persistence Tier"]
        PG_PRIMARY[("PostgreSQL 16 Primary\\n(ACID, Connection Pooler: PgBouncer)")]
        PG_REPLICA[("PostgreSQL 16 Read Replica\\n(Analytics & Live Dashboard Queries)")]
    end

    DNS --> NGINX
    NGINX -->|"Static / Media"| STATIC_VOL["Local SSD / S3 Volume"]
    NGINX -->|"HTTP Requests"| GUNICORN1 & GUNICORN2
    NGINX -->|"WebSocket Connections"| ASGI
    GUNICORN1 & GUNICORN2 --> DJ_CORE
    ASGI --> INVIG_SVC
    DJ_CORE --> REDIS
    DJ_CORE -->|"Write Queries"| PG_PRIMARY
    DJ_CORE -.->|"Read Replicas"| PG_REPLICA
    DJ_CORE -->|"Enqueue Execution Tasks"| REDIS
    REDIS --> CELERY
    CELERY --> DOCKER1 & DOCKER2
""",

    "03_deployment_lab_architecture.mmd": """flowchart TB
    subgraph CollegeLAN["College Computer Laboratory Local Area Network (192.168.1.0/24)"]
        SWITCH["Layer-2/3 Gigabit Managed Ethernet Switch (1000BASE-T)"]
        
        subgraph StudentWorkstations["50x Student Lab Workstations (DHCP: 192.168.1.50 - 192.168.1.100)"]
            PC1["Lab PC 01\\n(Chromium/Firefox)"]
            PC2["Lab PC 02\\n(Chromium/Firefox)"]
            PC_N["Lab PC 50\\n(Chromium/Firefox)"]
        end

        subgraph InvigilatorDesk["Invigilator & Placement Control Desk (192.168.1.10)"]
            INV_PC["Placement Officer Laptop\\n(Live Invigilation, Projector Output)"]
        end

        subgraph ServerHost["Local Host Server (Lab Head Machine / Mac Mini: 192.168.1.5:8000)"]
            HOST_OS["Host Operating System (macOS / Ubuntu Linux)"]
            PY_ENV[".venv Virtualenv (Python 3.13)"]
            DJ_INST["PyForgeLabs Django Core Instance\\n(Gunicorn / runserver)"]
            DB_FILE[("Local SQLite WAL File\\n(Fast NVMe / SSD Storage)")]
            WORKER_PROC["Background Worker Process\\n(run_execution_worker.py)"]
        end
    end

    PC1 & PC2 & PC_N -->|"Gigabit LAN Ethernet"| SWITCH
    INV_PC -->|"Ethernet / Wi-Fi"| SWITCH
    SWITCH -->|"HTTP Traffic (Port 8000)"| HOST_OS
    HOST_OS --> PY_ENV --> DJ_INST
    DJ_INST <--> DB_FILE
    WORKER_PROC <--> DB_FILE
    
    note["100% Offline Capability:\\nNo external internet connection required.\\nZero cloud API latency, resilient to ISP outage."]
""",

    "04_student_login_workflow.mmd": """sequenceDiagram
    autonumber
    actor Student
    participant Browser as Client Browser
    participant Server as Django Auth View
    participant DB as SQLite Database
    participant Session as Django Session Store

    Student->>Browser: Enters Roll Number / Email & Password
    Browser->>Server: POST /login/ (CSRF Token, Credentials)
    Server->>DB: Query Student(email/roll_number, password)
    alt Invalid Credentials
        Server-->>Browser: 200 OK (Render login with Error Alert)
        Browser-->>Student: Displays "Invalid Credentials"
    else Valid Credentials
        Server->>DB: Check Active Attempt for Student
        Server->>Session: Create Session (student_id, roll_number, auth_time)
        Server-->>Browser: 302 Redirect to /instructions/ (Set-Cookie sessionid, csrftoken)
        Browser->>Server: GET /instructions/
        Server->>DB: Query Exam Details, Section Sequence, Rules
        Server-->>Browser: 200 OK (Instructions Page)
        Student->>Browser: Clicks "I Agree & Start Examination"
        Browser->>Server: POST /start-exam/
        Server->>DB: Create Attempt(student, exam, start_time=now(), status='IN_PROGRESS')
        Server-->>Browser: 302 Redirect to /exam/
        Browser-->>Student: Exam Dashboard Active (Section 1 Begins)
    end
""",

    "05_exam_lifecycle_workflow.mmd": """stateDiagram-v2
    [*] --> Unauthenticated
    Unauthenticated --> Authenticated: Student Login
    Authenticated --> Instructions: View Rules & Code of Conduct
    Instructions --> InProgress: Start Exam (Attempt Created)
    
    state InProgress {
        [*] --> Section1_MCQ
        Section1_MCQ --> AutoSaveMCQ: Candidate selects option
        AutoSaveMCQ --> Section1_MCQ: DB confirms Answer saved
        Section1_MCQ --> Section2_Coding: Section 1 Time Expiry or Next
        
        Section2_Coding --> CodeDrafting: Typing in Monaco/Ace
        CodeDrafting --> AutoSaveDraft: 2s Debounce / Switch Language
        AutoSaveDraft --> Section2_Coding: Draft Saved in DB
        Section2_Coding --> CodeExecution: Click 'Run Code' (Sample Cases)
        CodeExecution --> Section2_Coding: Show Execution Results
        Section2_Coding --> FinalSubmission: Candidate Clicks 'Submit Exam'
    }

    FinalSubmission --> Completed: Modal Confirmation (status='COMPLETED')
    Completed --> Feedback: Post-Exam Survey (Optional)
    Feedback --> Done: Summary Screen (Score Locked)
    Done --> [*]
""",

    "06_mcq_answer_lifecycle.mmd": """sequenceDiagram
    autonumber
    actor Candidate
    participant UI as Exam UI (Vanilla JS)
    participant API as /api/save-answer/
    participant DB as Database (Answer Model)

    Candidate->>UI: Clicks Radio Button for Option B
    UI->>UI: Mark question palette item as "Answered" (Blue)
    UI->>UI: Prepare JSON payload {question_id: 101, option_id: 402}
    UI->>API: POST /api/save-answer/ (CSRF, JSON)
    activate API
    API->>API: Verify session & active Attempt status
    API->>API: Validate Question belongs to current Section
    API->>DB: Answer.objects.update_or_create(attempt, question, defaults={selected_option})
    activate DB
    DB-->>API: Row updated/created successfully
    deactivate DB
    API-->>UI: 200 OK {status: 'success', saved_at: '19:42:01'}
    deactivate API
    UI->>UI: Show unobtrusive green check indicator ("Saved")
""",

    "07_coding_question_lifecycle.mmd": """sequenceDiagram
    autonumber
    actor Candidate
    participant Editor as Code Editor (UI)
    participant View as Coding Question View
    participant DB as Database (CodeDraft & StarterCode)

    Candidate->>Editor: Navigates to Coding Question #1
    Editor->>View: GET /exam/question/12/
    View->>DB: Query CodeDraft(attempt, question, active_language)
    alt Draft Exists in DB
        DB-->>View: Returns saved code draft
    else No Prior Draft
        View->>DB: Query CodingQuestionStarterCode(question, active_language)
        DB-->>View: Returns template starter code
    end
    View-->>Editor: Render editor with code content
    
    Candidate->>Editor: Writes custom algorithm solution
    Editor->>Editor: Debounce Timer (2000ms idle)
    Editor->>View: POST /api/save-draft/ {question_id: 12, language: 'python', code: '...'}
    View->>DB: CodeDraft.objects.update_or_create(...)
    DB-->>View: Saved
    View-->>Editor: 200 OK {status: 'draft_saved'}

    opt Switch Language (e.g., Python to C++)
        Candidate->>Editor: Selects "C++" from dropdown
        Editor->>View: Save current Python draft
        Editor->>View: Request C++ draft or starter code
        View-->>Editor: Load C++ draft independently without data loss!
    end
""",

    "08_code_execution_judging.mmd": """flowchart TD
    START([Candidate Clicks 'Run' or 'Submit']) --> VALIDATE{Validate Request & Draft}
    VALIDATE -->|Empty Code| ERR_EMPTY[Return Error: Code cannot be empty]
    VALIDATE -->|Valid| CREATE_JOB[Create ExecutionJob in DB: Status 'PENDING']
    
    CREATE_JOB --> DISPATCH{Execution Mode}
    DISPATCH -->|Async Worker| QUEUE[Worker claims job: Status 'RUNNING']
    DISPATCH -->|Synchronous Fallback| RUNNER[Direct Sandbox Runner]
    
    QUEUE --> SETUP[Create Isolated /tmp/pyforgelabs_exec_* directory]
    RUNNER --> SETUP
    
    SETUP --> LANG{Target Language}
    
    LANG -->|C / C++| COMPILE[Compile with gcc/g++ -O2 -Wall]
    COMPILE -->|Compile Error| CE_FAIL[Status: COMPILE_ERROR<br/>Store compiler stderr]
    COMPILE -->|Success| EXEC_LOOP
    
    LANG -->|Python 3| EXEC_LOOP[Initialize Test Case Iteration]
    
    EXEC_LOOP --> TEST_CASE[Fetch TestCase: input_data & expected_output]
    TEST_CASE --> RUN_SANDBOX[Execute under Subprocess Sandbox:<br/>- RLIMIT_CPU: 2s<br/>- RLIMIT_AS: 128MB<br/>- stdin piped, stdout captured]
    
    RUN_SANDBOX --> OUT_CHECK{Outcome}
    OUT_CHECK -->|Timeout| TLE[Status: TIME_LIMIT_EXCEEDED]
    OUT_CHECK -->|Non-Zero Exit| RE[Status: RUNTIME_ERROR]
    OUT_CHECK -->|Zero Exit| DIFF{Compare Output with Expected}
    
    DIFF -->|Mismatch| WA[Status: WRONG_ANSWER]
    DIFF -->|Exact / Normalized Match| PASS[Status: PASSED]
    
    PASS & WA & TLE & RE --> MORE_TESTS{More Test Cases?}
    MORE_TESTS -->|Yes| TEST_CASE
    MORE_TESTS -->|No| AGGREGATE[Compute Total Score & Points]
    
    AGGREGATE --> PERSIST[Create CodeSubmission Record in DB]
    CE_FAIL --> PERSIST
    PERSIST --> CLEANUP[Remove /tmp scratch folder]
    CLEANUP --> RESP[Return JSON breakdown to UI]
""",

    "09_recruitment_progression.mmd": """stateDiagram-v2
    [*] --> DriveCreated: Admin sets up Recruitment Drive
    DriveCreated --> Round1_OA: Candidates Enrolled (Status: REGISTERED)
    
    state Round1_OA {
        [*] --> CBT_Exam: Online Assessment (MCQ + Coding)
        CBT_Exam --> AutomatedGrading: Exam Finalized
        AutomatedGrading --> CutoffEvaluation: Progression Engine runs
    }

    Round1_OA --> Round2_Tech: Score >= Cutoff (Decision: ADVANCE)
    Round1_OA --> Rejected_R1: Score < Cutoff (Decision: FAIL)
    
    state Round2_Tech {
        [*] --> AssignInterviewer: Assign Candidate to Technical Panel
        AssignInterviewer --> LiveInterview: Conduct Technical Interview
        LiveInterview --> RubricScore: Panel submits Rubric Evaluation
    }

    Round2_Tech --> Round3_HR: Panel Recommends (Decision: ADVANCE)
    Round2_Tech --> Rejected_R2: Panel Rejects (Decision: FAIL)
    
    state Round3_HR {
        [*] --> HR_Evaluation: Behavioral & Fit Assessment
        HR_Evaluation --> FinalDecision: Placement Committee Review
    }

    Round3_HR --> Offered: Decision: SELECTED (Offer Letter Issued)
    Round3_HR --> Rejected_R3: Decision: FAIL
    
    Offered --> [*]
    Rejected_R1 --> [*]
    Rejected_R2 --> [*]
    Rejected_R3 --> [*]
""",

    "10_live_invigilator_monitoring.mmd": """sequenceDiagram
    autonumber
    actor Candidate
    participant Browser as Student Browser
    participant API as /api/recruitment/telemetry/
    participant DB as SQLite DB
    participant Invig as Invigilator Console (Admin)

    loop Every 15 Seconds
        Browser->>API: POST /presence/ (heartbeat, section, focused: true)
        API->>DB: Update CandidatePresence(last_heartbeat=now())
    end

    opt Violation Occurs (Candidate switches tab or un-fullscreens)
        Candidate->>Browser: Tab switch away to search engine
        Browser->>Browser: Page Visibility API triggers `visibilitychange`
        Browser->>Browser: Render on-screen warning modal: "Warning! Tab change detected!"
        Browser->>API: POST /integrity-event/ (type='TAB_SWITCH', details='blur event')
        API->>DB: IntegrityEvent.objects.create(enrollment, 'TAB_SWITCH')
        API->>DB: CandidatePresence.violation_count += 1
    end

    loop Every 5 Seconds (Invigilator Live View)
        Invig->>API: GET /admin/recruitment/live-feed/
        API->>DB: Query active CandidatePresence & recent IntegrityEvents
        DB-->>API: Candidate records with status & violation tallies
        API-->>Invig: JSON live roster update
        alt Candidate Violations >= 3
            Invig->>Invig: Highlight Candidate card in RED (Audible Alert)
            Invig->>API: POST /admin/recruitment/warn-or-terminate/ (action='TERMINATE')
            API->>DB: Update Attempt status='TERMINATED'
        end
    end
""",

    "11_admin_operations.mmd": """flowchart LR
    subgraph AdminDashboard["Admin Console & Essential Navigation"]
        NAV["Modern Compact Sidebar"]
        DASH["Overview & System Health"]
    end

    subgraph ExamOps["Exam Operations"]
        EX_CONF["Create / Configure Exam"]
        SEC_CONF["Section & Timer Setup"]
        Q_IMPORT["Bulk Import MCQs (CSV/JSON)"]
        COD_CONF["Coding Problems & Test Cases"]
    end

    subgraph DriveOps["Recruitment Operations"]
        DRIVE_SETUP["Create Drive (Company, Role)"]
        ROSTER["Candidate Roster & Bulk Upload"]
        ROUND_CONF["Multi-Round Pipeline Config"]
        RUBRICS["Rubrics & Interview Panels"]
    end

    subgraph LiveOps["Live Operations & Monitoring"]
        MONITOR["Live Invigilator Grid"]
        ALERTS["Integrity Event Feed"]
        ACTIONS["Intervention: Warn / Terminate"]
    end

    subgraph AnalyticsOps["Results & Compliance"]
        PROG_RUN["Run Progression Cutoffs"]
        EXP_CSV["Export Results (CSV / Excel)"]
        AUDIT["Immutable Audit Log Review"]
    end

    NAV --> DASH
    NAV --> ExamOps
    NAV --> DriveOps
    NAV --> LiveOps
    NAV --> AnalyticsOps
""",

    "12_database_erd.mmd": """erDiagram
    Student ||--o{ Attempt : "starts"
    Student ||--o{ CandidateEnrollment : "enrolled in"
    
    Exam ||--o{ Section : "contains"
    Exam ||--o{ Attempt : "attempted via"
    Exam ||--o{ Round : "linked to"
    
    Section ||--o{ Question : "groups"
    Question ||--o{ Option : "has"
    
    Attempt ||--o{ Answer : "records"
    Option ||--o{ Answer : "selected in"
    Question ||--o{ Answer : "for question"
    Attempt ||--o| Feedback : "receives"
    
    CodingQuestion ||--o{ CodingQuestionStarterCode : "provides"
    CodingQuestion ||--o{ TestCase : "evaluated against"
    CodingQuestion ||--o{ CodeDraft : "drafted for"
    CodingQuestion ||--o{ CodeSubmission : "submitted for"
    
    Attempt ||--o{ CodeDraft : "holds"
    Attempt ||--o{ CodeSubmission : "contains"
    CodeSubmission ||--o| ExecutionJob : "triggers"
    
    RecruitmentDrive ||--o{ Round : "structures"
    RecruitmentDrive ||--o{ CandidateEnrollment : "enrolls"
    
    CandidateEnrollment ||--o{ RoundResult : "produces"
    CandidateEnrollment ||--o| CandidatePresence : "monitored by"
    CandidateEnrollment ||--o{ IntegrityEvent : "flags"
    CandidateEnrollment ||--o{ InterviewAssignment : "assigned to"
    
    Round ||--o{ RoundResult : "evaluates"
    Round ||--o{ InterviewAssignment : "conducts"
    
    InterviewTemplate ||--o{ RubricCriterion : "defines"
    InterviewAssignment ||--o| InterviewEvaluation : "produces"
    InterviewTemplate ||--o{ InterviewEvaluation : "grades with"
""",

    "13_security_authorization_boundaries.mmd": """flowchart TD
    subgraph UntrustedZone["Untrusted Network Zone"]
        CLIENT["Candidate Browser / Potential Adversary"]
    end

    subgraph EdgeBoundary["Edge Security Boundary"]
        FIREWALL["Local Subnet Firewall / Router (No WAN Access)"]
        CSRF_CHECK["Django CSRF Protection Middleware"]
        AUTH_GUARD["Authentication & Session Validation"]
    end

    subgraph AppBoundary["Application Authorization Boundary"]
        ROLE_CHECK{User Role?}
        STUDENT_SCOPE["Student Scope: Only Own Attempt & Active Section"]
        STAFF_SCOPE["Staff Scope: Live Invigilation & Scoring"]
        SUPER_SCOPE["Admin Scope: System Config & Audit Trail"]
    end

    subgraph ExecutionSandbox["Isolated Code Execution Boundary"]
        TEMP_DIR["Chrooted / Isolated Scratch Dir (/tmp)"]
        RLIMIT["OS Resource Limits (RLIMIT_CPU, RLIMIT_AS, RLIMIT_FSIZE)"]
        SEC_EXEC["Non-Privileged Subprocess Runner (No Network, Timeout Kill)"]
    end

    subgraph DBBoundary["Persistence Boundary"]
        ACID_DB[("SQLite Database (WAL Mode, Parameterized SQL Queries)")]
    end

    CLIENT --> FIREWALL --> CSRF_CHECK --> AUTH_GUARD
    AUTH_GUARD --> ROLE_CHECK
    
    ROLE_CHECK -->|Student| STUDENT_SCOPE
    ROLE_CHECK -->|Staff| STAFF_SCOPE
    ROLE_CHECK -->|Superuser| SUPER_SCOPE
    
    STUDENT_SCOPE -->|"Submit Code"| TEMP_DIR --> RLIMIT --> SEC_EXEC
    STUDENT_SCOPE & STAFF_SCOPE & SUPER_SCOPE --> ACID_DB
""",

    "14_error_handling_recovery.mmd": """flowchart TD
    START([System Anomaly / Error Event]) --> DETECT{Error Type}

    DETECT -->|Client Browser Crash / Refresh| CRASH_FLOW[Student reopens browser & logs in]
    CRASH_FLOW --> RESTORE[Restore active Attempt & timer from DB.<br/>Answers & drafts preserved.]

    DETECT -->|Network Drop / LAN Glitch| NET_FLOW[Client AJAX autosave fails]
    NET_FLOW --> RETRY_Q[Client local queue retries with exponential backoff.<br/>UI shows Amber 'Reconnecting' status.]

    DETECT -->|Stale CSRF Token on Back Navigation| CSRF_FLOW[POST rejected with 403 CSRF]
    CSRF_FLOW --> CSRF_HANDLER[Custom CSRF failure view / pageshow auto-refresh.<br/>Student clicks 'Continue' without session loss.]

    DETECT -->|Code Execution Timeout / Infinite Loop| TLE_FLOW[Subprocess exceeds 2000ms CPU limit]
    TLE_FLOW --> KILL_SIG[SIGKILL dispatched to process group.<br/>Status set to 'TIME_LIMIT_EXCEEDED'. Worker freed.]

    DETECT -->|Database Lock / Concurrency Surge| LOCK_FLOW[Multiple simultaneous writes]
    LOCK_FLOW --> WAL_RETRY[WAL mode + busy_timeout=15000.<br/>Query retries automatically without throwing SQLiteBusy.]

    RESTORE & RETRY_Q & CSRF_HANDLER & KILL_SIG & WAL_RETRY --> RESUME([Normal Operation Resumed])
"""
}

# -----------------------------------------------------------------------------
# VECTOR SVG BUILDER (Clean, professional, styled SVGs)
# -----------------------------------------------------------------------------

def create_svg_card(x, y, w, h, title, subtitle, fill="#ffffff", stroke="#cbd5e1", title_color="#0f172a", text_color="#64748b"):
    return f"""
    <g transform="translate({x},{y})">
        <rect width="{w}" height="{h}" rx="8" fill="{fill}" stroke="{stroke}" stroke-width="1.5" filter="url(#shadow)"/>
        <text x="16" y="24" font-family="-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif" font-size="13" font-weight="700" fill="{title_color}">{title}</text>
        <text x="16" y="42" font-family="-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif" font-size="11" fill="{text_color}">{subtitle}</text>
    </g>"""

def create_arrow(x1, y1, x2, y2, label=""):
    lbl_xml = ""
    if label:
        mx = (x1 + x2) / 2
        my = (y1 + y2) / 2 - 6
        lbl_xml = f'<text x="{mx}" y="{my}" font-family="-apple-system,sans-serif" font-size="10" fill="#64748b" text-anchor="middle" background="#ffffff">{label}</text>'
    return f"""
    <path d="M {x1} {y1} L {x2} {y2}" stroke="#64748b" stroke-width="1.5" stroke-dasharray="0" marker-end="url(#arrow)"/>
    {lbl_xml}"""

def generate_svg_file(filename, width, height, title, subtitle, content_xml):
    svg = f"""<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" width="{width}" height="{height}">
    <defs>
        <filter id="shadow" x="-5%" y="-5%" width="110%" height="110%" filterUnits="userSpaceOnUse">
            <feDropShadow dx="0" dy="2" stdDeviation="3" flood-opacity="0.08"/>
        </filter>
        <marker id="arrow" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse">
            <path d="M 0 1.5 L 8 5 L 0 8.5 z" fill="#64748b"/>
        </marker>
        <linearGradient id="headerGrad" x1="0%" y1="0%" x2="100%" y2="100%">
            <stop offset="0%" stop-color="#1e293b"/>
            <stop offset="100%" stop-color="#0f172a"/>
        </linearGradient>
    </defs>
    
    <!-- Background -->
    <rect width="{width}" height="{height}" fill="#f8fafc"/>
    
    <!-- Header Banner -->
    <rect width="{width}" height="70" fill="url(#headerGrad)"/>
    <text x="30" y="32" font-family="-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif" font-size="18" font-weight="800" fill="#38bdf8">PYFORGELABS ARCHITECTURE &amp; WORKFLOWS</text>
    <text x="30" y="52" font-family="-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif" font-size="13" font-weight="600" fill="#ffffff">{title} &mdash; <tspan fill="#94a3b8">{subtitle}</tspan></text>
    
    <!-- Content Body -->
    <g transform="translate(0, 80)">
        {content_xml}
    </g>
</svg>"""
    return svg

def build_all_svgs():
    # 01 Current Architecture
    svg1_body = f"""
    <!-- Layer Boxes -->
    <rect x="30" y="10" width="840" height="90" rx="10" fill="#e0f2fe" stroke="#38bdf8" stroke-width="1.5"/>
    <text x="50" y="30" font-family="sans-serif" font-size="12" font-weight="700" fill="#0369a1">CLIENT TIER (Lab Workstations &amp; Admin)</text>
    {create_svg_card(50, 40, 240, 50, "Student Examination UI", "Vanilla JS, Autosave, Monaco")}
    {create_svg_card(320, 40, 250, 50, "Invigilator Console", "Telemetry, Presence, Real-time Alerts")}
    {create_svg_card(600, 40, 250, 50, "Admin &amp; Interview Portal", "Rubric Evaluation &amp; Drive Setup")}

    <!-- Arrows to Django -->
    {create_arrow(170, 100, 250, 130, "HTTP / CSRF")}
    {create_arrow(445, 100, 445, 130, "Heartbeat Polling")}
    {create_arrow(725, 100, 640, 130, "Rubric POST")}

    <!-- Django Core -->
    <rect x="30" y="130" width="840" height="200" rx="10" fill="#f1f5f9" stroke="#94a3b8" stroke-width="1.5"/>
    <text x="50" y="150" font-family="sans-serif" font-size="12" font-weight="700" fill="#334155">APPLICATION TIER (Django 6.1.2 / Python 3.13)</text>
    {create_svg_card(50, 165, 360, 60, "portal Application", "MCQ Engine, Autosave Views, Drafts, Sandbox Runner")}
    {create_svg_card(450, 165, 400, 60, "recruitment Application", "Drives, Multi-Round Progression, Presence, Rubric Evaluations")}
    {create_svg_card(50, 245, 360, 65, "Execution Queue &amp; Sandbox", "portal.runner, Resource Limits, Compile/Judge")}
    {create_svg_card(450, 245, 400, 65, "Analytics &amp; Audit Engine", "recruitment.progression, retention &amp; audit logging")}

    <!-- Arrows to Storage -->
    {create_arrow(230, 330, 230, 360, "Job Claim")}
    {create_arrow(650, 330, 650, 360, "SQL ACID Read/Write")}

    <!-- Persistence Tier -->
    <rect x="30" y="360" width="840" height="110" rx="10" fill="#fef3c7" stroke="#f59e0b" stroke-width="1.5"/>
    <text x="50" y="380" font-family="sans-serif" font-size="12" font-weight="700" fill="#b45309">PERSISTENCE &amp; OS EXECUTION TIER</text>
    {create_svg_card(50, 395, 360, 60, "SQLite 3 Database (WAL Mode)", "busy_timeout=15000, 19 Relations, ACID")}
    {create_svg_card(450, 395, 400, 60, "Sandboxed Subprocess Runner", "/tmp scratch, RLIMIT_CPU, Timeout Kill, gcc/python3")}
    """
    svg1 = generate_svg_file("01_current_architecture.svg", 900, 580, "Diagram 1: Current System Architecture", "Component &amp; Process Topology", svg1_body)

    # 02 Target Architecture
    svg2_body = f"""
    <rect x="30" y="10" width="840" height="80" rx="10" fill="#e0f2fe" stroke="#38bdf8" stroke-width="1.5"/>
    <text x="50" y="30" font-family="sans-serif" font-size="12" font-weight="700" fill="#0369a1">EDGE INGRESS &amp; LOAD BALANCING</text>
    {create_svg_card(50, 40, 380, 40, "Nginx Reverse Proxy / SSL Termination", "Rate Limiting, Static Asset Caching")}
    {create_svg_card(470, 40, 380, 40, "Daphne ASGI WebSockets Gateway", "Real-Time Telemetry &amp; Alerts")}

    {create_arrow(240, 90, 240, 120, "")}
    {create_arrow(660, 90, 660, 120, "")}

    <rect x="30" y="120" width="840" height="120" rx="10" fill="#f1f5f9" stroke="#94a3b8" stroke-width="1.5"/>
    <text x="50" y="140" font-family="sans-serif" font-size="12" font-weight="700" fill="#334155">APPLICATION CLUSTER &amp; IN-MEMORY CACHE</text>
    {create_svg_card(50, 150, 250, 70, "Gunicorn Instance 1", "Django 6.1.2 Workers")}
    {create_svg_card(320, 150, 250, 70, "Gunicorn Instance 2", "Django 6.1.2 Workers")}
    {create_svg_card(590, 150, 260, 70, "Redis 7.x Broker &amp; Cache", "Celery Queue, Channels, Sessions")}

    {create_arrow(175, 240, 175, 270, "")}
    {create_arrow(720, 240, 720, 270, "")}

    <rect x="30" y="270" width="840" height="140" rx="10" fill="#dcfce7" stroke="#22c55e" stroke-width="1.5"/>
    <text x="50" y="290" font-family="sans-serif" font-size="12" font-weight="700" fill="#15803d">CONTAINERIZED RUNNERS &amp; CLUSTERED STORAGE</text>
    {create_svg_card(50, 305, 360, 85, "PostgreSQL 16 Primary + Read Replica", "PgBouncer Connection Pooler, WAL")}
    {create_svg_card(450, 305, 400, 85, "Distributed Celery Workers &amp; nsjail", "Isolated Linux cgroups, no network, 128MB")}
    """
    svg2 = generate_svg_file("02_target_architecture.svg", 900, 520, "Diagram 2: Target-State Production Architecture", "High-Availability, Caching &amp; Containerization", svg2_body)

    # 03 Deployment Lab Architecture
    svg3_body = f"""
    <rect x="30" y="10" width="840" height="150" rx="10" fill="#f8fafc" stroke="#64748b" stroke-width="1.5"/>
    <text x="50" y="30" font-family="sans-serif" font-size="12" font-weight="700" fill="#0f172a">COLLEGE COMPUTER LAB (Offline LAN 192.168.1.0/24)</text>
    {create_svg_card(50, 45, 145, 95, "Lab PC 01", "IP: 192.168.1.51\\nCandidate 1")}
    {create_svg_card(210, 45, 145, 95, "Lab PC 02", "IP: 192.168.1.52\\nCandidate 2")}
    {create_svg_card(370, 45, 145, 95, "Lab PC 03...49", "IP: 192.168.1.53..99\\nCandidates")}
    {create_svg_card(530, 45, 145, 95, "Lab PC 50", "IP: 192.168.1.100\\nCandidate 50")}
    {create_svg_card(690, 45, 160, 95, "Invigilator PC", "IP: 192.168.1.10\\nDashboard / Screen")}

    {create_arrow(450, 160, 450, 190, "Gigabit Ethernet (Cat6 / 1000BASE-T Switch)")}

    <rect x="30" y="190" width="840" height="150" rx="10" fill="#ede9fe" stroke="#8b5cf6" stroke-width="1.5"/>
    <text x="50" y="210" font-family="sans-serif" font-size="12" font-weight="700" fill="#5b21b6">LOCAL HOST SERVER (Mac / Linux Lab Master: 192.168.1.5:8000)</text>
    {create_svg_card(50, 230, 250, 85, "Django 6.1.2 Web Server", "Gunicorn / runserver\\nBound to 0.0.0.0:8000")}
    {create_svg_card(320, 230, 250, 85, "Background Worker", "run_execution_worker.py\\nQueue Polling &amp; Judging")}
    {create_svg_card(590, 230, 260, 85, "SQLite 3 WAL Database", "db.sqlite3 on Fast NVMe\\n15s lock timeout")}
    """
    svg3 = generate_svg_file("03_deployment_lab_architecture.svg", 900, 450, "Diagram 3: 50-Candidate LAN Lab Deployment", "Offline Campus Network Topology", svg3_body)

    # 04 Student Login Workflow
    svg4_body = f"""
    <rect x="30" y="10" width="840" height="340" rx="10" fill="#ffffff" stroke="#cbd5e1" stroke-width="1.5"/>
    {create_svg_card(50, 30, 220, 70, "1. Login Request", "Roll No / Email + Password\\nPOST /login/ with CSRF")}
    {create_arrow(270, 65, 330, 65, "Verify")}
    {create_svg_card(330, 30, 240, 70, "2. Authentication &amp; Validation", "Query Student &amp; Password\\nCheck active Session")}
    {create_arrow(570, 65, 630, 65, "Valid")}
    {create_svg_card(630, 30, 220, 70, "3. Session Established", "Set-Cookie sessionid\\nRedirect /instructions/")}

    {create_arrow(740, 100, 740, 140, "Read Rules")}

    {create_svg_card(630, 140, 220, 70, "4. Instructions Page", "Display Exam Duration, Sections,\\nConduct Guidelines")}
    {create_arrow(630, 175, 450, 175, "Click 'Start Exam'")}
    {create_svg_card(210, 140, 240, 70, "5. Create Attempt Record", "Attempt(student, exam,\\nstart_time=now(), status='IN_PROGRESS')")}
    {create_arrow(210, 175, 120, 175, "Redirect")}
    {create_svg_card(50, 250, 300, 70, "6. Active Exam Workspace", "Section 1 Loaded (Timer running, Autosave active)")}
    """
    svg4 = generate_svg_file("04_student_login_workflow.svg", 900, 450, "Diagram 4: Student Authentication &amp; Session Flow", "Login, Validation &amp; Exam Initialization", svg4_body)

    # 05 Examination Lifecycle
    svg5_body = f"""
    <rect x="30" y="10" width="840" height="260" rx="10" fill="#ffffff" stroke="#cbd5e1" stroke-width="1.5"/>
    {create_svg_card(50, 30, 160, 60, "1. LOGIN", "Auth &amp; Session Created")}
    {create_arrow(210, 60, 250, 60, "")}
    {create_svg_card(250, 30, 170, 60, "2. INSTRUCTIONS", "Rules Accepted")}
    {create_arrow(420, 60, 460, 60, "")}
    {create_svg_card(460, 30, 180, 60, "3. SECTION 1: MCQ", "Aptitude / Technical (Autosave)")}
    {create_arrow(640, 60, 680, 60, "Next / Timer")}
    {create_svg_card(680, 30, 170, 60, "4. SECTION 2: CODE", "Language Choice &amp; Drafts")}

    {create_arrow(765, 90, 765, 140, "Submit")}

    {create_svg_card(680, 140, 170, 60, "5. CONFIRM MODAL", "Attempt: COMPLETED")}
    {create_arrow(680, 170, 460, 170, "")}
    {create_svg_card(280, 140, 180, 60, "6. FEEDBACK SURVEY", "Rating &amp; Suggestions")}
    {create_arrow(280, 170, 200, 170, "")}
    {create_svg_card(50, 140, 150, 60, "7. DONE", "Exam Locked &amp; Logged")}
    """
    svg5 = generate_svg_file("05_exam_lifecycle_workflow.svg", 900, 370, "Diagram 5: Full Examination Lifecycle", "Multi-Section Student Assessment State Progression", svg5_body)

    # 06 MCQ Answer Lifecycle
    svg6_body = f"""
    <rect x="30" y="10" width="840" height="200" rx="10" fill="#ffffff" stroke="#cbd5e1" stroke-width="1.5"/>
    {create_svg_card(50, 40, 220, 70, "Candidate Selects Option", "UI marks palette item BLUE\\nTriggers change event")}
    {create_arrow(270, 75, 330, 75, "AJAX POST JSON")}
    {create_svg_card(330, 40, 240, 70, "/api/save-answer/ View", "Validates attempt ownership,\\nsection timing &amp; active state")}
    {create_arrow(570, 75, 630, 75, "Atomic Write")}
    {create_svg_card(630, 40, 220, 70, "DB: Answer Table", "update_or_create(attempt, question)\\nReturns 200 OK + Timestamp")}
    """
    svg6 = generate_svg_file("06_mcq_answer_lifecycle.svg", 900, 310, "Diagram 6: MCQ Answer Lifecycle &amp; Autosave", "Immediate Persistence &amp; Palette State Feedback", svg6_body)

    # 07 Coding Question Lifecycle
    svg7_body = f"""
    <rect x="30" y="10" width="840" height="280" rx="10" fill="#ffffff" stroke="#cbd5e1" stroke-width="1.5"/>
    {create_svg_card(50, 30, 220, 80, "Select Question &amp; Language", "Dropdown: Python, C, C++\\nFetches CodeDraft or StarterCode")}
    {create_arrow(270, 70, 330, 70, "Load Editor")}
    {create_svg_card(330, 30, 240, 80, "Code Editing in Browser", "Monaco / Ace Editor\\nDebounced 2s autosave listener")}
    {create_arrow(570, 70, 630, 70, "Autosave POST")}
    {create_svg_card(630, 30, 220, 80, "DB: CodeDraft", "Saved per (attempt, question, lang)\\nLanguage drafts kept isolated")}

    {create_arrow(450, 110, 450, 160, "Click 'Run' or 'Submit'")}

    {create_svg_card(330, 160, 240, 80, "Judging Engine Execution", "Sample vs Hidden Test Cases\\nReturns status &amp; diff output")}
    """
    svg7 = generate_svg_file("07_coding_question_lifecycle.svg", 900, 390, "Diagram 7: Coding Question &amp; Independent Drafts", "Language-Aware Starter Code &amp; Dual Action Workflow", svg7_body)

    # 08 Code Execution & Judging
    svg8_body = f"""
    <rect x="30" y="10" width="840" height="320" rx="10" fill="#ffffff" stroke="#cbd5e1" stroke-width="1.5"/>
    {create_svg_card(50, 30, 200, 65, "1. Code Submitted", "Run Sample or Full Grade")}
    {create_arrow(250, 62, 300, 62, "")}
    {create_svg_card(300, 30, 250, 65, "2. ExecutionJob Queued", "DB Record status='PENDING'")}
    {create_arrow(550, 62, 600, 62, "")}
    {create_svg_card(600, 30, 240, 65, "3. Worker Claims Job", "Atomic SELECT FOR UPDATE")}

    {create_arrow(720, 95, 720, 130, "")}

    {create_svg_card(600, 130, 240, 70, "4. Sandboxed Execution", "Resource Limits: 2s CPU, 128MB\\nCompile C/C++ or run Python3")}
    {create_arrow(600, 165, 550, 165, "")}
    {create_svg_card(300, 130, 250, 70, "5. Test Case Comparison", "Compare stdout vs expected_output\\nPoints, TLE, RE, WA, AC")}
    {create_arrow(300, 165, 250, 165, "")}
    {create_svg_card(50, 130, 200, 70, "6. CodeSubmission Stored", "Final Score &amp; Results to UI")}
    """
    svg8 = generate_svg_file("08_code_execution_judging.svg", 900, 430, "Diagram 8: Code Execution &amp; Judging Engine", "Queue Dispatch, Subprocess Isolation &amp; Verification", svg8_body)

    # 09 Recruitment Progression
    svg9_body = f"""
    <rect x="30" y="10" width="840" height="240" rx="10" fill="#ffffff" stroke="#cbd5e1" stroke-width="1.5"/>
    {create_svg_card(50, 30, 170, 70, "Drive Created", "Company, Role, Dates\\nStatus: ACTIVE")}
    {create_arrow(220, 65, 260, 65, "")}
    {create_svg_card(260, 30, 170, 70, "Round 1: CBT / OA", "Aptitude MCQ + Coding\\nCutoff Evaluated")}
    {create_arrow(430, 65, 470, 65, "Advance")}
    {create_svg_card(470, 30, 180, 70, "Round 2: Technical", "Interviewer Assigned\\nRubric Scoring Panel")}
    {create_arrow(650, 65, 690, 65, "Advance")}
    {create_svg_card(690, 30, 160, 70, "Round 3: HR / Fit", "Behavioral Evaluation\\nOffer Letter Issued")}

    {create_arrow(345, 100, 345, 140, "Fail")}
    {create_svg_card(260, 140, 170, 50, "Rejected Round 1", "Status: FAILED", "#fee2e2", "#ef4444", "#991b1b")}
    {create_arrow(560, 100, 560, 140, "Fail")}
    {create_svg_card(470, 140, 180, 50, "Rejected Round 2", "Status: FAILED", "#fee2e2", "#ef4444", "#991b1b")}
    """
    svg9 = generate_svg_file("09_recruitment_progression.svg", 900, 350, "Diagram 9: Multi-Round Recruitment Pipeline", "Candidate Enrollment, Cutoff Decisions &amp; Promotion", svg9_body)

    # 10 Live Invigilator Monitoring
    svg10_body = f"""
    <rect x="30" y="10" width="840" height="260" rx="10" fill="#ffffff" stroke="#cbd5e1" stroke-width="1.5"/>
    {create_svg_card(50, 30, 230, 75, "Student Client Telemetry", "15s Heartbeat to /presence/\\nPage Visibility &amp; Blur listeners")}
    {create_arrow(280, 67, 340, 67, "Tab Switch / Exit Fullscreen")}
    {create_svg_card(340, 30, 240, 75, "Integrity Event Engine", "Logs IntegrityEvent record\\nIncrements violation count")}
    {create_arrow(580, 67, 640, 67, "Poll Live Grid")}
    {create_svg_card(640, 30, 220, 75, "Invigilator Console", "Real-time Candidate Status Grid\\nGreen / Amber / Red Cards")}

    {create_arrow(750, 105, 750, 150, "Violations &gt;= 3")}
    {create_svg_card(640, 150, 220, 65, "Remote Intervention", "Issue Alert or Terminate Attempt", "#fee2e2", "#ef4444", "#991b1b")}
    """
    svg10 = generate_svg_file("10_live_invigilator_monitoring.svg", 900, 370, "Diagram 10: Live Invigilator &amp; Telemetry Feed", "Real-time Anti-Cheat, Presence &amp; Admin Interventions", svg10_body)

    # 11 Admin Operations
    svg11_body = f"""
    <rect x="30" y="10" width="840" height="250" rx="10" fill="#ffffff" stroke="#cbd5e1" stroke-width="1.5"/>
    {create_svg_card(50, 30, 180, 65, "Exam Management", "Create exams, sections, MCQs &amp; coding questions")}
    {create_svg_card(250, 30, 180, 65, "Student Management", "Bulk CSV enrollment, roll numbers, credentials")}
    {create_svg_card(450, 30, 180, 65, "Recruitment Pipeline", "Configure drives, rounds, rubrics &amp; panels")}
    {create_svg_card(650, 30, 180, 65, "Live Invigilation", "Real-time presence monitoring &amp; remote termination")}

    {create_svg_card(50, 120, 180, 65, "Results &amp; Analytics", "Cutoffs, rank lists, candidate scorecards")}
    {create_svg_card(250, 120, 180, 65, "Data Export", "Instant CSV / Excel result export")}
    {create_svg_card(450, 120, 180, 65, "Audit Logs", "Immutable audit trail of all actions")}
    {create_svg_card(650, 120, 180, 65, "System Health", "Database status, latency metrics &amp; queue depth")}
    """
    svg11 = generate_svg_file("11_admin_operations.svg", 900, 360, "Diagram 11: Unified Administrative Operations", "Workflows for Placement Officers &amp; System Administrators", svg11_body)

    # 12 Database ERD
    svg12_body = f"""
    <rect x="30" y="10" width="840" height="340" rx="10" fill="#ffffff" stroke="#cbd5e1" stroke-width="1.5"/>
    {create_svg_card(50, 30, 170, 75, "Student", "roll_number, name, email,\\ndepartment, year, is_active")}
    {create_arrow(220, 67, 260, 67, "1:N")}
    {create_svg_card(260, 30, 170, 75, "Attempt", "student_id, exam_id, score,\\nstatus, start_time, end_time")}
    {create_arrow(430, 67, 470, 67, "1:N")}
    {create_svg_card(470, 30, 170, 75, "Answer", "attempt_id, question_id,\\nselected_option_id, is_correct")}
    {create_arrow(640, 67, 680, 67, "1:N")}
    {create_svg_card(680, 30, 170, 75, "Question &amp; Option", "section_id, text, marks,\\noptions (text, is_correct)")}

    {create_arrow(345, 105, 345, 140, "1:N")}
    {create_svg_card(260, 140, 170, 75, "CodeDraft", "attempt_id, question_id,\\nlanguage, code, updated_at")}
    {create_arrow(430, 177, 470, 177, "1:N")}
    {create_svg_card(470, 140, 170, 75, "CodeSubmission", "attempt_id, question_id, code,\\nstatus, score, execution_time")}
    {create_arrow(640, 177, 680, 177, "1:N")}
    {create_svg_card(680, 140, 170, 75, "CodingQuestion", "title, statement, constraints,\\ntest_cases, starter_code")}

    {create_arrow(135, 105, 135, 240, "1:N")}
    {create_svg_card(50, 240, 170, 75, "CandidateEnrollment", "drive_id, student_id,\\ncurrent_round_id, status")}
    {create_arrow(220, 277, 260, 277, "1:1")}
    {create_svg_card(260, 240, 170, 75, "CandidatePresence", "enrollment_id, last_heartbeat,\\nis_focused, violation_count")}
    {create_arrow(430, 277, 470, 277, "1:N")}
    {create_svg_card(470, 240, 170, 75, "RoundResult", "enrollment_id, round_id,\\nscore, decision, evaluated_by")}
    {create_arrow(640, 277, 680, 277, "1:N")}
    {create_svg_card(680, 240, 170, 75, "RecruitmentDrive", "title, company_name, date,\\nrounds, rubrics, status")}
    """
    svg12 = generate_svg_file("12_database_erd.svg", 900, 450, "Diagram 12: Database Entity-Relationship Model", "19 Core Relations across portal and recruitment Apps", svg12_body)

    # 13 Security Boundaries
    svg13_body = f"""
    <rect x="30" y="10" width="840" height="260" rx="10" fill="#ffffff" stroke="#cbd5e1" stroke-width="1.5"/>
    {create_svg_card(50, 30, 240, 75, "1. Edge Network Boundary", "Offline Local Subnet Firewall\\nNo WAN egress, DNS isolated")}
    {create_arrow(290, 67, 340, 67, "")}
    {create_svg_card(340, 30, 240, 75, "2. Application Auth Boundary", "CSRF Middleware, Session Verification,\\nStrict Role Isolation (Student/Admin)")}
    {create_arrow(580, 67, 630, 67, "")}
    {create_svg_card(630, 30, 230, 75, "3. Execution Sandbox", "Non-privileged subprocess\\nRLIMIT_CPU, RLIMIT_AS, Timeout")}

    {create_arrow(460, 105, 460, 145, "")}
    {create_svg_card(340, 145, 240, 75, "4. Database Boundary", "Parameterized SQL queries (No SQLi)\\nWAL concurrency lock protection")}
    """
    svg13 = generate_svg_file("13_security_authorization_boundaries.svg", 900, 370, "Diagram 13: Security &amp; Authorization Boundaries", "Defense-in-Depth for Multi-Tenant College Examination", svg13_body)

    # 14 Error Handling & Recovery
    svg14_body = f"""
    <rect x="30" y="10" width="840" height="260" rx="10" fill="#ffffff" stroke="#cbd5e1" stroke-width="1.5"/>
    {create_svg_card(50, 30, 240, 70, "Lab Power Cut / PC Reboot", "Session restored upon re-login.\\nAnswers &amp; drafts intact in DB.")}
    {create_svg_card(320, 30, 250, 70, "LAN Packet Drop During Save", "Client queue retries with backoff.\\nVisual amber state alerts user.")}
    {create_svg_card(600, 30, 240, 70, "Stale CSRF on Back Navigation", "pageshow listener refreshes token.\\nBranded recovery screen.")}

    {create_svg_card(50, 130, 240, 70, "Infinite Loop in Student Code", "2s CPU limit triggers SIGKILL.\\nStatus: TIME_LIMIT_EXCEEDED.")}
    {create_svg_card(320, 130, 250, 70, "SQLite Concurrency Contention", "WAL mode + busy_timeout=15000\\nprevents locked database errors.")}
    {create_svg_card(600, 130, 240, 70, "Worker Crash / Power Glitch", "Orphan job sweeper resets status\\nand releases claimed jobs.")}
    """
    svg14 = generate_svg_file("14_error_handling_recovery.svg", 900, 370, "Diagram 14: Error Handling &amp; Fail-Safe Recovery", "Zero Data Loss Resilience for High-Stress Lab Exams", svg14_body)

    # Write SVGs
    svg_map = {
        "01_current_architecture.svg": svg1,
        "02_target_architecture.svg": svg2,
        "03_deployment_lab_architecture.svg": svg3,
        "04_student_login_workflow.svg": svg4,
        "05_exam_lifecycle_workflow.svg": svg5,
        "06_mcq_answer_lifecycle.svg": svg6,
        "07_coding_question_lifecycle.svg": svg7,
        "08_code_execution_judging.svg": svg8,
        "09_recruitment_progression.svg": svg9,
        "10_live_invigilator_monitoring.svg": svg10,
        "11_admin_operations.svg": svg11,
        "12_database_erd.svg": svg12,
        "13_security_authorization_boundaries.svg": svg13,
        "14_error_handling_recovery.svg": svg14,
    }

    for fname, content in svg_map.items():
        out_path = DIAGRAMS_DIR / fname
        out_path.write_text(content, encoding="utf-8")
        print(f"Generated SVG: {out_path.name}")

def main():
    print(f"Writing diagrams to: {DIAGRAMS_DIR}")
    # Write Mermaid files
    for filename, content in MERMAID_DIAGRAMS.items():
        filepath = DIAGRAMS_DIR / filename
        filepath.write_text(content.strip() + "\n", encoding="utf-8")
        print(f"Generated Mermaid: {filename}")

    # Build and write SVGs
    build_all_svgs()
    print("All 14 Mermaid (.mmd) and 14 Vector SVG (.svg) files generated successfully!")

if __name__ == "__main__":
    main()

