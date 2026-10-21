# P8-G4 Identity Classification

> 日期：2026-09-23  
> 分类：**TYPE C**

---

## 1. 判定

```text
P8-G4 = TYPE C
只有姓名 / 昵称 / 自由文本
没有确定性 identity join key
```

不实现 `MY_TASKS`。不实现 `TASKS_BY_ASSIGNEE`。保持 P8-G2 的固定安全回复。

---

## 2. 为什么不是 TYPE A

TYPE A 需要已经存在的稳定关系，例如：

```text
sender_wxid ↔ person_id
Task ↔ 同一个 person_id
```

真实系统里：

```text
sender_wxid 只挂在消息发送者上
Task 没有 person_id，并主动删除 assignee_id / assignee_wxid
```

消息上的 wxid 与任务上的负责人文本没有共同键。不构成 TYPE A。

---

## 3. 为什么不是 TYPE B

TYPE B 需要一份稳定人员目录，并且能证明：

```text
wxid → employee → canonical_name
Task.assignee_text 严格规范化后唯一对应这一个人
不存在重名、别名歧义、多人文本
```

真实系统里没有这份目录。

`CONVERSATIONS` 是聊天窗口，不是人。私聊的 `platform_conversation_id` 是对方会话 wxid，下面没有「这个 wxid 的规范姓名」，也不能用来过滤群里的 `assignee_text`。

`HeuristicTaskExtractor._KNOWN_NAMES` 是六个汉字的离线夹具。它用「开头匹配」或「前 8 个字里包含」来切名字，没有 id，也不能证明唯一。生产抽取不走这张表。

`assignee_text` 只做 strip。它不保证是姓名，也不保证唯一。字符串相同不能升格成身份相同。

因此不存在可以安全桥接的 TYPE B。

---

## 4. 为什么是 TYPE C

能用来对上的材料只有：

```text
sender_name
窗口昵称
Task.assignee_text
```

例如 `sender_name = 李明` 且 `assignee_text = 李明`，仍然没有唯一、稳定、明确的身份来源。两个都叫张三的发送者只有两份不同的 `sender_wxid`，任务侧无法表示「哪一个张三」。

规范禁止用昵称、包含、编辑距离、拼音或模型来补这层关系。本 Gate 到此停止。

---

## 5. 若要解除阻塞

需要单独一阶段的身份模型，而不是在本 Gate 给 Task 偷偷加字段。至少要先有：

```text
稳定人员主键
发送者 wxid 到该主键的已证明映射
任务负责人到同一主键的已证明映射
重名时保持 AMBIGUOUS
```

在那之前，个人任务查询保持固定拒绝。
