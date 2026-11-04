# 真实 LLM 接入改造路线（DeepSeek，OpenAI-compatible）

> 目标：把最小闭环里的 `MockLLM` 换成真实 DeepSeek 模型，跑通"真模型决策 → 工具调用 → 回复"。
> 原则：保持 Mock 路径与现有 87 个测试不回归；Mock/真实两种后端可切换。
> 本路线是"陪练不代写"——每步给出改动点、接口约束、踩坑提示，代码由你自己落笔。

## 前置

- 依赖：`requirements.txt` 已补 `openai`（见提交）；安装：`.venv\Scripts\python -m pip install -r requirements.txt`
- 密钥：`.env` 已有 `DEEPSEEK_API_KEY`、`BASE_URL=https://api.deepseek.com`、`MODEL_NAME=deepseek:deepseek-v4-flash`

## 改造步骤

### Step 0 删除示例文件

- 删除 `src/init.py`（DeepSeek 调用示例，其逻辑将被 `DeepSeekLLM` 吸收）
- 提交：`git commit src/init.py -m "..."`（删除记录）

### Step 1 抽象加 init（src/agent/llm.py）

`LLMClient` 增加抽象方法，声明"子类必须初始化底层客户端"：

```python
@abstractmethod
def init(self) -> None:
    """初始化底层客户端（如 OpenAI-compatible client）。Mock 可空实现。"""
```

`MockLLM` 补一个空实现（`return None`），保证抽象契约完整。

### Step 2 实现 DeepSeekLLM（新建 src/agent/deepseek_llm.py）

```python
class DeepSeekLLM(LLMClient):
    def __init__(self, model: str | None = None, api_key: str | None = None,
                 base_url: str | None = None): ...
    def init(self) -> None:          # 读环境变量/缺省值 → self.client = OpenAI(...)
    def generate(self, messages) -> LLMResponse: ...
```

**generate 内部要做三件事**：

1. **消息格式转换**：把内部消息历史转成 OpenAI 格式
   - `role:"user" / "assistant"` 直接映射
   - `role:"tool"` 必须转成 OpenAI 的 tool 消息（**带 `tool_call_id`**，见踩坑 ①）
2. **工具 schema 下发**：从 `TOOL_REGISTRY` 生成 OpenAI `tools` 参数
   ```python
   tools = [{"type": "function", "function": {"name": t.name, "description": t.description,
            "parameters": t.parameters}} for t in get_all_tools()]
   ```
   `t.parameters` 本身就是 JSON Schema 格式（tools/base.py 已定义），可直接用。
3. **响应解析**：
   - `message.tool_calls` 非空 → 每个 `tool_calls[i]`：`ToolCall(name=fn.name, args=json.loads(fn.arguments))` → 返回 `LLMResponse(content=None, tool_calls=[...])`
   - 否则 → `LLMResponse(content=message.content, tool_calls=None)`

### Step 3 main.py 接线（后端切换开关）

```python
import os
backend = os.environ.get("LLM_BACKEND", "mock")
if backend == "deepseek":
    runtime = AgentRuntime(llm=DeepSeekLLM().init(), max_rounds=8)
else:
    runtime = AgentRuntime(llm=MockLLM(), max_rounds=8)
```

默认保持 `mock`（测试/演示稳定）；要真模型时 `$env:LLM_BACKEND="deepseek"` 再启动。

### Step 4 测试策略

- **单元测试**：`tests/test_deepseek_llm.py`，用 `monkeypatch` 伪造 OpenAI client 响应，覆盖三类：纯文本响应 / 工具调用响应 / API 异常，断言解析出的 `LLMResponse` 正确。**不联网、不用真 key**。
- **回归**：现有 87 个测试必须全绿（Mock 路径未动）。
- **手动联调**：临时脚本用真 key 发"北京天气怎么样"，确认工具调用链路真实走通后删脚本（勿遗留临时文件）。

## 三个必踩的坑（先看再写）

1. **tool 消息必须回显 `tool_call_id`**：OpenAI/DeepSeek 的 tool 消息结构是 `{"role":"tool","tool_call_id":"call_xxx","content":...}`，且该 `tool_call_id` 必须来自上一轮 assistant 的 `tool_calls[i].id`。当前 runtime 的 tool 消息是 `{"role":"tool","name":...,"content":...}`（无 id）——**要么扩展 runtime 的 tool 消息加 id，要么在 DeepSeekLLM.generate 里转换时补 id 占位**。这是自实现框架接真实 API 最典型的断点。
2. **`arguments` 是 JSON 字符串**：OpenAI 返回的 `function.arguments` 是 str，必须 `json.loads` 后才是 `ToolCall.args`（dict）。
3. **模型名与 tools 支持确认**：`.env` 的 `MODEL_NAME=deepseek:deepseek-v4-flash` 与 `src/init.py` 示例里的 `model="deepseek-flash"` 不一致，且需确认该模型是否支持 function calling。启动前先跑一个最小工具调用验证。

## 验收清单

- [ ] 现有 87 测试全绿
- [ ] 新增 DeepSeekLLM 单测（伪造 client，不联网）全绿
- [ ] `LLM_BACKEND=deepseek` 启动后，"北京天气怎么样"真实走通：trace 有 weather 工具调用，回复基于工具结果
- [ ] `src/init.py` 已删除，无遗留临时脚本
