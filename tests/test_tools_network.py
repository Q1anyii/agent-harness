"""联网工具单元测试：解析逻辑 + 失败/超时兜底。

conftest 已把 _fetch 全局 patch 成假数据（离线确定性）；
本文件额外测"网络失败"路径时，用 monkeypatch 局部覆盖 _fetch 返回 None。
"""
from __future__ import annotations

import asyncio

import agent.tools.search as search_mod
import agent.tools.weather as weather_mod


def _w(*args):
    return asyncio.run(weather_mod.run(*args))


def _s(*args):
    return asyncio.run(search_mod.run(*args))


async def _fake_weather_none(city):
    return None


async def _fake_weather_empty(city):
    return {}


async def _fake_search_none(query):
    return None


async def _fake_search_empty(query):
    return []


# ---------- weather：正常解析 ----------

def test_weather_run_formats_output():
    """联网返回字段应组装成可读中文文本。"""
    result = _w("北京")
    assert "天气查询（联网）：北京" in result
    assert "晴" in result
    assert "9℃" in result
    assert "湿度 59%" in result


def test_weather_run_empty_city():
    assert "错误" in _w("   ")


# ---------- weather：失败兜底 ----------

def test_weather_fetch_failure_fallback(monkeypatch):
    """网络失败时返回错误文案，而不是抛异常。"""
    monkeypatch.setattr(weather_mod, "_fetch", _fake_weather_none)
    result = _w("北京")
    assert "暂时无法获取" in result


def test_weather_fetch_returns_empty_dict(monkeypatch):
    """服务返回空结构时不崩溃，字段缺省为 ?。"""
    monkeypatch.setattr(weather_mod, "_fetch", _fake_weather_empty)
    result = _w("北京")
    assert "北京" in result
    assert "?" in result


# ---------- search：正常解析 ----------

def test_search_run_returns_results():
    result = _s("agent")
    assert "搜索结果（联网）：「agent」" in result
    assert "agent 相关结果一" in result
    assert "这是摘要一" in result


def test_search_run_empty_query():
    assert "错误" in _s("  ")


# ---------- search：失败兜底 ----------

def test_search_fetch_failure_fallback(monkeypatch):
    monkeypatch.setattr(search_mod, "_fetch", _fake_search_none)
    result = _s("agent")
    assert "未找到" in result


def test_search_fetch_empty_results(monkeypatch):
    """无结果时返回未找到文案。"""
    monkeypatch.setattr(search_mod, "_fetch", _fake_search_empty)
    result = _s("不存在的关键词xyz")
    assert "未找到" in result
