from .runner import run_code


def normalize(text):
    """Ignore trailing spaces on each line and blank lines at the end."""
    lines = [line.rstrip() for line in (text or "").replace("\r\n", "\n").split("\n")]
    while lines and lines[-1] == "":
        lines.pop()
    return "\n".join(lines)


def judge(question, language, code):
    """Run code against every test case of a CodingQuestion.

    Returns a dict: verdict, passed, total, score, results
    results holds one entry per test case: {"n", "verdict", "sample"}
    (hidden cases never include their input or expected output).
    """
    results = []
    passed = 0
    earned = 0
    total_marks = 0
    first_failure = None

    testcases = list(question.testcases.all().order_by("id"))

    for n, tc in enumerate(testcases, start=1):
        total_marks += tc.marks
        res = run_code(language, code, tc.input_data, question.time_limit_seconds)

        if res["status"] == "compile_error":
            v = "Compilation Error"
            first_failure = v
            results.append({"n": n, "verdict": v, "sample": tc.is_sample})
            for rem_idx, rem_tc in enumerate(testcases[n:], start=n + 1):
                total_marks += rem_tc.marks
                results.append({"n": rem_idx, "verdict": "Compilation Error", "sample": rem_tc.is_sample})
            break
        elif res["status"] == "timeout":
            v = "Time Limit Exceeded"
        elif res["status"] == "runtime_error":
            v = "Runtime Error"
        elif res["status"] == "error":
            v = "Error"
        elif normalize(res["stdout"]) == normalize(tc.expected_output):
            v = "Passed"
        else:
            v = "Wrong Answer"

        if v == "Passed":
            passed += 1
            earned += tc.marks
        elif first_failure is None:
            first_failure = v

        results.append({"n": n, "verdict": v, "sample": tc.is_sample})

    total = len(testcases)
    if total == 0:
        verdict = "No test cases"
    elif passed == total:
        verdict = "Accepted"
    else:
        verdict = first_failure

    score = round(question.marks * earned / total_marks) if total_marks else 0

    return {
        "verdict": verdict,
        "passed": passed,
        "total": total,
        "score": score,
        "results": results,
    }