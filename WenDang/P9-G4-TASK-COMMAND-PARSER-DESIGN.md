# P9-G4 Task Command Parser Design

> 日期：2026-09-24

## 边界

`task_command_parser.py` 是无副作用的确定性语法解析器。它不读 Task Store，不解析 `task_id`，不调用模型、Extractor、Business Action、Lifecycle 或发送接口。

唯一输出动作是：

```text
COMPLETE_TASK + EXACT_TITLE(title)
```

## 支持语法

```text
把{标题}这个任务标记为完成
请把{标题}这个任务标记为完成
帮我把{标题}这个任务标记为完成
完成任务：{标题}
请完成任务：{标题}
```

标题只执行 `strip()`，以及移除最外层成对的 `「」` 或 `“”`。不做模糊匹配、contains、拼音、大小写折叠、同义词或语义改写。

## 安全负样本

完成陈述、完成询问、泛化口语、slash command 和普通确认词均返回 `NOT_COMMAND`。`这个任务`、`刚才那个任务`、序号引用返回 `UNSUPPORTED`，由会话层给固定指导，不进入 Resolver。

