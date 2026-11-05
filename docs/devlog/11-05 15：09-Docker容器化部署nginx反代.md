# Docker 容器化部署：nginx 静态托管 + API 反代（P2 ⑧）

## 背景

用户收尾项：加 Docker 部署，"nginx 可以手动下一个，或者直接复制 Mitta 的"。本机无 docker（仅静态校验），配置对齐 Mitta 的 compose 结构（api + nginx 双服务）按本项目规模精简：无 postgres/redis/milvus，后端仅 FastAPI + SQLite。

## 设计

### 1. `Dockerfile`（后端 API 服务）

- `python:3.12-slim`（对齐 Mitta 选型）；`APT_MIRROR`/`PIP_INDEX` build-arg 支持国内构建加速（Debian 12 .sources 格式）；
- 系统依赖仅 `curl`（健康检查）——本项目无编译依赖/MCP/psycopg，比 Mitta 精简；
- **非 root 运行**：预建 `appuser` + `COPY --chown` + `USER appuser`（最小权限，安全实践）；
- `PYTHONPATH=/app/src` → `CMD uvicorn main:app`；`HEALTHCHECK` 探活 `/api/health`；
- 只 COPY `src/` + `api.json`；`data/`（SQLite）不进镜像，compose 卷挂载持久化。

### 2. `deploy/nginx/nginx.conf`（复制 Mitta 精简）

- 静态根 `/usr/share/nginx/html`（挂载前端 dist）+ `try_files` SPA fallback；
- `location /api/` 反代 `api:8000`（`resolver 127.0.0.11` 运行时 DNS）+ **`proxy_buffering off`**——本项目流式输出走事件轮询 + `message_delta` 增量，缓冲会攒满才转发导致延迟/粘包（对齐 Mitta 对 SSE 的处理）；
- 静态资源 30d immutable 长缓存；80 纯 HTTP（笔试/本机演示），上 HTTPS 参照 Mitta ssl 配置。

### 3. `docker-compose.yml`（api + nginx 双服务）

- api：build + `LLM_BACKEND`/`DEEPSEEK_API_KEY`/`BASE_URL`/`MODEL_NAME` 从宿主机 `.env` 透传（默认 mock 零配置可跑）+ `./data:/app/data` SQLite 持久化 + healthcheck；
- nginx：`nginx:1.27-alpine` + 挂载 `./frontend/dist` 与 nginx.conf，`depends_on: api`，暴露 80。

### 4. `.dockerignore` + README

- `.dockerignore` 复制 Mitta 实践：排除 .env/.venv/tests/docs/frontend/data 等；
- README 新增「Docker 部署」章节（前置 npm build → compose up）并收尾过时信息：测试数 120→170（实测）、memory 段落「待设计」→「已实现（⑦）」、后续规划去掉 Docker。

## 验证

- `docker-compose.yml` YAML 语法校验通过（services: api/nginx，端口/挂载正确）——本机无 docker，无法真跑 `compose up`，配置人工核验 + 与 Mitta 可用配置逐项比对；
- 全量测试 **170 passed** 无回归（本次改动纯部署层，不触碰代码路径）。

## 后续

- 真机验证：有 docker 的环境跑 `docker compose up -d --build` 冒烟（本机未装，README 已写明步骤）；
- HTTPS：证书 + 80→443 301，直接套用 Mitta nginx ssl 段落；
- 前端多阶段构建（node build → nginx COPY dist）可作为进阶优化，当前挂载式简单可讲。
