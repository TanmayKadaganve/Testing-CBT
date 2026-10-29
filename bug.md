# Software Bug and Error Review

## Scope and review method

This review covers source in `portal/`, `recruitment/`, `config/`, and `deploy/`, including request flows, data models, scoring, code execution, admin workflows, client JavaScript, and deployment settings. On 30 October 2026 I reran Django checks, Python compilation, migration consistency checks, and the automated test suite. The results are recorded below. A passing system check does not establish that every security or deployment property works in production.

The findings below are grouped by severity. Each entry explains the issue name, why it occurs, its system effect, and a repair approach designed to preserve existing data and behavior. A suggested fix should be implemented with regression coverage and reviewed against the institution's actual exam rules before release.

## Remediation status (30 October 2026, re-audited)

“Fixed in code” means the source contains a mitigation; it does not mean the behavior passed runtime verification. The test run below failed, and the Docker runner could not be exercised on this workstation. Treat fixes that lack passing regression coverage as provisional until those failures are resolved or their tests are updated to match an explicitly approved policy.

| Finding | Status |
|---|---|
| BUG-01 | Fixed in code: production uses a networkless, resource limited container runner and fails closed without the runtime. Container behavior could not be run on this workstation. |
| BUG-02 | Fixed in settings and deployment examples: production requires secret, hosts, and CSRF origins; HTTPS cookies and redirect are enabled. |
| BUG-03 | Fixed: explicit manual outcome, audit-history backfill when possible, accurate status/selection updates and display. Historical rows with no matching audit entry remain marked for review. |
| BUG-04 | Fixed: success is returned only after persistence; retry exhaustion returns 503. |
| BUG-05 | Fixed: draft errors stop run/submit and return a retryable response. |
| BUG-06 | Fixed: login retry exhaustion now has a useful busy message. |
| BUG-07 | Fixed: recruitment custom operations require action-specific Django model permissions in addition to staff login. |
| BUG-08 | Fixed for the supported policy: one attempt per linked portal exam is enforced, and a server-owned round deadline gates exam access. Retry values above one are rejected until the underlying one-attempt portal model is redesigned. |
| BUG-09 | Fixed: round entry requires an active drive, an assigned current round, and the round session; linked exam URLs are gated too. |
| BUG-10 | Fixed: JSON object shape, IDs, and numeric event values are validated before ORM use. |
| BUG-11 | Fixed: local compiler detection and invocation resolve the same GCC/Clang executable; the container uses known toolchains from its image. |
| BUG-12 | Fixed: language availability is cached per worker process after its initial probe. |
| BUG-13 | Fixed for production: coding page uses async jobs; production requests do not run the queue synchronously, and a missing worker produces 503. Debug mode retains local synchronous execution. |
| BUG-14 | Fixed: queue admissions serialize through a database singleton lock; lock contention returns 503. |
| BUG-15 | Clarified: `score_weight` is explicitly reporting-only and does not affect cutoffs or final selection. |
| BUG-16 | Fixed: attempt, submission, and feedback redirects depend on successful writes. |
| BUG-17 | Fixed as an evidence-handling control: client browser reports remain informational, are labeled unverified, cannot produce automatic warning severity, and are rate-limited by the shared Nginx configuration in production. |
| BUG-18 | Fixed in reporting: performance page identifies the current worker PID and per-process scope. |
| BUG-19 | Fixed in health checks: runner image/toolchains are probed and the execution worker heartbeat is checked. |
| BUG-20 | Fixed: Gunicorn and PostgreSQL driver are included in requirements; deployment examples use PostgreSQL. |
| BUG-21 | Fixed: strings beginning with spreadsheet formula characters are escaped in Excel exports. |
| BUG-22 | Fixed for application ORM use: instance and queryset update/delete are rejected. Database-level superuser/raw SQL changes still require database controls. |
| BUG-23 | Fixed: candidate logout is POST-only and uses a CSRF-protected form. |
| BUG-24 | Fixed best-effort: navigation attempts a CSRF-protected `fetch` with `keepalive`; normal debounced saves remain. Browser shutdown/network loss can still prevent any final request from arriving. |
| BUG-25 | Mitigated: staff can reset a stale candidate session and the action is audited. No automatic takeover occurs during an active exam. |
| BUG-26 | README and Markdown audit were revised to reflect the code. The generated architecture PDF remains a historical snapshot and should not be used to infer current behavior. |

