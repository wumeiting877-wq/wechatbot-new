# P6-G4 Deferred Issues

> 日期：2026-09-22  
> 不阻塞 P6-G4 COMPLETE。

---

## D1. create_* 仍非幂等

已确认无生产调用。本轮锁定 internal/legacy + suffix。  
若未来变成公开 API，必须先定义同 id 是重试还是第二实体。见语义报告。

---

## D2. 自然哈希碰撞概率

确定性 id 是 sha1-12。真碰撞要靠测试强制才能稳定复现。  
生产上不同 `created_msg_id` 几乎总是不同 id。remap 是正确性收口，不是高频路径。

---

## D3. Engine 在无碰撞时 applied_ids 与本地收集等价

无碰撞时 `make_*_id` 已是最终 id。只有强制碰撞才会走到 suffix remap。  
未改 Extractor。

---

## D4. Retry preflight reconcile

P6-G3 D3 / P6-G2 D5 仍有效：processing 缺失时 Retry Service 仍 `NOT_FOUND`。本轮不补。

---

## D5. 人工入口 / 自动 retry

仍禁止 WebUI Retry、失败列表、cron、queue。

---

## D6. Topic

未改。Topic replay / Topic FAILED 补偿不在范围。
