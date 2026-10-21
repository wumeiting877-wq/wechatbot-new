# P6-G6 State Classification

> 日期：2026-09-23  
> 结论：**TYPE C**  
> `P6-G6 = BLOCKED`

---

## 问题

```text
processing 缺失是否永远等于这个 Engine 从未执行？
```

不是。

CASE B 探针已经证明：业务 apply 成功之后，SUCCESS 与 FAILED 两次 `write_processing` 都失败，processing 会不存在，而 Topic / Task / Decision / Risk 实体和 CREATED_BY 已经在。

---

## 为什么不是 TYPE A

TYPE A 要求：只要业务 apply 发生，processing 至少留下 SUCCESS 或 FAILED。

CASE B 否定了这一点。`_isolate` 吞掉第二次写入失败，调用方拿到的是 `EngineResult(FAILED)`，磁盘上没有 processing。

---

## 为什么不是 TYPE B

TYPE B 要求：processing 不存在时，Store 里有足够稳定字段，能证明这次 apply 已经完成，并且能还原：

```text
原 Engine decision
最终 entity ids
topic_id
message_id
version
```

不能猜 decision。不能用正文、标题、时间接近来判断。

已证明做不到：

```text
UNRELATED 双写失败
与
Extractor 在 apply 之前失败且 FAILED processing 也没写上
```

业务 Store 相同，audit decision 都是 `FAILED`。

```text
EXISTING_TOPIC 双写失败
与
该消息只是另一条 NEW_TOPIC 的 RELATED evidence
```

都只有 RELATED，没有 processing。

```text
decision_summary = NEW_TASK
与
decision_summary = NEW_TASK,UNRELATED
```

Task / CREATED_BY 足迹相同。原 summary 没落盘。  
Decision / Risk 的 summary 同样可以夹带不落实体的 `UNRELATED`。

Topic 落盘对象没有 `created_msg_id`。  
成功 audit 写在 processing 之后，CASE B 的 audit 记的是 `FAILED`，不能用来还原 NEW_TOPIC。

因此不能构造一条与原 Engine 结果一致的 processing，除非猜测 decision。

---

## TYPE C

```text
processing 缺失可达
现有 Store 不能可靠区分
    从未执行
    与
    执行过但 processing 丢失
```

按 Gate 规则：

```text
P6-G6 = BLOCKED
不自动恢复
不把 NOT_FOUND 改成首次执行
不新增 processing_recovery.py
```

这是本 Gate 的正确闭环。
