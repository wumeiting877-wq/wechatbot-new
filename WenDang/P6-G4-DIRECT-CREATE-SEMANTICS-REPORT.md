# P6-G4 Direct Create Semantics Report

> 日期：2026-09-22  
> 不阻塞 Evidence 修复。用于锁定 Gate 2 情况 A，避免以后把测试 API 误改成幂等。

---

## 结论

```text
create_task / create_decision / create_risk
= internal / legacy / 测试 fixture API
≠ 公开业务 API
≠ Engine 生产写路径
```

相同 id 第二次调用：

```text
当前行为 = suffix _2（新建第二实体）
不得改成幂等 skip
```

原因：全仓零生产调用，无法证明“同 id 再 create = 重试同一逻辑实体”。  
Engine retry 已经走 `commit_apply` 的 skip，不需要这条直连 API 帮忙。

---

## 证据

Gate 0 扫描：Engine / Side-path / WebUI / Bot / Retry 均不调用。  
仅 Store 单测与 Engine `_prepare` fixture 调用。

直连 API 在 suffix **之后**生成 CREATED_BY，所以它自己没有 P6-G4 的孤儿问题。

调用方有时显式传 id，有时不传而由 `make_*_id` 生成。  
禁止用 title / description / condition / decision_text 判断幂等。

---

## 锁定方式

1. 方法 docstring：`Internal/legacy 直连创建。生产 Engine 走 commit_apply。同 id 仍 suffix。`
2. REF-09：同 id 两次 create 仍得到 `*_2`，且 suffix 实体有自己的 CREATED_BY
3. REF-09：Engine / Side-path / bot / webui_data 源码不含 `create_task(` / `create_decision(` / `create_risk(`

---

## 若未来变成公开 API

必须先单独定义：

```text
A. 同逻辑身份 → 返回已有实体
B. 用户明确创建第二实体 → 继续 suffix
```

在那之前保持 suffix。
