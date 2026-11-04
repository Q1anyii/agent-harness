"""工具路由测试：命中/未命中/参数提取/边界。"""
from __future__ import annotations

import pytest

from agent.router import extract_args, route


# ---------- 路由命中 ----------

@pytest.mark.parametrize("query,expected", [
    ("帮我计算 1+2*3", "calculator"),
    ("算一下 (10-4)/2", "calculator"),
    ("搜索一下 RAG 是什么", "search"),
    ("介绍一下 agent", "search"),
    ("北京天气怎么样", "weather"),
    ("今天多少度", "weather"),
])
def test_route_hit(query, expected):
    assert route(query) == expected


@pytest.mark.parametrize("query", [
    "你好", "你是谁", "讲个笑话", "今天过得怎么样", "谢谢", "",
    None, "   ",
])
def test_route_no_hit(query):
    assert route(query) is None


# ---------- 参数提取 ----------

def test_extract_calculator_expression():
    args = extract_args("calculator", "帮我计算 1+2*3")
    assert args["expression"].replace(" ", "") in ("1+2*3", "1+2*3")


def test_extract_calculator_no_expression():
    args = extract_args("calculator", "帮我计算一下")
    assert args["expression"] == ""


def test_extract_search_query():
    args = extract_args("search", "搜索一下 RAG 是什么")
    assert "rag" in args["query"].lower()


def test_extract_weather_city():
    args = extract_args("weather", "北京天气怎么样")
    assert "北京" in args["city"]


def test_extract_weather_unknown_text():
    args = extract_args("weather", "天气")
    # 纯触发词无城市信息时，回退为原文本，避免空参
    assert args["city"] != ""


def test_extract_unknown_tool_returns_empty():
    assert extract_args("not_exist", "任意文本") == {}
