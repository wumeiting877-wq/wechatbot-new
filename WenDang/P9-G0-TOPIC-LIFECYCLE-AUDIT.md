# P9-G0 Topic Lifecycle Audit

> 扫描：`topic_store.py`、`topic_engine.py`、`topic_sidepath.py`、`topic_extractor_client.py`
> 结论先写：生产 Engine 不改变 `Topic.status`。没有 RESOLVED / ARCHIVED 写入链。

## 1. 状态常量

`topic_store.py`：

```text
TOPIC_STATUS_ACTIVE = ACTIVE
TOPIC_STATUS_WAITING = WAITING
TOPIC_STATUS_OPEN = OPEN
TOPIC_STATUS_RESOLVED = RESOLVED
TOPIC_STATUS_ARCHIVED = ARCHIVED
CANDIDATE_STATUSES = (ACTIVE, WAITING, OPEN)
```

候选集合给检索用。它不表示 Engine 会把主题写成 WAITING 或 OPEN。

## 2. 创建

`create_topic` 把 status 写成 `ACTIVE`。没有别的创建状态。

## 3. 生产 Engine 实际更新什么

`TopicEngine._apply_decision`：

```text
NEW_TOPIC
  → create_topic（status=ACTIVE）
  → 链接 CREATED_BY / RELATED

EXISTING_TOPIC / TOPIC_UPDATE
  → add_link
  → update_topic 的 fields 只有 confidence、last_message_at
  → TOPIC_UPDATE 且摘要非空时再加 summary
  → refresh_topic_message_count（message_count、last_message_at）
```

这次调用不传 `status`。Extractor 允许的 decision 是 `NEW_TOPIC`、`EXISTING_TOPIC`、`TOPIC_UPDATE`、`UNRELATED`，没有 RESOLVED / ARCHIVED。

```text
生产 Engine 不会改变 Topic.status
```

创建之后，生产路径上的主题保持 `ACTIVE`。

## 4. Store 比 Engine 松

`update_topic` 在调用方传入 `status` 时，会把该字符串原样写上。这里没有允许列表，也不区分 RESOLVED 与任意别的词。

这是 Store 方法的行为，不是生产能力。当前 Engine 不传这个字段。不能据此说「已经支持把主题标成结束」。

## 5. 「这个事情已经结束了」

```text
没有正式的 RESOLVED 写入链
没有正式的 ARCHIVED 写入链
```

标记：Deferred。

这句话匹配不上 Command 模板，会进入普通聊天。`TOPIC_ENGINE_ENABLED=false`，旁路不跑。即便旁路打开，现有 Engine 也只可能更新摘要或链接，不会把 status 写成 RESOLVED 或 ARCHIVED。

微信回复里的主题状态来自已存储的值。列表和摘要不提供结束主题的写入口。
