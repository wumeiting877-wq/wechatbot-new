# P8-G2 Live Classifier Smoke

> 日期：2026-09-23  
> 可选。不作为单测，也不作为回归通过条件。  
> 模型：已有配置 `deepseek-v4-flash`。没有新增 Key 或 Provider。

---

## 1. 方法

`route_hybrid` 走生产分类器，底层是 `call_narrow_completion`。8 条都是候选句，所以每条分类器调用数是 1。没有读 Store，没有发微信。

## 2. 结果

| 输入 | 状态 | 路由 | query_type |
| --- | --- | --- | --- |
| 帮我盘一下现在手上的待办 | OK | QUERY | LIST_TASKS |
| 我们主要有哪些潜在问题需要注意 | OK | QUERY | OPEN_RISKS |
| 我们现在主要卡在哪些风险点 | OK | QUERY | OPEN_RISKS |
| 之前到底定下来了哪些事情 | OK | QUERY | LIST_DECISIONS |
| 这个群现在主要在推进哪些事情 | OK | QUERY | LIST_TOPICS |
| 帮我看看当前主题整体怎么样 | OK | QUERY | TOPIC_SUMMARY |
| 帮我看一下当前主题的整体情况 | OK | QUERY | TOPIC_SUMMARY |
| 任务怎么样了 | CLASSIFIER_INVALID | CLASSIFIER_FAILURE | 空 |

前 7 条和 Fake 测试锁定的枚举一致。第 8 条单独再调一次，`content` 长度为 0。按非法输出处理：固定指引，不猜测，不进旁路，不进 Chat。

没有为了这条空回复修改解析或业务规则。

## 3. 和 Extractor live 的关系

四个 Real Extractor 套件这次没有跑。原先 10 条连接 / 超时失败仍然是：

```text
KNOWN LIVE DEPENDENCY FAILURE
```
