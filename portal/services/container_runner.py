"""Fail-closed Docker/Podman runner for untrusted candidate submissions."""
import os
import shutil
import subprocess
import tempfile
import threading
import time
import uuid

from django.conf import settings

MAX_OUTPUT = 10000


def _drain(stream, destination, exceeded):
    size = 0
    while True:
        chunk = stream.read(2048)
        if not chunk:
            break
        remaining = MAX_OUTPUT - size
        if remaining > 0:
            destination.append(chunk[:remaining])
            size += min(len(chunk), remaining)
        if len(chunk) > remaining:
            exceeded.set()


def _kill(runtime, name):
    try:
        subprocess.run([runtime, "kill", "--signal=KILL", name], capture_output=True, timeout=3)
    except Exception:
        pass
    try:
        subprocess.run([runtime, "rm", "--force", name], capture_output=True, timeout=3)
    except Exception:
        pass


def _container_command(language, tmp, code_file, stdin_text, timeout):
    if language == "python":
        compile_cmd, run_cmd = None, ["python3", "-I", "/input/main.py"]
    elif language == "c":
        compile_cmd, run_cmd = ["gcc", "-O2", "-std=c11", "/input/main.c", "-o", "/workspace/a.out"], ["/workspace/a.out"]
    elif language == "cpp":
        compile_cmd, run_cmd = ["g++", "-O2", "-std=c++17", "/input/main.cpp", "-o", "/workspace/a.out"], ["/workspace/a.out"]
    elif language == "java":
        compile_cmd, run_cmd = ["javac", "-d", "/workspace", "/input/Main.java"], ["java", "-Xmx256m", "-Xss1m", "-cp", "/workspace", "Main"]
    else:
        return {"status": "error", "stdout": "", "stderr": f"Unsupported language: {language}", "duration_ms": 0}

    runtime = settings.CODE_EXECUTION_CONTAINER_RUNTIME
    image = settings.CODE_EXECUTION_CONTAINER_IMAGE
    if not shutil.which(runtime):
        return {"status": "error", "stdout": "", "stderr": "Isolated execution is unavailable: configured container runtime was not found.", "duration_ms": 0}
    name = "cbt-job-" + uuid.uuid4().hex[:20]
    start = time.perf_counter()

    def command(inner, limit):
        return [runtime, "run", "--rm", "--name", name, "--pull=never",
                "--network=none", "--read-only", "--cap-drop=ALL",
                "--security-opt=no-new-privileges", "--pids-limit=32",
                "--memory=512m", "--cpus=1", "--ulimit=nofile=64:64",
                "--ulimit=fsize=5242880:5242880", "--user=65534:65534",
                "--tmpfs", "/tmp:rw,nosuid,nodev,noexec,size=32m",
                "--tmpfs", "/workspace:rw,nosuid,nodev,size=32m",
                "--mount", f"type=bind,source={tmp},target=/input,readonly",
                "--workdir=/workspace", "--env=HOME=/tmp", "--env=TMPDIR=/tmp",
                image, *inner], limit

    def run_limited(inner, limit, input_text=""):
        cmd, limit = command(inner, limit)
        output, errors, exceeded = [], [], threading.Event()
        try:
            proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                    stderr=subprocess.PIPE, text=True, encoding="utf-8",
                                    errors="replace")
        except OSError as exc:
            return None, "error", str(exc)
        threads = [threading.Thread(target=_drain, args=(proc.stdout, output, exceeded), daemon=True),
                   threading.Thread(target=_drain, args=(proc.stderr, errors, exceeded), daemon=True)]
        for thread in threads:
            thread.start()
        try:
            if input_text:
                proc.stdin.write(input_text[:50000])
            proc.stdin.close()
            deadline = time.monotonic() + limit
            while proc.poll() is None:
                if exceeded.is_set():
                    _kill(runtime, name)
                    proc.kill()
                    returncode = proc.wait(timeout=2)
                    return ("".join(output), "".join(errors)[:MAX_OUTPUT], returncode), "output_limit", "Output exceeded 10000 characters."
                if time.monotonic() >= deadline:
                    _kill(runtime, name)
                    proc.kill()
                    proc.wait(timeout=2)
                    return None, "timeout", f"Time limit exceeded ({limit}s)"
                time.sleep(0.02)
            for thread in threads:
                thread.join(timeout=1)
            result = ("".join(output), "".join(errors)[:MAX_OUTPUT], proc.returncode)
            if exceeded.is_set():
                return result, "output_limit", "Output exceeded 10000 characters."
            return result, "ok", ""
        except Exception as exc:
            _kill(runtime, name)
            try:
                proc.kill()
            except OSError:
                pass
            return None, "error", str(exc)

    if compile_cmd:
        compiled, state, error = run_limited(compile_cmd, 10)
        if state != "ok":
            duration = round((time.perf_counter() - start) * 1000, 2)
            return {"status": "compile_error", "stdout": "", "stderr": error[:MAX_OUTPUT], "duration_ms": duration}
        if compiled[2] != 0:
            duration = round((time.perf_counter() - start) * 1000, 2)
            return {"status": "compile_error", "stdout": "", "stderr": (compiled[1] or compiled[0])[:MAX_OUTPUT], "duration_ms": duration}

    result, state, error = run_limited(run_cmd, timeout, stdin_text)
    duration = round((time.perf_counter() - start) * 1000, 2)
    if state == "timeout":
        return {"status": "timeout", "stdout": "", "stderr": error, "duration_ms": duration}
    if state != "ok":
        return {"status": "error", "stdout": "", "stderr": error[:MAX_OUTPUT], "duration_ms": duration}
    stdout, stderr, returncode = result
    return {"status": "ok" if returncode == 0 else "runtime_error", "stdout": stdout, "stderr": stderr, "duration_ms": duration}


def run_code(language, code, stdin_text="", time_limit=2):
    """Run code in a constrained, networkless container. Host fallback is forbidden."""
    if not isinstance(code, str) or len(code) > 100000:
        return {"status": "error", "stdout": "", "stderr": "Source code is invalid or too large.", "duration_ms": 0}
    timeout = max(1, min(int(time_limit or 2), 10))
    with tempfile.TemporaryDirectory(prefix="cbt_container_") as tmp:
        filename = {"python": "main.py", "c": "main.c", "cpp": "main.cpp", "java": "Main.java"}.get(language)
        if not filename:
            return {"status": "error", "stdout": "", "stderr": f"Unsupported language: {language}", "duration_ms": 0}
        with open(os.path.join(tmp, filename), "w", encoding="utf-8") as source:
            source.write(code)
        return _container_command(language, tmp, filename, (stdin_text or "")[:50000], timeout)
