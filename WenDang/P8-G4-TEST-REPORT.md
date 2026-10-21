# P8-G4 Test Report

> 日期：2026-09-23  
> 分类：TYPE C。测试锁定「不能查询」，不实现查询。

---

## 1. 结果

```text
.\.venv\Scripts\python.exe -m unittest tests.test_p8g4_identity -v
Ran 3 tests in 0.080s
OK
```

| 用例 | 场景 | 结果 |
| --- | --- | --- |
| IDENTITY-01 | `sender_name` 与 `assignee_text` 都是「李明」，且带 `sender_wxid` | 仍回复「当前暂不支持按个人身份查询任务」，不出现「完成接口联调」 |
| IDENTITY-02 | 两个不同 wxid 都叫张三；库里有两条 `assignee_text=张三` | 不猜。两条「我有什么任务」都是个人固定句；「张三负责什么」「张三有哪些任务」是人员固定句。两个人的任务不混在回复里 |
| IDENTITY-03 | 负责人文本为「李明负责」「由李明」「研发部李明」「@李明」和空 | 「李明有哪些任务」「李明负责什么」不模糊命中这些任务 |

三条都确认：

```text
Query Intent Classifier calls = 0
QueryService 不被调用
不进旁路，不进 Chat
tasks.json / topics.json / decisions.json / risks.json / links.json / processed.json 字节不变
四个 Engine 开关仍为 false
```

## 2. 未跑的实现用例

IDENTITY-10 到 IDENTITY-17 依赖已证明的人员主键。TYPE C 不实现，这些用例不存在，也不该用昵称匹配去凑绿。
