# Prompt / 配置管理第二轮收口修复报告

## 1. 修改前问题

上一阶段（见 `WenDang/PROMPT-SELECT-FIX-REPORT.md`）已修好监听对象新增行的 Jinja-in-JS，并统一了 `GET /api/prompts`。本轮只收口确认遗留的 5 项，没有重做第一轮功能。

### P0-01 保存失败错误信息不准确

后端失败时返回 `{"error": "..."}`，前端保存逻辑读取 `errorData.detail`。字段对不上时，页面可能把真实写入错误（如 `WinError 5`）显示成「请先停止运行程序！」。

### P0-02 `config.local.json` 写入不稳定

上一轮真实保存时，`os.replace(tmp, config.local.json)` 抛出 `WinError 5`（拒绝访问）。说明 Windows 上目标文件被短暂占用时，原子替换会失败。

### P0-03 不完整监听对象被静默跳过

后端保存时若 `nickname == ""` 或 `prompt_file == ""` 直接 `continue`。用户点「保存」看起来成功，缺名字或缺 Prompt 的行实际被丢掉，页面无提示。

### P1-01 快速配置 `addEntry()` 同类 Jinja-in-JS

`templates/quick_start.html` 的「添加用户」仍把 `{{ file }}` / `{% for file in prompt_files %}` 写进运行期 JS 字符串。该页动态 HTML 不会再经 Jinja 渲染，下拉框会显示字面量 `{{ file }}`。

### P1-02 论坛角色 Prompt 只靠首次 SSR

「趣味实验室 → 选择论坛角色」只在 `config_editor.html` 第一次 Jinja 渲染时填选项，不走 `GET /api/prompts`。新增/删除 Prompt 后，不刷新整页就看不到变化。

---

## 2. 根因

### P0-01

`saveConfig()` 用 `errorData.detail` 当错误文案，而 `/submit_config` 异常分支只放 `error`。协议不一致。另有一条「程序正在运行」的 400 文案被误当成所有失败的默认显示。

### P0-02

`app_config._atomic_write()` 先写临时文件，再 `os.replace(tmp, dest)`。读取侧 `load_config()` 已使用 `with open(...)`，进程内不长期持有句柄。失败点是 **Windows 上对已存在的 `config.local.json` 做 replace**：目标文件被其它进程短暂打开（编辑器、杀毒、索引、上一轮会话里的读锁）时，`os.replace` 报 `PermissionError` / `winerror == 5`。这不是「JSON 半写入」本身；replace 失败时原文件仍在。

### P0-03

`submit_config` / 快速配置 / 首页 POST 解析 `LISTEN_LIST` 时对空行 `continue`，不返回 400。前端也没有提交前校验。

### P1-01

与第一轮相同：Jinja 写进浏览器会执行的 JS 字符串。快速配置的 `addEntry()` 未改，所以回归仍在。

### P1-02

论坛 `<select id="forumCharacterSelect">` 只有模板 `{% for file in prompt_files %}`。监听对象已经改为 API 填充，论坛角色没有接入同一套 `fillPromptSelect()`。

---

## 3. 修改文件

| 文件 | 修改内容 | 原因 |
| --- | --- | --- |
| `static/js/prompt_options.js` | 新增公共模块：`loadPromptOptions` / `fillPromptSelect` / `refreshPromptSelects` / `validateListenRows` / `apiErrorMessage` | 禁止第三套 Prompt 加载机制；监听对象、快速配置、论坛角色共用 |
| `static/js/config_editor.js` | `addEntry` 继续用 DOM + `PromptOptions`；`refreshAllPromptConsumers` 同时刷新监听下拉和论坛角色；`saveConfig` 先校验再提交，按 `ok/message/detail/error` 显示错误 | 收口错误协议；论坛接入统一数据源 |
| `templates/config_editor.html` | 在 `config_editor.js` 之前加载 `prompt_options.js`；论坛 select 增加 `data-selected` | 保证模块顺序；删除 Prompt 后能显示「原 Prompt 已不存在」 |
| `templates/quick_start.html` | 加载 `prompt_options.js`；`addEntry()` 改为 `createElement`，不再内嵌 Jinja；提交前 `validateListenRows` | 修复快速配置 Jinja-in-JS |
| `static/css/config_editor.css` | `.listen-field-error` 红框高亮 | 校验失败时聚焦并标出输入框/下拉框 |
| `app_config.py` | `_atomic_write`：二进制 UTF-8、`flush`/`fsync` 后 `_replace_with_retry`（WinError 5 / `PermissionError` 短重试） | 降低 Windows replace 瞬时占用导致的写入失败 |
| `config_editor.py` | `_json_error` / 成功 `{ok:true,message}`；`listen_list_from_form` 拒绝不完整行；`/submit_config`、快速配置 POST、首页 POST 共用 | 前后端字段一致；禁止静默 skip |
| `tests/test_config_save.py` | 监听校验、10 次原子写入、replace 重试、submit_config 400/500 协议 | 锁住 P0 行为 |
| `tests/test_webui_data.py` | 断言静态 JS 不再含 `{{ file }}`，且引用 `prompt_options.js` | 防止 Jinja-in-JS 回归 |
| `PROMPT-CONFIG-HARDENING-REPORT.md` | 本报告 | 任务要求 |

