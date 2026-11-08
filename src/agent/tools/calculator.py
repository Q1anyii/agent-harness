"""计算器工具：安全求值四则运算表达式（防注入）。"""
from __future__ import annotations

import ast
import operator

from .base import Tool, register

_ALLOWED_OPS: dict[type[ast.operator], object] = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
    ast.USub: operator.neg,
    ast.UAdd: operator.pos,
}

_ALLOWED_NODES = tuple(_ALLOWED_OPS.keys()) + (ast.Expression, ast.BinOp, ast.UnaryOp, ast.Constant)


def _validate(tree: ast.AST) -> None:
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant):
            if isinstance(node.value, bool) or not isinstance(node.value, (int, float)):
                raise ValueError(f"仅支持数字常量，不支持: {type(node.value).__name__}")
        elif not isinstance(node, _ALLOWED_NODES):
            raise ValueError(f"不支持的语法节点: {type(node).__name__}")


def evaluate(expression: str) -> float:
    """安全求值：AST 白名单 + 无内置命名空间，杜绝 eval 注入。"""
    text = expression.strip()
    if not text:
        raise ValueError("表达式为空")
    try:
        tree = ast.parse(text, mode="eval")
    except SyntaxError as e:
        raise ValueError(f"表达式语法错误: {e.msg}") from e
    _validate(tree)
    code = compile(tree, "<expr>", "eval")
    try:
        return float(eval(code, {"__builtins__": {}}, {}))  # noqa: S307 - 白名单已校验
    except ZeroDivisionError as e:
        raise ZeroDivisionError("除数不能为 0") from e


async def run(expression: str) -> str:
    try:
        value = evaluate(expression)
    except ZeroDivisionError:
        return "错误：除数不能为 0"
    except ValueError as e:
        return f"错误：{e}"
    except OverflowError:
        return "错误：数值溢出"
    return f"{expression.strip()} = {value}"


register(Tool(
    name="calculator",
    description="计算数学表达式，支持 + - * / % ** 和括号。",
    parameters={
        "type": "object",
        "properties": {
            "expression": {
                "type": "string",
                "description": "要计算的数学表达式，例如 1+2*3、(10-4)/2",
            },
        },
        "required": ["expression"],
    },
    handler=run,
))
