# 监听对象 Prompt 下拉框修复报告

## 1. 问题现象

页面：企业智能助手管理平台 → 机器人管理 → 监听对象。

已有监听对象的 Prompt 可以正常显示（例如 `ceshi -> 企业_1`、`哈 -> 企业_1`）。

点击【新增监听对象】后，新一行的 Prompt 下拉框没有显示系统已有 Prompt，只显示：

- `-- 选择 Prompt --`
- `{{ file }}`

`{{ file }}` 被当作普通文本渲染。

## 2. 根因

`static/js/config_editor.js` 中的 `addEntry()` 把 Flask/Jinja 模板语法写进了**静态 JavaScript 字符串**：

```javascript
row.innerHTML = `
    ...
    <select name="prompt_file" required>
        <option value="">-- 选择 Prompt --</option>
        {% for file in prompt_files %}
        <option value="{{ file }}">{{ file }}</option>
        {% endfor %}
    </select>
`;
```

该文件通过 `<script src=".../config_editor.js">` 加载，**不会经过 Jinja 渲染**。浏览器执行 JS 时不会处理 `{% for %}` / `{{ file }}`，因此把 `{{ file }}` 原样显示出来。

已有行正常，是因为它们写在 `templates/config_editor.html` 里，由服务端 Jinja 在 GET `/` 时展开为真实 Prompt 名。

两套生成逻辑不一致：初始化走服务端模板，新增行走未渲染的 JS 模板字符串。

## 3. 涉及文件

| 文件 | 作用 |
|---|---|
| `static/js/config_editor.js` | 统一 `loadPromptOptions()` / `fillPromptSelect()` / `addEntry()` |
| `templates/config_editor.html` | 已有行增加 `data-selected`，绑定丢失时显示「原 Prompt 已不存在」 |
| `webui_data.py` | 新增 `list_prompt_names()` 与 `GET /api/prompts` |
| `config_editor.py` | 主页 GET 改用 `list_prompt_names()`，与 Prompt 管理同一数据源 |
| `tests/test_webui_data.py` | 覆盖 API、目录扫描、JS 不再内嵌 Jinja |

## 4. 原错误代码位置

`wechatbot-new/static/js/config_editor.js` 原 `addEntry()`（约第 881–899 行）。

## 5. 修改内容

- 删除 JS 中的 `{% for file in prompt_files %}` / `{{ file }}`。
- 新增统一加载函数：
  - `loadPromptOptions()`：请求 `GET /api/prompts`
  - `fillPromptSelect(select, selectedValue)`：用 `document.createElement('option')` 填充
  - `addEntry()`：动态建行后调用上述函数
- 页面初始化对已有 `select[name="prompt_file"]` 也走同一套填充逻辑。
- 空列表、接口失败、已绑定 Prompt 被删除分别给出明确选项文案，不静默改绑其他 Prompt。
- 新增 `GET /api/prompts`，扫描 `prompts/*.md`，返回：

```json
{ "ok": true, "prompts": ["AI", "QIYE", "企业_1"] }
```

## 6. Prompt 数据来源

唯一数据源：项目目录 `prompts/` 下的 `.md` 文件（文件名去掉 `.md` 即为 Prompt 名称）。

这与 Prompt 管理页的创建 / 编辑 / 删除是同一目录，不在监听对象页面单独维护一份名字列表。

## 7. 页面初始化加载流程

1. GET `/` 渲染已有监听对象行，`data-selected` 保存当前绑定。
2. JS `DOMContentLoaded` 后调用 `loadPromptOptions()` → `GET /api/prompts`。
3. `refreshAllListenPromptSelects()` 用同一函数填充每一行 Prompt 下拉框。
4. 若绑定值不在当前 Prompt 列表中，保留原 value，文案为「原 Prompt 已不存在」。

## 8. 新增监听对象加载流程

1. 点击【新增监听对象】→ `addEntry()`。
2. 用 DOM API 创建一行（input / select / 删除按钮），不再拼接 Jinja。
3. 再次 `await loadPromptOptions()`（拿到最新 Prompt 列表）。
4. `fillPromptSelect(newSelect, '')` 填充该行下拉框。

