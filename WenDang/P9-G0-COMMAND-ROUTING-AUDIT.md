# P9-G0 Command Routing Audit

> 扫描：`query_router.py`、`collaboration_query.py`、`query_formatter.py`、`message/listener.py`
> 结论先写：写句型被收成 `COMMAND`，固定一句回复。这条路径不写 Store，不跑 Engine。

源码里没有名为 `COMMAND_NOT_SUPPORTED` 的常量。行为等价于固定拒绝。回复文案是：

```text
COMMAND_REPLY = 当前不能在这里修改任务、风险或决定。
```

## 1. 怎样才算 Command

`_is_command` 对整句做 `fullmatch`。可选前缀是「帮我 / 请 / 麻烦」。句尾可去掉「吧 / 一下 / 呀 / 啊」。不是看到「完成」「关闭」就拒绝。

当前模板覆盖：

| 用户要求的类 | 实际命中的句型 | 不命中的例子 |
| --- | --- | --- |
| 创建 / 新增 | 创建、新建、新增、添加 + 任务 / 风险 / 决定 / 主题 | 「记录一个决定」不含这些动词 |
| 完成 | 「把任务改成/改为/标记为/设为完成」「完成任务」，中间可插入「这个 / 该 / 这条」 | 「把接口联调这个任务标记为完成」「接口联调今天已经完成了」 |
| 关闭 | 「把风险关掉/关闭」「关闭风险」，可插入「这个 / 该 / 这条」 | 「关闭这个任务」「这个事情已经结束了」 |
| 修改 | 只覆盖「修改/更改决定」「把决定修改/更改/改掉」 | 「修改任务描述」 |
| 指派 | 「分配任务」「给某名分配任务」会命中 Command | 「指派负责人」虽然写在模板里，但身份规则先匹配「…负责」，`classify_agent_message` 与 `route_hybrid` 都把它收成 `NOT_QUERY`，固定拒绝句不会发出。「把接口联调改由李明负责」也不命中 |
| 删除 | 删除 / 删掉 + 任务 / 风险 / 决定 / 主题 | 没有单实体删除实现，命中后也只是拒绝 |

以 `/` 开头的句子（`/重启`、`/总结`）在协作路由里是 `NOT_QUERY`，走另一套文本命令，不进这条 Command 回复。

身份规则写在 Command 判断之前。`_is_identity_deferred` 用「2 到 8 个汉字 + 负责」做搜索，不是整句匹配。因此「指派负责人」先被当成身份句拦下，后面的 Command 模板没有机会执行。这是当前路由顺序，不是写操作已经放开。

## 2. 路径

```text
微信消息
↓
message/listener.py  evaluate_inbound，action=REPLY
↓
handle_collaboration_route
↓
route_hybrid → classify_agent_message → KIND_COMMAND
↓
_fixed_plan(COMMAND_REPLY)     kind=FIXED，不调用 QueryService.execute
↓
offer_agent_reply
↓
materialize 返回固定句子
↓
send_reply
↓
listener：trace.abort("collaboration_route") 然后 return
```

`return` 发生在 `try_enqueue_topic_sidepath` 之前。Topic / Task / Decision / Risk 旁路都不会入队。

```text
当前 0 Store write
当前 0 Engine action
```

`KIND_FIXED` 的 materialize 只返回 `fixed_text`。不读任务列表，不调用四个 Engine。

P8-G1 已有测试：Command 期间若 `atomic_write_json` 被调用则失败。该测试期望只发出 `COMMAND_REPLY`。

## 3. 为什么固定拒绝

P8 把写句型识别出来，是为了不让它们掉进聊天或查询。识别之后没有 Action Service，只有这一句固定回复。拒绝发生在路由层，不到达 Store 的 `INVALID_STATUS`。

## 4. Command 与业务讨论必须分开

| 句子 | 当前路由 | 若 Engine 打开，会怎样 |
| --- | --- | --- |
| 帮我把任务改成完成 | COMMAND，固定拒绝 | 到不了 Extractor |
| 接口联调今天已经完成了 | NOT_QUERY，普通聊天 | Task 提示词要求输出 UNRELATED，不结束任务 |
| 把接口联调这个任务标记为完成 | 匹配不上 Command 全字模板，普通聊天 | 同上，不写 DONE |
| 之前那个决定作废，改成周一上线 | 普通聊天 | Decision Engine 当前关闭；打开后也只可能新建 RECORDED，并可带指针，不会把旧行改成 SUPERSEDED |

风险记录：

```text
不能用「句中出现 完成 / 关闭 / 修改 / 删除」做唯一判断。
当前能分开，是因为 Command 用整句 fullmatch，讨论句落在模板外。
若下一版改成关键词包含，业务陈述会被误当成写命令，或写命令被误送进 Extractor。
两种语义以后要有两套入口：Command Intent 与业务讨论。
```

P8 Query 分类不承担这个区分的扩展。`QueryService` 继续只读。
