"""todo 工具测试：add/list/done 正常流与异常边界。"""
from __future__ import annotations

import asyncio

import pytest

import agent.tools.todo as todo_mod
from agent.tools.todo import run


def _run(*args):
    """驱动 async 工具（不引入 pytest-asyncio 依赖）。"""
    return asyncio.run(run(*args))


@pytest.fixture(autouse=True)
def _clean_todos() -> None:
    """每个用例前清空内存待办表，避免用例间状态污染。"""
    todo_mod._TODOS.clear()
    todo_mod._NEXT_ID = 1
    yield


# ---------- 正常路径 ----------

def test_todo_add_and_list():
    result = _run("add", "买牛奶")
    assert "已添加待办：买牛奶" in result
    result = _run("list")
    assert "买牛奶" in result
    assert "[ ] #1 买牛奶" in result


def test_todo_done_marks_completed():
    _run("add", "买牛奶")
    _run("add", "写周报")
    result = _run("done", "1")
    assert "已完成待办：买牛奶" in result
    # 完成项标记为 [x]
    listed = _run("list")
    assert "[x] #1 买牛奶" in listed
    assert "[ ] #2 写周报" in listed


def test_todo_done_by_text():
    _run("add", "买牛奶")
    result = _run("done", "买牛奶")
    assert "已完成待办：买牛奶" in result


def test_todo_list_empty():
    assert "当前没有待办事项" in _run("list")


# ---------- 异常与边界 ----------

def test_todo_invalid_action():
    assert "错误" in _run("delete")


def test_todo_missing_action():
    assert "错误" in _run(None)


def test_todo_add_empty_text():
    assert "错误" in _run("add", "   ")


def test_todo_done_empty_text():
    assert "错误" in _run("done", "  ")


def test_todo_done_not_found():
    _run("add", "买牛奶")
    assert "找不到待办" in _run("done", "999")


def test_todo_done_not_found_by_text():
    assert "找不到待办" in _run("done", "不存在的待办")