## Verification evidence (30 October 2026)

Commands were run from the project root with `DJANGO_DEBUG=True` for local development checks. The existing `db.sqlite3` was not migrated or modified by these checks; Django's test runner created and removed its temporary test database.

| Check | Result | Evidence |
|---|---|---|
| `python manage.py check` | PASS | `System check identified no issues (0 silenced).` |
| `python -m compileall -q config portal recruitment` | PASS | No Python syntax/bytecode compilation errors reported. |
| `python manage.py makemigrations --check --dry-run` | PASS | `No changes detected`. |
| `python manage.py showmigrations` | PARTIAL | Existing local DB has unapplied `portal.0009`, `recruitment.0003`, and `recruitment.0004`. The test runner successfully built its temporary test database, but the local DB remains behind. |
| `python manage.py test` | FAIL | 105 tests ran: 15 failures and 1 error. Do not consider the project fully verified. |
| Container runner | NOT RUN | `docker` is not installed/available on this workstation; BUG-01 isolation, image and health-check behavior need a Linux/container-capable staging host. |

### Failed test details

The failed assertions are concrete regression signals. Some appear to encode older behavior than the current fixes; that needs an explicit policy decision and corrected tests before they can be called resolved.

- **Queue and health (BUG-13/14/19):** `test_execution_job_lifecycle_and_polling` and `test_per_student_concurrency_admission_limit` received HTTP 503 instead of 200; `test_system_health_check` returned `Critical`. The worker/container prerequisites are absent locally, but the test setup should provide a deterministic worker stub or assert the intended unavailable response. Production async behavior is not proven by these tests.
- **Code-language availability (BUG-11/12):** C and C++ are unavailable on this Windows machine, and the C/C++ run, compile-error, language registry, and draft tests fail as a result. This establishes that local toolchains are missing here, not that compiler resolution works on the intended deployment image. Add toolchain-aware skips or run the suite inside the runner image, then verify C and C++ there.
- **Coding flow compatibility (BUG-05/13):** `test_candidate_switching_languages_autosaves_and_restores` got 400 where the test expects 200. This endpoint behavior needs inspection and a regression test aligned with supported language policy; it is not explained solely by absent Docker.
- **Recruitment end-to-end and manual result behavior (BUG-03/08/09):** the successful candidate flow could not find an `Attempt`, the below-cutoff scenario reported zero failed candidates, and `test_override_updates_enrollment_status` expected `PROMOTED` but received `PASSED`. These demonstrate mismatch between current access/progression semantics and existing tests or a broken workflow. The affected scenarios need to be traced and made consistent before marking these findings verified.
- **Integrity severity (BUG-17):** `test_tab_switch_escalation_to_warning` expected `WARNING` but got `INFO`. The current mitigation intentionally prevents client-reported events from automatically reaching warning severity; update the test to assert the new policy and human-review path, or revise the policy if escalation is required.
- **End-to-end C/C++ (BUG-11):** recruitment scenario G failed because C execution returned `error`; same missing local toolchain limitation applies.

The test output also contains other failures not fully diagnosed in this summary. Re-run the suite after fixes and record a clean result before calling the project verified. Do not apply pending migrations to a production database without backup and a reviewed deployment plan.

## Critical / release-blocking risks

### BUG-01 — Student code executes without a strong isolation boundary

