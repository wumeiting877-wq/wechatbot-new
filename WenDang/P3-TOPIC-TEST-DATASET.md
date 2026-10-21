# P3 Topic 离线测试数据集

> 日期：2026-09-20  
> 阶段：P3-G0  
> 用途：离线聚类验证。**不**验证 Task / Risk / Decision。  
> 不跑真实微信。  
> 机器可读副本：`tests/fixtures/topic_engine/`

---

## 1. 固定 Conversation

```text
id                 conv_zhiqun_demo01
platform           WECHAT
conversation_type  GROUP
display_name       智群Demo
```

人员只作 sender_name。不建 Task 责任人字段。

---

## 2. 智群 Demo 主样本（第一组）

来源：《智群-企业消息协同智能体-Demo与开发实施方案》第 6 节。  
Agent 此阶段不主动回复；P3 只看 Topic 聚类。

| msg id | 时间 | 发送者 | 内容 | v1 期望决策 | 期望 Topic |
|---|---|---|---|---|---|
| msg_demo_0905 | 09:05 | 陈总 | ERP 增量同步的问题现在解决了吗？ | NEW_TOPIC | A |
| msg_demo_0906 | 09:06 | 王强 | 昨晚同步链路已经跑通，不过还有 126 条供应商编码为空。 | TOPIC_UPDATE | A |
| msg_demo_0907 | 09:07 | 李娜 | 权限页面这里也发现一个问题，质检员现在还能看到采购价格。 | NEW_TOPIC | B |
| msg_demo_0908 | 09:08 | 周敏 | 王强今天 16 点前把空值处理规则做完，再跑一次回归。 | EXISTING_TOPIC 或 TOPIC_UPDATE | A |
| msg_demo_0909 | 09:09 | 王强 | 收到，16 点前给结果。 | UNRELATED 或 EXISTING_TOPIC(A) | 不新建 |
| msg_demo_0910 | 09:10 | 赵凯 | 周五现场演示，客户希望 15:30 开始。 | NEW_TOPIC | C |
| msg_demo_0911 | 09:11 | 陈总 | 演示必须包含订单导入、排产和质检追溯。 | TOPIC_UPDATE | C |
| msg_demo_0913 | 09:13 | 李娜 | 权限问题我中午前修复。 | EXISTING_TOPIC 或 TOPIC_UPDATE | B |
| msg_demo_0914 | 09:14 | 王强 | 我建议供应商编码缺失的数据先进异常池，不阻塞正常订单。 | TOPIC_UPDATE | A |
| msg_demo_0915 | 09:15 | 周敏 | 可以，先按照这个方案做，明天看看异常池数量。 | TOPIC_UPDATE 或 EXISTING_TOPIC | A |
| msg_demo_0917 | 09:17 | 赵凯 | 现场 Wi-Fi 最近不太稳定，最好准备一份离线演示数据。 | TOPIC_UPDATE | C |
| msg_demo_0919 | 09:19 | 周敏 | 赵凯明天 12 点前准备离线包和现场检查清单。 | EXISTING_TOPIC 或 TOPIC_UPDATE | C |
| msg_demo_0920 | 09:20 | 赵凯 | 收到。 | UNRELATED | 不新建 |
| msg_demo_0923 | 09:23 | 陈总 | 还有一点，现场演示不要用管理员账号。 | 见 CASE-07 | B 或 C（只选一个主 Topic） |
| msg_demo_0925 | 09:25 | 李娜 | 我建一个 demo-viewer 只读账号。 | 跟随 0923 的主 Topic | 不新建第三主题 |

### 会话结束后期望的 Topic 集合

必须正好 **3** 个业务 Topic（允许 title 近义，不允许拆成 5+ 个）：

```text
Topic A  ERP 数据同步异常
         覆盖：增量同步、126 条空编码、异常池方案
         消息至少含 0905, 0906, 0914

Topic B  权限整改
         覆盖：质检员看到采购价格、权限修复
         消息至少含 0907, 0913

Topic C  现场演示准备
         覆盖：周五 15:30、演示范围、Wi-Fi、离线包
         消息至少含 0910, 0911, 0917
```

**不验收：** 王强/李娜/赵凯是否写入负责人；16:00 / 中午 / 明天 12 点是否写入截止；异常池是否写成 Decision。

0909 / 0920「收到」：不得新建 Topic。挂到上文或 UNRELATED 均可，以「不新建」为准。

