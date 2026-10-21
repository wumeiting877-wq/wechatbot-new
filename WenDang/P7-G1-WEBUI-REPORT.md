# P7-G1 WebUI Report

> 日期：2026-09-23

---

## 按钮

`/operations` 只在 `state == FAILED_RETRYABLE` 且 `retryable` 时渲染「重试」。

```text
SUCCESS、UNRELATED、SKIPPED  无按钮
NOT_FOUND_UNKNOWN             无按钮，也没有禁用按钮
```

页面没有全选、批量重试或「重试全部」。

---

## 确认与双击

Topic：

```text
确认重新执行「Topic」处理？
Topic 重试成功后可能按现有规则再次触发 Task / Decision / Risk。
```

Task / Decision / Risk：

```text
确认重新执行「当前这一路」处理？
本操作只会重新执行这一路，不会重新执行 Topic，也不会触发另外两路。
```

点击后先占住 `data-busy`。确认取消则恢复。确认后按钮禁用，文案变为「正在重试…」。这只挡住普通双击；同时请求仍由服务器的 identity 锁和重读挡住。

---

## 完成后

POST 返回后，页面再请求：

```text
GET /api/operations/messages/<message_id>?conversation_id=...
```

用返回结果重画四列和原因。不整页刷新。

结果文案：

```text
重试完成            after 为 SUCCESS，并带上最新 decision
重试仍失败          保留 error
当前状态已变化      NOT_RETRYABLE
处理状态未知…       NOT_FOUND_UNKNOWN
```

---

## 浏览器核对

用临时 Store 打开了 `/operations`。快照里只有一个「重试」按钮，页脚说明未知状态没有重试按钮。未知行没有按钮。接口契约由 Flask test client 覆盖。没有在生产页面上点击重试。