**Why it is happening:** `portal/runner.py` executes student code as local subprocesses in a temporary directory. It supplies a reduced environment and attempts Unix `resource` limits, but this is not a filesystem or network sandbox. The child process can still access files readable by the service account and use network access available to the host. Resource limits are skipped on Windows. Compilation also runs before the runtime limiter is applied.

**Effect on the system:** A malicious submission may read or alter files accessible to the service account, contact local/network services, consume resources during compilation, or escape expected process limits. On Windows, process-tree cleanup and OS resource enforcement are weaker still. This can expose database files, source, student records, or disrupt the exam server.

**Safe fix without disrupting the software:** Preserve the existing runner interface (`run_code(language, code, stdin, time_limit)`) but execute it through a separately configured sandbox backend: rootless container or a purpose-built sandbox with no network, read-only root filesystem, per-job writable temp storage, CPU/memory/process/file limits, and a low-privilege account. Add the backend behind a setting so the current code path remains available only for local development. Do not expose this runner to untrusted candidates until the isolation layer is active and verified.

**Where:** `portal/runner.py`; the repository README also warns about this limitation.

### BUG-02 — Production defaults enable debug mode and use a known fallback secret

**Why it is happening:** In `config/settings.py`, `DJANGO_DEBUG` defaults to `True`; `DJANGO_SECRET_KEY` has a checked-in insecure fallback. The sample deployment file has placeholders and sets `DJANGO_SECURE_SSL=False`.

**Effect on the system:** If an operator starts the deployed service without overriding these values, error pages may disclose internals and a predictable secret can undermine signed sessions and other Django protections. Secure session and CSRF cookies also remain disabled when SSL is in use but the environment flag is left false.

**Safe fix without disrupting the software:** In deployment configuration, require a generated secret from a protected environment file, fail startup when the secret is missing/placeholder, set debug false, configure valid hosts, and set secure-cookie behavior to match HTTPS. Keep local developer defaults separate from production. Do not rotate an in-use production secret without planning session invalidation.

**Where:** `config/settings.py`, `deploy/cbt.env.example`.

### BUG-03 — Recruitment result processing can overstate a failed manual override as passed

**Why it is happening:** `apply_manual_override()` stores `RoundResult.DECISION_OVERRIDE` regardless of whether the requested override was PASS, FAIL, or ABSENT. `RoundResult.passed` treats every `DECISION_OVERRIDE` as passed. The service also maps ABSENT to enrollment status FAILED. A pass on the final round sets enrollment status PROMOTED but does not set `final_selected=True` or use the normal final status PASSED.

**Effect on the system:** Candidate result displays, reports, filters, and selection counts can disagree with the actual administrator decision. An absent override can appear passed in a `passed` property, and a final-round manual pass can be omitted from selected-candidate counts.

**Safe fix without disrupting the software:** Preserve existing audit history. Introduce an explicit overridden outcome field (or store the actual decision in a compatible, unambiguous result field) and update result display/export helpers to use it. Make status mapping explicit for PASS, FAIL, and ABSENT; make final-round PASS update selection fields exactly as the automated progression path does. Before changing existing rows, provide a data migration/report that identifies prior overrides for review rather than guessing their intent.

**Where:** `recruitment/services/progression.py`, `recruitment/models.py` (`RoundResult.passed`).

## High-priority correctness and access-control defects

### BUG-04 — MCQ answer endpoint can return success after every database retry failed

**Why it is happening:** `save_answer()` loops over `range(5)`, but the database-busy branch checks `attempt_i == 14`; that condition is unreachable. If all five writes raise `OperationalError`, execution leaves the loop and returns `{ "ok": true }`.

**Effect on the system:** The candidate sees “Saved on server” although the answer was not written. The lost answer can affect the final score and recruitment decision. The page retries explicit error responses, so a false success defeats the client recovery behavior.

**Safe fix without disrupting the software:** Track whether the transaction actually completed. Return HTTP 503 with `{ok:false}` after the last failure, and only return success after a successful create/update. Keep the existing response shape so the frontend can continue using its retry logic. Add a regression test that simulates repeated database lock errors and verifies no false success.

