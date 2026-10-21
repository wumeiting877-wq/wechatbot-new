# P9-G5 Implementation Report

> 日期：2026-09-24

## 代码

- 新增 `business_action_authorizer.py`：实现 `BusinessActionAuthorizer`、`AuthorizationDecision`、`TASK_ASSIGNEE_ONLY_V1` 与确定性拒绝状态。
- 修改 `business_action.py`：在 prepare 的唯一 Target 后授权；在 confirm 的 actor/state 校验后、生命周期前重新授权；公开 Business Action 状态 `NOT_AUTHORIZED`。
- 修改 `business_action_conversation.py`：增加身份未绑定、人员停用、任务未绑定负责人、一般无权限四类稳定文案；不披露真正负责人。
- 新增 `tests/test_p9g5_action_authorization.py` 19 条测试。
- P9-G3/G4 旧测试只补充明确 `Person + WechatBinding + TaskIdentityLink` 夹具；Preview、Confirmation、Idempotency、Crash Recovery 原断言保留。

## 未修改

- `task_command_parser.py`；
- Identity model/schema；
- `task_identity_link.py`；
- Action Record schema 与 action_id；
- Task Lifecycle、Task Store、Query 逻辑；
- 四个 Engine 与 Real Extractor expectation。

## 安全边界

拒绝发生在 BusinessActionService 内，结构化调用方不能绕过微信层直接 prepare。确认阶段的授权检查发生在 Action lock 内 actor 匹配之后，授权失败不会删除或改写 PREPARED。
