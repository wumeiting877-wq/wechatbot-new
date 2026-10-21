# P9-G5 Authorization Source Audit

> 日期：2026-09-24

## 唯一授权事实

```text
actor_ref = sender_wxid
sender_wxid --IdentityResolver.resolve_wxid--> actor person_id
conversation_id + task_id --TaskIdentityLinkStore.find_link--> target person_id
actor person_id == target person_id → AUTHORIZED
```

Actor Person 还必须存在且为 `ACTIVE`。Task Link 指向不存在的 Person 被视为身份数据损坏并拒绝。

## 明确未使用

- `sender_name`、`display_name`、`canonical_name`；
- `Task.assignee_text`；
- 昵称、包含匹配、拼音、模糊匹配；
- LLM、Prompt 或自然语言推断；
- 群主、管理员、经理、老板等非正式角色；
- 跨 Conversation 的 Task Link。

`business_action_authorizer.py` 不读取上述字段。`business_action_conversation.py` 中原有的 `assignee_text` 仅用于 Target 本身歧义时展示候选，不参与权限判断；授权拒绝文案不披露负责人。

## 异常映射

| 来源 | 结果 |
|---|---|
| wxid 未绑定 | `ACTOR_IDENTITY_NOT_FOUND` |
| wxid 指向多个 person | `ACTOR_IDENTITY_AMBIGUOUS` |
| Actor 为 DISABLED | `ACTOR_DISABLED` |
| Task Link 缺失 | `TASK_ASSIGNMENT_NOT_FOUND` |
| 同一会话任务存在重复/冲突 Link | `TASK_ASSIGNMENT_AMBIGUOUS` |
| Person 不一致 | `NOT_TASK_ASSIGNEE` |
| Identity/Link 损坏或引用悬空 | `IDENTITY_CORRUPT` |
| 非 COMPLETE_TASK | `ACTION_NOT_AUTHORIZABLE` |

所有非 `AUTHORIZED` 决策均为 deny，不存在 fallback。
