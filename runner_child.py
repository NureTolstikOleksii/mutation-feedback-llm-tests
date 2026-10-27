"""
Дочірній процес: для кожної версії коду (оригінал, мутанти) виконує набір тестів
і друкує результат кожного тесту окремим рядком JSON.
Запускається з runner.py в ізольованому режимі (python -I).

Формат виводу:
  {"c": i, "ready": true}                       - код версії i завантажено
  {"c": i, "name": ..., "ok": ..., "err": ...}  - результат тесту
"""
import json
import sys
import traceback


def main():
    payload = json.load(open(sys.argv[1], encoding="utf-8"))
    start_c, start_t = payload.get("start", [0, 0])
    try:
        import pytest
    except Exception:
        pytest = None
    tests = payload["tests"]
    compiled = {}
    for ci in range(start_c, len(payload["codes"])):
        base_ns = {"__name__": "solution"}
        if pytest:
            base_ns["pytest"] = pytest
        code_error = None
        try:
            exec(compile(payload["codes"][ci], "<solution>", "exec"), base_ns)
        except Exception as e:
            code_error = f"code: {type(e).__name__}: {e}"
        sys.stdout.write(json.dumps({"c": ci, "ready": True}) + "\n")
        sys.stdout.flush()
        first = start_t if ci == start_c else 0
        for t in tests[first:]:
            if code_error:
                res = {"c": ci, "name": t["name"], "ok": False, "err": code_error}
            else:
                ns = dict(base_ns)
                try:
                    key = t["name"]
                    if key not in compiled:
                        compiled[key] = compile(t.get("preamble", "") + "\n" + t["source"], "<tests>", "exec")
                    exec(compiled[key], ns)
                    ns[t["name"]]()
                    res = {"c": ci, "name": t["name"], "ok": True, "err": ""}
                except BaseException as e:  # noqa: BLE001
                    if isinstance(e, KeyboardInterrupt):
                        raise
                    msg = traceback.format_exception_only(type(e), e)[-1].strip()
                    res = {"c": ci, "name": t["name"], "ok": False, "err": msg[:300]}
            sys.stdout.write(json.dumps(res) + "\n")
            sys.stdout.flush()


if __name__ == "__main__":
    main()
