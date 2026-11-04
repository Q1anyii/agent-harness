"""工具模块测试：覆盖正常路径、异常路径、边界值、特殊场景。"""
from __future__ import annotations

import pytest

from agent.tools import get_all_tools, get_tool
from agent.tools.calculator import evaluate
from agent.tools.search import run as search_run
from agent.tools.weather import run as weather_run


# ---------- 注册表 ----------

def test_registry_contains_three_required_tools():
    names = {t.name for t in get_all_tools()}
    assert {"calculator", "search", "weather"} <= names


def test_registry_schema_fields_present():
    for t in get_all_tools():
        assert t.name
        assert t.description
        assert t.parameters.get("type") == "object"
        assert "properties" in t.parameters
        assert "required" in t.parameters


def test_get_tool_unknown_returns_none():
    assert get_tool("not_exist") is None


# ---------- calculator ----------

@pytest.mark.parametrize("expr,expected", [
    ("1+2", 3),
    ("1+2*3", 7),
    ("(10-4)/2", 3),
    ("2**10", 1024),
    ("10%3", 1),
    ("-5+3", -2),
    (" 7 * 8 ", 56),
    ("0.5+0.25", 0.75),
])
def test_calculator_normal(expr, expected):
    assert evaluate(expr) == expected


def test_calculator_division_by_zero():
    result = get_tool("calculator").handler("1/0")
    assert "除数不能为 0" in result


@pytest.mark.parametrize("bad", ["", "   ", "abc", "1+", "sqrt(4)", "import os", "__import__('os')", "1;2", "True+1", "'a'+'b'"])
def test_calculator_invalid_or_injection(bad):
    result = get_tool("calculator").handler(bad)
    assert result.startswith("错误："), f"应当返回错误而非执行: {bad!r} -> {result!r}"


def test_calculator_ast_injection_blocked():
    """白名单之外的所有可执行节点必须被拒绝（防注入核心用例）。"""
    with pytest.raises(ValueError):
        evaluate("__import__('os').system('whoami')")
    with pytest.raises(ValueError):
        evaluate("open('README.md').read()")


# ---------- search (mock) ----------

def test_search_normal_hit():
    result = search_run("介绍一下 RAG")
    assert "搜索结果（mock）" in result and "RAG" in result


def test_search_no_hit_fallback():
    result = search_run("量子计算")
    assert "未找到" in result


@pytest.mark.parametrize("bad", [None, "", "   "])
def test_search_empty_query(bad):
    assert "错误" in search_run(bad)


def test_search_case_insensitive():
    assert "搜索结果" in search_run("LangGraph")


# ---------- weather (mock) ----------

def test_weather_normal():
    result = weather_run("北京")
    assert "北京" in result and "℃" in result


def test_weather_unknown_city():
    result = weather_run("火星")
    assert "暂未收录" in result


@pytest.mark.parametrize("bad", [None, "", "  "])
def test_weather_missing_city(bad):
    assert "错误" in weather_run(bad)


def test_weather_known_cities_cover():
    for city in ["上海", "广州", "赣州"]:
        assert "天气查询" in weather_run(city)
