# P8-G5 Test Report

> 日期：2026-09-23

```text
.\.venv\Scripts\python.exe -m unittest tests.test_p8g5_identity_model
Ran 20 tests in 0.440s
OK
```

四个 Engine 开关在用例结束时仍为 `false`。用例不调用模型。

---

## 1. Person

| 用例 | 行为 | 结果 |
| --- | --- | --- |
| IDENTITY-MODEL-01 | 创建 `person_001` / 李明，主键与姓名分开 | PASS |
| IDENTITY-MODEL-02 | `person_002` 也可以叫张三；姓名本身不能解析 | PASS |
| IDENTITY-MODEL-03 | 重复 `person_001` 返回 `DUPLICATE_PERSON_ID`，目录仍是一行 | PASS |

## 2. 微信绑定

| 用例 | 行为 | 结果 |
| --- | --- | --- |
| IDENTITY-MODEL-04 | `wxid_a` → `person_001`，重复绑定不增加行 | PASS |
| IDENTITY-MODEL-05 | `resolve_wxid(" wxid_a ")` → `person_001` | PASS |
| IDENTITY-MODEL-06 | 再绑 `person_002` 返回 `CONFLICT`，文件字节不变 | PASS |
| IDENTITY-MODEL-07 | 未知 wxid 为 `NOT_FOUND`，不创建人员文件 | PASS |

## 3. Alias

| 用例 | 行为 | 结果 |
| --- | --- | --- |
| IDENTITY-MODEL-08 | `李明` → `person_001`，strip 后的重复登记不增加行 | PASS |
| IDENTITY-MODEL-09 | 未登记前 `李明` 为 `NOT_FOUND`；登记后精确解析到 `person_001` | PASS |
| IDENTITY-MODEL-10 | `李明负责` 为 `NOT_FOUND` | PASS |
| IDENTITY-MODEL-11 | 同一 alias 再绑 `person_002` 返回 `CONFLICT` | PASS |
| IDENTITY-MODEL-12 | `@李明`、`研发部李明`、`由李明`、`李明负责` 全部 `NOT_FOUND` | PASS |

另有一条：手改文件让 `张三` 同时指向 `person_001` 和 `person_002` 时，解析为 `AMBIGUOUS`，继续写入被拒绝，文件不变。

## 4. 持久化

| 检查 | 结果 |
| --- | --- |
| 新 Store 实例从同一目录读回人员、wxid、alias | PASS |
| `os.replace` 失败时原人员文件不变，没有残留 `.tmp` | PASS |
| 持有 FileLock 时第二次创建被挡住，释放后才写入 | PASS |
| 损坏的 `people.json` 读和写都返回 `CORRUPT`，字节不变 | PASS |
| `DISABLED` 保留原行，绑定仍能解析，主键仍不能重建 | PASS |

## 5. 查询冻结

| 用例 | 行为 | 结果 |
| --- | --- | --- |
| IDENTITY-MODEL-13 | `我有什么任务` 仍是「不支持按个人身份查询」；QueryService 0；分类器 0；不创建 `data/identity` | PASS |

源码扫描确认 `identity_store.py` 和 `identity_resolver.py` 没有抽取、模型、编辑距离、拼音、子串猜测和发送调用。
