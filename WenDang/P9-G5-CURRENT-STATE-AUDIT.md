# P9-G5 Current State Audit

> 日期：2026-09-24  
> Gate 0：只读审计先于实现完成。进入基线为 Non-Live 880 OK，四个 Engine 均为 false。

## Gate 0 七项结论

1. 微信 Action 入口的 `actor_ref` 由 `business_action_conversation._actor_ref` 直接读取 `inbound.sender_wxid`。显示名只用于消息投递参数，不进入 ActionRequest。
2. 身份解析的生产创建位置原有两处：`collaboration_query` 和 `query_service`。本 Gate 在 `BusinessActionService` 默认构造的 `BusinessActionAuthorizer` 内新增写动作专用的 `IdentityStore` / `resolve_wxid` 使用点。
3. `TaskIdentityLinkStore.find_link(conversation_id, task_id)` 同时匹配会话和任务；返回零条、唯一一条，重复时抛 `TaskIdentityLinkError`，能够作为严格唯一负责人来源。
4. Link 文件缺失返回空集合；目标 Link 缺失返回 `None`；重复或冲突 Link 抛错；JSON/结构损坏抛 `CORRUPT`。Identity 文件缺失表现为未绑定，损坏抛 `IdentityStoreError`。所有异常都可 safe-deny。
5. 两个授权点确定为：`prepare_action` 在 Target 唯一解析后、状态适用性和 Preview 前；`confirm_action` 在 Action Store 校验 PREPARED 与 actor 一致后、生命周期调用前。
6. 不需要 Action Record schema change。授权事实每次从 Identity 与 TaskIdentityLink 当前状态读取，审计记录拒绝原因即可。
7. 老 PREPARED 与当前 schema 相同；确认时按记录中的 `conversation_id + target_task_id + actor_ref + action_type` 重新授权，不重新解析标题，也不因旧记录跳过授权。

## 顺序

```text
prepare: request validation → target resolution → authorization → status applicability → PREPARED
confirm: action lookup/state/actor match → authorization re-check → lifecycle → terminal action state
```

Target `NOT_FOUND` / `AMBIGUOUS` / `UNSUPPORTED` 时不调用 Authorizer。未授权者不会通过该流程得到目标状态。

## 结论

没有出现 schema breaking change 或 STOP 条件，可以进入实现。