**Where:** `portal/views.py`, `save_answer()`.

### BUG-05 — Code draft persistence errors are discarded

**Why it is happening:** `_save_draft()` unpacks `CodeDraftService.save_draft()` into `draft, _`, ignoring the error string. `save_code()`, `code_run()`, and `code_submit()` continue as if the draft was saved. The draft service can return `(None, "Database busy...")` after retries.

**Effect on the system:** The UI can report a successful save or accept a code run/submission while the latest draft was not stored. A disconnect or database lock can therefore erase the candidate's last unsent work after navigation.

**Safe fix without disrupting the software:** Have `_save_draft()` raise/return a structured failure when the service returns no draft. Each endpoint should return a retryable 503 JSON response and skip execution/submission when persistence fails. Keep the response key `ok` and use an explicit error so existing frontend error handling remains compatible.

**Where:** `portal/views.py`, `_save_draft()` and coding endpoints; `portal/services/code_draft.py`.

### BUG-06 — Login lock retries can end with no useful error message

**Why it is happening:** `login_view()` also loops five times but checks whether `attempt_i == 14`. After five `OperationalError`s, `error` can remain `None` and the login form is rendered as if no specific failure occurred.

**Effect on the system:** Under database contention, candidates receive a blank or confusing failure instead of a retryable busy message. It also makes diagnosis harder during an exam.

**Safe fix without disrupting the software:** Align the retry count and terminal condition, or use a `saved/finished` flag. On exhaustion, show a generic temporary-server-busy message and log the exception with a request identifier, not candidate DOB or other sensitive payload.

**Where:** `portal/views.py`, `login_view()`.

### BUG-07 — Staff-only is used where action-specific permissions are needed

**Why it is happening:** Many custom recruitment operations are protected with `staff_member_required`, which checks that the user is staff but does not require specific Django model permissions. This includes sensitive actions such as processing rounds, manual overrides, exporting results, changing drive state, and reviewing integrity events. The interviewer panel is appropriately scoped to the assigned interviewer, but general staff operations are broad.

**Effect on the system:** A staff account created for a limited function may still be able to change candidate outcomes or download all drive results by reaching the custom route directly.

**Safe fix without disrupting the software:** Keep staff login as the first gate, then add explicit permissions per action (for example, `recruitment.process_round`, `recruitment.override_result`, `recruitment.export_results`, and `recruitment.review_integrity`). Assign the new permissions to existing admin groups in a documented migration/setup step. Preserve current administrator access by granting the full set to the current authorized role.

**Where:** `recruitment/admin_views.py`.

### BUG-08 — Round retry and duration settings are not enforced by candidate attempt logic

**Why it is happening:** `Round.max_attempts` and `Round.duration_minutes` are configuration fields, but the attempt flow is keyed to a unique `(student, exam)` attempt and relies on exam section times. Candidate round entry does not enforce a per-round attempt counter or apply the configured duration as an authoritative deadline.

**Effect on the system:** Administrators may configure retry/duration policies that candidates do not actually receive. Recruitment rounds can differ from the configured policy, and a candidate may be blocked from retrying even when the round allows it (or have timing governed only by the linked exam rather than the round).

**Safe fix without disrupting the software:** First define the intended rule for an attempt: whether retry means a new `Attempt`, a new try under the same attempt, or a reset. Then add a round-attempt record keyed by enrollment and round, and enforce attempt count and end time server-side. Migrate existing attempts as the first attempt; do not alter current exam timing until the new policy is tested against existing exam schedules.

**Where:** `recruitment/models.py` (`Round.max_attempts`, `duration_minutes`); `recruitment/views.py`; `portal/views.py`.

### BUG-09 — Candidate round entry does not check drive state and can allow a null current round

**Why it is happening:** `round_instructions()` checks the enrollment status, optional `current_round` mismatch, and round time, but it does not require the drive to be ACTIVE. Its round mismatch check is skipped when `current_round` is null.

