# P7-G2 WebUI Report

> 日期：2026-09-23

---

## 入口

`/operations` 每一行消息下有「查看详情」，进入：

```text
/operations/messages/<message_id>?conversation_id=<id>
```

页头链接为「← 返回运维中心」。

---

## 详情结构

```text
消息信息
    时间（message.created_at）
    入库时间（message.ingested_at）
    发送人
    消息内容
    Conversation
    Message ID

Runtime / Engine 状态

处理状态
    Topic / Task / Decision / Risk 的既有状态标签
    已存储 decision
    可重试：是 / 否

诊断详情
    每路 Processing、Entity、Evidence、Audit

人工重试审计
```

Evidence 分开显示 `CREATED_BY`、`UPDATED_BY`、`RELATED` 的条数。为 0 时写「无记录」。

Processing 不存在时写：

```text
Processing Record：未找到
处理状态未知
禁止自动重试
需要人工调查
需人工调查
```

有实体或证据时追加「系统存在业务写入痕迹，但无法从现有数据确定原 Processing Decision。」没有这些痕迹时写「未发现业务处理记录」。

Audit 区块固定显示：「Audit 为诊断记录，不是 Processing 真值。」

人工重试区块固定显示：审计不能用来补 processing。

---

## 没有新的操作按钮

详情模板没有 `<button>`，没有 `/retry`，没有 Repair / Reprocess。

`FAILED_RETRYABLE` 的「重试」仍只在列表页，走原来的 P7-G1 POST。详情页连失败状态也不放第二个按钮，避免出现第二套重试逻辑。

列表页的重试脚本、确认文案和单条刷新保持原样。

---

## 样式

沿用处理状态页的表格、定义列表和灰底标签。没有大统计卡片，没有渐变，没有图表。
