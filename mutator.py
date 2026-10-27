"""
Генератор мутантів на основі AST з фіксацією типу мутації.

Оператори (типові набори mutmut / PIT):
  ROR - заміна оператора порівняння (<, <=, >, >=, ==, !=, in, is)
  AOR - заміна арифметичного оператора (+, -, *, /, //, %, **)
  LCR - заміна логічного оператора (and <-> or)
  UOD - видалення унарного оператора (not x -> x, -x -> x)
  CRP - заміна константи (n -> n+1, n -> n-1, True <-> False)
"""
import ast
import copy
from dataclasses import dataclass, asdict

ROR_MAP = {
    ast.Lt: [ast.LtE, ast.GtE],
    ast.LtE: [ast.Lt, ast.Gt],
    ast.Gt: [ast.GtE, ast.LtE],
    ast.GtE: [ast.Gt, ast.Lt],
    ast.Eq: [ast.NotEq],
    ast.NotEq: [ast.Eq],
    ast.In: [ast.NotIn],
    ast.NotIn: [ast.In],
    ast.Is: [ast.IsNot],
    ast.IsNot: [ast.Is],
}
AOR_MAP = {
    ast.Add: [ast.Sub],
    ast.Sub: [ast.Add],
    ast.Mult: [ast.FloorDiv],
    ast.Div: [ast.Mult],
    ast.FloorDiv: [ast.Mult, ast.Div],
    ast.Mod: [ast.FloorDiv],
    ast.Pow: [ast.Mult],
}
LCR_MAP = {ast.And: [ast.Or], ast.Or: [ast.And]}


@dataclass
class Mutant:
    id: str
    operator: str      # ROR / AOR / LCR / UOD / CRP
    line: int          # номер рядка
    source_line: str   # рядок вихідного коду, де внесено зміну
    before: str        # фрагмент до зміни
    after: str         # фрагмент після зміни
    code: str          # повний код мутанта

    def to_dict(self):
        d = asdict(self)
        d.pop("code")
        return d


def _sites(tree):
    """Перелічує всі можливі точки мутації: (вузол, оператор, індекс варіанта)."""
    sites = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Compare):
            for i, op in enumerate(node.ops):
                for alt in ROR_MAP.get(type(op), []):
                    sites.append((node, "ROR", (i, alt)))
        elif isinstance(node, (ast.BinOp, ast.AugAssign)):
            for alt in AOR_MAP.get(type(node.op), []):
                sites.append((node, "AOR", alt))
        elif isinstance(node, ast.BoolOp):
            for alt in LCR_MAP.get(type(node.op), []):
                sites.append((node, "LCR", alt))
        elif isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.Not, ast.USub)):
            sites.append((node, "UOD", None))
        elif isinstance(node, ast.Constant):
            v = node.value
            if isinstance(v, bool):
                sites.append((node, "CRP", not v))
            elif isinstance(v, int):
                sites.append((node, "CRP", v + 1))
                sites.append((node, "CRP", v - 1))
    return sites


class _Apply(ast.NodeTransformer):
    def __init__(self, target_idx, kind, arg):
        self.target_idx = target_idx
        self.kind = kind
        self.arg = arg
        self.before = self.after = None
        self.line = None

    def _hit(self, node):
        return getattr(node, "_mut_idx", None) == self.target_idx

    def generic_visit(self, node):
        node = super().generic_visit(node)
        if not self._hit(node):
            return node
        self.line = getattr(node, "lineno", None)
        self.before = ast.unparse(node)
        if self.kind == "ROR":
            i, alt = self.arg
            node.ops[i] = alt()
        elif self.kind in ("AOR", "LCR"):
            node.op = self.arg()
        elif self.kind == "UOD":
            new = node.operand
            self.after = ast.unparse(new)
            return new
        elif self.kind == "CRP":
            node.value = self.arg
        self.after = ast.unparse(node)
        return node


def generate_mutants(code: str, prefix: str = "m"):
    """Повертає список унікальних мутантів для заданого коду."""
    base_tree = ast.parse(code)
    original_norm = ast.unparse(base_tree)
    src_lines = code.splitlines()
    n_sites = len(_sites(base_tree))
    seen = {original_norm}
    mutants = []
    for k in range(n_sites):
        tree = copy.deepcopy(base_tree)
        site_list = _sites(tree)
        node, kind, arg = site_list[k]
        node._mut_idx = k
        applier = _Apply(k, kind, arg)
        try:
            new_tree = applier.visit(tree)
            ast.fix_missing_locations(new_tree)
            new_code = ast.unparse(new_tree)
            compile(new_code, "<mutant>", "exec")
        except Exception:
            continue
        if new_code in seen:
            continue
        seen.add(new_code)
        line = applier.line or 0
        mutants.append(Mutant(
            id=f"{prefix}{len(mutants):03d}",
            operator=kind,
            line=line,
            source_line=src_lines[line - 1].strip() if 0 < line <= len(src_lines) else "",
            before=applier.before or "",
            after=applier.after or "",
            code=new_code,
        ))
    return mutants


if __name__ == "__main__":
    demo = "def can_vote(age):\n    return age > 18 and not age < 0\n"
    for m in generate_mutants(demo):
        print(m.id, m.operator, f"`{m.before}` -> `{m.after}`")
