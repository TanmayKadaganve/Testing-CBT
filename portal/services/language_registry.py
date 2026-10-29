"""
portal/services/language_registry.py
====================================
Single Source of Truth (SSOT) for all programming language specifications,
compilation toolchains, execution adapters, starter scaffolds, and
availability diagnostics across PyForgeLabs CBT.
"""

from dataclasses import dataclass
from functools import lru_cache
import os
import shutil
import subprocess
import sys
from typing import Dict, List, Optional, Tuple


@dataclass(frozen=True, eq=False)
class LanguageSpec:
    id: str
    name: str
    extension: str
    filename: str
    highlight_mode: str
    compile_cmd: Optional[List[str]]
    run_cmd: List[str]
    default_starter_code: str
    binary_name: Optional[str] = None

    @lru_cache(maxsize=32)
    def check_availability(self) -> Tuple[bool, str, str]:
        """
        Verifies if the required compiler/runtime is genuinely installed and executable.
        Returns: (is_available, version_string, missing_reason)
        """
        if self.id == "python":
            py_ver = f"Python {sys.version.split()[0]}"
            return True, py_ver, ""

        if self.id in ("c", "cpp"):
            compiler = "gcc" if self.id == "c" else "g++"
            compiler_path = shutil.which(compiler)
            if not compiler_path:
                compiler = "clang" if self.id == "c" else "clang++"
                compiler_path = shutil.which(compiler)

            if not compiler_path:
                return False, "", f"Neither {self.id} compiler (gcc/clang) was found in PATH."

            try:
                res = subprocess.run([compiler_path, "--version"], capture_output=True, text=True, timeout=2)
                ver = (res.stdout or res.stderr).splitlines()[0]
                return True, ver, ""
            except Exception as e:
                return False, "", f"Failed to invoke {compiler}: {e}"

        if self.id == "java":
            javac_path = shutil.which("javac")
            java_path = shutil.which("java")
            if not javac_path or not java_path:
                return False, "", "Java Development Kit (JDK/javac) or runtime (java) is not installed."
            try:
                res = subprocess.run([javac_path, "-version"], capture_output=True, text=True, timeout=2)
                output = (res.stdout or res.stderr).strip()
                if "Unable to locate a Java Runtime" in output or res.returncode != 0:
                    return False, "", "Unable to locate a Java Runtime on this system (requires JDK)."
                return True, output.splitlines()[0], ""
            except Exception as e:
                return False, "", f"Failed to invoke javac: {e}"

        return False, "", f"Unknown language identifier: {self.id}"

    def get_compile_command(self):
        """Return the same compiler executable that availability detection resolves."""
        if self.id in ("c", "cpp"):
            candidates = ("gcc", "clang") if self.id == "c" else ("g++", "clang++")
            compiler = next((shutil.which(name) for name in candidates if shutil.which(name)), None)
            if compiler:
                return [compiler, *self.compile_cmd[1:]]
        return list(self.compile_cmd) if self.compile_cmd else None


PYTHON_STARTER = """import sys


def solve():
    # Read input from standard input
    input_data = sys.stdin.read().split()
    if not input_data:
        return

    # TODO: Implement your solution here


if __name__ == "__main__":
    solve()
"""

C_STARTER = """#include <stdio.h>
#include <stdlib.h>

int main(void) {
    // TODO: Read input from standard input and implement your solution

    return 0;
}
"""

CPP_STARTER = """#include <iostream>
#include <vector>
#include <string>
#include <algorithm>

using namespace std;

int main() {
    ios_base::sync_with_stdio(false);
    cin.tie(NULL);

    // TODO: Read input from standard input and implement your solution

    return 0;
}
"""

JAVA_STARTER = """import java.util.*;
import java.io.*;

public class Main {
    public static void main(String[] args) throws Exception {
        BufferedReader reader = new BufferedReader(new InputStreamReader(System.in));
        // TODO: Read input from standard input and implement your solution

    }
}
"""


