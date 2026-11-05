# ============================================================
# Dockerfile — agent-harness 后端 API 服务
# 构建：docker build -t agent-harness-api .
# 运行：docker run -p 8000:8000 --env-file .env agent-harness-api
# 国内构建加速：docker build --build-arg APT_MIRROR=mirrors.aliyun.com --build-arg PIP_INDEX=https://mirrors.aliyun.com/pypi/simple .
# ============================================================

# Python 3.12 slim（对齐 Mitta 选型，AI 生态兼容性最好）
FROM python:3.12-slim

# 构建参数：CI 境外默认官方源，国内 ECS 构建可传阿里云源
ARG APT_MIRROR=deb.debian.org
ARG PIP_INDEX=https://pypi.org/simple
# Debian 12 bookworm 使用 .sources 格式
RUN sed -i "s/deb.debian.org/${APT_MIRROR}/g" /etc/apt/sources.list.d/debian.sources && \
    sed -i "s/security.debian.org/${APT_MIRROR}/g" /etc/apt/sources.list.d/debian.sources

WORKDIR /app

# 不以 root 运行容器：预建 appuser，COPY --chown 归属后运行时以最小权限身份
# （安全实践：容器内非 root 降低提权攻击面）
RUN useradd -m appuser

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONPATH=/app/src

# 系统依赖：仅 curl（健康检查）；本项目无编译依赖/MCP/psycopg，比 Mitta 精简
RUN apt-get update && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

# 先复制依赖文件，利用 Docker 缓存层（代码变更不触发重装）
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt -i ${PIP_INDEX}

# 复制项目代码：src/（main.py 与 agent 包）+ api.json（前后端契约）
# data/（SQLite）不进镜像，由 compose volume 挂载持久化
COPY --chown=appuser:appuser src/ src/
COPY --chown=appuser:appuser api.json api.json

USER appuser

EXPOSE 8000

# 健康检查：探活 FastAPI 的 /api/health
HEALTHCHECK --interval=30s --timeout=10s --start-period=30s --retries=3 \
    CMD curl -f http://localhost:8000/api/health || exit 1

# PYTHONPATH=/app/src 已在 ENV 设置，uvicorn main:app 直接可找
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
