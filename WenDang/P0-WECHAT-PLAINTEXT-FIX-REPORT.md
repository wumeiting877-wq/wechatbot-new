# P0 微信纯文本修复报告

> 日期：2026-09-20  
> 范围：发出前 Markdown → 微信普通文本；正文一次发送  
> **P0 STATUS = CLOSED**

---

## 1. 问题

真机回归时，机器人回复正文仍出现：

```text
|---|---|
```

以及标题 `#`、加粗 `**`。  
此前已去掉部分 Markdown，并改为一次发送，但 **Markdown Table 未处理**。

微信是普通文本气泡，不渲染 Markdown。

---

## 2. 处理链（当前）

```text
LLM 返回
    ↓
remove_timestamps / 可选去括号
    ↓
strip_markdown_for_wechat  →  WeChatPlainTextFormatter
    ↓
split_message_with_context  →  只拆 [tickle] / [recall]
    ↓
register_outbound
    ↓
wx.SendMsg（一条正文）
```

入口：`bot.py` `send_reply`。

---

## 3. 规则

`WeChatPlainTextFormatter`：

| 输入 | 输出 |
|---|---|
| `## 当前状态` | `当前状态` |
| `**当前状态说明**` | `当前状态说明` |
| 含 separator 的表格 | `名称：ERP` / `状态：完成` |
| `对比结果：A \| B`（无 separator） | 原样保留，不删 `\|` |
| 代码围栏 | 去掉 \`\`\`，保留内容 |
| 围栏内的表格 | **不**当表格转换 |

禁止全局 `replace("|---|---|", "")`。  
只在「表头行 + separator 行」结构成立时改写。

`split_message_with_context`：不再按 `$` 或换行切正文。混合标题/加粗/表格/列表仍是 **一条** 微信消息。

---

## 4. 测试

单元：`tests/test_wechat_reply_format.py` TEST-A01～A04 及表格多行、业务竖线、代码围栏。**PASS**。

真实微信最终回归：

| 项 | 结果 |
|---|---|
| 表格、标题、加粗转为纯文本 | PASS |
| 回复正文一次性发送，不再分段 | PASS |

---

## 5. 已知限制（不阻塞 P0）

复杂嵌套 HTML 表格、GFM 对齐以外的奇异 separator，未作为 P0 范围。  
当前规则覆盖真机已出现的 `|---|---|` 与 `:---|---:` 形式。