**Effect on the system:** Depending on status and schedule, an enrolled candidate may still enter a round in a paused/closed drive, or access a round when their enrollment has no assigned current round. This can bypass intended administrative pause/round assignment controls.

**Safe fix without disrupting the software:** Define allowed drive states for candidate entry (typically ACTIVE) and require a current round, with an explicit first-round initialization path for new enrollments. Preserve result/dashboard viewing for closed drives; gate only entry and new exam work. Verify the candidate dashboard and round launch flow together before deployment.

**Where:** `recruitment/views.py`, `round_instructions()`; `recruitment/models.py`, enrollment status helpers.

## Medium-priority functional and reliability issues

### BUG-10 — Valid JSON with the wrong shape, or malformed numeric fields, can produce HTTP 500 errors

**Why it is happening:** Several endpoints parse JSON but assume the result is a dictionary. A valid JSON value such as `null`, a string, or an array passes `json.loads()` and then fails at `.get()`. `record_integrity_event()` converts untrusted values with `int()` without handling conversion errors. `live_monitor_updates()` similarly converts `since_event_id` directly to `int()`.

**Effect on the system:** Bad or manipulated requests generate server errors instead of clean 400 responses. Repeated errors add noise to logs and may disrupt live monitoring.

**Safe fix without disrupting the software:** Validate that the decoded body is an object before reading keys. Validate numeric values as bounded integers and return HTTP 400 with a stable JSON error. Treat missing optional values as defaults. Add request tests for `null`, arrays, strings, nonnumeric counts, and malformed polling cursors.

**Where:** `portal/views.py` (`save_answer`, `_coding_request`); `recruitment/views.py` (`candidate_heartbeat`, `record_integrity_event`); `recruitment/admin_views.py` (`live_monitor_updates`).

### BUG-11 — C/C++ availability detection can select a compiler that execution never calls

**Why it is happening:** `LanguageSpec.check_availability()` falls back to `clang`/`clang++` when GCC/G++ is unavailable. The `compile_cmd` remains hard-coded to `gcc`/`g++` in the registry and is used by `portal/runner.py`.

**Effect on the system:** On a Clang-only host, the language appears available in the UI but each run fails because the runner invokes a missing GCC executable.

**Safe fix without disrupting the software:** Store the resolved compiler executable in a host configuration/diagnostic object and use that exact path for both availability checks and compilation. Alternatively, configure compiler commands explicitly and report a language unavailable unless the configured executable is present. Keep language IDs and UI labels unchanged.

**Where:** `portal/services/language_registry.py`; `portal/runner.py`.

### BUG-12 — Compiler availability checks spawn processes on frequent page and autosave requests

**Why it is happening:** `get_supported_languages()` checks each runtime/compiler. C/C++/Java checks can run `--version` subprocesses. `_coding_request()` and `CodeDraftService.save_draft()` each call `is_supported()`, so coding saves/runs may repeat those checks.

**Effect on the system:** Every draft save can start multiple extra subprocesses. With many candidates and one-second autosaves, this adds avoidable CPU/process load and may increase request latency or database contention.

**Safe fix without disrupting the software:** Check and cache toolchain availability at startup or for a bounded TTL, and expose diagnostics separately for administrators. Use the cached registry result in request validation. Preserve the availability check in an explicit health/diagnostic action so compiler changes can still be detected operationally.

**Where:** `portal/services/language_registry.py`, `portal/services/code_draft.py`, `portal/views.py`.

### BUG-13 — Background execution queue is bypassed by the normal coding page

**Why it is happening:** The view supports asynchronous mode only when `?async=1` or JSON `async: true` is supplied. The coding page posts to the plain run and submit URLs without either value. The views pass `run_sync_fallback=True`, so `enqueue_job()` executes the job immediately in the web request.

**Effect on the system:** Long compilations and full multi-case judging occupy a web request worker. Candidate requests can hit server timeouts or consume all Gunicorn threads, and the configured background workers do not provide the expected throughput for ordinary usage.

