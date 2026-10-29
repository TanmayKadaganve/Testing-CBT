# PyForgeLabs Computer Based Testing Portal

A Django application for timed multiple choice and programming exams, recruitment drives, candidate monitoring, and interview evaluation. Candidates authenticate with USN and date of birth. Staff manage exams and recruitment workflows through Django Admin and the recruitment console.

## Main features

- Student roster imports and exam registration
- Timed MCQ and coding sections with autosaved answers and code drafts
- Automated coding evaluation in background execution workers
- Recruitment drive rounds, result processing, audited manual overrides, and interviews
- Candidate presence and browser reported integrity signals for human review
- Excel templates and result exports

## Project layout

- `config/`: Django settings and application entry points
- `portal/`: Candidate exam flows, models, code execution queue, runner, and admin
- `recruitment/`: Drive, round, progression, monitoring, and interviewer workflows
- `deploy/`: Example environment, Nginx, systemd, and runner image configuration
- `bug.md`: Source review findings and remediation status
- `docs/audits/`: Detailed architecture audit and diagrams

The architecture audit PDF files are historical snapshots. Use `bug.md` and the current source as the status of the implementation.

## Local development

Create a virtual environment and install dependencies:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
$env:DJANGO_DEBUG = "True"
python manage.py migrate
python manage.py createsuperuser
python manage.py runserver
```

Open `http://127.0.0.1:8000/` for candidate login and `/admin/` for Django Admin. Debug mode enables the local host code runner for development; it is not a security boundary and must not be exposed to untrusted users.

## Production requirements

Production defaults to `DEBUG=False`, requires a non-placeholder `DJANGO_SECRET_KEY`, explicit `DJANGO_ALLOWED_HOSTS`, and explicit `DJANGO_CSRF_TRUSTED_ORIGINS`. Use HTTPS, PostgreSQL, Gunicorn, and the configuration in `deploy/`. The production code runner is fail closed and requires the local Podman or Docker runtime and the image built from `deploy/runner/Dockerfile`. It never falls back to host subprocess execution. Start `manage.py run_execution_worker` and ensure its service account can run the configured container runtime.

See [deploy/LAB_SETUP_GUIDE.md](deploy/LAB_SETUP_GUIDE.md) for infrastructure setup. Set real credentials and certificate paths; the example environment contains placeholders.

## Operational notes

- Browser integrity events are unverified candidate reports. They are stored as informational triage signals and require human review.
- Performance samples are in memory per web worker process and reset when that process restarts.
- Candidate code is stored in the database; protect database backups and restrict staff permissions.
- Manual candidate login resets are available to staff and recorded in the audit log.

## Checks

The repository contains Django test modules. Run `python manage.py check` and `python manage.py test` in a configured development environment before release. A source edit alone does not establish runtime or deployment correctness.
