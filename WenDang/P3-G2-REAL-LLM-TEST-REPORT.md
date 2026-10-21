# P3-G2 真实 LLM 测试报告

> 日期：2026-09-21（Key 更新后重跑，Gate 2 语义 PASS）  
> 必须区分 Heuristic 与真实 MODEL。禁止记录 API Key。

---

## Heuristic

`tests.test_topic_engine_offline`：**39 PASS**（与 G1 基线一致）

---

## 真实 MODEL

| 项 | 值 |
|---|---|
| model name | `deepseek-v4-flash` |
| base URL | `https://api.deepseek.com` |
| prompt name | `TOPIC_EXTRACTOR` |
| prompt hash | `d5e9de22b2676b4686bd5a371cc913e8c60232b1f3af4dbf0d630512c58b99df` |
| temperature | 0.2 |
| max_tokens | 1200（reasoning 模型在约 800 基础上留余量） |
| timeout | 20s |
| store_context | false |

未记录 Key。

命令：

```text
.\.venv\Scripts\python.exe -m unittest tests.test_topic_live_adapter.RealTopicExtractorTests -v
```

第三次（Key 更新后）结果：**8 tests, OK**，约 113s（含同进程其它用例时合计）。单独语义 8 项均 PASS。

---

## CASE-01 ～ CASE-07（真实模型）

| CASE | 结果 | 说明 |
|---|---|---|
| CASE-01 连续 ERP | **PASS** | 最终 Topic 数 = 1 |
| CASE-02 闲聊 | **PASS** | 「中午吃什么？」UNRELATED/SKIPPED，ERP Topic 仍为 1 |
| CASE-03 ERP→权限→ERP | **PASS** | 2 个 Topic，最后一条回到原 ERP `topic_id` |
| CASE-04 同义不拆 | **PASS** | 接口问题 Topic 数 = 1 |
| CASE-05 关键词召回 | **PASS** | 演示 Topic 被时间挤出 top5 后，仍被召回 |
| CASE-06 收到/好的 | **PASS** | 预筛，0 Topic |
| CASE-07 双主题 | **PASS** | 不创建第三个综合/Wi-Fi Topic |

`test_prompt_and_model_are_recorded`：**PASS**

---

## 适配说明（未改 Chat）

- `get_extractor_response` 只读 `content`；为空且 reasoning 含 `"decision"` 才回退  
- 截断 JSON / 空输出：Extractor 内最多再试 1 次，不阻塞 listener  
- Extractor Prompt 补充：双主题必须挂已有 `topic_id`，禁止单建 Wi-Fi 主题  
- 未修改 `get_deepseek_response` / `QIYE.md` / `企业_1.md`

---

## 结论

```text
真实 Extractor 入口 = VERIFIED
真实 MODEL 语义 CASE-01～07 = PASS
Gate 2 = PASS
可以进入真机 R1～R12（需微信已连接且由测试号发群消息）
```
