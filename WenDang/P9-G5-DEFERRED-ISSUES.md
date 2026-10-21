# P9-G5 Deferred Issues

> 本文件只记录本 Gate 明确不实现的事项。

- 企业 RBAC：ADMIN、BOSS、MANAGER、PROJECT_MANAGER、PROJECT_OWNER 等；
- 管理员、经理、群主或机器人管理员 override；
- HR、组织架构、部门、岗位、审批与代确认；
- Task reassignment / TaskIdentityLink rebind；
- PREPARED 在持续无权限后的过期、撤销或人工处置状态；
- Action Record 中持久化 authorization snapshot；
- 人员目录维护 UI；
- Read Authorization；
- CURRENT_TASK、稳定短编号、重复标题交互消歧；
- COMPLETE_TASK 以外的写 Action；
- Real Extractor 42 条 live 依赖。

这些事项不得通过 sender_name、assignee_text、Prompt、LLM、昵称或角色猜测临时绕过。
