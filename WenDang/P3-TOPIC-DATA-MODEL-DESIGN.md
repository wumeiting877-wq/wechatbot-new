# P3 Topic 数据模型设计

> 日期：2026-09-20  
> 阶段：P3-G0  
> 对照：`P3-TOPIC-ENGINE-CURRENT-STATE-AUDIT.md`  
> 本文件是设计，不是已落地代码。

---

## 1. 设计目标

P3 只回答：

```text
当前 Conversation 正在讨论什么主题？
```

不存：负责人、截止时间、Task、Risk、Decision、进度、日报。  
这些字段即使 Demo 文本里出现，也不进入 Topic 模型。

绑定规则：

```text
Topic.conversation_id = Conversation.id     # conv_xxxxx
禁止 Topic.conversation = display_name
```

联系人 / 群改名后，Topic 仍属于原 Conversation。

---

## 2. 存储方案对比

### 方案 A：独立 JSON Store（推荐）

```text
data/topic_store/
  conversations/{conversation_id}/
    messages.jsonl          追加 MessageRecord
    topics.json             Topic 列表（小，可整体重写）
    links.json              TopicMessageLink
    processed.json          幂等标记
  topic_engine_audit.jsonl  处理审计（无 API Key）
```

优点：

- 复用现有 `store_io` 原子写 / FileLock
- 不污染 `config.local.json`
- Demo 体量（3 会话、数十条消息）完全够用
- 按 Conversation 分目录，删除会话可整目录处理
- 实施成本低于引入 ORM

缺点：

- 跨会话查询弱（P3 不需要）
- Message 增长后整文件 rewrite 不适合；所以 **消息用 jsonl 追加**
- 并发以进程内锁 + 文件锁为准（与现网一致）

### 方案 B：SQLite

适合以后 Message 过万、P4 要 JOIN Task/Risk/Evidence。  
当前仓库 **没有业务 SQLite**，只有 wechatauto 读微信客户端库。  
为 Demo 上 SQLite 会引入迁移、备份、连接生命周期，收益不明显。

### 方案 C：塞入现有存储

| 现有位置 | 判定 |
|---|---|
| `config.local.json` | **禁止**。配置文件已含密钥与 CONVERSATIONS；Topic/Message 会持续膨胀 |
| `chat_contexts.json` | **禁止**。窗口缓存，按 nickname，会裁剪 |
| `CoreMemory` | **禁止**。记忆摘要，无 id / evidence |
| `AGENT_CONFIGS` | **禁止**。Agent 配置不是业务事件 |

### 推荐

**方案 A：独立 JSON Store。不上 SQLite，不上大型数据库。**

升级条件（P4+ 再评估，不构成本轮 BLOCKER）：

- 单会话 MessageRecord > ~5000 且检索变慢
- 需要跨会话 Topic 搜索
- P4 实体要与 Evidence 做稳定 JOIN

第一阶段目录名 `data/topic_store/`，**不要**写进 `config.local.json`。  
`config.local.json` 最多以后加一个可选路径配置，G1 实施时再定，G0 不改配置 schema。

---

## 3. 实体总览

```text
Conversation.id
    ├── MessageRecord[]          该会话持久化消息
    ├── Topic[]                  该会话主题
    ├── TopicMessageLink[]       N:N evidence
    └── TopicProcessingRecord    每条 Message 的处理幂等标记
```

ID 前缀与现网对齐：

```text
conv_xxxxxxxxxxxx
agt_xxxxxxxxxxxx
msg_xxxxxxxxxxxx
topic_xxxxxxxxxxxx
```

---

## 4. MessageRecord（业务持久化，不是 InboundMessage）

P0 `InboundMessage` 保持运行时对象，**不重构**。

投影：

```text
InboundMessage  --normalize/project-->  MessageRecord
```

