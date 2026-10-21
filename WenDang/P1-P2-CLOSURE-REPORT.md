# P1 / P2 关闭报告

> 日期：2026-09-20  
> 项目：wechatbot-new  
> **P0 STATUS = CLOSED**（冻结，本轮未解冻）  
> **P1 STATUS = CLOSED**  
> **P2 STATUS = CLOSED**  
> **未进入 P3 Topic Engine / Extractor**

---

## 1. 关闭结论

P1 Conversation 主键与 P2 Agent/Prompt 绑定已完成代码、自动测试与真机验收。  
关闭当轮真机：2026-09-20 13:54–14:16，主模型已配置（`coding-glm-4.7-free`）。不粘贴密钥。

上一轮 13:34–13:45 主模型未配置，A/B 回复 NOT RUN，当时不得关闭。本轮补齐后关闭。

---

## 2. 关闭门槛

| 条件 | 结果 |
|---|---|
| Conversation 内部 id，不随 display_name 重生 | PASS（单元 TEST-03；真机全程 id 未变） |
| platform_conversation_id / PRIVATE / GROUP 落盘 | PASS（TEST-LIVE-07） |
| enabled=false 不进投影、不 AddListenChat、不回复 | PASS（TEST-LIVE-04，监听 2，无 哈 事件） |
| enabled=true 恢复且不影响另一会话 | PASS（TEST-LIVE-05） |
| Conversation → AgentConfig → Chat Prompt | PASS（TEST-LIVE-01/02） |
| A/B 隔离真机回复 | PASS（ceshi=`A-链路正常`，哈=`B-链路正常`） |
| 交换绑定后回复互换 | PASS（TEST-LIVE-03） |
| 缺 Prompt 无静默 fallback、不调通主 LLM | PASS（TEST-LIVE-09，`PROMPT_FILE_NOT_FOUND`） |
| 引用中删除 Prompt → 409 PROMPT_IN_USE | PASS（TEST-LIVE-08） |
| P0 59 自动测试 | PASS（59 OK） |
| P1/P2 组合 103 自动测试 | PASS（103 OK） |
| P0 真机 smoke | PASS（inbound EXTERNAL、自回复 NO_ACTION、一次 outbound、明文、Start/Stop、WebUI 存活、Stop 后不回） |
| 生产绑定已恢复 | PASS（ceshi/哈→企业_1，QIYE→QIYE；临时 Prompt 已删） |

---

## 3. 真机绑定证据（测试期，已撤销）

```text
TEST-LIVE-01  ceshi  conv_b35d9b7aaba2  agt_6403ddd8c317  P1P2_TEST_A
              prompt_hash=3b37c5035b63539a8e348cabf51d7609ba777c61220a289785d36cb71ed30c10
              outbound=A-链路正常

TEST-LIVE-02  哈     conv_2f82b3dbce7e  agt_679873182096  P1P2_TEST_B
              prompt_hash=afc3452bdde9c402339e657e64d6b0b4bba5a75cfdb30d7dbb86aeadaa3bc645
              outbound=B-链路正常   @扶级
```

交换后：ceshi→B，哈→A。三个 Conversation id 未重生。

---

## 4. 恢复后生产

```text
LISTEN_LIST
  ceshi → 企业_1
  哈    → 企业_1
  QIYE  → QIYE

MODEL = coding-glm-4.7-free
Bot = STOPPED
WebUI web_pid = 19896
GET /api/prompts = ["AI","QIYE","企业_1"]
```

---

## 5. 明确未做（不阻塞本关闭）

- Topic Engine / Extractor Prompt
- 数据库 PromptVersion
- 微信操作层仍用 `AddListenChat(nickname=display_name)`
- `chat_contexts` / 记忆文件仍按 nickname 分键
- 未改真实微信昵称（id 稳定性由保存逻辑 + 单元证明）
- 未重写 `QIYE.md` / `企业_1.md`
- 未进入 P3

残留见 `WenDang/P1-P2-REMAINING-RISKS.md`。那些项不推翻本关闭。

---

## 6. 状态

```text
P0 STATUS = CLOSED
P1 STATUS = CLOSED
P2 STATUS = CLOSED
禁止进入 P3 Topic Engine
```
