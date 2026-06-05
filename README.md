# 12306 抢票助手

基于 Python + PyQt6 的 12306 桌面抢票工具，按流程图实现完整抢票链路。

## 功能

| 模块 | 说明 |
|------|------|
| 用户配置 | 账号、乘客、出发/到达、日期、车次、席别 |
| 登录验证 | 密码登录、扫码登录、ddddocr 验证码识别 |
| 余票监控 | APScheduler 定时轮询、多车次并行、候补策略 |
| 自动下单 | 发现余票自动提交订单 |
| 支付提醒 | 桌面通知、30 分钟倒计时 |
| 历史订单 | SQLite 本地存储 |
| 日历同步 | 出票后写入 ICS 文件 |
| 代理 IP 池 | 防封与限速规避 |

## 环境要求

- Python 3.10+
- Windows / macOS / Linux

## 安装

```powershell
cd C:\Users\Administrator\Projects\12306-ticket-grabber
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

## 运行

### 方式一：双击启动（推荐）

- **模拟模式**：双击 `run_mock.bat`
- **真实模式**：双击 `run.bat`

### 方式二：命令行

**如果你用的是 cmd（命令提示符）：**

```cmd
cd C:\Users\Administrator\Projects\12306-ticket-grabber
set TICKET_MOCK=1
.venv\Scripts\python.exe main.py
```

**如果你用的是 PowerShell：**

```powershell
cd C:\Users\Administrator\Projects\12306-ticket-grabber
$env:TICKET_MOCK = "1"
.\.venv\Scripts\python.exe main.py
```

**模拟模式（推荐先测试 UI 与流程）：** 设置 `TICKET_MOCK=1`

**连接真实 12306：** 设置 `TICKET_MOCK=0` 或不设置该变量

## 使用流程

1. **行程配置** — 选择出发/到达站、**多个出发日期**、席别，添加乘车人
2. **查询车次** — 点击「查询车次」调用 **12306 实时接口**，在表格中勾选目标车次
3. **登录** — 密码或扫码登录 12306
4. **抢票监控** — 对**所有已选日期**轮询余票并自动下单
5. **支付** — 收到桌面通知后在 12306 App 完成支付
6. **历史订单** — 查看本地订单记录

## 打包为 exe

```powershell
pip install pyinstaller
pyinstaller build.spec
```

输出：`dist/12306抢票助手.exe`

## 项目结构

```
12306-ticket-grabber/
  main.py                 # 入口
  requirements.txt
  build.spec              # PyInstaller 配置
  data/
    stations.json         # 常用车站
  app/
    config.py             # 全局配置
    core/                 # 核心业务
      api_client.py       # 12306 HTTP 接口
      auth.py             # 登录
      captcha.py          # 验证码识别
      ticket_monitor.py   # 余票监控
      order.py            # 下单
      payment.py          # 支付倒计时
      notification.py     # 桌面通知
      proxy_pool.py       # 代理池
      calendar_sync.py    # 日历同步
      scheduler.py        # 任务调度
    database/             # SQLite 持久化
    ui/                   # PyQt6 界面
```

## 注意事项

- 12306 接口会不定期变更，真实环境下可能需要更新 `api_client.py`
- 请遵守 12306 用户协议，合理设置轮询间隔（建议 ≥ 3 秒）
- 账号密码使用 Fernet 加密存储在本地 SQLite
- 模拟模式不会请求真实 12306 服务器