```text
MessageRecord

id                      msg_{12 hex}          内部主键
conversation_id         conv_xxxxx            必须是 Conversation.id
platform_message_id     chat_wxid:local_id    来自 InboundMessage，可空
sender_id               原始 sender_id        可空
sender_wxid             稳定发送者            可空
sender_name             展示名
content                 规范化正文
message_type            text | quote | ...    来自 raw_type
created_at              ISO-8601              优先平台时间，否则入库时间
direction               INBOUND | OUTBOUND
reply_to_message_id     msg_xxxxx | ""        能解析才写；第一阶段常空
raw_reference           小结构，见下
ingested_at             ISO-8601
schema_version          1
```

`raw_reference`（最小）：

```json
{
  "chat_name": "QIYE",
  "chat_wxid": "58847495172@chatroom",
  "local_id": "123",
  "create_time": 1690000000,
  "quote_excerpt": "供应商编码为空"
}
```

不存：完整 WxMessage 对象、鼠标/窗口、API Key。

### id 生成

```text
msg_id = "msg_" + sha1(
    conversation.id + "|" + (platform_message_id or event_fingerprint)
)[:12]
```

`event_fingerprint` 仅在没有 `platform_message_id` 时使用：

```text
sender_wxid|message_type|create_time|normalized_content
```

同一 `platform_message_id` 在同一 Conversation 下必须得到同一 `msg_*`。  
这是业务层幂等的第一道，与 P0 Dedupe 内存 TTL **独立**。

### 与 InboundMessage 的边界

| | InboundMessage | MessageRecord |
|---|---|---|
| 生命周期 | 单次回调 | 长期 |
| conversation_id | wxid / nickname | `conv_*` |
| content | 运行时全文 | 持久化全文 |
| 用途 | Self / Dedupe / Trigger | Topic / Evidence |
| 可否修改 P0 字段 | **禁止** | 新增 store |

OUTBOUND（机器人自己的回复）第一阶段 **可以入库但不送 Extractor**。  
入库是为了上下文完整；分析对象默认只处理 `direction=INBOUND` 且发送者非 bot。

---

## 5. Topic

```text
Topic

id                  topic_{12 hex}
conversation_id     conv_xxxxx           禁止 nickname
title               短业务标题            例如「ERP 数据同步异常」
summary             当前理解（可变）
status              ACTIVE | WAITING | RESOLVED | ARCHIVED
confidence          HIGH | MEDIUM | LOW  最近一次有效判断
created_at          ISO-8601
updated_at          ISO-8601
last_message_at     ISO-8601
message_count       int                  由 links 维护，可冗余
schema_version      1
```

不采用建议字段里的 `OPEN` 作为第一阶段写入值。  
枚举仍 **保留 OPEN** 以便以后兼容，但引擎只创建 `ACTIVE`。理由：OPEN 与 ACTIVE 在 Demo 中无产品差异，两个「进行中」会增加 Extractor 噪声。

```text
写入白名单（P3 v1）：ACTIVE
只读/预留：OPEN, WAITING, RESOLVED, ARCHIVED
```

### Topic.id 生成

**不要**用 title hash（标题会被更新）。

```text
topic_id = "topic_" + sha1(
    conversation.id + "|" + created_msg_id + "|" + utc_now_iso
)[:12]
```

`created_msg_id` 是 CREATED_BY 那条 MessageRecord.id。  
碰撞时后缀 `_2`（与 Conversation 首次迁移同策略）。  
一旦写入，id 永不因改名 / 改 summary 而重生。

---

## 6. TopicMessageLink（Evidence）

P3 就必须可追溯。用户看到「ERP 数据同步异常」时，必须能列出形成它的消息。

```text
TopicMessageLink

id              link_{12 hex}          可选；也可用 (topic_id, message_id, relation) 联合唯一
topic_id        topic_xxxxx
message_id      msg_xxxxx
relation        CREATED_BY | RELATED | UPDATED_BY
confidence      HIGH | MEDIUM | LOW
created_at      ISO-8601
```

联合唯一：

```text
(topic_id, message_id, relation)
```

