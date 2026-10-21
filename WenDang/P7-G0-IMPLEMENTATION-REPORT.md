# P7-G0 Implementation Report

> 日期：2026-09-23

---

## 新增

```text
operations_read_model.py
operations_routes.py
templates/operations.html
tests/test_p7g0_operations_read_model.py
```

## 接入

```text
config_editor.py
  register_operations_routes(app, login_required, BASE_DIR)

templates/config_editor.html
  顶栏与运维中心增加「处理状态」链接

static/js/config_editor.js
  没有 data-target 的侧栏链接允许正常跳转
```

未改：

```text
topic_engine.py topic_store.py topic_retry.py topic_sidepath.py
task_engine.py task_store.py task_sidepath.py
decision_engine.py decision_store.py decision_sidepath.py
risk_engine.py risk_store.py risk_sidepath.py
downstream_retry.py
listener dedupe keep_alive bot_lifecycle Stop / Start
```

四个 Engine 默认开关保持 false。

---

## 读模型

`OperationsReadModel` 只调用：

```text
get_processing
list_messages
read_audit
read_status_file
is_*_engine_enabled
stop_requested / emergency_stop_requested
```

`operations_read_model.py` 源码不包含 `write_processing`、`retry_topic(`、`retry_downstream(`、`send_reply`。

Runtime 视图字段：`runtime_state`、`is_accepting_work`、`bot_pid`、`wechat_connected`、`listen_count`。`listen_count` 仅当 status 字典里已有该键时带出，否则为 null。
