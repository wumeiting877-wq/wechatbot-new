# P8-G6 Test Report

> 日期：2026-09-23  
> 命令：`python -m unittest tests.test_p8g6_task_identity_link`  
> 结果：32 OK

---

## 1. TaskIdentityLink

| 用例 | 结果 |
| --- | --- |
| LINK-01 MANUAL 创建 | PASS |
| LINK-02 重复绑定幂等 | PASS |
| LINK-03 第二个人 CONFLICT，原链接不变 | PASS |
| LINK-04 PERSON_NOT_FOUND，不建文件 | PASS |
| LINK-05 TASK_NOT_FOUND，不建文件 | PASS |
| LINK-06 CONVERSATION_MISMATCH | PASS |
| LINK-07 DISABLED 不允许新链接 | PASS |
| LINK-08 CORRUPT，原字节保持 | PASS |
| LINK-09 `李明` → EXACT_EXPLICIT_ALIAS | PASS |
| LINK-10 `李明负责` → NOT_FOUND，不写链接 | PASS |

另有：preview 不调用写入；源码没有解绑、改派、模糊匹配和发送者姓名匹配。

## 2. 新任务与更新

| 用例 | 结果 |
| --- | --- |
| 新任务精确别名可绑定；历史同名任务保持未绑定 | PASS |
| 链接抛错时 Task processing 仍成功，任务仍在 | PASS |
| assignee_text 改为王强后，旧 person_001 链接保留 | PASS |
| `李明负责` 的 best-effort 不写链接 | PASS |

## 3. 个人查询

| 用例 | 结果 |
| --- | --- |
| PERSONAL-01 同名文本只返回已链接任务 | PASS |
| PERSONAL-02 只返回当前 person | PASS |
| PERSONAL-03 未绑定 wxid，固定拒绝，QueryService 未调用 | PASS |
| PERSONAL-04 空 wxid 不回退 sender_name | PASS |
| PERSONAL-05 别名张三，显示 canonical_name 张三丰 | PASS |
| PERSONAL-06 只有 canonical_name、没有别名，不返回任务 | PASS |
| PERSONAL-07 只返回当前会话 | PASS |
| PERSONAL-08 pending 保存 person_id；补发重读链接；不再 resolve | PASS |
| PERSONAL-09 Stop 清空 pending，不发送 | PASS |
| Emergency 清空 pending，不发送 | PASS |
| PERSONAL-10 「李明负责补材料」仍进主题旁路 | PASS |
| PERSONAL-11 两条个人问句 classifier calls = 0 | PASS |
| wxid 冲突固定文案，不猜 | PASS |
| pending 期间 DISABLED，发送前改发停用文案，链接仍在 | PASS |
| 无链接时使用「已确认负责人绑定」空结果文案 | PASS |
| QueryService 源码没有 assignee_text 相等或包含过滤 | PASS |
