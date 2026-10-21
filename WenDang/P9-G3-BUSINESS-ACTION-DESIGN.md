# P9-G3 Business Action Design

> 日期：2026-09-23

v1 只有一条业务动作：`COMPLETE_TASK`。输入必须已经是结构化 `ActionRequest`。服务不解析自然语言，不发送微信。

## 1. 模块

```text
business_action.py         Action Service
business_action_store.py   Action Record / 幂等 / 锁
business_action_audit.py   append-only 追踪
```

服务可以依赖 `TaskTargetResolver` 和 `TaskLifecycleService`。它不调用 `update_task`，也不直接调用 `transition_task_status`。状态写入只发生在 `confirm_action` 内部的 `complete_task`。

## 2. ActionRequest

```text
action_type
conversation_id
message_id
actor_ref
target_selector
```

`actor_ref` 由调用方传入稳定账号 id，例如 `sender_wxid`。服务不读取 `sender_name`、nickname 或 display name。

`target_selector` 复用 `TaskTargetSelector`。服务不自己解释标题，一律交给 `TaskTargetResolver.resolve_task_target`。

## 3. 准备阶段

`prepare_action` 的顺序：

```text
动作类型必须是 COMPLETE_TASK
actor_ref 非空
message_id 非空
actions.json 未损坏
Resolver 得到 RESOLVED
当时 status = OPEN
写入一条 PREPARED
```

任一前序条件失败，都不创建可确认的 Action。`prepare_action` 不调用 `complete_task`，也不调用 `transition_task_status`。`tasks.json` 字节保持不变。

成功的 Preview 固定为四行：

```text
操作：完成任务
任务：接口联调
当前状态：OPEN
目标状态：DONE
```

`requires_confirmation = true`。`state = PREPARED`。任务此时仍是 `OPEN`。

## 4. 解析结果

| Resolver | Action |
| --- | --- |
| `AMBIGUOUS` | `ACTION_TARGET_AMBIGUOUS`，不选取候选 |
| `NOT_FOUND` | `ACTION_TARGET_NOT_FOUND` |
| `UNSUPPORTED_REFERENCE` | 原样返回，含 `CURRENT_TASK` |
| `INVALID_SELECTOR` | 原样返回 |
| `CORRUPT` | 原样返回，不创建 Action |
| `RESOLVED` 且 `DONE` | `NO_ACTION_NEEDED`，不写 PREPARED |
| `RESOLVED` 且 `IN_PROGRESS` / `CANCELLED` / 其它 | `ACTION_NOT_APPLICABLE` |

`actor_ref` 为空返回 `ACTOR_REQUIRED`。`message_id` 为空返回 `MESSAGE_ID_REQUIRED`。这两种情况不调用 Resolver。

其它动作类型返回 `ACTION_TYPE_NOT_ALLOWED`，包括 `CREATE_TASK`、`UPDATE_TASK`、`START_TASK`、`CANCEL_TASK`、`REASSIGN_TASK`、Risk、Decision、Topic 和 `DELETE`。

## 5. Action ID

```text
conversation_id
message_id
action_type
target_task_id
```

每个字段按长度前缀拼接后做 SHA1，得到 `act_<hash>`。正文、标题和 selector 类型都不进入这个指纹。同一次业务请求得到同一个 `action_id`，Action Store 里只有一条记录。

指纹不含 `actor_ref`。同一指纹先写入的记录保留其 `actor_ref`。后到的准备调用返回这条已有记录，不另建第二条。

## 6. 确认阶段

```text
confirm_action(action_id, actor_ref)
→ 读取已保存的 Action Record
→ 仅 PREPARED 可以进入执行
→ actor_ref 必须与记录一致
→ complete_task(conversation_id, target_task_id)
```

确认时不再按标题解析。Preview 当时确定的 `task_123`，确认时仍只操作 `task_123`。期间出现另一个同名任务也不改变目标。

没有 `confirm_action`，就没有 Task 写入。

## 7. 本 Gate 不做

不判断老板、项目负责人或普通成员。只保存 Actor 身份。不建立 `chat_id → pending action`。不接 `AgentReplyDelivery`。不写 Processing，不写 Evidence，不改 `TaskIdentityLink`。
