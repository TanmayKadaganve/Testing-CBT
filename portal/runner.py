import os
import signal
import subprocess
import sys
import tempfile
import time

MAX_OUTPUT = 10000  # characters kept from stdout/stderr

from portal.services.language_registry import LanguageRegistry

# Single Source of Truth for languages
LANGUAGES = {
    lang_id: {
        "filename": spec.filename,
        "compile": spec.get_compile_command(),
        "run": spec.run_cmd,
    }
    for lang_id, spec in LanguageRegistry.get_supported_languages().items()
}


def _build_sanitized_environment():
    """
    Builds an isolated, minimal environment for student program execution.
    Strictly prevents leaking Django SECRET_KEY, DATABASE_URL, or host credentials.
    """
    safe_path = os.environ.get("PATH", "/usr/local/bin:/usr/bin:/bin")
    # Clean out any project or private directories from path
    safe_path_elements = [
        p for p in safe_path.split(os.pathsep)
        if "cbt" not in p.lower() and ".gemini" not in p.lower()
    ]
    clean_path = os.pathsep.join(safe_path_elements) if safe_path_elements else "/usr/local/bin:/usr/bin:/bin"

    env = {
        "PATH": clean_path,
        "LANG": "en_US.UTF-8",
        "LC_ALL": "en_US.UTF-8",
        "PYTHONPATH": "",
        "PYTHONUNBUFFERED": "1",
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONHASHSEED": "random",
        "TMPDIR": "/tmp",
    }
    # Retain Windows system paths if running under Windows
    for win_var in ("SYSTEMROOT", "COMSPEC", "PATHEXT", "WINDIR"):
        if win_var in os.environ:
            env[win_var] = os.environ[win_var]
    return env


def _make_resource_limiter(cpu_limit=3, mem_mb=256):
    """
    Returns a preexec_fn callable that applies OS-level resource limits
    before executing the student's process.
    """
    def _apply_limits():
        try:
            import resource
            # CPU time limit in seconds
            try:
                resource.setrlimit(resource.RLIMIT_CPU, (cpu_limit + 1, cpu_limit + 2))
            except (ValueError, OSError):
                pass

            # Virtual address space limit (guarded against macOS dylib allocation failures)
            try:
                mem_bytes = mem_mb * 1024 * 1024
                soft, hard = resource.getrlimit(resource.RLIMIT_AS)
                if mem_bytes <= hard:
                    resource.setrlimit(resource.RLIMIT_AS, (mem_bytes, hard))
            except (ValueError, OSError):
                pass

            # Max file write size (e.g. 5 MB)
            try:
                fsize_bytes = 5 * 1024 * 1024
                resource.setrlimit(resource.RLIMIT_FSIZE, (fsize_bytes, fsize_bytes))
            except (ValueError, OSError):
                pass

            # Max open file descriptors
            try:
                resource.setrlimit(resource.RLIMIT_NOFILE, (64, 64))
            except (ValueError, OSError):
                pass

            # Max processes to prevent fork bombs
            if hasattr(resource, "RLIMIT_NPROC"):
                try:
                    resource.setrlimit(resource.RLIMIT_NPROC, (16, 16))
                except (ValueError, OSError):
                    pass
        except ImportError:
            pass

    return _apply_limits


def run_code(language, code, stdin_text="", time_limit=2):
    """Run student code with sandbox resource limits and return {"status", "stdout", "stderr", "duration_ms"}.

    status is one of: ok, runtime_error, timeout, error
    """
    from django.conf import settings

    backend = getattr(settings, "CODE_EXECUTION_BACKEND", "local")
    if backend == "container":
        from portal.services.container_runner import run_code as run_container_code
        return run_container_code(language, code, stdin_text, time_limit)
    if backend != "local" or not getattr(settings, "CODE_EXECUTION_ALLOW_UNSANDBOXED", False):
        return {"status": "error", "stdout": "", "stderr": "Code execution is disabled: isolated runner is not configured.", "duration_ms": 0}

    cfg = LANGUAGES.get(language)
    if cfg is None:
        return {"status": "error", "stdout": "", "stderr": f"Unsupported language: {language}", "duration_ms": 0}

    stdin_text = (stdin_text or "")[:50000]
    time_limit = max(1, min(int(time_limit or 2), 10))

    start_time = time.perf_counter()
    with tempfile.TemporaryDirectory(prefix="cbt_exec_") as tmp:
        code_file = os.path.join(tmp, cfg["filename"])
        with open(code_file, "w", encoding="utf-8") as f:
            f.write(code)

        sanitized_env = _build_sanitized_environment()

        # Compilation step for compiled languages (C, C++)
        if cfg.get("compile"):
            try:
                comp_proc = subprocess.run(
                    cfg["compile"],
                    cwd=tmp,
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=10,
                    env=sanitized_env,
                )
                if comp_proc.returncode != 0:
                    duration_ms = round((time.perf_counter() - start_time) * 1000, 2)
                    return {
                        "status": "compile_error",
                        "stdout": "",
                        "stderr": (comp_proc.stderr or comp_proc.stdout)[:MAX_OUTPUT],
                        "duration_ms": duration_ms,
                    }
            except subprocess.TimeoutExpired:
                duration_ms = round((time.perf_counter() - start_time) * 1000, 2)
                return {
                    "status": "compile_error",
                    "stdout": "",
                    "stderr": "Compilation timed out after 10s",
                    "duration_ms": duration_ms,
                }
            except Exception as e:
                duration_ms = round((time.perf_counter() - start_time) * 1000, 2)
                return {
                    "status": "compile_error",
                    "stdout": "",
                    "stderr": f"Compiler invocation error: {e}",
                    "duration_ms": duration_ms,
                }

        limiter = _make_resource_limiter(cpu_limit=time_limit, mem_mb=256)

        proc = None
        try:
            # start_new_session creates a new process group for clean group termination on timeout
            proc = subprocess.Popen(
                cfg["run"],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                cwd=tmp,
                env=sanitized_env,
                preexec_fn=limiter if os.name != "nt" else None,
                start_new_session=(os.name != "nt"),
            )
            stdout, stderr = proc.communicate(input=stdin_text, timeout=time_limit)
            duration_ms = round((time.perf_counter() - start_time) * 1000, 2)

            return {
                "status": "ok" if proc.returncode == 0 else "runtime_error",
                "stdout": stdout[:MAX_OUTPUT],
                "stderr": stderr[:MAX_OUTPUT],
                "duration_ms": duration_ms,
            }
        except subprocess.TimeoutExpired:
            if proc:
                try:
                    if os.name != "nt":
                        # Terminate entire process group (including child processes)
                        os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
                    else:
                        proc.kill()
                except (OSError, ProcessLookupError):
                    pass
                try:
                    proc.communicate(timeout=0.5)
                except Exception:
                    pass
            duration_ms = round((time.perf_counter() - start_time) * 1000, 2)
            return {
                "status": "timeout",
                "stdout": "",
                "stderr": f"Time limit exceeded ({time_limit}s)",
                "duration_ms": duration_ms,
            }
        except Exception as e:
            if proc:
                try:
                    proc.kill()
                except Exception:
                    pass
            duration_ms = round((time.perf_counter() - start_time) * 1000, 2)
            return {
                "status": "error",
                "stdout": "",
                "stderr": f"Execution error: {str(e)}",
                "duration_ms": duration_ms,
            }
