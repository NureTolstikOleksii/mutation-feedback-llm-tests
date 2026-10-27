"""
Запуск тестів на одній або кількох версіях коду в окремому процесі
з тайм-аутом на КОЖЕН тест.
"""
import json
import os
import queue
import subprocess
import sys
import tempfile
import threading

CHILD = os.path.join(os.path.dirname(os.path.abspath(__file__)), "runner_child.py")
PER_TEST_TIMEOUT = 2.0   # секунд на один тест
STARTUP_TIMEOUT = 15.0   # запуск інтерпретатора / завантаження коду


def _reader(stream, q):
    for line in iter(stream.readline, ""):
        q.put(line)
    q.put(None)


def run_matrix(codes: list, tests: list) -> list:
    """
    Виконує кожен тест на кожній версії коду.
    Повертає список (за версіями) словників {name: (ok, err)}.
    Зациклений тест отримує TIMEOUT; процес перезапускається з наступного тесту.
    """
    n, T = len(codes), len(tests)
    results = [dict() for _ in codes]
    if not n or not T:
        return results
    pos_c, pos_t = 0, 0  # з якої версії коду й якого тесту продовжувати
    while pos_c < n:
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as f:
            json.dump({"codes": codes, "tests": tests, "start": [pos_c, pos_t]}, f)
            path = f.name
        proc = subprocess.Popen(
            [sys.executable, "-I", CHILD, path],
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            text=True, encoding="utf-8", errors="replace",
        )
        q = queue.Queue()
        threading.Thread(target=_reader, args=(proc.stdout, q), daemon=True).start()

        expect_ready = pos_c      # версія, завантаження якої очікуємо (None - виконуються тести)
        cur_c, next_t = pos_c, pos_t
        status, finished = None, False
        while True:
            try:
                line = q.get(timeout=STARTUP_TIMEOUT if expect_ready is not None else PER_TEST_TIMEOUT)
            except queue.Empty:
                status = "TIMEOUT"
                break
            if line is None:
                status = "CRASH"
                break
            try:
                r = json.loads(line)
            except Exception:
                continue
            if r.get("ready"):
                cur_c = r["c"]
                next_t = pos_t if cur_c == pos_c else 0
                expect_ready = None
                continue
            results[r["c"]][r["name"]] = (r["ok"], r["err"])
            next_t += 1
            if next_t >= T:
                if cur_c == n - 1:
                    finished = True
                    break
                expect_ready = cur_c + 1

        if proc.poll() is None:
            proc.kill()
        try:
            proc.wait(timeout=5)
        except Exception:
            pass
        try:
            os.unlink(path)
        except OSError:
            pass

        if finished:
            break
        if expect_ready is not None:
            # код цієї версії не завантажився (завис або впав): її тести вважаються проваленими
            first = pos_t if expect_ready == pos_c else 0
            for t in tests[first:]:
                results[expect_ready][t["name"]] = (False, f"code: {status}")
            pos_c, pos_t = expect_ready + 1, 0
        else:
            results[cur_c][tests[next_t]["name"]] = (False, status)
            pos_c, pos_t = (cur_c, next_t + 1) if next_t + 1 < T else (cur_c + 1, 0)
    return results


def run_tests(code: str, tests: list) -> dict:
    """Тести на одній версії коду. Повертає {name: (ok, err)}."""
    return run_matrix([code], tests)[0]
