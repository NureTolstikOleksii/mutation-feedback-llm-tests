"""
Експеримент:
Для кожної функції (версія з дефектом + виправлена) і кожної умови:
  раунд 0     - модель пише 5 тестів для коду з дефектом (однаково для обох умов);
  раунди 1-2  - модель дописує ще по 3 тести:
                  plain    - загальне прохання посилити набір;
                  mutation - список мутантів, яких тести не виявили.

Кожен тест запускається на обох версіях коду й отримує клас:
  detects - падає на коді з дефектом, проходить на виправленому (виявляє дефект)
  locks   - проходить на коді з дефектом, падає на виправленому (закріплює дефект)
  neutral - проходить на обох
  broken  - падає на обох

Запуск:
  python experiment.py --limit 40
"""
import argparse
import ast
import json
import os
import random
import re

import prompts
from llm import LLM
from mutator import generate_mutants
from runner import run_matrix

HERE = os.path.dirname(os.path.abspath(__file__))
CONDITIONS = ("plain", "mutation")
CLASSES = ("detects", "locks", "neutral", "broken")


# ------------------------------------------------ 1. Розбір відповіді моделі

def split_tests(text, entry_point, tag):
    """Витягує з відповіді моделі окремі тестові функції test_*."""
    blocks = re.findall(r"```(?:python|py)?\s*\n(.*?)```", text, re.S)
    src = "\n\n".join(blocks) if blocks else text
    try:
        tree = ast.parse(src)
    except SyntaxError:
        return []

    helpers, tests = [], []
    for node in tree.body:
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            names = [a.name for a in node.names]
            if entry_point in names or getattr(node, "module", "") in ("solution", entry_point):
                continue                      # імпорт тестованої функції не потрібен
            helpers.append(node)
        elif isinstance(node, ast.FunctionDef):
            if node.name == entry_point:
                continue                      # модель переписала функцію - ігноруємо
            (tests if node.name.startswith("test") else helpers).append(node)
        elif isinstance(node, (ast.Assign, ast.AnnAssign)):
            helpers.append(node)

    preamble = "\n".join(ast.unparse(n) for n in helpers)
    result = []
    for i, node in enumerate(tests):
        node.decorator_list = []
        node.name = f"{node.name}__{tag}_{i}"   # унікальне ім'я тесту
        result.append({"name": node.name, "source": ast.unparse(node), "preamble": preamble})
    return result


def suite_text(suite):
    """Код поточного набору тестів одним текстом (для запиту до моделі)."""
    preambles = list(dict.fromkeys(t["preamble"] for t in suite if t["preamble"]))
    return "\n\n".join(preambles + [t["source"] for t in suite])


# ------------------------------------------------ 2. Запуск тестів

def classify(task, tests):
    """Запускає тести на обох версіях коду й визначає клас кожного."""
    on_buggy, on_correct = run_matrix([task["buggy_code"], task["correct_code"]], tests)
    for t in tests:
        pass_buggy = on_buggy.get(t["name"], (False, ""))[0]
        pass_correct = on_correct.get(t["name"], (False, ""))[0]
        if pass_buggy and not pass_correct:
            t["cls"] = "locks"
        elif not pass_buggy and pass_correct:
            t["cls"] = "detects"
        elif pass_buggy:
            t["cls"] = "neutral"
        else:
            t["cls"] = "broken"
    return tests


def killed_mutants(mutants, tests):
    """Для кожного мутанта - список тестів, що його вбивають (на ньому падають)."""
    if not mutants or not tests:
        return {m.id: [] for m in mutants}
    results = run_matrix([m.code for m in mutants], tests)
    return {m.id: [t["name"] for t in tests if not r.get(t["name"], (False, ""))[0]]
            for m, r in zip(mutants, results)}


def fix_like_mutants(task, mutants):
    """Мутанти, що проходять офіційні тести, тобто поводяться як виправлений код."""
    official = [{"name": "test_official", "preamble": task["test"],
                 "source": f"def test_official():\n    check({task['entry_point']})"}]
    results = run_matrix([m.code for m in mutants], official)
    return {m.id for m, r in zip(mutants, results) if r.get("test_official", (False, ""))[0]}


# ------------------------------------------------ 3. Один прогін: функція x умова x повтор

