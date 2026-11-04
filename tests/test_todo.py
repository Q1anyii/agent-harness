"""todo 工具测试：add/list/done 正常流与异常边界。"""
from __future__ import annotations

import pytest

import agent.tools.todo as todo_mod
from agent.tools.todo import run


@pytest.fixture(autouse=True)
def _clean_todos() -> None:
    """每个用例前清空内存待办表，避免用例间状态污染。"""
    todo_mod._TODOS.clear()
    todo_mod._NEXT_ID = 1
    yield


# ---------- 正常路径 ----------

def test_todo_add_and_list():
    result = run("add", "买牛奶")
    assert "已添加待办：买牛奶" in result
    result = run("list")
    assert "买牛奶" in result
    assert "[ ] #1 买牛奶" in result


def test_todo_done_marks_completed():
    run("add", "买牛奶")
    run("add", "写周报")
    result = run("done", "1")
    assert "已完成待办：买牛奶" in result
    # 完成项标记为 [x]
    listed = run("list")
    assert "[x] #1 买牛奶" in listed
    assert "[ ] #2 写周报" in listed


def test_todo_done_by_text():
    run("add", "买牛奶")
    result = run("done", "买牛奶")
    assert "已完成待办：买牛奶" in result


def test_todo_list_empty():
    assert "当前没有待办事项" in run("list")


# ---------- 异常与边界 ----------

def test_todo_invalid_action():
    assert "错误" in run("delete")


def test_todo_missing_action():
    assert "错误" in run(None)


def test_todo_add_empty_text():
    assert "错误" in run("add", "   ")


def test_todo_done_empty_text():
    assert "错误" in run("done", "  ")


def test_todo_done_not_found():
    run("add", "买牛奶")
    assert "找不到待办" in run("done", "999")


def test_todo_done_not_found_by_text():
    assert "找不到待办" in run("done", "不存在的待办")