0923 / 0925：v1 **不支持**一条消息挂两个 Topic。  
可接受：主 Topic = B（账号/权限）或 C（演示约束）。  
不可接受：因此产生 Topic D，或把 A/B/C 合成一个「项目综合」。

---

## 3. 边界测试集

均使用同一 `conv_zhiqun_demo01` 的独立 run（每 CASE 单独回放，不与主样本状态混合），除非注明接在主样本之后。

### CASE-01 连续 ERP → 1 Topic

```text
E1  张三  ERP 同步失败了
E2  李四  我看了日志，还是增量任务超时
E3  张三  超时发生在供应商主数据拉取
E4  李四  主数据接口返回 500
E5  张三  那我们先重启同步任务
```

期望：1 个 Topic（ERP/同步）。禁止 5 个 Topic。

### CASE-02 插入闲聊 → UNRELATED

在 CASE-01 的 E2 与 E3 之间插入：

```text
X1  王五  中午吃什么？
```

期望：X1 = `UNRELATED`，不新建业务 Topic。ERP Topic 仍为 1 个。

### CASE-03 ERP → 权限 → ERP → 回到原 Topic

```text
P1  陈总  ERP 增量同步还在报错
P2  李娜  权限页面质检员能看到采购价格
P3  王强  ERP 那边我继续查供应商编码
```

期望：

- 2 个 Topic（ERP、权限）
- P3 = EXISTING_TOPIC / TOPIC_UPDATE，**回到 ERP**，不是第三个 Topic

### CASE-04 用词变化仍同一 Topic

```text
U1  甲  接口有问题
U2  乙  接口还是不通
```

期望：1 个 Topic。U2 不得 NEW_TOPIC。

### CASE-05 长间隔回到演示 Topic

构造：

1. 先有演示 Topic（可用 0910 等价句「周五演示」建成）。
2. 插入 **20** 条无关或其它业务消息（可用「这条占位 n」+ 一条权限句，避免 20 条全被预筛掉导致窗口丢失演示候选）。
3. 最后：`演示账号已经建好了`

期望：回到演示 Topic，不新建第 N 个「账号」Topic 作为首选。  
若候选检索未带回演示 Topic，本 CASE 记为引擎检索失败（应靠 last_message_at 以外的关键词「演示」召回）。这是检索策略测试，不只是 LLM 测试。

实施提示：20 条间隔后演示 Topic 可能被挤出「最近 5 个 ACTIVE」。  
**必须**用标题/关键词重叠把「演示」召回进候选，不能只按时间取最近 5 个。

### CASE-06 acknowledgement 不建 Topic

连续：

```text
收到
好的
1
嗯
```

期望：全部 UNRELATED 或 SKIPPED。Topic 数 = 0。

### CASE-07 一条消息两个业务问题

```text
D1  王强  ERP 数据问题处理完了，但是现场 Wi-Fi 还是不稳定。
```

前置：已存在 Topic A（ERP）与 Topic C（演示/现场）。

v1 期望（**限制，不是能力**）：

- 只输出 **一个** decision
- topic_id 为 A 或 C
- 不得 NEW 第三个
- 不得声称 multi-topic 成功

若未来 P3.1 支持 N 决策，本 CASE 才改为两条 link。

---

## 4. 离线 runner 期望（G1）

```text
python -m tests 或 独立脚本读取 fixtures
禁止 Start Bot
禁止 wx.SendMsg
禁止改 prompts/QIYE.md
```

断言优先：

1. 主样本最终 Topic 数 = 3（允许 title 近义匹配白名单）
2. CASE-01 Topic 数 = 1
3. CASE-02 不因「中午吃什么」增 Topic
4. CASE-03 最后一条的 topic_id == 第一条 ERP 的 topic_id
5. CASE-04 Topic 数 = 1
6. CASE-06 Topic 数 = 0
7. CASE-07 decisions 长度 = 1
8. 任一 CASE 不得出现 tasks/risks/decisions 落盘

title 近义白名单：

```text
A: ERP 数据同步异常 | ERP 增量同步 | ERP 同步异常
B: 权限整改 | 权限页面问题 | 质检权限
C: 现场演示准备 | 周五现场演示 | 演示准备
```

---

## 5. 本轮不测

- 真机群
- 是否回复微信
- 自动 RESOLVED
- Prompt 被 Chat 下拉框误选（G1 再测隔离）