未改：微信监听、self 判断、去重、自动回复、模型调用、群聊、Stop Bot、鼠标控制、数据库、整体 UI。

---

## 4. Prompt 数据流

```text
prompts/*.md
        │
        ▼
list_prompt_names()          # webui_data.py，扫描目录，不含后缀
        │
        ▼
GET /api/prompts             # { ok: true, prompts: ["AI", "QIYE", "企业_1"] }
        │
        ▼
static/js/prompt_options.js
  loadPromptOptions()
  fillPromptSelect()
  refreshPromptSelects()
        │
        ├──────────────┐────────────────┐
        ▼              ▼                ▼
   机器人管理        快速配置         趣味实验室
   监听对象          添加用户         论坛角色选择
        │              │
        └──────┬───────┘
               ▼
        POST /submit_config 或 快速配置 POST
               │
               ▼
        listen_list_from_form() 校验
               │
               ▼
        save_config() → config.local.json 的 LISTEN_LIST
```

唯一文件名来源：`prompts/*.md`。

页面首次 HTML 里的 `{% for file in prompt_files %}` **仅存在于** `templates/*.html`，由 Flask 服务端渲染，属于合法首屏。动态新增行 **禁止** 再写 Jinja，一律走 `/api/prompts`。

全仓库复查：

- `static/*.js`：**没有** `{{ file }}` / `{% for file in prompt_files %}`
- `templates/quick_start.html`、`templates/config_editor.html` 中的 `{% for file in prompt_files %}`：服务端渲染，合法
- Prompt 管理列表：仍为 Jinja + 创建/删除后 `location.reload()`（P2 / 可优化，本轮保留）

---

## 5. 保存链路

```text
浏览器
  1. 点击「保存配置」
  2. PromptOptions.validateListenRows('#listen-list')
     - 空名称 → 禁止提交，文案「第 N 个监听对象未填写监听对象名称」，输入框 .listen-field-error + focus
     - 未选 Prompt → 禁止提交，文案「监听对象「名字」尚未选择 Prompt」，下拉框高亮 + focus
  3. FormData POST /submit_config
后端
  4. 若机器人进程仍在跑 → 400 BOT_RUNNING（明确文案，不再冒充所有错误）
  5. listen_list_from_form() 二次校验；不完整行 → 400 VALIDATION_ERROR，不 skip
  6. update_config() / save_config()
     FileLock(config.local.json.lock)
       写临时文件 → flush → fsync → os.replace（WinError 5 短重试）
  7. 成功 200 {"ok": true, "message": "配置保存成功"}
     写入失败 500 {"ok": false, "error": "CONFIG_WRITE_FAILED", "message": "无法写入配置文件", "detail": "<异常>"}
前端
  8. 仅当 response.ok && payload.ok 视为成功
  9. 失败用 apiErrorMessage：message +（若不同）detail
     例如：无法写入配置文件：[WinError 5] 拒绝访问。: config.local.json
     不再显示「请先停止运行程序！」作为万能失败文案
```

成功 / 失败字段前后端一致：`ok`、`error`、`message`、`detail`。

---

## 6. WinError 5 根因

**CONFIRMED（失败点）**

上一轮真实日志与代码路径一致：失败发生在 `os.replace(临时文件, config.local.json)`，Windows 返回 `WinError 5` / `PermissionError`。

本轮取证：

