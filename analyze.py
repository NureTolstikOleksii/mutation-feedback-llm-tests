"""
Аналіз результатів експерименту.

  python analyze.py

Друкує зведення (англійською) і зберігає CSV-таблиці в results/analysis/.

Розділи:
  1. Усі тести за класами
  2. Лише тести раундів зворотного зв'язку (раунди 1-2)
  3. Парне порівняння умов на рівні функцій (ОСНОВНИЙ результат) + статистика
  4. Типи мутацій
  5. Типи дефектів
  6. Мутаційна оцінка та витрати токенів
"""
import argparse
import csv
import json
import math
import os
from collections import Counter, defaultdict

CLASSES = ("detects", "locks", "neutral", "broken")
CONDITIONS = ("plain", "mutation")


# ------------------------------------------------ Допоміжне

def read_jsonl(path):
    if not os.path.exists(path):
        return []
    return [json.loads(line) for line in open(path, encoding="utf-8") if line.strip()]


def save_csv(path, header, rows):
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f, delimiter=";")
        writer.writerow(header)
        writer.writerows(rows)


# ------------------------------------------------ Статистичні тести

def mcnemar_exact(b, c):
    """Точний двосторонній тест Мак-Немара.
    b - пари, де ознака є лише в mutation; c - лише в plain."""
    n = b + c
    if n == 0:
        return 1.0
    p = 2 * sum(math.comb(n, i) for i in range(min(b, c) + 1)) / 2 ** n
    return min(p, 1.0)


def wilcoxon(diffs):
    """Двосторонній знаково-ранговий критерій Вілкоксона (нормальне наближення).
    Повертає (z, p, кількість ненульових різниць)."""
    d = [x for x in diffs if x != 0]
    n = len(d)
    if n == 0:
        return 0.0, 1.0, 0
    order = sorted(range(n), key=lambda i: abs(d[i]))
    ranks = [0.0] * n
    i = 0
    while i < n:                              # однаковим значенням - середній ранг
        j = i
        while j + 1 < n and abs(d[order[j + 1]]) == abs(d[order[i]]):
            j += 1
        for k in range(i, j + 1):
            ranks[order[k]] = (i + j) / 2 + 1
        i = j + 1
    w_plus = sum(r for r, x in zip(ranks, d) if x > 0)
    mean = n * (n + 1) / 4
    sd = math.sqrt(n * (n + 1) * (2 * n + 1) / 24)
    z = (w_plus - mean) / sd
    return z, math.erfc(abs(z) / math.sqrt(2)), n


# ------------------------------------------------ Розділи аналізу

def class_table(tests, title, csv_path):
    print(f"\n=== {title} ===")
    rows = []
    for cond in CONDITIONS:
        cnt = Counter(t["cls"] for t in tests if t["condition"] == cond)
        total = sum(cnt.values())
        share = 100 * cnt["locks"] / total if total else 0
        rows.append([cond, total] + [cnt[c] for c in CLASSES] + [f"{share:.1f}"])
        print(f"{cond:9s} total={total:4d}  " + "  ".join(f"{c}={cnt[c]}" for c in CLASSES)
              + f"  locks share={share:.1f}%")
    save_csv(csv_path, ["condition", "total", *CLASSES, "locks_%"], rows)


def paired_comparison(tests, rounds, title, csv_path, min_round):
    """Порівняння plain і mutation для однієї й тієї самої функції."""
    print(f"\n=== {title} ===")
    # pairs[(функція, повтор)][умова] = {"locks": .., "detects": ..}
    pairs = defaultdict(lambda: {c: {"locks": 0, "detects": 0} for c in CONDITIONS})
    for r in rounds:                          # функції без тестів теж враховуються (з нулями)
        pairs[(r["task_id"], r["repeat"])]
    for t in tests:
        pair = pairs[(t["task_id"], t["repeat"])]
        if t["round"] >= min_round and t["cls"] in ("locks", "detects"):
            pair[t["condition"]][t["cls"]] += 1

    n = len(pairs)
    print(f"pairs (function x repeat): {n}")
    for metric in ("locks", "detects"):
        has_p = [v["plain"][metric] > 0 for v in pairs.values()]
        has_m = [v["mutation"][metric] > 0 for v in pairs.values()]
        only_m = sum(m and not p for p, m in zip(has_p, has_m))
        only_p = sum(p and not m for p, m in zip(has_p, has_m))
        diffs = [v["mutation"][metric] - v["plain"][metric] for v in pairs.values()]
        z, p_w, nz = wilcoxon(diffs)
        print(f"[{metric}] functions with >=1 such test: plain={sum(has_p)}/{n}  mutation={sum(has_m)}/{n}")
        print(f"    only in mutation={only_m}, only in plain={only_p}, McNemar exact p={mcnemar_exact(only_m, only_p):.3f}")
        print(f"    test count (mutation - plain): sum={sum(diffs)}, Wilcoxon z={z:.2f}, p={p_w:.3f} "
              f"(non-zero pairs: {nz})")
    if n < 20:
        print("    (small sample: p-values are only indicative)")

    save_csv(csv_path,
             ["task_id", "repeat", "locks_plain", "locks_mutation", "detects_plain", "detects_mutation"],
             [[k[0], k[1], v["plain"]["locks"], v["mutation"]["locks"],
               v["plain"]["detects"], v["mutation"]["detects"]] for k, v in sorted(pairs.items())])


