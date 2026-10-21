# P8-G5 Gate 0 Identity Model Audit

> 日期：2026-09-23  
> 方式：只读扫描。本文件记录审计当时的代码，不把随后新增的身份模块算进「已有目录」。

---

## 1. 结论

```text
Source of Truth = A. 项目本地显式人员目录
实现分级       = MODEL-A
```

项目里没有适合直接承载 Person / 微信绑定 / 负责人别名的现有模块。也没有企业通讯录、HR、企业微信通讯录。

独立 JSON 目录可以按现有 Store 的 FileLock 和原子替换来做，并且不碰已冻结的查询和 Task schema。

## 2. 扫描了什么

```text
用户
人员
账号
联系人
微信账号
监听对象
白名单
配置
管理员配置
```

## 3. 候选模块

| 位置 | 实际保存的内容 | 能否当人员目录 |
| --- | --- | --- |
| `config.local.json` 的 `LISTEN_LIST` | 三个监听窗口：`ceshi`、`哈`、`智群 · 企业消息协同智能体`。每项是窗口名和提示词 | 否。一行是一个聊天窗口 |
| `CONVERSATIONS` | 会话 id、平台会话 wxid、群/私聊、显示名、Agent | 否。群 id 下面有多人，没有成员表 |
| `AGENT_CONFIGS` | 聊天提示词和抽取提示词绑定 | 否。绑定的是会话，不是员工 |
| `config_editor.py` | 保存监听窗口、会话、Agent、提示词 | 否。这是会话配置后台，不是人员后台 |
| `bot.py` 动态配置里的白名单 | 安静时间、自动消息 | 否。名字叫白名单，内容不是人员名单 |
| `operations_routes.py` | 运维状态、消息诊断、问题列表 | 否。只读运维，没有人员编辑 |
| `operations_action_*` | 人工重试和动作审计 | 否。不维护员工 |
| `wxbot.py` `_resolve_uname` / `search_contact` | 用微信本地库把监听窗口昵称换成 username | 否。这是昵称查找窗口，本 Gate 禁止拿它认人 |
| `message/identity.py` | `sender_wxid`、`sender_id`、`sender_name`，以及机器人自己的 `bot_wxid` | 否。只描述这条消息的发送账号和机器人自身 |
| `RuntimeIdentity` | `bot_wxid` / `bot_name` / `login_account` | 否。只用于 self 判断 |
| `user_queues` / reminders 的 `user_id` | 聊天窗口名 | 否 |
| `MessageRecord.sender_wxid` | 入站发送者投影 | 否。发送者经常不是任务负责人 |
| `Task.assignee_text` | strip 后的自由文本 | 否。Task 写入前删除 `assignee_id`、`assignee_wxid` |
| `HeuristicTaskExtractor` `_KNOWN_NAMES` | 离线夹具里的汉字 | 否。没有 wxid，生产抽取不靠这张表 |
| Decision / Risk 的负责人字段 | 写入前被删除 | 否 |
| 企业通讯录 / HR / 企业微信 | 代码和配置里都没有 | 不存在，不能当 B/C/D |

`config.json` 不存在。仓库里没有人员表、员工号、群成员表、wxid 到规范姓名的对照。

## 4. Source of Truth

候选：

```text
A. 项目本地显式人员目录
B. 现有后台人员配置
C. 企业通讯录
D. 外部 HR / 企业微信通讯录
```

B 不存在。配置后台维护的是监听会话和 Agent。  
C 不存在。  
D 不存在。

因此第一版采用 A。写入必须是人工明确配置，或将来来自已经证明的可信通讯录。目录自己不会根据昵称、发送者姓名或任务文本创建人员。

## 5. 现有 Store 风格

业务 Store 都是本地 JSON，不用 SQLite / ORM / Redis。

```text
store_io.py          FileLock、临时文件、os.replace
task_store.py        data/task_store/conversations/<id>/tasks.json
decision_store.py    同样的会话目录
risk_store.py        同样的会话目录
topic_store.py       data/topic_store
```

`store_io.read_json` 在 JSON 损坏时返回默认值。身份目录不能沿用这个行为，否则坏文件会被看成空目录。身份文件必须在损坏时失败，并保持原字节。

Task 文件按会话拆开。人员目录是全局的，一个人可以出现在多个会话里，所以不应该塞进某个 `conv_*` 目录，也不应该写进 `config.local.json`。

## 6. 分级

```text
MODEL-A
```

理由：

```text
可以新建 data/identity/ 下的独立 JSON
写入走单独的锁和原子替换
不修改 Task schema
不修改 Task Engine / Extractor
不修改四个 Engine 开关
不修改 query_router / QueryService / delivery
```

Task 负责人绑定如果要做，也不必改 Task schema，见 `P8-G5-TASK-BINDING-OPTIONS.md`。本 Gate 仍不写这层绑定。先把人员、微信账号、精确别名稳定下来。

MODEL-B 和 MODEL-C 不成立：身份目录不依赖 Task Engine，也没有架构禁止本地显式目录。

## 7. 最小管理入口

第一版不做人员管理页面，也不把人员塞进配置编辑器。

```text
调用 IdentityStore 显式写入
落盘 data/identity/*.json
```

这样可以单测锁、原子替换、重复键和损坏文件。页面和外部通讯录留到以后。
