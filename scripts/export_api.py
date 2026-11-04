"""导出 FastAPI 生成的 OpenAPI 3.0 契约到项目根目录 api.json。

用法：.venv/Scripts/python.exe scripts/export_api.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

# 让脚本可直接运行（不受包路径限制）
SRC_DIR = Path(__file__).resolve().parent.parent / "src"
sys.path.insert(0, str(SRC_DIR))

from main import app  # noqa: E402


def main() -> None:
    schema = app.openapi()
    out_path = Path(__file__).resolve().parent.parent / "api.json"
    out_path.write_text(
        json.dumps(schema, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"api.json 已生成: {out_path} (openapi={schema.get('openapi')}, paths={len(schema.get('paths', {}))})")


if __name__ == "__main__":
    main()
