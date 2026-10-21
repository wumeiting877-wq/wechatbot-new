# P3 下一步实施计划（等待指令）

> 日期：2026-09-20  
> 阶段：P3-G0 **已完成，在此 STOP**  
> 本文件只划 G1 范围。**不要在未收到实施指令时执行。**  
> 禁止自动进入 P4 Task / Risk / Decision。

---

## 1. G0 已交付

| 文件 | 内容 |
|---|---|
| `WenDang/P3-TOPIC-ENGINE-CURRENT-STATE-AUDIT.md` | 冻结基线 + 真实链路 + 无 Topic 能力确认 |
| `WenDang/P3-TOPIC-DATA-MODEL-DESIGN.md` | JSON Store、MessageRecord、Topic、Link、幂等 |
| `WenDang/P3-TOPIC-ENGINE-DESIGN.md` | 旁路调用、决策、失败隔离、候选 5 个 |
| `WenDang/P3-TOPIC-EXTRACTOR-PROMPT-DESIGN.md` | 与 Chat 隔离的 Extractor 方案与正文稿 |
| `WenDang/P3-TOPIC-TEST-DATASET.md` | 智群 Demo + CASE-01～07 |
| `WenDang/P3-TOPIC-GAP-REPORT.md` | 15 问 + BLOCKER |
| `tests/fixtures/topic_engine/` | 离线 JSON |

未实现引擎，未改冻结模块，未改生产群行为。

---

## 2. 建议的下一阶段：P3-G1（实施 + 离线验收）

目标：可在 **离线 fixture** 上跑通 Topic Engine；默认不启用生产旁路。

### 2.1 新增文件（优先）

```text
topic_store.py                  JSON store：Message / Topic / Link / processed
topic_engine.py                 流水线：预筛 / 候选 / 校验 / 落地
topic_extractor_client.py       独立 LLM 调用，不碰 chat_contexts
prompts/extractors/TOPIC_EXTRACTOR.md
tests/test_topic_engine_offline.py
tests/fixtures/topic_engine/    （已有，G1 可增期望文件）
```

可选：`scripts/topic_engine_replay.py` CLI dump，不要 Web UI。

### 2.2 允许的最小修改

```text
conversation_store.py   新增 find_by_platform_conversation_id；不改 id 规则
agent_store.py          resolve_extractor_prompt；不改 Chat resolve 语义
message/listener.py     仅当实施指令明确授权：evaluate_inbound 后旁路调用
                        默认仍可用 TOPIC_ENGINE_ENABLED=false 跳过
```

### 2.3 禁止修改

```text
message/identity.py          InboundMessage 字段语义
message/dedupe.py
message/outbound.py
message/trigger.py           不要为 Topic 返回 UPDATE_ONLY 当回复策略
message/reply_format.py
bot_runtime.py               evaluate_inbound 顺序
prompts/QIYE.md
prompts/企业_1.md
config.local.json 内塞 TOPICS 数组
```

### 2.4 默认开关

```text
TOPIC_ENGINE_ENABLED = false
```

未打开时：生产收发与现在完全一致。  
G1 验收以离线测试为准，不要求真机群理解。

---

## 3. G1 验收门槛（离线）

```text
主样本最终 3 Topic（A/B/C 近义白名单）
CASE-01  1 Topic
CASE-02  「中午吃什么」UNRELATED，不新建业务 Topic
CASE-03  最后一条回到 ERP Topic
CASE-04  1 Topic
CASE-05  「演示账号已经建好了」回到演示 Topic（关键词召回）
CASE-06  0 Topic
CASE-07  单 decision；不宣称 multi-topic
失败注入：Extractor 抛错时 Chat 路径单测仍过（若已接旁路）
P0 59 tests 仍 OK
P1/P2 103 tests 仍 OK
```

不验收：Task/Risk/Decision、自动 RESOLVED、主题中心 UI、真机主动理解。

---

## 4. 再下一阶段（不要现在做）

| 阶段 | 内容 | 前提 |
|---|---|---|
| P3-G2 | 可选：授权后打开旁路，真机群只入库不回复 | G1 离线 PASS；明确指令 |
| P4 | Task / Risk / Decision | P3 Topic 稳定且 Evidence 可查 |

G2 之前生产群不得因 Topic 多发一条微信。

---

## 5. 实施顺序建议（收到 G1 指令后）

1. `topic_store.py` + MessageRecord upsert  
2. Extractor md + resolve_extractor_prompt  
3. `topic_engine.py` 离线可跑（无 listener 挂钩也能 replay fixture）  
4. 离线单测 CASE  
5. **再**考虑 listener 旁路与开关  
6. 复跑 P0/P1/P2 测试

先离线、后挂钩。挂钩不是 G1 第一天工作。

---

## 6. STOP

```text
P3-G0 STATUS = COMPLETE
P3 Topic Engine 未实施
P4 未开始
等待下一阶段指令
```