**Safe fix without disrupting the software:** Make async mode explicit in the coding page and use the existing job polling flow; ensure the execution worker service is running before enabling it. Keep a separately configured synchronous mode for local development or worker outages, with a bounded timeout and visible error. Roll out behind a setting and compare result/status behavior before changing production defaults.

**Where:** `portal/templates/portal/coding.html`; `portal/views.py` (`code_run`, `code_submit`); `portal/services/execution_queue.py`.

### BUG-14 — Execution queue capacity and per-student admission checks are race-prone

**Why it is happening:** `enqueue_job()` counts queued/active rows and then inserts a job without locking or a database constraint that makes admission atomic. Two simultaneous requests can both pass the count check.

**Effect on the system:** The queue can exceed its configured capacity, and a candidate can create more than one active job in a race. This weakens fairness and can overload workers.

**Safe fix without disrupting the software:** Serialize admission through a database lock or dedicated queue broker, and enforce per-attempt active-job coordination atomically. On SQLite, use a transaction strategy compatible with its write locking; on PostgreSQL, use row/advisory locking or a broker. Keep the same 503/429 response behavior.

**Where:** `portal/services/execution_queue.py`, `enqueue_job()`.

### BUG-15 — Round score weights are stored but not part of a combined drive score

**Why it is happening:** `score_weight` is saved in each `Round` and copied into `score_rule_snapshot`, but `process_round_results()` calculates a percentage for the current round and makes a per-round pass/fail decision. There is no weighted total across rounds in the progression logic inspected.

**Effect on the system:** Admins may believe round weights affect final ranking or selection when they currently do not. Final selected status is driven by passing each round, not a weighted overall score.

**Safe fix without disrupting the software:** Confirm whether weights are intended for final ranking. If not, relabel the field/help text to explain that it is informational or remove it only after checking existing data. If weights are intended, implement a separately versioned final aggregate and export column; do not alter existing per-round cutoff decisions.

**Where:** `recruitment/models.py`, `recruitment/services/progression.py`.

### BUG-16 — Feedback/database retry exhaustion can redirect as if the write succeeded

**Why it is happening:** `instructions()`, `submit_exam()`, and `feedback_page()` retry `OperationalError`, but the loops do not keep a success flag or return an error after all attempts fail. `feedback_page()` redirects to done even if no feedback row was created. `instructions()` may redirect to exam without an attempt row.

**Effect on the system:** Candidates can enter redirect loops, see a completion page without stored feedback, or believe submission/attempt creation succeeded when it did not. This appears mainly during database contention.

**Safe fix without disrupting the software:** Use an explicit success flag for each write. On exhaustion, render a retryable message or return 503; do not redirect to a state that assumes the write happened. Keep idempotent writes (unique attempt/feedback relationship) and avoid asking candidates to submit duplicate records.

**Where:** `portal/views.py`, `instructions()`, `submit_exam()`, `feedback_page()`.

### BUG-17 — Integrity events are candidate-reported and should not be treated as authoritative evidence

**Why it is happening:** The browser sends event types and context to `record_integrity_event()`. The server validates the event type and associates it with the authenticated student's enrollment, but it cannot verify that a reported browser event actually occurred. The client can directly call the endpoint for its own account.

**Effect on the system:** Candidates can fabricate or inflate their own event counts, producing false warnings and unnecessary invigilator work. Browser visibility/focus events also cannot detect other devices or OS-level activity.

**Safe fix without disrupting the software:** Treat these records as review indicators only, as the model documentation says. Label the source as client-reported, keep human review mandatory, and avoid automatic penalties based solely on these events. Validate payload size/ranges and rate-limit at a shared server layer.

**Where:** `portal/static/portal/js/integrity_monitor.js`; `recruitment/views.py`; `recruitment/services/integrity.py`.

### BUG-18 — Performance metrics are per-process and can look incomplete in multi-worker deployment

