# P8-G6 Regression Report

> 日期：2026-09-23

P8-G1 到 P8-G5 重新通过。Non-Live 767 OK。旧 735 没有新增失败。

---

## 1. P8-G1 到 P8-G5

与 P8-G6 一起运行：

```text
tests.test_p8g1_collaboration_query
tests.test_p8g2_query_intent
tests.test_p8g3_query_delivery
tests.test_p8g4_identity
tests.test_p8g5_identity_model
tests.test_p8g6_task_identity_link
```

随后又跑了 `tests.test_task_engine_offline`、`tests.test_task_store`、`tests.test_task_sidepath`。合计 196 OK。

分类器枚举没有加入 `MY_TASKS`。`我有什么任务` 在规则层仍不是 `LIST_TASKS`。同名、自由文本负责人在没有 wxid / 别名 / 链接时仍不返回任务。`sender_name == assignee_text` 仍然不是身份绑定。

## 2. 一处受控断言

`tests/test_p8g5_identity_model.py` 的 `test_identity_model_13_my_tasks_stays_fixed`：

```text
未绑定 wxid 仍固定拒绝
QueryService 调用次数仍为 0
分类器仍为 0
不进入主题旁路
不创建 data/identity
```

拒绝句子从「暂不支持按个人身份查询」改为本 Gate 规定的「无法确定你的人员身份」。这是 P8-G4 固定拒绝在身份无法确定时的保留，文案换成了 P8-G6 的句子。

## 3. Non-Live

`discover -s tests`，排除四个 `Real*ExtractorTests`：

```text
Ran 767 tests in 52.638s
OK
failures 0
errors 0
```

767 = 进入本 Gate 前的 735 + 本 Gate 32。Real Extractor 42 条未运行，也未修改。

## 4. Engine 与 P0

```text
TOPIC_ENGINE_ENABLED=false
TASK_ENGINE_ENABLED=false
DECISION_ENGINE_ENABLED=false
RISK_ENGINE_ENABLED=false
```

没有改 P0，没有改 P6-G6 processing，没有改 Task schema。
