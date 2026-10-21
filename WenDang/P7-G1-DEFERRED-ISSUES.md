# P7-G1 Deferred Issues

> 日期：2026-09-23

---

## 本 Gate 明确不做

```text
自动 retry / cron / backoff / retry queue
批量重试 / Retry All
UNKNOWN recovery
Reminder / 催办 / 日报 / 周报
Dashboard 大改版
新的 AI Engine
RBAC
CSRF token 框架
Redis 或跨进程锁
```

P6-G6 仍是 BLOCKED / TYPE C。缺 processing 不能重试，也不能用本 Gate 的审计补真值。

---

## 使用条件

`ENABLE_LOGIN_PASSWORD=false` 时，人工重试 POST 返回 403，不会执行。要使用这条写接口，需要先打开现有登录开关。这不是新的角色系统。

进程内锁只覆盖当前 Flask 进程。多进程部署不在本 Gate。

Topic 重试若拉起下游队列，接线层最多等待每路 30 秒再关闭临时旁路，避免请求一返回就把尚未执行的 fan-out 丢掉。更长的真实 LLM 不在本轮验证范围内。

---

## 真机

本轮没有在生产页面上点击重试，也没有用真实微信。需要的话另开 LIVE Manual Retry。