- 读：`load_config()` 使用 `with open(LOCAL_CONFIG_PATH)`，离开即释放句柄
- 写：`save_config()` 使用 `FileLock` + `_atomic_write`（mkstemp → 写入 → flush/fsync → replace）
- 应用代码没有在 `json.dump` 后不关闭文件的路径
- 单测：`os.replace` 前两次抛 `PermissionError`，第三次成功，配置仍为合法 JSON
- 浏览器连续 10 次真实 `POST /submit_config`：全部 `{"ok": true, "message": "配置保存成功"}`，`config.local.json` 仍可 `json.load`，`LISTEN_LIST` 完整

**NOT CONFIRMED（占用者身份）**

本轮没有在生产写入路径上抓到一个稳定的锁定进程名（编辑器 / 杀毒 / 索引服务等）。对真实 `config.local.json` 做独占锁探测被环境策略拦截，因此不能把「某个具体进程长期锁文件」写成已证实结论。

缓解措施（最小修改，未重构配置系统）：`fsync` + WinError 5 短重试。replace 失败时删除临时文件并返回 `CONFIG_WRITE_FAILED` + `detail`，不破坏原 JSON。

---

## 7. 自动测试结果

```
python -m unittest tests.test_webui_data tests.test_config_save tests.test_config_validate tests.test_store_io -v
Ran 28 tests in 0.368s
OK
```

| 用例 | 结果 |
| --- | --- |
| `test_listen_add_entry_js_does_not_embed_jinja` | passed |
| `test_api_prompts_returns_prompt_names` | passed |
| `test_api_prompts_tracks_create_and_delete` | passed |
| `test_complete_rows` / `test_missing_name` / `test_missing_prompt` | passed |
| `test_incomplete_listen_is_rejected` | passed |
| `test_missing_prompt_is_rejected` | passed |
| `test_write_failure_returns_real_message` | passed |
| `test_atomic_write_ten_times_keeps_valid_json` | passed |
| `test_replace_retries_permission_error` | passed |
| 其余既有 webui / validate / store_io | passed |

---

## 8. 浏览器测试结果

| 编号 | 内容 | 结果 |
| --- | --- | --- |
| TEST-01 | 机器人管理 → 新增监听对象，Prompt 为 AI / QIYE / 企业_1，无 `{{ file }}` | passed |
| TEST-02 | 快速配置 → 添加用户，真实 Prompt，无 `{{ file }}` | passed |
| TEST-03 | 连续添加 3 个用户，三行分别选 AI / QIYE / 企业_1 | passed |
| TEST-04 | 空名称点保存：拦截，「第 4 个监听对象未填写监听对象名称」，输入框高亮并聚焦 | passed |
| TEST-05 | 名称「张三」未选 Prompt：拦截，「监听对象「张三」尚未选择 Prompt」，下拉框高亮并聚焦 | passed |
| TEST-06 | 绕过前端直接 POST 空名称 / 空 Prompt：400 `VALIDATION_ERROR`，文案与前端一致 | passed |
| TEST-07 | 写入失败协议：500 `CONFIG_WRITE_FAILED`，前端 `无法写入配置文件：[WinError 5] ...`，**不是**「请先停止运行程序！」 | passed |
| TEST-08 | 真实环境连续保存 10 次，全部 200 `配置保存成功`，JSON 完好，无随机 WinError 5 | passed |
| TEST-09 | 新建 `_hardening_test` 后，监听对象 / 快速配置 / 论坛角色下拉均出现该名字 | passed |
| TEST-10 | 删除后新列表不再出现；已绑定值保留为 `_hardening_test`，文案「原 Prompt 已不存在」，不自动改绑 | passed |
| TEST-11 | 刷新后仍为 ceshi→企业_1、哈→企业_1、QIYE→QIYE | passed |
| TEST-12 | 重启 `config_editor.py` 后再打开页面，绑定与 `config.local.json` 一致 | passed |

测试后已删除 `_hardening_test.md`，未把测试行写入配置。

---

## 9. 遗留问题

### P2 / 可优化：Prompt 管理列表仍为 SSR + `location.reload()`

创建 / 删除 Prompt 后整页刷新，列表正确。本轮按任务要求不改为 `/api/prompts` 动态刷新，避免扩大改动。

无其它本轮测试新发现的功能缺陷。独占锁复现 WinError 5 的环境探测未获准执行；失败点本身已由上一轮日志与本轮代码/单测确认。
