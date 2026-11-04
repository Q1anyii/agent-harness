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

测试：`.venv/Scripts/python.exe -m pytest`（120 passed，实测；联网工具与真实 LLM 路径通过 monkeypatch 离线验证）。

> 注：Windows 端口处于 Hyper-V/WSL2 保留段（7449-8248）会报 WinError 10013，用 `$env:PORT=18000` 换端口。

## 系统设计

架构分层：FastAPI（`src/main.py`）→ Agent 运行时（`src/agent/`：runtime/router/session/llm/tools）→ 内存存储；前端 `frontend/`（会话列表 + 聊天框 + trace 面板 + localStorage 缓存兜底）。

- 主循环四步流转与继续/终止判断；消息结构支持 OpenAI 兼容工具调用（tool_call_id 回显）
- 工具注册表（参数 Schema + 安全校验，calculator 为 AST 白名单防注入）；search/weather 真实联网查询
- LLM 后端切换：MockLLM（默认）与 DeepSeekLLM（真实），`LLM_BACKEND` 环境变量控制
- trace 记录与独立面板展示；前端会话删除、失效自动重建、本地缓存

完整设计与六大模块实现细节、API 契约、测试、边界与限制见 [docs/系统设计.md](docs/系统设计.md)。

## memory 召回时机与放置方式

**状态：待设计（暂搁置）。**

当前仅实现短期记忆（会话消息历史随主循环上下文累积）；长期记忆（参考 mem0 式召回）尚未落地。召回时机（何时从向量库召回用户事实）与放置方式（以何种形式注入 context）待实现时明确，届时同步更新本 README。对应架构题模块二。

## 后续规划

- 前端：tool trace 嵌入 AI 消息流（其余不再优化）
- 工具：继续扩展真实网络查询类工具（如 fetch）
- AgentRuntime：针对性优化（异步工具 / 状态机细化等）
- 中间件：PostgreSQL / Redis / ChromaDB / Docker 等正式启用
- memory：召回时机与放置方式设计（搁置中）
