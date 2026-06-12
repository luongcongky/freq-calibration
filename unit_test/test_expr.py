"""
unit_test/test_expr.py
======================
Test engine biểu thức an toàn core/expr.py.
"""

import math
import pytest

from core.expr import evaluate, validate, ExprError


# ---------------------------------------------------------------------------
# Số học cơ bản + ưu tiên toán tử
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("expr,expected", [
    ("1 + 2 * 3", 7),
    ("(1 + 2) * 3", 9),
    ("2 ** 10", 1024),
    ("10 / 4", 2.5),
    ("10 % 3", 1),
    ("-5 + 2", -3),
    ("-(3 + 4)", -7),
    ("1e9 * 2", 2e9),
])
def test_arithmetic(expr, expected):
    assert evaluate(expr) == pytest.approx(expected)


# ---------------------------------------------------------------------------
# Biến thường + biến đặc biệt $last, $iter
# ---------------------------------------------------------------------------

def test_variables():
    assert evaluate("a + b", {"a": 3, "b": 4}) == 7


def test_dollar_last_iter():
    assert evaluate("$last * 2", {"$last": 50.0}) == 100.0
    assert evaluate("p + 0.5*($iter-1)", {"p": -5, "$iter": 3}) == pytest.approx(-4.0)


def test_undefined_variable_raises():
    with pytest.raises(ExprError, match="biến chưa định nghĩa: x"):
        evaluate("x + 1")
    with pytest.raises(ExprError, match=r"biến chưa định nghĩa: \$last"):
        evaluate("$last + 1")


# ---------------------------------------------------------------------------
# Hàm gộp: avg/mean/std/count/last/min/max + abs/sqrt
# ---------------------------------------------------------------------------

def test_aggregate_on_list():
    v = {"s": [10.0, 10.2, 9.8]}
    assert evaluate("avg(s)", v) == pytest.approx(10.0)
    assert evaluate("mean(s)", v) == pytest.approx(10.0)
    assert evaluate("count(s)", v) == 3
    assert evaluate("last(s)", v) == 9.8
    assert evaluate("min(s)", v) == 9.8
    assert evaluate("max(s)", v) == 10.2


def test_aggregate_on_args():
    assert evaluate("avg(1, 2, 3)") == pytest.approx(2.0)
    assert evaluate("max(1, 5, 3)") == 5


def test_std_population():
    # pstdev([10,10,10]) = 0 ; n=1 không lỗi
    assert evaluate("std(x)", {"x": [10.0, 10.0, 10.0]}) == 0
    assert evaluate("std(x)", {"x": [5.0]}) == 0


def test_abs_sqrt():
    assert evaluate("abs(-7)") == 7
    assert evaluate("sqrt(9)") == 3


# ---------------------------------------------------------------------------
# List literal (khởi tạo biến tích lũy)
# ---------------------------------------------------------------------------

def test_list_literal():
    assert evaluate("[]") == []
    assert evaluate("[1, 2, 3]") == [1, 2, 3]


# ---------------------------------------------------------------------------
# Kịch bản đo độ nhạy: trung bình + sai số tương đối
# ---------------------------------------------------------------------------

def test_sensitivity_expressions():
    v = {"samples": [1.0000001e9, 1.0000000e9, 0.9999999e9], "f_set": 1e9}
    f_avg = evaluate("avg(samples)", v)
    v["f_avg"] = f_avg
    error = evaluate("abs(f_avg - f_set)/f_set", v)
    assert error == pytest.approx(abs(f_avg - 1e9) / 1e9)
    assert error < 1e-6


# ---------------------------------------------------------------------------
# An toàn: chặn mã nguy hiểm / cú pháp lạ
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("expr", [
    "__import__('os')",          # gọi hàm cấm
    "os.system('x')",            # truy cập thuộc tính
    "open('f')",                 # hàm không whitelist
    "(1).__class__",             # thuộc tính
    "a if b else c",             # ternary
    "lambda: 1",                 # lambda
    "[x for x in y]",            # comprehension
    "1 < 2",                     # so sánh (không cho phép trong expr)
    "'string'",                  # hằng chuỗi
])
def test_disallowed_constructs_raise(expr):
    with pytest.raises(ExprError):
        evaluate(expr, {"a": 1, "b": 1, "c": 1, "y": [1]})


def test_divide_by_zero():
    with pytest.raises(ExprError, match="chia cho 0"):
        evaluate("1/0")
    with pytest.raises(ExprError, match="chia cho 0"):
        evaluate("a/b", {"a": 5, "b": 0})


def test_syntax_error():
    with pytest.raises(ExprError, match="sai cú pháp"):
        evaluate("1 +")


def test_validate_ok_and_fail():
    validate("abs(f_avg - f_set)/f_set")     # không ném
    with pytest.raises(ExprError):
        validate("1 + * 2")
