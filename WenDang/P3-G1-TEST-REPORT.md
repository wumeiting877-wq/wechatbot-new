# P3-G1 测试报告

> 日期：2026-09-21  
> 解释器：`wechatbot-new\.venv\Scripts\python.exe`  
> 命令：

```text
.\.venv\Scripts\python.exe -m unittest ^
  tests.test_topic_store ^
  tests.test_extractor_prompt ^
  tests.test_topic_engine_offline
```

结果：**39 tests, OK**

离线 fixture：`tests/fixtures/topic_engine/zhiqun_demo.json`、`boundary_cases.json`。  
未替换为更简单数据集。未 Start Bot，未 `wx.SendMsg`。

---

## 主样本

```text
PASS
```

最终 Topic 数 = **3**。title 落入近义白名单：

- A：ERP 数据同步异常
- B：权限整改
- C：现场演示准备

必含消息链接：0905/0906/0914 ∈ A；0907/0913 ∈ B；0910/0911/0917 ∈ C。  
未落盘 tasks/risks/decisions。0923/0925 未创建第四主题。

---

## CASE-01

```text
PASS
```

连续五条 ERP 讨论，最终 Topic 数 = **1**。

---

## CASE-02

```text
PASS
```

插入「中午吃什么？」→ `UNRELATED`，不新建 Topic。ERP Topic 仍为 1。

---

## CASE-03

```text
PASS
```

最终 2 个 Topic。最后一条 ERP 消息的 `topic_id` == 第一条 ERP `topic_id`。

---

## CASE-04

```text
PASS
```

「接口有问题」/「接口还是不通」最终 Topic 数 = **1**。第二条不得 NEW_TOPIC。

---

## CASE-05

```text
PASS
```

演示 Topic 被 6 个更新的无关 Topic 挤出「最近 5 个按时间」。  
「演示账号已经建好了」经关键词召回回到原演示 Topic。  
独立检索单测：`test_keyword_recall_beats_recency_only_top5` PASS。

---

## CASE-06

```text
PASS
```

`收到` / `好的` / `1` / `嗯` 全部 UNRELATED 或 SKIPPED。Topic 数 = **0**。

---

## CASE-07

```text
PASS
```

decision 数量 = **1**。`topic_id` 属于已有 ERP 或演示 Topic。  
未创建第三个「综合问题」。`multi_topic_supported = false`（限制，不是能力）。

---

## 失败注入

```text
PASS
```

| 项 | 结果 |
|---|---|
| Extractor timeout | PASS（FAILED，无脏 Topic，isolated） |
| Extractor exception | PASS |
| invalid JSON | PASS |
| invalid topic_id | PASS（不创建该 id） |
| Prompt missing | PASS（EXTRACTOR_PROMPT_NOT_FOUND，不调 LLM） |
| Prompt empty | PASS（EXTRACTOR_PROMPT_EMPTY，不调 LLM） |
| 测试进程不崩 | PASS |

FAILED 后同 message 可重试成功。

---

## 幂等

```text
PASS
```

| 项 | 结果 |
|---|---|
| 相同 platform_message_id 重放不重复 Message | PASS |
| Link 不重复 | PASS |
| 成功 processing 重放跳过 | PASS |
| FAILED 可重试 | PASS |
| message_count 不因重放增加 | PASS |
| 主样本整段重放 Topic/Link 数不变 | PASS |

---

## Gate 2 Prompt 隔离（附）

| 项 | 结果 |
|---|---|
| TOPIC_EXTRACTOR 可读取 | PASS |
| Chat Prompt loader 不读 extractors 子目录 | PASS |
| Extractor 不出现在 Chat Prompt 列表 | PASS |
| Prompt hash 稳定 | PASS |
| 文件缺失独立错误 | PASS |
| 空文件独立错误 | PASS |