class LanguageRegistry:
    """
    Central repository of configured languages and runtime execution adapters.
    """

    _REGISTRY: Dict[str, LanguageSpec] = {
        "python": LanguageSpec(
            id="python",
            name="Python 3",
            extension=".py",
            filename="main.py",
            highlight_mode="python",
            compile_cmd=None,
            run_cmd=[sys.executable, "-I", "main.py"],
            default_starter_code=PYTHON_STARTER,
        ),
        "c": LanguageSpec(
            id="c",
            name="C (C11)",
            extension=".c",
            filename="main.c",
            highlight_mode="c",
            compile_cmd=["gcc", "-O2", "-std=c11", "main.c", "-o", "a.out"],
            run_cmd=["./a.out"],
            binary_name="a.out",
            default_starter_code=C_STARTER,
        ),
        "cpp": LanguageSpec(
            id="cpp",
            name="C++ (C++17)",
            extension=".cpp",
            filename="main.cpp",
            highlight_mode="cpp",
            compile_cmd=["g++", "-O2", "-std=c++17", "main.cpp", "-o", "a.out"],
            run_cmd=["./a.out"],
            binary_name="a.out",
            default_starter_code=CPP_STARTER,
        ),
        "java": LanguageSpec(
            id="java",
            name="Java (OpenJDK)",
            extension=".java",
            filename="Main.java",
            highlight_mode="java",
            compile_cmd=["javac", "Main.java"],
            run_cmd=["java", "-Xmx256m", "-Xss32m", "Main"],
            default_starter_code=JAVA_STARTER,
        ),
    }

    @classmethod
    def get(cls, lang_id: str) -> Optional[LanguageSpec]:
        if not lang_id:
            return None
        return cls._REGISTRY.get(lang_id.strip().lower())

    @classmethod
    def get_supported_languages(cls) -> Dict[str, LanguageSpec]:
        """
        Returns only languages whose compilers/runtimes are verified available on this host.
        """
        from django.conf import settings
        if getattr(settings, "CODE_EXECUTION_BACKEND", "local") == "container":
            # Language support is provided by the pinned runner image, not host compilers.
            return dict(cls._REGISTRY)
        supported = {}
        for lang_id, spec in cls._REGISTRY.items():
            avail, _, _ = spec.check_availability()
            if avail:
                supported[lang_id] = spec
        return supported

    @classmethod
    def get_supported_language_ids(cls) -> List[str]:
        return list(cls.get_supported_languages().keys())

    @classmethod
    def get_choices(cls) -> List[Tuple[str, str]]:
        """Choices tuple for forms and dropdowns (only supported languages)."""
        return [(spec.id, spec.name) for spec in cls.get_supported_languages().values()]

    @classmethod
    def get_all_choices(cls) -> List[Tuple[str, str]]:
        """All choices including planned languages (for admin template authoring)."""
        return [(spec.id, spec.name) for spec in cls._REGISTRY.values()]

    @classmethod
    def get_default_starter_code(cls, lang_id: str) -> str:
        spec = cls.get(lang_id)
        if spec:
            return spec.default_starter_code
        return "// Write your solution here\n"

    @classmethod
    def is_supported(cls, lang_id: str) -> bool:
        spec = cls.get(lang_id)
        if not spec:
            return False
        from django.conf import settings
        if getattr(settings, "CODE_EXECUTION_BACKEND", "local") == "container":
            return bool(shutil.which(getattr(settings, "CODE_EXECUTION_CONTAINER_RUNTIME", "podman")))
        avail, _, _ = spec.check_availability()
        return avail

    @classmethod
    def get_diagnostics(cls) -> List[Dict]:
        """Diagnostic report for admin health monitoring and system diagnostics."""
        report = []
        for lang_id, spec in cls._REGISTRY.items():
            avail, ver, reason = spec.check_availability()
            report.append({
                "id": spec.id,
                "name": spec.name,
                "available": avail,
                "version": ver,
                "reason": reason,
                "filename": spec.filename,
                "has_compile_step": spec.compile_cmd is not None,
            })
        return report

