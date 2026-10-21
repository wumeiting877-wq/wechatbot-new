# P7-G0 WebUI Report

> 日期：2026-09-23

---

## 页面

`GET /operations`，模板 `templates/operations.html`。

两块：

```text
系统状态
  Bot / 是否接收工作 / PID / WeChat / 监听数
  Topic Task Decision Risk 开关

需要关注 / 最近消息
  时间 | 消息 | Topic | Task | Decision | Risk | 原因
```

状态标签：

```text
已处理
处理失败，可重试
处理状态未知，需人工检查
```

筛选是两个 GET 链接。页面没有重试按钮，没有 POST 表单。

入口：配置页顶栏和侧栏「运维中心 / 处理状态」。侧栏点击在没有 `data-target` 时不再被页内切换拦截。

监听数若 status.json 没有该字段，显示「未写入 status.json」，不显示成 0。
