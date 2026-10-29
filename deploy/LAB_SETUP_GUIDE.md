# PyForgeLabs College Laboratory Deployment & Security Hardening Guide

## 1. Scope and System Architecture

The **PyForgeLabs College Interview & Placement Simulator** is engineered to operate on a dedicated college server over a local, wired or managed campus network (LAN). Normal examination and interview workflows **must not require internet connectivity**.

```
[ College Lab Candidates (50+ PCs) ]
                 │  (1 Gbps Wired LAN / Isolated Subnet)
                 ▼
[ Nginx Reverse Proxy / Static Assets ] ──> Port 80 / 443
                 │
                 ▼
[ Gunicorn / WSGI Application Server ] ──> 4-8 Workers (Django 6.1)
                 │
                 ├──> [ PostgreSQL 16 Concurrency Database ]
                 │
                 └──> [ Execution Worker Daemon (run_execution_worker) ]
                            │
                            └──> Subprocess Sandboxed Runner (RLIMITs, TempDir, Process Groups)
```

---

## 2. Server Infrastructure & Operating System

### 2.1 Hardware Requirements (Dedicated Server for 50-100 Concurrent Candidates)
- **CPU:** 8 cores / 16 threads (e.g., AMD EPYC, Intel Xeon, or modern Core i7/i9 server).
- **RAM:** 16 GB minimum (32 GB recommended if hosting PostgreSQL and multiple compiler toolchains locally).
- **Storage:** 256 GB NVMe SSD (fast I/O for temporary code build directories and concurrent database transactions).
- **Network:** 1 Gbps NIC wired directly to lab core switch.
- **Power:** UPS (Uninterruptible Power Supply) backing the server and distribution switches to prevent exam disruption during power fluctuations.

### 2.2 Operating System & Core Packages
- **OS:** Ubuntu Server 22.04 LTS or 24.04 LTS (Zero license fees).
- **Database:** PostgreSQL 16 with connection pooling (`CONN_MAX_AGE=60`).
- **Python:** Python 3.13 (or 3.12+).
- **Web Server:** Nginx.

---

## 3. Local College Network & Firewall Configuration

### 3.1 Subnet Isolation
- Deploy student client computers on a dedicated VLAN (e.g., `192.168.100.0/24`).
- Server LAN IP (e.g., `192.168.100.10`).
- Gateway firewall should block all outbound internet traffic from the candidate VLAN during scheduled examinations.

### 3.2 UFW Firewall Configuration on the Server
```bash
# Allow SSH only from administrator management IP
sudo ufw default deny incoming
sudo ufw default allow outgoing
sudo ufw allow from 192.168.100.250 to any port 22 proto tcp

# Allow HTTP and HTTPS only from the candidate lab subnet
sudo ufw allow from 192.168.100.0/24 to any port 80 proto tcp
sudo ufw allow from 192.168.100.0/24 to any port 443 proto tcp

# Enable firewall
sudo ufw enable
```

---

## 4. Managed Lab Computers & Kiosk Policies

Application-level JavaScript checks cannot prevent physical device use or OS-level app switching. True laboratory integrity requires managed operating system policies on student lab PCs.

### 4.1 Standardized Lab User Accounts
- Create a non-privileged, locked-down user account (e.g., `candidate`).
- Disable administrative/sudo privileges on student workstations.
- Hide system tools: Task Manager, Terminal/Command Prompt, PowerShell, Registry Editor.
- Disable removable USB storage via Group Policy (Windows) or `modprobe -r usb_storage` (Linux).

### 4.2 Safe Exam Browser (SEB) or Kiosk Mode
- **Safe Exam Browser (SEB):** Free and open-source (MPL 2.0). Install SEB on candidate machines.
  - Locks the computer into full-screen kiosk mode.
  - Disables keyboard shortcuts (Alt+Tab, Win key, Ctrl+Alt+Del, PrintScreen).
  - Enforces URL allowlist (`http://192.168.100.10/*` only).
  - Blocks virtual machines, remote desktop clients, and screen recorders.
- **Chromium / Edge Kiosk Mode:**
  ```bash
  google-chrome --kiosk --disable-features=TranslateUI --no-first-run --incognito "http://192.168.100.10/"
  ```

### 4.3 Browser Extension Restrictions
- Force-disable all browser extensions (especially ChatGPT, Copilot, grammar checkers, and search extensions).
- Disable Developer Tools (Inspect Element / Console / Network tab).

### 4.4 Post-Session Cleanup
- Configure automatic browser cache and cookie flushing upon exit.
- Use a reboot-to-restore software utility (such as Deep Freeze, Reboot Restore Rx, or Linux overlayfs) so that any downloaded files or modified settings are discarded between candidates.

---

## 5. Code Execution Sandboxing & Security Boundaries

### 5.1 Production runner requirements
Production settings select the container backend and never fall back to host execution. Each job uses a dedicated container with networking disabled, a read-only root filesystem, dropped capabilities, a non-root UID, memory/CPU/process/file limits, bounded output, and a temporary per-job workspace. Local host subprocess execution is enabled only when `DJANGO_DEBUG=True` and `CODE_EXECUTION_ALLOW_UNSANDBOXED=True`.

### 5.2 Build the language runner image
Install Podman or Docker and build the image on the execution worker host:

```bash
podman build -t pyforgelabs/runner:latest -f deploy/runner/Dockerfile deploy/runner
podman image exists pyforgelabs/runner:latest
```