**Why it is happening:** `portal/middleware.py` stores request measurements in a module-level in-memory deque. Each Gunicorn worker process has a different copy; restarting a worker clears its samples.

**Effect on the system:** Dashboard metrics represent only the worker that handled the dashboard request, not the whole service. Values can vary between page loads and cannot be used as reliable system-wide performance data.

**Safe fix without disrupting the software:** Label existing values as per-worker diagnostics, or move aggregation to a shared monitoring store/metrics system. Do not combine process-local values and label them as server-wide. Existing dashboard layout can remain while the data source is changed.

**Where:** `portal/middleware.py`; `portal/dashboard_views.py`, performance view.

### BUG-19 — System health can show a clear queue without confirming a worker is alive

**Why it is happening:** `check_system_health()` inspects current queue counts and Python availability, but it does not verify that an execution worker process is running or that C/C++/Java toolchains can compile and execute.

**Effect on the system:** A queue with no pending work may appear healthy while the worker is stopped; an empty queue does not prove future jobs will be processed. Python being available does not verify configured non-Python runners.

**Safe fix without disrupting the software:** Add a worker heartbeat/last-seen record and report stale/missing workers as a warning. Use language registry diagnostics to report each configured compiler/runtime. Keep health checks non-destructive; do not run candidate code during a health probe.

**Where:** `portal/services/system_health.py`; `portal/management/commands/run_execution_worker.py`.

### BUG-20 — PostgreSQL/Gunicorn deployment can fail after installing only pinned requirements

**Why it is happening:** `config/settings.py` supports PostgreSQL and deployment config runs Gunicorn, but `requirements.txt` does not include a PostgreSQL Python adapter or Gunicorn.

**Effect on the system:** Following the README's `pip install -r requirements.txt` alone does not install all packages required by the documented PostgreSQL/Gunicorn deployment. Django may fail to load the PostgreSQL backend or the service command may not find Gunicorn.

**Safe fix without disrupting the software:** Add the production server and the selected PostgreSQL adapter to an explicit production requirements file (or the main file if every deployment needs them). Pin and document platform-compatible versions, then install them in a staging environment before applying migrations to production.

**Where:** `requirements.txt`, `config/settings.py`, `deploy/systemd/`, `deploy/gunicorn.conf.py`.

## Lower-priority integrity, usability, and documentation issues

### BUG-21 — Excel exports may interpret imported candidate text as formulas

**Why it is happening:** Export routines write user-controlled values such as student names, USNs, and option text directly into workbook cells. Spreadsheet applications may interpret strings beginning with formula characters as formulas.

**Effect on the system:** A crafted roster/question value can execute a spreadsheet formula when an administrator opens an exported workbook, potentially causing data disclosure through linked formulas or misleading output.

**Safe fix without disrupting the software:** Before writing strings to Excel, escape or prefix formula-leading values (`=`, `+`, `-`, `@`, and leading control whitespace) as literal text. Keep numeric/date values typed. Apply this to both portal and recruitment exports and test with representative formula-like values.

**Where:** `portal/admin.py` result export; `recruitment/admin_views.py` drive export; `recruitment/admin.py` exports.

### BUG-22 — Audit log immutability can be bypassed by bulk ORM operations

**Why it is happening:** `AuditLog.save()` and `delete()` reject updates/deletes on model instances, but Django `QuerySet.update()` and `QuerySet.delete()` bypass those instance methods. The database itself has no immutability constraint or trigger.

**Effect on the system:** Code with ORM access can rewrite or remove audit history despite the model's “immutable” description. This weakens the audit trail's evidentiary value.

**Safe fix without disrupting the software:** Make the admin read-only (already intended), prohibit bulk update/delete through a custom queryset/manager, and use database permissions or append-only triggers for stronger guarantees. Preserve a controlled archival procedure for legal retention requirements.

**Where:** `recruitment/models.py`, `AuditLog`.

