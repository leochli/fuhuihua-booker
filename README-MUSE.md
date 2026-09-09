# Fuhuihua Booker — 24/7 改版说明 (Muse, 2026-09-08)

原来的 `book.py` 是"一次性"逻辑：等一个固定的放号时间点、轮询 ~5 分钟、退出。
但 2026 年 9 月实测发现 Tock 页面上**没有任何放号预告**，而社区帖子 + 实测证实：
**每天下午 5 点 (PT) 释放约 6 天后的位置**（滚动窗口）。所以整个策略重写了。

## 新文件

| 文件 | 说明 |
|---|---|
| `booker.py` | 24/7 主程序，替代 `book.py` |
| `config.py` | 已更新：17:00 放号、轮询策略、座位偏好 |
| `run_booker.sh` | 守护进程：崩溃自动重启（指数退避）；预订成功后自动退出 |
| `watchdog.sh` | 供 cron 调用的看门狗：bot 没跑就拉起来；预订成功上报一次 |
| `logs/` | 运行日志（按启动时间分文件） |
| `debug/` | 截图（checkout 各阶段、异常现场） |
| `status.json` | 心跳状态：last_check、booked 等 |

## 运行模式

- **Burst 模式**：每天 16:57–17:06 PT（已知放号窗口），对最可能放号的日期
  （今天+6天为中心）直接打开 `?date=YYYY-MM-DD&size=N`（小红书帖子的技巧），~1 秒轮询抢位。
- **整点微 Burst**：每小时 :59 到下一小时 :01，同样高频轮询，抓取消位 / 临时放号。
- **Steady 模式**：其余时间每 ~2 分钟轮询一个候选日期（round-robin），
  捡取消位 / 提前释放的日期。
- 预付费 $258/人 + 20% 服务费 + 税，Tock 账号里必须**绑好卡**，
  否则 bot 会发通知然后继续监控（不再像以前那样 `input()` 卡死）。

## 安全机制（保留并增强）

1. `booking.lock` 文件锁 —— 单实例
2. `booking_confirmed.txt` —— 成功后 bot 退出，不再重复预订（删掉可重新跑）
3. 内存标记 —— 一次运行内成功后立即停
4. 新增：通知限流（payment_needed 45 分钟、错误 60 分钟最多报一次）

## 用法

```bash
./run_booker.sh            # 24/7 跑（推荐）
python booker.py --once    # 只扫一遍候选日期（测试用）
python booker.py --dry-run # 找到位置但不进 checkout（测试用）
```

## 还差一步：Tock 登录态

Google OAuth 无法自动化，需要手动导一次 cookie：

1. 在自己电脑浏览器登录 https://www.exploretock.com/login（Google 登录）
2. F12 → Console，粘贴 `auth.py` 打印的 JS snippet，回车（会自动复制）
3. 把复制的 JSON 交给 Muse（通过安全通道），Muse 会写入 `tock_session/state.json`

session 一般能用几周，过期后 bot 会发通知提醒重导。
