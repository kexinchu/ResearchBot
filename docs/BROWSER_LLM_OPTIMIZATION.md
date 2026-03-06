# 浏览器模式 LLM 优化说明

参考 [OpenClaw Zero Token](https://github.com/linuxhsj/openclaw-zero-token) 的「**一个任务在一个 session 中处理**」思路，对当前 ResearchBot 的浏览器调用大模型方式做对比与优化规划。

---

## 当前实现 vs OpenClaw 思路

| 维度 | 当前 ResearchBot | OpenClaw Zero Token 思路 |
|------|------------------|---------------------------|
| **会话粒度** | 每次 `call_llm` 都 `_go_new_chat()`，即 **一次 LLM 调用 = 一个新对话** | 一个任务在一个 session 中处理，**多轮对话复用同一会话** |
| **浏览器生命周期** | 全局单例，进程内复用同一 tab，atexit 关闭 | 按任务/网关管理，凭证可持久化 |
| **认证方式** | 依赖用户先用 CDP Chrome 登录 ChatGPT，无凭证持久化 | 捕获 cookie/bearer 存 `auth.json`，可脱离浏览器进程调用 |
| **平台** | 仅 ChatGPT Web | 多平台：DeepSeek、千问、Kimi、Claude、豆包、Gemini、Grok、GLM 等 |
| **调用方式** | 每次完整流程：导航 → 填输入 → 点发送 → 等完成 → 取最后一条回复 | 同会话内多轮：首轮等同；后续轮在**同一对话**中追加 user 消息并取最新 assistant 回复 |

---

## 可优化点列表

### 1. 一个 Pipeline 任务在一个 Browser Session（同一对话）中完成 【高优先级，已实现】

- **现状**：Ideator、Scout、DeepResearcher、Skeptic、Experimenter、Writer、Editor 等每次 `call_llm` 都会 `_go_new_chat()`，整页导航到 ChatGPT，相当于 7～20+ 次「新对话」。
- **问题**：  
  - 每次整页加载，耗时长、易因 DOM/网络波动失败；  
  - 模型看不到前面 Agent 的产出，无法在**同一对话**里利用上下文。
- **优化**：  
  - **同一 pipeline 运行期间**保持**一个对话**：第一次调用时 new chat 并发送；后续调用**不再** `_go_new_chat()`，而是在当前对话中**追加一条 user 消息**（把 system+user 拼成一条），发送后取**最后一条 assistant 回复**。  
  - 由 pipeline 在开始时「开启会话」，结束时「结束会话」；或由 `call_llm_browser(..., same_session=True)` 控制是否沿用当前会话。
- **实现位置**：`tools/browser_llm.py`（会话状态、是否 new chat、追加消息）；pipeline 或 config 层传入「当前是否在同一 pipeline 会话内」。

### 2. 减少整页导航，提高稳定性

- **现状**：每次 `_go_new_chat()` 都 `_page.goto(CHATGPT_URL, ...)`，整页重载。
- **优化**：  
  - 在「同一 session」模式下，只有**第一次**需要打开新对话（new chat 或首次 goto）；后续仅「在当前页面填输入框 + 发送」。  
  - 若 ChatGPT 提供「新对话」按钮且可用，可优先用点击按钮代替 `goto`，进一步减少整页刷新。

### 3. Pipeline 显式会话生命周期

- **现状**：浏览器通过全局单例 + atexit 关闭，没有「当前是第几次 pipeline 运行」的概念。
- **优化**：  
  - 在 `run_pipeline` 开始时调用 `browser_llm.start_session()`（或通过 `same_session=True` 的第一次调用隐式开始）；  
  - 在 `run_pipeline` 正常/异常结束时调用 `browser_llm.end_session()`。  
  - 这样「一个 task 一个 session」语义清晰，便于后续做会话级重试、超时或清理。

### 4. 多平台 / 凭证持久化（可选，参考 OpenClaw）

- **现状**：仅支持 ChatGPT Web，且依赖已用 CDP Chrome 登录，不保存凭证。
- **优化**：  
  - 参考 OpenClaw 的 `auth.json` + 各平台 `*-web-auth.ts` / `*-web-client.ts`：  
    - 用 Playwright 监听请求，捕获 cookie / Authorization；  
    - 存到本地（不提交 git），后续请求直接带凭证调用对应 Web API 或仍在浏览器内执行。  
  - 可逐步支持 DeepSeek Web、千问、Claude Web 等，便于无 API Key 或希望免 Token 的场景。

### 5. 长输出与流式/进度反馈（可选）

- **现状**：Writer/Editor 等长输出依赖 `_wait_for_completion()` 一次性等完再取全文。
- **优化**：  
  - 若 ChatGPT 页面支持流式渲染，可考虑边等边取已渲染内容，给用户「正在写」的进度感；  
  - 或至少对超长等待做超时与重试策略，避免长时间卡住无反馈。

### 6. 错误与登录态检测

- **现状**：输入框找不到或回复取不到时直接抛异常。
- **优化**：  
  - 检测到登录页或明显错误页时，给出明确提示（如「请先在浏览器中登录 ChatGPT」）并可选重试；  
  - 同一 session 内若检测到「会话失效」，可自动触发一次 new chat 或提示重新登录。

---

## 已实现的优化（本次改动）

- **One session per pipeline**  
  - 在 `browser_llm` 中增加「当前是否处于同一 pipeline 会话」状态。  
  - 第一次调用：`_go_new_chat()` 后发送并取回复。  
  - 后续调用（同一会话内）：**不** `_go_new_chat()`，只在当前对话中追加一条合并后的 user 消息，发送后取最后一条 assistant 回复。  
- Pipeline 在开始时标记「会话开始」，结束时标记「会话结束」，确保下一次完整 pipeline 重新用新对话。

详见：`tools/browser_llm.py` 中的 `start_browser_session()`、`end_browser_session()` 以及 `call_llm_browser(..., same_session=...)` 的语义。

---

### 7. 独立浏览器优先，不占用日常 Chrome（已实现）

- **现状**：此前默认尝试 CDP 连接调试端口 Chrome，用户需先 `./start_chrome_debug.sh`，会占用或影响日常使用的浏览器。
- **优化**（参考 OpenClaw 的「专用 profile」思路）：
  - **默认**：用独立 profile（如 `~/.chatgpt-bot-profile`）启动**仅给 bot 用的** Chrome 窗口，与用户主浏览器完全分离；首次在该窗口登录 ChatGPT 即可，之后同一 profile 保持登录。
  - **可选**：仅当设置 `EFFICIENT_RESEARCH_USE_CHROME_CDP=1` 时，才先尝试 CDP 连接，再回退到独立浏览器。
- **实现**：`tools/browser_llm.py` 中 `USE_CHROME_CDP` 由环境变量控制；默认 False，直接 `_launch_dedicated_chrome()`。

---

## 小结

| 优化项 | 优先级 | 状态 |
|--------|--------|------|
| 一个 pipeline 一个 browser session（同一对话多轮） | 高 | 已实现 |
| 减少整页导航（同一 session 内不重复 goto） | 高 | 随上面一并实现 |
| **独立浏览器默认，不占用日常 Chrome** | 高 | 已实现 |
| Pipeline 显式会话生命周期 | 中 | 已通过 session 开始/结束标记实现 |
| 多平台 / 凭证持久化 | 低/可选 | 未做 |
| 长输出流式/进度 | 低/可选 | 未做 |
| **错误与登录态检测**（登录页检测 + 中文提示） | 中 | 已实现 |
| **start_chrome_debug.sh 增强**（专用 profile、单实例、CDP 参数、就绪等待、跨平台） | 中 | 已实现 |
| **长输出进度**（_wait_for_completion 每 30s 打印进度） | 低 | 已实现 |
| **瞬时失败重试**（输入/提取失败自动重试 1 次，可配置 EFFICIENT_RESEARCH_BROWSER_RETRIES） | 中 | 已实现 |
| **反自动化**（AutomationControlled + navigator.webdriver 隐藏 + ignore_default_args） | 中 | 已实现 |

以上优化使浏览器模式更贴近 OpenClaw 的「一个任务在一个 session 中处理」及「专用 profile / 不干扰主浏览器」思路，同时保持当前项目以 pipeline 为单位的架构不变。

### 长时间运行与请求频率控制（已实现）

- **问题**：连续过快请求 GPT 容易触发限流或失败，长时间 workflow 需要可持续节奏。
- **实现**：在每次浏览器 LLM 调用前检查与上次调用的间隔；若小于 `EFFICIENT_RESEARCH_BROWSER_MIN_INTERVAL`（默认 5 秒），则先等待再发请求；完成后更新上次调用时间。这样整条 pipeline（Ideator → Scout → … → Writer → Editor）自动保持间隔，无需每阶段手写 sleep。
- **建议**：长时间跑（数小时）时可将 `EFFICIENT_RESEARCH_BROWSER_MIN_INTERVAL` 设为 8–15 秒，配合 `nohup`/tmux 使用；workflow 会不断整理与优化，最终得到稳定结果。

### 长期记忆（本地 RAG，已实现）

- **问题**：所有结果依赖 GPT，跨 run 无持久记忆，难以在后续 run 中复用历史结论。
- **实现**：本地 RAG（`tools/rag.py`）使用 ChromaDB + sentence-transformers，将每次完整 run 的 artifacts（假设、贡献、实验设计、写作片段等）分块并嵌入，存入 `artifacts/rag/`。新 run 开始时按 topic 检索 top-k 片段，注入 Ideator 的 prompt；run 结束后自动将本 run 索引进 RAG。详见 README「长期记忆（本地 RAG）」。

---

## 参考 OpenClaw 源码后的进一步可优化点

在阅读 [OpenClaw Zero Token 仓库](https://github.com/linuxhsj/openclaw-zero-token/tree/main) 的 `start-chrome-debug.sh`、`src/browser/chrome.ts`、`openclaw.json` 等之后，可考虑的后续优化如下。

### 8. start_chrome_debug.sh 增强（跨平台 + 单实例 + 专用 profile）

| OpenClaw 做法 | 当前 ResearchBot | 建议 |
|---------------|-------------------|------|
| **跨平台**：`detect_os` (mac/linux/win/wsl)、`detect_chrome` 多路径、`detect_user_data_dir` 按 OS 不同目录 | 仅 macOS 路径，且未用专用 user-data-dir | 可选：按 OS 检测 Chrome 路径与专用数据目录；CDP 模式也用**独立 user-data-dir**（如 `Chrome-ResearchBot-Debug`），与主浏览器完全分离 |
| **单实例**：启动前 `pkill -f "chrome.*remote-debugging-port=9222"`，避免多实例抢端口 | 仅检测端口已占用则跳过启动 | 可选：启动前先关闭已有调试 Chrome，再启动新实例，保证单实例 |
| **CDP 参数**：`--remote-allow-origins=*`、`--disable-sync`、`--disable-background-networking` | 未加 | 可选：增加 `--remote-allow-origins=*` 等，减少 CDP 连接被拒 |
| **就绪等待**：轮询 `curl 9222/json/version` 再提示下一步 | 无 | 可选：启动后轮询至 CDP 就绪再打印「请登录并运行 bot」 |
| **日志**：输出重定向到 `/tmp/chrome-debug.log` | 无 | 可选：便于排查启动失败 |

**已实现**：在 `start_chrome_debug.sh` 中已增加：
- **专用 user-data-dir**：按 OS 使用独立目录（如 macOS `~/Library/Application Support/ResearchBot-Chrome-Debug`，Linux/WSL `~/.config/researchbot-chrome-debug`），与主浏览器完全分离；
- **单实例**：启动前先关闭占用 9222 的 Chrome，再启动新实例；
- **CDP 参数**：`--remote-allow-origins=*`、`--disable-sync`、`--disable-background-networking`；
- **就绪等待**：轮询 `curl 127.0.0.1:9222/json/version` 至成功再提示下一步；
- **跨平台**：`detect_os`（mac/linux/win/wsl）、`detect_chrome`（多路径）、`detect_user_data_dir`（按 OS）；
- **日志**：输出重定向到 `/tmp/researchbot-chrome-debug.log`。  
仍支持环境变量 `CHROME_BIN`、`CHROME_DEBUG_PORT`、`CHROME_PROFILE_DIR` 覆盖。

**浏览器模式相关环境变量汇总**（`tools/browser_llm.py` / `start_chrome_debug.sh`）：

| 变量 | 含义 | 默认 |
|------|------|------|
| `EFFICIENT_RESEARCH_USE_CHROME_CDP` | 是否先尝试 CDP 连接 | 不设置则用独立浏览器 |
| `CHROME_DEBUG_PORT` | CDP 端口 | 9222 |
| `CHROME_PROFILE_DIR` | 独立浏览器 profile 目录 | `~/.chatgpt-bot-profile` |
| `CHATGPT_URL` | ChatGPT 页面 URL | https://chatgpt.com/ |
| `EFFICIENT_RESEARCH_COOKIE_FILE` | Cookie 文件路径（JSON 或 Netscape .txt），启动时注入后打开即已登录 | 不设置则需手动登录 |
| `EFFICIENT_RESEARCH_BROWSER_RETRIES` | 输入/提取失败时的重试次数（实际尝试次数 = 1 + 该值） | 1（即最多 2 次） |
| `EFFICIENT_RESEARCH_BROWSER_MIN_INTERVAL` | 两次浏览器 LLM 调用之间的最小间隔（秒），避免请求过快导致限流或失败 | 5 |

### 9. 程序内启动 Chrome（可选）

- OpenClaw 的 `chrome.ts` 支持**程序内** `launchOpenClawChrome()`：指定 userDataDir、端口、`--disable-features=AutomationControlled` 等，并轮询 CDP 就绪。
- 当前 ResearchBot 仅通过 Playwright `launch_persistent_context` 或 CDP attach，未在「CDP 模式」下由脚本/程序启动 Chrome。
- 可选：若需「一键 CDP 模式」，可由 Python 子进程调用本机 Chrome 可执行文件并传参（类似 OpenClaw），再 attach；或保持现状，由用户先运行 `start_chrome_debug.sh`。

### 10. 自动登录（Cookie 导入，已实现）

- 设置 `EFFICIENT_RESEARCH_COOKIE_FILE` 为本地 cookie 文件路径后，启动浏览器时会先注入这些 cookie，再打开 ChatGPT，因此**打开即已登录**，无需在独立窗口里再登一次。
- **导出方式**：在**日常已登录 ChatGPT 的浏览器**中安装扩展（如 [Cookie-Editor](https://chrome.google.com/webstore/detail/cookie-editor)），打开 https://chatgpt.com 后导出为 **JSON**（或 Netscape `.txt`），保存到本地；将该路径设为环境变量即可。
- **安全**：Cookie 文件含登录态，不要提交到 git；建议 `chmod 600` 限制仅自己可读。
- **多站点**：当前 pipeline 只使用 ChatGPT；若将来支持 Claude/Gemini/Kimi，可为不同站点配置不同 cookie 文件或同一文件中包含多域名的 cookie。

### 11. 登录态 / 就绪检测（已实现）

- OpenClaw 有 `isChromeReachable`、`isChromeCdpReady`（fetch `/json/version`、WebSocket 握手）。
- **已实现**：`_is_login_page()` 通过当前 URL 判断是否在 `auth/login` 或 `auth/signup`；`_go_new_chat()` 后若输入框未就绪且为登录页，打印「请在弹出的浏览器窗口中登录 ChatGPT」；`_fill_input` / `_get_last_response` 失败时若在登录页，抛出带中文提示的 `RuntimeError`，便于用户排查。

### 12. 反自动化检测（已实现，减轻「验证是否为机器人」）

- OpenClaw 启动 Chrome 时传 `--disable-features=AutomationControlled`，降低 `navigator.webdriver` 被站点识别为自动化。
- **已实现**：
  - **Chrome 启动参数**：`--disable-features=AutomationControlled`、`--disable-blink-features=AutomationControlled`，以及 `ignore_default_args=["--enable-automation"]`（独立浏览器与 `start_chrome_debug.sh` 均一致）。
  - **页面注入**：在首次导航前通过 `add_init_script` 删除/覆盖 `navigator.webdriver`，使页面内检测读不到自动化标识。
  - **视口**：固定 1280×800，避免默认视口被识别。
- **若仍频繁出现验证**：可尝试 (1) 删除独立 profile 后重跑一次并在弹出窗口中**手动完成登录与一次人机验证**（`rm -rf ~/.chatgpt-bot-profile` 后再 `./run.sh --browser`）；(2) 换网络或稍后再试；(3) 使用 CDP 模式，先手动用 `./start_chrome_debug.sh` 启动带反检测参数的 Chrome，在窗口中登录通过验证后再 `export EFFICIENT_RESEARCH_USE_CHROME_CDP=1 && ./run.sh --browser`。

### 13. 配置集中化（低优先级）

- OpenClaw 将 browser 配置放在 `openclaw.json`（如 `browser.attachOnly`、`browser.profiles[].cdpUrl`）。
- 当前 ResearchBot 用环境变量（`EFFICIENT_RESEARCH_USE_CHROME_CDP`、`CHROME_DEBUG_PORT`、`CHROME_PROFILE_DIR`）。
- 可选：若后续增加多 profile 或多端口，可引入小型 JSON 配置与 env 覆盖并存。
