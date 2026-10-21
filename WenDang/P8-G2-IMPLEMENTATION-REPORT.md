# P8-G2 Implementation Report

> 日期：2026-09-23

---

## 1. 改了什么

```text
query_router.py                 候选门、身份问句、route_hybrid；补上「删除这个任务」整句写指令
query_intent_classifier.py      新模块。独立 prompt，只解析 query_type
llm_client.py                   call_narrow_completion，并加入现有 EXPORTS
query_formatter.py              三条固定安全文案
collaboration_query.py          REPLY 之后走 route_hybrid；分类在会话锁之前
tests/test_p8g2_query_intent.py 25 条，全部使用 Fake Completer
```

没有改 `query_service.py`。没有改 Chat Prompt、System Prompt、Memory Prompt。没有改四个 Engine、P0 去重、Store schema。

## 2. 调用链

```text
evaluate_inbound
↓
route_hybrid
    规则命中 → 不调用 classify
    candidate → classify → call_narrow_completion
↓
Query Service 或固定文案
↓
allow_reply
↓
try_acquire_session
↓
send_reply
```

`call_narrow_completion` 使用已经存在的主模型 client 和 `MODEL`。请求只有一条 system 和一条 user。超时 8 秒，`max_retries=0`，`temperature=0`，`max_tokens=128`。不碰 `chat_contexts`，不清理记忆，不改聊天超时。

## 3. 分类器边界

`query_intent_classifier.py` 不引用四个 Store，不写 processing，不调用 Engine / Extractor，不调用 `send_reply`，不调用 `get_deepseek_response`。

成功时回复正文来自 Query Service 和 Formatter。模型 JSON 里的 `answer` 或 `topic_title` 被忽略。

失败时发送固定指引并结束本轮。不把这句话送进 Topic 旁路。

## 4. 身份与写指令

查询形态的「我有什么任务 / 我的任务 / 张三负责什么 / 张三有哪些任务」在分类器之前结束，并给出固定回复。

「李明负责补材料」仍回到原旁路。

「删除这个任务」并入原有整句写指令，回复仍是「当前不能在这里修改任务、风险或决定。」

## 5. 没有做

```text
MY_TASKS 身份映射
TASKS_BY_ASSIGNEE 模糊匹配
写命令真正落库
跨会话查询
RECENT_DECISIONS
Query Queue / Worker
自动重试
新的业务 Engine
```