### BUG-23 — Logout is a state-changing GET request

**Why it is happening:** `logout_view()` clears the student's active token and flushes the session, but the route accepts GET and is not protected by `require_POST`.

**Effect on the system:** A cross-site link or image can force a candidate to log out, interrupting an exam session. The single-login token is cleared, which may also allow a different machine to log in.

**Safe fix without disrupting the software:** Change logout to POST and submit it from a CSRF-protected form/button. Preserve a temporary redirect for bookmarks only if it does not perform the logout on GET.

**Where:** `portal/views.py`, `logout_view()`; `portal/urls.py`.

### BUG-24 — A last-second code edit can be lost during page navigation

**Why it is happening:** Coding autosave is debounced by one second. The `beforeunload` handler only updates in-memory browser state; it does not send the pending draft to the server.

**Effect on the system:** If a candidate navigates away, loses power, or the section changes before the debounce request completes, the most recent edit may not be in `CodeDraft`.

**Safe fix without disrupting the software:** Keep the current autosave but add a best-effort flush using `fetch(..., {keepalive:true})` or `sendBeacon` with the CSRF-safe endpoint design, and show an unsaved state until the server confirms. Do not rely on `beforeunload` as the only persistence mechanism.

**Where:** `portal/templates/portal/coding.html`, autosave and `beforeunload` handler.

### BUG-25 — Stale active-login token can lock out a candidate after an unclean exit

**Why it is happening:** A new login is rejected when `Student.active_token` is set to a different token. The token is cleared on explicit logout or the completion page, but there is no expiry/heartbeat-based recovery in the login flow.

**Effect on the system:** A browser crash, power loss, or network interruption can leave the student unable to resume on the same or replacement computer until an administrator resets the login.

**Safe fix without disrupting the software:** Preserve the single-session policy but add an audited recovery path, such as an administrator reset and a last-activity/lease expiry policy. During an active exam, do not automatically clear a token merely because a short heartbeat was missed; use a conservative timeout and explicit invigilator action.

**Where:** `portal/views.py`, `login_view()` and `release_student()`; `portal/models.py`, `Student.active_token`.

### BUG-26 — README and architecture audit make contradictory claims about current source

**Why it is happening:** Documentation describes an older or intended system. For example, the audit describes password login and `/api/save-answer/`, while current code uses USN/date-of-birth login and `/exam/save/`. The README says there are no automated tests, but test modules exist. Some deployment and sandbox claims also exceed the implementation.

**Effect on the system:** Maintainers may troubleshoot the wrong endpoint, assume a protection exists when it does not, or miss existing tests. This increases deployment and maintenance errors.

**Safe fix without disrupting the software:** Treat `bug.md` and the current URL/model source as the reference during remediation. Update README and generated audit artifacts after fixes land; add a lightweight documentation review step to releases so claims about routes, dependencies, and security match the code.

**Where:** `README.md`, `docs/audits/PyForgeLabs_Whole_Project_Architecture_and_Audit.md`.

## Recommended repair order

1. Gate all untrusted code execution until a real sandbox is in place; fix production secret/debug/host/cookie settings.
2. Fix answer and draft false-success paths, plus retry exhaustion behavior.
3. Correct manual override semantics and add explicit staff permissions.
4. Validate request payload shapes and numeric fields; gate round entry using drive/current-round policy.
5. Decide and enforce round attempt/duration/weight rules.
6. Enable the background worker for normal coding traffic, make queue admission safe, and cache compiler diagnostics.
7. Fix exports, audit immutability, logout method, monitoring accuracy, deployment dependencies, and stale documentation.

## Verification needed before marking fixes complete

For each repaired item, add targeted automated tests for the expected behavior and failure path. Resolve or update the failing tests listed above, then rerun the suite. Test supported language toolchains and the container sandbox on the actual deployment OS, and verify a candidate flow end-to-end with a non-production exam. The system check, compilation, and migration consistency checks passed locally; the full runtime suite did not.