## 9. 保存配置流程

未改保存接口本身。流程仍是：

1. 表单字段 `nickname` + `prompt_file` 成对提交到 `POST /submit_config`。
2. 后端写入 `config.local.json` 的 `LISTEN_LIST`。
3. 名称为空或 Prompt 为空的行会被跳过（原有逻辑）。
4. 刷新后按 `LISTEN_LIST` 重新渲染，并再次走统一 Prompt 加载。

实测：新增 `QIYE` 并选择 `企业_1`，保存成功后 `LISTEN_LIST` 为：

```json
[["ceshi", "企业_1"], ["哈", "企业_1"], ["QIYE", "企业_1"]]
```

刷新页面后三行均仍为对应 Prompt，未回退到「-- 选择 Prompt --」。

## 10. 测试结果

| 编号 | 场景 | 结果 |
|---|---|---|
| TEST-01 | 打开监听对象，已有行 Prompt 正常 | 通过。`ceshi` / `哈` 均为 `企业_1` |
| TEST-02 | 点击新增监听对象，下拉框显示真实 Prompt | 通过。选项为 `-- 选择 Prompt --`、`AI`、`QIYE`、`企业_1` |
| TEST-03 | 页面中不再出现 `{{ file }}` | 通过。监听对象 HTML / 正文 / `config_editor.js` 均无该字面量 |
| TEST-04 | 选择 `企业_1`，保存，刷新 | 通过。`QIYE -> 企业_1` 仍在 |
| TEST-05 | 连续新增 3 个监听对象，下拉框可独立选择 | 通过 |
| TEST-06 | 修改其中一个 Prompt，不影响其他行 | 通过。将新行改为 `AI` 后，`QIYE` 仍为 `企业_1` |
| TEST-07 | Prompt 管理新增后可被监听对象选择 | 通过。单元测试创建 `测试Prompt_001` 后 `/api/prompts` 包含该名；新增行每次都会重新请求该接口 |
| TEST-08 | Prompt 管理删除后新增行不再显示 | 通过。单元测试删除 `测试Prompt_001` 后接口不再返回 |
| TEST-09 | 重启程序后绑定仍在 | 通过（配置层）。绑定写入 `config.local.json` 的 `LISTEN_LIST`，与机器人进程无关 |

浏览器检查：

- Console：无因本次修改引起的 JS exception
- `GET /api/prompts`：200，结构 `{ok, prompts}` 与前端解析一致
- 无 `{{ file }}`、无 `prompts.map is not a function`

补充说明：第一次点保存时因 Windows 占用 `config.local.json` 出现 `WinError 5`，前端误报「请先停止运行程序」（见下方遗留问题）。第二次保存成功，刷新后绑定正确。

## 11. 是否还存在 `{{ file }}`

监听对象页相关静态 JS 中：**不存在**。

`templates/config_editor.html` 里 Prompt 管理、论坛角色选择、以及已有监听对象行的 `{% for file in prompt_files %}{{ file }}` 仍是合法服务端 Jinja，渲染后会变成真实文件名，不会显示 `{{ file }}`。

**未改** `templates/quick_start.html` 的 `addEntry()`，该页仍有同样的 Jinja-in-JS 问题（见遗留问题）。

## 12. 是否存在遗留风险

- 快速配置页「添加用户」仍用 JS 字符串里的 `{{ file }}`，该页未纳入本次修复范围。
- 保存失败时前端读取 `errorData.detail`，后端实际返回 `error`，会误显示「请先停止运行程序！」。
- 名称为空或未选 Prompt 的行保存时会被静默丢弃。
- Windows 下 `config.local.json` 被占用时保存会 `WinError 5`。
- Prompt 管理列表本身仍是服务端渲染；创建/删除成功后现有逻辑会 `location.reload()`，因此监听对象页能拿到最新列表。若将来去掉刷新，新增行仍会通过 `/api/prompts` 拿到最新数据，但已有行需再调一次 `loadPromptOptions()`。

本次未改微信监听、self 判断、消息发送、机器人回复、AI 模型、群聊策略、停止机器人、数据库结构和整体 UI。
