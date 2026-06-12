"""
core/expr.py
============
Engine đánh giá BIỂU THỨC an toàn cho Scenario (tính trung bình, sai số…).

KHÔNG dùng eval() thô. Duyệt AST với DANH SÁCH TRẮNG node/toán tử/hàm — chặn
gọi hàm lạ, truy cập thuộc tính, import, lambda, so sánh, indexing…

Cú pháp hỗ trợ:
  - số, tên biến (tra trong `variables`)
  - toán tử:  + - * / % **   và đơn nguyên -x / +x
  - ngoặc ( )
  - list literal:  []  , [1, 2, 3]   (để khởi tạo biến tích lũy)
  - biến đặc biệt:  $last (giá trị đo gần nhất), $iter (chỉ số vòng lặp)
  - hàm:
      abs(x) sqrt(x)
      avg(xs) / mean(xs)   std(xs)   count(xs)   last(xs)   min(...) max(...)
    Các hàm gộp nhận 1 list  (avg(samples))  HOẶC nhiều đối số (avg(1,2,3)).

Ví dụ:
  evaluate("abs(f_avg - f_set)/f_set", {"f_avg": 1.0001e9, "f_set": 1e9})
  evaluate("avg(samples)", {"samples": [10.0, 10.2, 9.9]})
  evaluate("p + 0.5*($iter-1)", {"p": -5, "$iter": 3})
"""

from __future__ import annotations

import ast
import re
import math
import statistics
from typing import Any, Mapping, Optional


class ExprError(Exception):
    """Lỗi cú pháp / runtime khi đánh giá biểu thức (thông báo thân thiện)."""


# $ident  ->  định danh an toàn (ast không parse được ký tự '$')
_DOLLAR = re.compile(r"\$([A-Za-z_]\w*)")


def _dollar_key(name: str) -> str:
    return "__dollar_" + name


def _flatten(args: tuple) -> list:
    """Hàm gộp: nhận 1 list/tuple -> phần tử của nó; ngược lại -> chính các đối số."""
    if len(args) == 1 and isinstance(args[0], (list, tuple)):
        return list(args[0])
    return list(args)


def _need(xs: list, fn: str) -> list:
    if not xs:
        raise ExprError(f"{fn}(): danh sách rỗng")
    return xs


_FUNCS = {
    "abs":   lambda *a: abs(_one(a, "abs")),
    "sqrt":  lambda *a: math.sqrt(_one(a, "sqrt")),
    "avg":   lambda *a: statistics.fmean(_need(_flatten(a), "avg")),
    "mean":  lambda *a: statistics.fmean(_need(_flatten(a), "mean")),
    "std":   lambda *a: statistics.pstdev(_need(_flatten(a), "std")),
    "count": lambda *a: float(len(_flatten(a))),
    "last":  lambda *a: _need(_flatten(a), "last")[-1],
    "min":   lambda *a: min(_need(_flatten(a), "min")),
    "max":   lambda *a: max(_need(_flatten(a), "max")),
}


def _one(args: tuple, fn: str):
    if len(args) != 1:
        raise ExprError(f"{fn}() cần đúng 1 đối số")
    return args[0]


_BINOPS = {
    ast.Add:  lambda a, b: a + b,
    ast.Sub:  lambda a, b: a - b,
    ast.Mult: lambda a, b: a * b,
    ast.Div:  lambda a, b: _div(a, b),
    ast.Mod:  lambda a, b: _mod(a, b),
    ast.Pow:  lambda a, b: a ** b,
}


def _div(a, b):
    if b == 0:
        raise ExprError("chia cho 0")
    return a / b


def _mod(a, b):
    if b == 0:
        raise ExprError("chia lấy dư cho 0")
    return a % b


def _eval(node, names: Mapping[str, Any]):
    if isinstance(node, ast.Constant):
        if isinstance(node.value, bool) or not isinstance(node.value, (int, float)):
            raise ExprError(f"hằng không hợp lệ: {node.value!r}")
        return node.value
    if isinstance(node, ast.Name):
        if node.id not in names:
            disp = node.id.replace("__dollar_", "$")
            raise ExprError(f"biến chưa định nghĩa: {disp}")
        return names[node.id]
    if isinstance(node, ast.BinOp):
        op = _BINOPS.get(type(node.op))
        if op is None:
            raise ExprError("toán tử không cho phép")
        return op(_eval(node.left, names), _eval(node.right, names))
    if isinstance(node, ast.UnaryOp):
        if isinstance(node.op, ast.USub):
            return -_eval(node.operand, names)
        if isinstance(node.op, ast.UAdd):
            return +_eval(node.operand, names)
        raise ExprError("toán tử đơn nguyên không cho phép")
    if isinstance(node, ast.Call):
        if not isinstance(node.func, ast.Name):
            raise ExprError("chỉ cho phép gọi hàm theo tên")
        fn = node.func.id
        if fn not in _FUNCS:
            raise ExprError(f"hàm không hỗ trợ: {fn}")
        if node.keywords:
            raise ExprError(f"{fn}(): không nhận tham số dạng key=value")
        args = [_eval(a, names) for a in node.args]
        try:
            return _FUNCS[fn](*args)
        except ExprError:
            raise
        except Exception as e:  # noqa: BLE001
            raise ExprError(f"lỗi khi gọi {fn}(): {e}") from e
    if isinstance(node, ast.List):
        return [_eval(e, names) for e in node.elts]
    raise ExprError(f"thành phần không cho phép: {type(node).__name__}")


def _prepare(expr: str, variables: Optional[Mapping[str, Any]]):
    safe = _DOLLAR.sub(lambda m: _dollar_key(m.group(1)), expr)
    names: dict[str, Any] = {}
    for k, v in (variables or {}).items():
        names[_dollar_key(k[1:]) if k.startswith("$") else k] = v
    return safe, names


def validate(expr: str) -> None:
    """Kiểm tra CÚ PHÁP (parse) — dùng để validate trước khi chạy. Ném ExprError."""
    safe, _ = _prepare(expr, None)
    try:
        ast.parse(safe, mode="eval")
    except SyntaxError as e:
        raise ExprError(f"sai cú pháp: '{expr}' ({e.msg})") from e


def evaluate(expr: str, variables: Optional[Mapping[str, Any]] = None):
    """Đánh giá biểu thức. Trả số (hoặc list cho list literal). Ném ExprError."""
    if not isinstance(expr, str):
        raise ExprError("biểu thức phải là chuỗi")
    safe, names = _prepare(expr, variables)
    try:
        tree = ast.parse(safe, mode="eval")
    except SyntaxError as e:
        raise ExprError(f"sai cú pháp: '{expr}' ({e.msg})") from e
    return _eval(tree.body, names)
