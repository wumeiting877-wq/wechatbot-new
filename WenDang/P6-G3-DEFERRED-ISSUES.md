# P6-G3 Deferred Issues

> 日期：2026-09-22  
> 不阻塞 P6-G3 COMPLETE。

---

## D1. create_* 直连 API 仍 suffix

Engine retry 走 `commit_apply`，已幂等。  
`create_task` / `create_decision` / `create_risk` 仍按碰撞后缀 `_2`。  
若未来有旁路直接调 create，同 id 仍可能重复。本轮不扩大。

---

## D2. 真哈希碰撞的 suffix 实体 Evidence

同 id、不同 `created_msg_id` 仍 suffix。  
suffix 后 `new_links` 仍带原 id，suffix 实体可能没有自己的 CREATED_BY。  
这是碰撞路径的既有行为，不是 retry 窗口。未改 id 生成规则。

---

## D3. Retry preflight reconcile

本轮不需要：Store skip + 再跑 `_finalize` 已能把 FAILED 写成 SUCCESS。  
若未来出现“processing 缺失（Isolate 也失败）”，Retry Service 仍 `NOT_FOUND`，不会补跑。P6-G2 D5 仍有效。

---

## D4. Extractor 在 retry 时可能给出不同 decision

scripted extractor 稳定返回 `NEW_*`。  
真模型第二次可能改成 UNRELATED / UPDATE。那是业务决策变化，不是本窗口的 duplicate。不在本 Gate 改 Extractor。

---

## D5. 人工入口 / 自动 retry

仍禁止 WebUI Retry、失败列表、cron、queue。  
数据一致性已证明后，人工入口仍需单独 Gate。

---

## D6. Topic

未改。Topic replay / Topic FAILED 补偿不在范围。
