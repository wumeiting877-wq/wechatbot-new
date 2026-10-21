# P9-G5 Test Report

> 日期：2026-09-24

## 专项

```text
python -m unittest tests.test_p9g5_action_authorization
Ran 19 tests
OK
```

覆盖：

- AUTH-01 负责人 prepare；
- AUTH-02 非负责人拒绝且零 Action；
- AUTH-03 未绑定 wxid；
- AUTH-04 assignee_text 相同但无 Link；
- AUTH-05 同名不同 person；
- AUTH-06 DISABLED；
- AUTH-07 prepare 后停用；
- AUTH-08 prepare 后 Link 改人及 Link 删除；
- AUTH-09 Actor mismatch 优先；
- AUTH-10 授权确认执行；
- AUTH-11 授权 NOOP；
- AUTH-12 Identity Store 损坏；
- AUTH-13 Link Store 损坏；
- AUTH-14 Query 行为不增加读权限；
- Actor / Task assignment 歧义；
- Target 未唯一时 Authorizer 调用为 0；
- 拒绝审计不含姓名推断；
- 微信拒绝文案不披露负责人。

## 编译

```text
python -m compileall -q .
exit 0
```

编译期间仅出现第三方 `pyautogui` 的既有 SyntaxWarning，不影响结果。
