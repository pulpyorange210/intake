"""Exact decimal arithmetic tool, so the model never does money math in its head.

Results are only treated as grounded if every operand is itself grounded: a number printed
in the document, a previous grounded result, or a small integer (counts, months, percent base).
"""
from __future__ import annotations

import ast
import operator
from decimal import Decimal, DivisionByZero, InvalidOperation, getcontext
from typing import Set, Tuple

from .pdf import cents

getcontext().prec = 28

SMALL_INT_LIMIT = 1000

_BINOPS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
}


class ComputeError(ValueError):
    pass


def evaluate(expression: str, grounded: Set[Decimal]) -> Tuple[Decimal, bool]:
    """Evaluate +,-,*,/ and round(x, n) over decimals. Returns (value, all_operands_grounded)."""
    try:
        tree = ast.parse(expression.strip(), mode="eval")
    except SyntaxError as exc:
        raise ComputeError(f"could not parse expression: {exc.msg}. Use plain numbers without thousands separators.")

    operands_grounded = True

    def walk(node) -> Decimal:
        nonlocal operands_grounded
        if isinstance(node, ast.Expression):
            return walk(node.body)
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)) and not isinstance(node.value, bool):
            value = Decimal(str(node.value))
            is_small_int = value == value.to_integral_value() and abs(value) <= SMALL_INT_LIMIT
            if not is_small_int and cents(value) not in grounded:
                operands_grounded = False
            return value
        if isinstance(node, ast.BinOp) and type(node.op) in _BINOPS:
            return _BINOPS[type(node.op)](walk(node.left), walk(node.right))
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.USub, ast.UAdd)):
            value = walk(node.operand)
            return -value if isinstance(node.op, ast.USub) else value
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "round"
                and len(node.args) in (1, 2) and not node.keywords):
            value = walk(node.args[0])
            places = int(walk(node.args[1])) if len(node.args) == 2 else 0
            return value.quantize(Decimal(1).scaleb(-places))
        raise ComputeError(f"unsupported syntax: {ast.dump(node)[:80]}. Allowed: numbers, + - * /, parentheses, round(x, n).")

    try:
        value = walk(tree)
    except (DivisionByZero, InvalidOperation) as exc:
        raise ComputeError(f"arithmetic error: {exc!r}")
    return value, operands_grounded
