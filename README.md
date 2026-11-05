# agent-harness

A self-implementation agent harness project.

自实现 Agent harness：FastAPI 后端 + Vite/React/TS 前端，无外部 Agent 框架，自实现类 LangGraph 的循环、节点、状态机与 Runtime。

## 功能

- **主循环**：接收输入 → 判断直接回复/调用工具 → 调用工具 → 继续/终止（单次问答轮次上限 8）
- **工具注册**：name / description / 参数 Schema（JSON Schema）；内置 `calculator`（安全求值）、`search`（联网 DuckDuckGo）、`weather`（联网 wttr.in）、`todo`（待办 add/list/done）
- **LLM 输出解析**：思考/工具调用/最终答案三类；默认 MockLLM（规则式），可选 DeepSeekLLM 真实接入（`LLM_BACKEND=deepseek`，OpenAI-compatible 工具调用）
- **session 管理**：多会话隔离、可续聊、删除会话、列表空自动建默认会话、会话忙保护（HTTP 409）
- **context 管理**：轮次上限、短期记忆、追问路由；基础压缩待实现
- **健壮性**：工具级异常兜底（含联网工具网络失败兜底）+ 工具调用 trace（工具名/参数/结果/耗时）

详细实现见 [docs/系统设计.md](docs/系统设计.md)。

## 运行方式

后端（Python 3.13）：

```powershell
# 一键构建 .venv 并安装依赖
powershell -ExecutionPolicy Bypass -File .\setup.ps1
# 默认 Mock 模式启动（8000 端口，可用 PORT 覆盖）
python src/main.py
# 接入真实 DeepSeek：先配置 .env（DEEPSEEK_API_KEY / BASE_URL / MODEL_NAME），再
$env:LLM_BACKEND = "deepseek"
python src/main.py
```

前端（Node）：

```powershell
cd frontend
npm install
npm run dev   # 5173 端口，Vite proxy 将 /api 转发到 127.0.0.1:8000
```

契约导出：`.venv/Scripts/python.exe scripts/export_api.py` → `api.json`（OpenAPI 3.0.3）。

测试：`.venv/Scripts/python.exe -m pytest`（170 passed，实测；联网工具与真实 LLM 路径通过 monkeypatch 离线验证）。

> 注：Windows 端口处于 Hyper-V/WSL2 保留段（7449-8248）会报 WinError 10013，用 `$env:PORT=18000` 换端口。

## Docker 部署（前后端分离：nginx 静态托管 + API 反代）

前置：本机安装 Docker，先构建前端产物（compose 以挂载方式接入 dist/，不进镜像）：

```powershell
cd frontend
npm install
npm run build        # 生成 frontend/dist/
cd ..
docker compose up -d --build   # 或 --build 首次构建后端镜像
```

访问 `http://localhost`：nginx（80）托管前端静态产物，`/api/` 反代到后端容器 `api:8000`。SQLite 经 `./data` 卷持久化；默认 Mock 模式零配置可跑，接真实 DeepSeek 时在 `.env` 配置 `DEEPSEEK_API_KEY` 后置 `LLM_BACKEND=deepseek` 再 `docker compose up -d`。

关键点（面试可讲）：
- **`proxy_buffering off`**：本项目流式输出走 `/api/.../events` 轮询 + `message_delta` 增量，nginx 缓冲会攒满才转发导致延迟/粘包；
- **非 root 运行**：Dockerfile 用 `appuser` 运行容器（最小权限）；
- **挂载式接入**：前端 dist 与 nginx.conf 由 compose 挂载，改前端无需重建后端镜像。

## 系统设计

架构分层：FastAPI（`src/main.py`）→ Agent 运行时（`src/agent/`：runtime/router/session/llm/tools）→ 内存存储；前端 `frontend/`（会话列表 + 聊天框 + trace 面板 + localStorage 缓存兜底）。

- 主循环四步流转与继续/终止判断；消息结构支持 OpenAI 兼容工具调用（tool_call_id 回显）
- 工具注册表（参数 Schema + 安全校验，calculator 为 AST 白名单防注入）；search/weather 真实联网查询
- LLM 后端切换：MockLLM（默认）与 DeepSeekLLM（真实），`LLM_BACKEND` 环境变量控制
- trace 记录与独立面板展示；前端会话删除、失效自动重建、本地缓存

完整设计与六大模块实现细节、API 契约、测试、边界与限制见 [docs/系统设计.md](docs/系统设计.md)。

## memory 召回时机与放置方式

**状态：已实现（⑦ 长期记忆）。**

`src/agent/memory.py` 提供插件化 `MemoryStrategy` 抽象 + `BM25Memory`（Okapi BM25 k1=1.5/b=0.75，CJK 单字+英文按词切分，乘法衰减 `decay_factor^access_count`）。runtime 每轮以本轮提问召回 top-k 拼入本次 system 动态段（不污染静态 base）；落库层经 `MemoryExtractor`（对齐 mem0/Mitta 写入管线）由 LLM 从「已有记忆 + 最近消息 + 本轮 QA」提取自包含事实、md5 去重后逐条落库，指代（如"那南昌呢"承接上文）在提取阶段消解。详见 [docs/系统设计.md](docs/系统设计.md) 与 `docs/devlog/`。

## 后续规划

- 工具：继续扩展真实网络查询类工具（如 fetch）
- AgentRuntime：针对性优化（异步工具 / 状态机细化等）
- 中间件：PostgreSQL / Redis / ChromaDB 等正式启用（存储与记忆已插件化抽象，SQLite/内存实现笔试规模够用）
- 记忆：SQLite 落库（复用 `connect_sqlite`/`sqlite_transaction` 加 memories 表）