同一消息对同一 Topic 的同一 relation 不得重复插入。

relation 语义：

| relation | 何时 |
|---|---|
| CREATED_BY | NEW_TOPIC 的那条消息，每个 Topic 恰好一条 |
| RELATED | 归属已有 Topic，无足够新事实更新 summary |
| UPDATED_BY | 归属已有 Topic，且 summary 被更新 |

---

## 7. Message ↔ Topic 基数（架构决策，本轮不实现）

### 方案对比

| | 处理时 1 Message → 1 Topic | 处理时 1 Message → N Topics |
|---|---|---|
| Extractor 输出 | 单 decision | `decisions[]` |
| 实现复杂度 | 低 | 中 |
| Demo「ERP 完了，但现场 Wi-Fi 还不行」 | 丢一半 | 可两边挂 |
| CASE-07 | 必须声明不支持 | 可支持 |
| 存储 | 即使 1:1 处理，link 表仍可 N:N | 同左 |

### 推荐

```text
存储模型：N:N（TopicMessageLink 从第一天就按多对多建）
Extractor v1：每次调用只产出 1 个 decision（1 Message → 1 主 Topic）
```

理由：

- 表结构一次做对，P3.1 加多决策不必迁 schema。
- v1 Prompt 单决策更稳，避免模型乱造第二个 Topic。
- **不伪装支持 multi-topic。** CASE-07 为已知限制。

双主题消息的 v1 行为：

1. 选 **主业务对象**（当前句更强调的那个）。
2. `confidence` 最多 MEDIUM。
3. `reason` 写明另一主题被省略。
4. 不得为此再造一个模糊大 Topic（如「项目综合」）。

---

## 8. TopicProcessingRecord（业务幂等）

P0 Dedupe 防的是微信重复回调。  
同一条 MessageRecord 仍可能被离线重放、G1 重跑 fixture、或将来手动重提取。

```text
TopicProcessingRecord

message_id                  msg_xxxxx
conversation_id             conv_xxxxx
topic_processing_version    1
extractor_prompt_name       TOPIC_EXTRACTOR
extractor_prompt_hash       sha256
decision                    NEW_TOPIC | EXISTING_TOPIC | TOPIC_UPDATE | UNRELATED | SKIPPED | FAILED
topic_id                    可空
processed_at                ISO-8601
error                       可空；不含密钥
```

主键：`message_id` + `topic_processing_version`。

规则：

- 已有成功记录（decision 非 FAILED）→ 跳过，不建 Topic、不重复 link、不刷新 summary。
- FAILED 允许按同一 version 重试。
- 更换 Prompt 正文（hash 变）**默认不自动重跑**；升 `topic_processing_version` 才重跑。
- **不修改** P0 `DedupeIndex`。

---

## 9. 生命周期与级联（隐私，先设计）

Topic Store 可能保存真实企业消息。不做权限系统，但必须有删除语义。

| 事件 | 行为 |
|---|---|
| 删除 Conversation | 删除 `data/topic_store/conversations/{id}/` 整目录（Topic + Message + Link + processed） |
| 删除单条 Message | MessageRecord 标记 `deleted_at`；Link 保留 `message_id`，content 改为空或 `[redacted]`；Topic.summary 不自动改写 |
| 保留期限 | P3 v1 **不自动过期**。后续可加按 Conversation 的保留天数 |
| 导出 / 备份 | jsonl 可复制；禁止把 API Key 写入任何 topic 文件 |
| 日志 | 审计可记 content 的短 preview（≤80 字），完整正文只在 MessageRecord |

第一阶段不做多租户 ACL。本地单实例默认：能访问 Bot 数据目录即能访问 Topic Store。

---

## 10. 不放入本模型的字段

```text
assignee / owner / due_at
task_ids / risk_ids / decision_ids
progress_percent
daily_report_flag
embedding / vector
```

Extractor 若输出这些，校验器丢弃，不落盘。