The worker service account must be allowed to run rootless Podman (or access the Docker socket). Keep the runner image local on each worker; runtime uses `--pull=never`. Never grant candidate accounts access to the container runtime socket.

## 6. PostgreSQL Concurrency & Connection Pooling

### 6.1 Database Initialization
```bash
# Connect as postgres user
sudo -u postgres psql

CREATE DATABASE cbt_db;
CREATE USER cbt_user WITH PASSWORD 'secure_college_lan_password';
ALTER ROLE cbt_user SET client_encoding TO 'utf8';
ALTER ROLE cbt_user SET default_transaction_isolation TO 'read committed';
ALTER ROLE cbt_user SET timezone TO 'Asia/Kolkata';
GRANT ALL PRIVILEGES ON DATABASE cbt_db TO cbt_user;
GRANT ALL ON SCHEMA public TO cbt_user;
\q
```

### 6.2 Environment Configuration (`deploy/cbt.env`)
```ini
DJANGO_SECRET_KEY=REPLACE_WITH_GENERATED_SECRET
DJANGO_DEBUG=False
DJANGO_ALLOWED_HOSTS=127.0.0.1,localhost,exam.cbt.college.lan,192.168.100.10
DJANGO_CSRF_TRUSTED_ORIGINS=https://exam.cbt.college.lan,https://192.168.100.10
DJANGO_SECURE_SSL_REDIRECT=True
CODE_EXECUTION_BACKEND=container
CODE_EXECUTION_CONTAINER_RUNTIME=podman
CODE_EXECUTION_CONTAINER_IMAGE=pyforgelabs/runner:latest
EXECUTION_WORKER_HEARTBEAT_DIR=/var/lib/cbt/worker-heartbeats
DATABASE_URL=postgresql://cbt_user:secure_college_lan_password@127.0.0.1:5432/cbt_db
DB_CONN_MAX_AGE=60
```

### 6.3 Run Migrations
```bash
python -c "import secrets; print(secrets.token_urlsafe(64))"
cd /opt/cbt/cbt_test
source .venv/bin/activate
python manage.py migrate
python manage.py collectstatic --noinput
```

Install application dependencies from `requirements.txt` first; deployment requirements include Gunicorn and the PostgreSQL driver. Configure a trusted TLS certificate at the paths in `deploy/nginx/cbt_lan.conf`; the sample redirects HTTP to HTTPS and will not serve until those files exist.

Create the shared heartbeat directory with permissions for the web and worker service account:

```bash
sudo install -d -o cbtadmin -g cbtadmin -m 0750 /var/lib/cbt/worker-heartbeats
```

After migrations, assign Django model permissions to staff groups in Django Admin. Recruitment read access needs `view_recruitmentdrive` and the relevant `view_*` permissions; candidate details also need `view_candidateenrollment`, `view_roundresult`, `view_integrityevent`, and `view_interviewevaluation`. Round processing and overrides need `change_roundresult`; drive transitions need `change_recruitmentdrive`; enrollment actions need `add_candidateenrollment` or `change_candidateenrollment`; interview panel users need `view_interviewassignment`, `change_interviewassignment`, and evaluation add/change permissions; integrity review requires `view_integrityevent` and `change_integrityevent`. Superusers retain full access.

---

## 7. Systemd Service Management

### 7.1 Web Service (`/etc/systemd/system/cbt-web.service`)
```ini
[Unit]
Description=PyForgeLabs CBT Gunicorn Application Server
After=network.target postgresql.service

[Service]
User=cbt
Group=cbt
WorkingDirectory=/opt/cbt/cbt_test
EnvironmentFile=/opt/cbt/cbt_test/deploy/cbt.env
ExecStart=/opt/cbt/cbt_test/.venv/bin/gunicorn --config deploy/gunicorn.conf.py config.wsgi:application
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
```

### 7.2 Execution Worker Service (`/etc/systemd/system/cbt-worker.service`)
```ini
[Unit]
Description=PyForgeLabs CBT Code Execution Worker
After=network.target postgresql.service

[Service]
User=cbt
Group=cbt
WorkingDirectory=/opt/cbt/cbt_test
EnvironmentFile=/opt/cbt/cbt_test/deploy/cbt.env
ExecStart=/opt/cbt/cbt_test/.venv/bin/python manage.py run_execution_worker --worker-id=worker-01
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
```

Enable and start services:
```bash
sudo systemctl daemon-reload
sudo systemctl enable --now cbt-web.service
sudo systemctl enable --now cbt-worker.service
```

---

## 8. Backup & Disaster Recovery Procedures

### 8.1 Automated Pre-Exam Backup
Execute prior to every placement drive:
```bash
# Run existing backup script
bash scripts/backup_database.sh
```
Backups are archived into `backups/` with timestamps and checksums. Store a secondary copy on an offline, USB-connected drive or secondary NAS.

### 8.2 Recovery Procedure
If the server suffers power or disk failure:
1. Provision fallback server using the same OS image.
2. Install PostgreSQL and configure `cbt_db`.
3. Restore database:
   ```bash
   bash scripts/restore_database.sh backups/cbt_backup_YYYYMMDD_HHMMSS.sql.gz
   ```
4. Restart services. Candidate attempts and autosaved drafts are preserved due to continuous, sub-second atomic saves.

