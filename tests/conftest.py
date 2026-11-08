"""pytest 配置：把 src 加入 sys.path；联网工具在测试中一律走假数据，保离线确定性。"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parent.parent / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


@pytest.fixture(autouse=True)
def _offline_tools(monkeypatch: pytest.MonkeyPatch) -> None:
    """所有测试默认离线：patch 天气/搜索的网络入口，返回固定假数据。

    真实网络路径仅在 LLM_BACKEND=deepseek 联调时验证（网络测试不稳定，
    不能作为单元测试的确定性依赖）。
    """
    import agent.tools.search as search_mod
    import agent.tools.weather as weather_mod

    async def _fake_weather(city: str):
        return {
            "lang_zh": [{"value": "晴"}],
            "temp_C": "9",
            "humidity": "59",
            "winddir16Point": "西北",
            "windspeedKmph": "11",
        }

    async def _fake_search(query: str):
        return [
            {"title": f"{query} 相关结果一", "snippet": "这是摘要一"},
            {"title": f"{query} 相关结果二", "snippet": "这是摘要二"},
        ]

    monkeypatch.setattr(weather_mod, "_fetch", _fake_weather)
    monkeypatch.setattr(search_mod, "_fetch", _fake_search)