def run_one(task, condition, repeat, llm, args, log):
    rng = random.Random(f"{task['task_id']}|{repeat}")
    code = task["buggy_code_display"]          # те, що бачить модель
    mutants = generate_mutants(task["buggy_code"])
    by_id = {m.id: m for m in mutants}
    fix_like = fix_like_mutants(task, mutants)

    suite = []                                 # тести, що проходять на коді з дефектом
    test_rows, round_rows = [], []

    for rnd in range(args.rounds + 1):
        # 3.1. Складаємо запит
        shown = []
        if rnd == 0:
            prompt = prompts.initial(code, args.n_initial)
        else:
            if condition == "mutation":
                status = killed_mutants(mutants, suite)
                survivors = [m for m in mutants if not status[m.id]]
                rng.shuffle(survivors)
                shown = survivors[:args.max_mutants]
            if shown:
                prompt = prompts.mutation_feedback(code, suite_text(suite),
                                                   [m.to_dict() for m in shown], args.n_new)
            else:   # умова plain або всі мутанти вже вбиті
                prompt = prompts.plain_feedback(code, suite_text(suite), args.n_new)

        # 3.2. Запит до моделі
        answer, usage = llm.chat([{"role": "system", "content": prompts.SYSTEM},
                                  {"role": "user", "content": prompt}])
        log.write(json.dumps({"task_id": task["task_id"], "condition": condition,
                              "repeat": repeat, "round": rnd, "model": llm.model,
                              "prompt": prompt, "response": answer, "usage": usage},
                             ensure_ascii=False) + "\n")

        # 3.3. Розбираємо й класифікуємо тести
        new_tests = classify(task, split_tests(answer, task["entry_point"], f"r{rnd}"))

        # 3.4. Яких із показаних мутантів убиває кожен новий тест
        passing = [t for t in new_tests if t["cls"] in ("locks", "neutral")]
        kills = {t["name"]: [] for t in new_tests}
        for m_id, killers in killed_mutants(shown, passing).items():
            for name in killers:
                kills[name].append(m_id)

        for t in new_tests:
            test_rows.append({
                "task_id": task["task_id"], "bug_type": task.get("bug_type", ""),
                "condition": condition, "repeat": repeat, "round": rnd,
                "test_name": t["name"], "cls": t["cls"],
                "kills_shown": kills[t["name"]],
                "kills_shown_ops": sorted({by_id[k].operator for k in kills[t["name"]]}),
                "kills_fixlike": any(k in fix_like for k in kills[t["name"]]),
                "source": t["source"],
            })

        # 3.5. Оновлюємо набір і записуємо підсумок раунду
        suite += passing
        killed = sum(1 for v in killed_mutants(mutants, suite).values() if v)
        round_rows.append({
            "task_id": task["task_id"], "condition": condition, "repeat": repeat, "round": rnd,
            **{c: sum(1 for t in new_tests if t["cls"] == c) for c in CLASSES},
            "suite_size": len(suite), "n_mutants": len(mutants),
            "n_fixlike_mutants": len(fix_like), "mutants_killed": killed,
            "mutation_score": round(killed / len(mutants), 3) if mutants else None,
            "shown_mutants": [m.to_dict() | {"fixlike": m.id in fix_like} for m in shown],
            "prompt_tokens": usage.get("prompt_tokens", 0),
            "completion_tokens": usage.get("completion_tokens", 0),
        })
    return test_rows, round_rows


# ------------------------------------------------ 4. Вибір функцій і головний цикл

def pick_tasks(tasks, limit, seed):
    """Відбирає limit функцій по черзі з кожного типу дефекту (відтворювано, seed)."""
    if not limit or limit >= len(tasks):
        return tasks
    rng = random.Random(seed)
    by_type = {}
    for t in tasks:
        by_type.setdefault(t.get("bug_type", ""), []).append(t)
    for group in by_type.values():
        rng.shuffle(group)
    picked = []
    while len(picked) < limit:
        for bug_type in sorted(by_type):
            if by_type[bug_type] and len(picked) < limit:
                picked.append(by_type[bug_type].pop())
    return picked


def main():
    ap = argparse.ArgumentParser(description="LLM test generation with mutation feedback")
    ap.add_argument("--data", default=os.path.join(HERE, "data", "humanevalfix_python.jsonl"))
    ap.add_argument("--out", default=os.path.join(HERE, "results"))
    ap.add_argument("--limit", type=int, default=8, help="number of functions (0 = all)")
    ap.add_argument("--repeats", type=int, default=1)
    ap.add_argument("--rounds", type=int, default=2, help="feedback rounds after round 0")
    ap.add_argument("--n-initial", type=int, default=5, help="tests requested in round 0")
    ap.add_argument("--n-new", type=int, default=3, help="tests requested in each feedback round")
    ap.add_argument("--max-mutants", type=int, default=5, help="surviving mutants shown to the model")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--temperature", type=float, default=0.7)
    args = ap.parse_args()

    tasks = [json.loads(line) for line in open(args.data, encoding="utf-8") if line.strip()]
    tasks = pick_tasks(tasks, args.limit, args.seed)

    os.makedirs(args.out, exist_ok=True)
    path = lambda name: os.path.join(args.out, name)
    done = set(open(path("done.txt"), encoding="utf-8").read().split()) if os.path.exists(path("done.txt")) else set()

    llm = LLM(temperature=args.temperature)
    print(f"Model: {llm.model}")
    print(f"Functions: {len(tasks)}, repeats: {args.repeats}, already done: {len(done)}")

    total = len(tasks) * args.repeats * len(CONDITIONS)
    step = 0
    with open(path("tests.jsonl"), "a", encoding="utf-8") as f_tests, \
         open(path("rounds.jsonl"), "a", encoding="utf-8") as f_rounds, \
         open(path("llm_log.jsonl"), "a", encoding="utf-8") as log, \
         open(path("done.txt"), "a", encoding="utf-8") as f_done:
        for repeat in range(args.repeats):
            for task in tasks:
                for condition in CONDITIONS:
                    step += 1
                    key = f"{task['task_id']}|{condition}|{repeat}"
                    if key in done:
                        continue
                    print(f"[{step}/{total}] {task['task_id']}  condition={condition}  repeat={repeat}")
                    test_rows, round_rows = run_one(task, condition, repeat, llm, args, log)
                    for row in test_rows:
                        f_tests.write(json.dumps(row, ensure_ascii=False) + "\n")
                    for row in round_rows:
                        f_rounds.write(json.dumps(row, ensure_ascii=False) + "\n")
                    f_done.write(key + "\n")
                    for f in (f_tests, f_rounds, log, f_done):
                        f.flush()
                    c = {x: sum(1 for t in test_rows if t["cls"] == x) for x in CLASSES}
                    print(f"    tests: {len(test_rows)}  detects={c['detects']}  locks={c['locks']}  "
                          f"neutral={c['neutral']}  broken={c['broken']}")
    print(f"\nDone. Results saved to {args.out}. Next: python analyze.py --out {args.out}")


if __name__ == "__main__":
    main()