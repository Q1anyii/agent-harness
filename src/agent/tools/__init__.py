"""工具包入口：导入即注册全部内置工具。"""
from .base import Tool, get_all_tools, get_tool, register
from . import calculator, search, todo, weather  # noqa: F401  (触发注册)

__all__ = ["Tool", "get_all_tools", "get_tool", "register"]