def mutation_operators(tests, rounds, csv_path):
    print("\n=== 4. Mutation operators (mutation condition, rounds >= 1) ===")
    shown = Counter(m["operator"] for r in rounds if r["condition"] == "mutation"
                    for m in r.get("shown_mutants", []))
    killed_by_locks, killed_by_neutral = Counter(), Counter()
    for t in tests:
        if t["condition"] == "mutation" and t["round"] >= 1:
            target = killed_by_locks if t["cls"] == "locks" else killed_by_neutral
            target.update(t.get("kills_shown_ops", []))
    rows = []
    for op in sorted(set(shown) | set(killed_by_locks) | set(killed_by_neutral)):
        rows.append([op, shown[op], killed_by_locks[op], killed_by_neutral[op]])
        print(f"{op}: shown={shown[op]:3d}  killed by locking tests={killed_by_locks[op]:3d}  "
              f"killed by neutral tests={killed_by_neutral[op]:3d}")
    save_csv(csv_path, ["operator", "shown_to_model", "killed_by_locking_tests", "killed_by_neutral_tests"], rows)

    locking = [t for t in tests if t["condition"] == "mutation" and t["round"] >= 1 and t["cls"] == "locks"]
    if locking:
        fx = sum(1 for t in locking if t.get("kills_fixlike"))
        print(f"locking tests that kill a fix-like mutant: {fx}/{len(locking)}")


def bug_types(tests, csv_path):
    print("\n=== 5. Locking tests by bug type (rounds >= 1; all rounds in brackets) ===")
    rows = []
    for bug in sorted({t["bug_type"] for t in tests}):
        def count(cond, min_round):
            return sum(1 for t in tests if t["bug_type"] == bug and t["condition"] == cond
                       and t["cls"] == "locks" and t["round"] >= min_round)
        fb = [count(c, 1) for c in CONDITIONS]
        allr = [count(c, 0) for c in CONDITIONS]
        rows.append([bug or "-"] + fb + allr)
        print(f"{bug or '-':18s} " + "  ".join(f"{c}={v} ({a})" for c, v, a in zip(CONDITIONS, fb, allr)))
    save_csv(csv_path, ["bug_type", *(f"{c}_rounds_1_2" for c in CONDITIONS),
                        *(f"{c}_all_rounds" for c in CONDITIONS)], rows)


def score_and_cost(rounds):
    print("\n=== 6. Final mutation score (on buggy code) and token cost ===")
    last = {}
    for r in rounds:
        key = (r["task_id"], r["condition"], r["repeat"])
        if key not in last or r["round"] > last[key]["round"]:
            last[key] = r
    for cond in CONDITIONS:
        scores = [r["mutation_score"] for r in last.values()
                  if r["condition"] == cond and r["mutation_score"] is not None]
        tokens = sum(r["prompt_tokens"] + r["completion_tokens"] for r in rounds if r["condition"] == cond)
        if scores:
            print(f"{cond:9s} mean mutation score={sum(scores) / len(scores):.3f}   tokens={tokens}")


# ------------------------------------------------ main

def main():
    ap = argparse.ArgumentParser(description="Analyse experiment results")
    ap.add_argument("--out", default="results")
    args = ap.parse_args()

    tests = read_jsonl(os.path.join(args.out, "tests.jsonl"))
    rounds = read_jsonl(os.path.join(args.out, "rounds.jsonl"))
    if not tests:
        raise SystemExit("No results found. Run experiment.py first.")
    out_dir = os.path.join(args.out, "analysis")
    os.makedirs(out_dir, exist_ok=True)
    csv = lambda name: os.path.join(out_dir, name)

    class_table(tests, "1. All generated tests", csv("1_classes.csv"))
    class_table([t for t in tests if t["round"] >= 1],
                "2. Tests added in feedback rounds (rounds >= 1)", csv("2_feedback_rounds.csv"))
    paired_comparison(tests, rounds, "3a. Paired comparison, feedback rounds only (MAIN RESULT)",
                      csv("3_per_function_feedback.csv"), min_round=1)
    paired_comparison(tests, rounds, "3b. Paired comparison, all rounds",
                      csv("3_per_function_all.csv"), min_round=0)
    mutation_operators(tests, rounds, csv("4_mutation_operators.csv"))
    bug_types(tests, csv("5_bug_types.csv"))
    score_and_cost(rounds)
    print(f"\nCSV tables saved to {out_dir}")


if __name__ == "__main__":
    main()