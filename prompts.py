"""
Тексти запитів до моделі. Вони фіксуються ДО основного експерименту
й наводяться в розділі «Методика» статті без змін.
"""

SYSTEM = "You are an experienced Python developer who writes thorough unit tests."

RULES = """Rules:
- Each test is a separate top-level function whose name starts with test_.
- Use plain assert statements; you may use pytest.raises for expected exceptions.
- Do not use fixtures, parametrize, classes or mocks.
- Do not import or redefine the function under test: it is already defined.
- Return only one ```python code block with the tests."""


def initial(code: str, n: int) -> str:
    return f"""Write {n} pytest unit tests for the following Python function.

```python
{code.strip()}
```

{RULES}"""


def plain_feedback(code: str, tests_src: str, n: int) -> str:
    """Умова A: повторна спроба без конкретного зворотного зв'язку."""
    return f"""Here is a Python function and the current unit tests for it.

```python
{code.strip()}
```

Current tests:
```python
{tests_src.strip() or '# (no tests yet)'}
```

Improve the test suite: write {n} additional tests that make it stronger.

{RULES}
Return only the new tests."""


def mutation_feedback(code: str, tests_src: str, mutants: list, n: int) -> str:
    """Умова B: мутаційний зворотний зв'язок (вцілілі мутанти)."""
    lines = []
    for i, m in enumerate(mutants, 1):
        lines.append(f"{i}. In the line `{m['source_line']}`: `{m['before']}` was changed to `{m['after']}`")
    listing = "\n".join(lines)
    return f"""Here is a Python function and the current unit tests for it.

```python
{code.strip()}
```

Current tests:
```python
{tests_src.strip() or '# (no tests yet)'}
```

A mutation testing tool made small changes to the function. The current tests did not detect the following changes (surviving mutants):
{listing}

Write {n} additional tests that detect these changes.

{RULES}
Return only the new tests."""