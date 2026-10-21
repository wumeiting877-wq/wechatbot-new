# P9-G0 Decision Lifecycle Audit

> 扫描：`decision_store.py`、`decision_engine.py`、`decision_sidepath.py`、`decision_extractor_client.py`、`prompts/extractors/DECISION_EXTRACTOR.md`
> 结论先写：生产只新建 RECORDED。`supersedes_decision_id` 是关系指针。旧 Decision 的 status 不会被改成 SUPERSEDED。

## 1. 状态常量

`decision_store.py`：

```text
DECISION_STATUS_RECORDED = RECORDED
DECISION_STATUS_SUPERSEDED = SUPERSEDED
DECISION_STATUS_CANCELLED = CANCELLED
ALLOWED_WRITE_STATUSES = (RECORDED,)
```

文件头：v1 不提供原地覆盖 `decision_text`，不自动写 SUPERSEDED / CANCELLED。

没有 `update_decision`。

## 2. 生产写入支持什么

Extractor 允许的 decision 只有：

```text
NEW_DECISION
UNRELATED
```

`DECISION_UPDATE`、`SUPERSEDED`、`CANCELLED` 在禁止列表里，解析时直接失败。输出里的 `status` 键会被剥掉。

`create_decision` → `_normalize_new_decision`：

```text
status 不是 RECORDED → INVALID_STATUS「v1 只允许写入 RECORDED」
落盘 status 强制为 RECORDED
```

Engine `_apply_decisions` 只接受 `NEW_DECISION`，记录里写 `status = RECORDED`，然后 `commit_apply(new_decisions, new_links)`。`commit_apply` 没有 updates 参数，不会回写旧行。

```text
CURRENT PRODUCTION WRITE = RECORDED ONLY
```

允许的消息关系只有 `CREATED_BY`、`RELATED`。`UPDATED_BY`、`CONFIRMED_BY`、`SUPERSEDED_BY` 被禁止。

没有按 decision_id 删除。`delete_conversation_decision_data` 只删整个会话目录。

## 3. supersedes_decision_id 是什么

它是新 Decision 上的关系指针，不是旧行的状态迁移。

写入时：

```text
Engine 校验：非空指针必须出现在本次 existing_decisions 的 id 里
create_decision 校验：指针必须指向本会话已有 Decision
两条路径都不读取旧行再改它的 status
```

提示词写明：替换关系只写在新行的 `supersedes_decision_id`，禁止自动把旧 Decision 标成 SUPERSEDED / CANCELLED。

查询层的隐藏是另一件事：

```text
QueryService._effective_decisions
若某条 Decision 的 id 被别的行的 supersedes_decision_id 指向
列表和主题摘要里不再展示被指向的那条
```

被隐藏的行在 Store 里仍然是 `status = RECORDED`。`list_decisions` 原样返回它们。

`list_recorded_decisions(current_effective=True)` 也会先按指针过滤；若过滤后一条不剩，这个 Store 辅助方法会退回展示全部 RECORDED。查询服务不走这个退回，查询路径会把被指向的行都拿掉。

```text
supersedes_decision_id = 关系指针
不是「真正会修改旧 Decision.status」
```

## 4. 「之前那个决定作废，改成周一上线」

| 问题 | 代码事实 |
| --- | --- |
| 能否新建一条新 Decision | Engine 开启时，`NEW_DECISION` 可以新建，status 只能是 RECORDED。当前 `DECISION_ENGINE_ENABLED=false`，这条旁路不跑 |
| 能否写上 `supersedes_decision_id` | 可以。Extractor 允许这个字段。Engine 要求它等于某条 existing decision id。Store 创建路径要求目标已存在 |
| 能否把旧 Decision 标成 SUPERSEDED | 不能。没有更新旧行 status 的代码。写 SUPERSEDED 会在规范化时 `INVALID_STATUS` |
| 微信现在能不能做 | 不能。「修改这个决定」命中 Command，固定拒绝。这句「作废，改成周一上线」匹配不上 Command 全字模板，落入普通聊天；Engine 关闭，不会写 Decision |

```text
新建 + 指针 = 代码合同里有，生产 Engine 当前关闭
旧 status = SUPERSEDED = 没有这条写入
```

不能把查询时隐藏旧决定说成旧决定已经 SUPERSEDED。
