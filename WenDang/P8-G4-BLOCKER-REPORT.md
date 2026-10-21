# P8-G4 Blocker Report

> 日期：2026-09-23  
> 状态：BLOCKED / NEEDS IDENTITY MODEL UPGRADE

---

## 1. 阻塞原因

缺少确定性 identity join key。

```text
InboundMessage.sender_wxid   发送账号，可空
InboundMessage.sender_name   昵称，可回落到窗口名
Task.assignee_text           自由文本
```

中间没有 `person_id`，也没有 wxid 到规范姓名的目录。Task Store 明确禁止 `assignee_id` 和 `assignee_wxid`。

因此：

```text
MY_TASKS 无法安全实现
TASKS_BY_ASSIGNEE 无法安全实现
```

`sender_name` 与 `assignee_text` 写成同一个「李明」，不是身份证明。

---

## 2. 本 Gate 拒绝的做法

```text
按昵称模糊匹配
字符串包含
编辑距离
拼音相似
用 LLM 猜是不是同一个人
用聊天上下文猜负责人
用 sender_name 直接当 assignee_text
为了让 Gate 变绿而给 Task 加 assignee_id / assignee_wxid / employee_id
扫描其他会话
把身份映射顺手用于写任务
```

---

## 3. 保持的行为

这些句子仍在分类器之前结束，固定回复，不读 Task Store，不进 Chat，不进旁路：

```text
我有什么任务
我的任务
张三负责什么
张三有哪些任务
```

回复仍是：

```text
当前暂不支持按个人身份查询任务。
你可以问“现在有哪些任务？”

当前暂不支持按人员身份查询任务。
```

`现在有哪些任务` 仍是 `LIST_TASKS`，只列当前会话。

---

## 4. 下一阶段

单独设计身份模型。本 Gate 不改 Task schema。
