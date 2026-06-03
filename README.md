# Torfinder
```
  '########::'#######::'########::'########:'####:'##::: ##:'########::'########:'########::
  ... ##..::'##.... ##: ##.... ##: ##.....::. ##:: ###:: ##: ##.... ##: ##.....:: ##.... ##:
  ::: ##:::: ##:::: ##: ##:::: ##: ##:::::::: ##:: ####: ##: ##:::: ##: ##::::::: ##:::: ##:
  ::: ##:::: ##:::: ##: ########:: ######:::: ##:: ## ## ##: ##:::: ##: ######::: ########::
  ::: ##:::: ##:::: ##: ##.. ##::: ##...::::: ##:: ##. ####: ##:::: ##: ##...:::: ##.. ##:::
  ::: ##:::: ##:::: ##: ##::. ##:: ##:::::::: ##:: ##:. ###: ##:::: ##: ##::::::: ##::. ##::
  ::: ##::::. #######:: ##:::. ##: ##:::::::'####: ##::. ##: ########:: ########: ##:::. ##:
  :::..::::::.......:::..:::::..::..::::::::....::..::::..::........:::........::..:::::..::
```

TORFINDER 是一个中文友好的 Tor Relay 地址库采集工具。它从 Tor Metrics Onionoo 接口获取当前运行中的 Tor relay OR 地址，保存到本地 SQLite 数据库，并支持动态更新、查询、统计、导出、快照留存和前后两次爬取差异分析。

项目定位：为 Tor Browser 流量识别实验提供低误报地址库。推荐使用 `目的 IP + 目的端口 ORPort` 同时命中作为高置信判据，不建议只按 IP、端口或 TLS 长连接单独判定。

## 功能特性

- 中文交互式 CLI
- ASCII Logo 启动界面
- 支持 `↑ / ↓` 方向键切换菜单
- 支持数字键快速选择
- 执行过程输出时间戳日志
- SQLite 本地数据库
- 当前 relay OR 地址动态同步
- 每次同步自动生成新的快照 CSV
- 自动对比前后两次快照差异
- IP 命中查询
- Guard / Exit / 国家地区 / IPv4 / IPv6 过滤
- CSV / JSON 手动导出
- 无第三方 Python 依赖

## 环境要求

- Python 3.10 或更高版本
- Windows / Linux / macOS 均可运行
- 需要能访问 Tor Metrics Onionoo：

```text
https://onionoo.torproject.org/
```

## 快速启动

Windows 用户可以双击：

```text
start_torfinder.bat
```

或中文启动脚本：

```text
启动Tor爬虫.bat
```

也可以使用命令行：

```powershell
python .\tor_relay_cli.py
```

直接运行时会进入交互式菜单：

```text
1. 初始化数据库
2. 立即同步 Tor Relay 地址库
3. 查看数据库统计
4. 查询某个 IP 是否命中
5. 列出当前 OR 地址
6. 导出当前地址库
7. 动态循环更新
8. 查看命令行帮助
0. 退出
```

## 命令行用法

初始化数据库：

```powershell
python .\tor_relay_cli.py init
```

立即同步。每次同步都会自动生成一份新的快照文件，并和上一份快照做差异分析：

```powershell
python .\tor_relay_cli.py sync
```

如果当前网络到 Onionoo 偶发 TLS 断开，可以调高失败重试次数：

```powershell
python .\tor_relay_cli.py sync --retries 5
```

如果直连 Onionoo 持续超时或 TLS 重置，可以指定代理：

```powershell
python .\tor_relay_cli.py sync --proxy http://127.0.0.1:7890 --retries 5
```

也可以设置环境变量：

```powershell
$env:TORFINDER_PROXY = "http://127.0.0.1:7890"
python .\tor_relay_cli.py sync
```

查看统计：

```powershell
python .\tor_relay_cli.py stats
```

查询某个 IP：

```powershell
python .\tor_relay_cli.py search 1.2.3.4
```

列出当前 Guard 节点：

```powershell
python .\tor_relay_cli.py list --flag Guard --limit 20
```

只看 IPv4 Guard 节点：

```powershell
python .\tor_relay_cli.py list --flag Guard --ip-version 4 --limit 20
```

每小时动态更新。每一轮同步都会生成新的快照和差异分析文件：

```powershell
python .\tor_relay_cli.py loop --interval 3600
```

循环更新也支持设置失败重试次数：

```powershell
python .\tor_relay_cli.py loop --interval 3600 --retries 5
```

循环更新同样可以指定代理：

```powershell
python .\tor_relay_cli.py loop --interval 3600 --proxy http://127.0.0.1:7890 --retries 5
```

手动导出当前地址库：

```powershell
python .\tor_relay_cli.py export --format csv
python .\tor_relay_cli.py export --format json
```

手动导出默认保存到当前工作目录。通过 `start_torfinder.bat` 或 `启动Tor爬虫.bat` 启动时，默认保存到批处理文件所在目录。

## 数据目录

程序运行后会自动创建独立数据目录：

```text
data/
  tor_relays.sqlite3
  snapshots/
  diffs/
```

说明：

```text
data/tor_relays.sqlite3
  本地 SQLite 数据库。

data/snapshots/
  每次同步后自动生成的新快照 CSV。
  示例：tor_relays_20260603_101530_run2.csv

data/diffs/
  从第二次同步开始，自动生成与上一份快照的差异分析 CSV/JSON。
  差异类型包括 added、removed、port_changed。
```

如果旧版本根目录下已经有 `tor_relays.sqlite3`，程序首次使用新版默认数据库时会自动复制到 `data/tor_relays.sqlite3`，旧文件不会被删除。

这些运行产物已经被 `.gitignore` 排除，不建议上传到 GitHub。

## 差异分析

每次同步成功后，终端会输出类似信息：

```text
本次快照文件：data\snapshots\tor_relays_20260603_101530_run2.csv
对比上一份快照：data\snapshots\tor_relays_20260603_100000_run1.csv
差异分析结果：新增=12，移除=8，端口变化=1
差异 CSV：data\diffs\diff_...csv
差异 JSON：data\diffs\diff_...json
```

差异判定：

```text
added
  当前快照新增的 fingerprint + ip + port。

removed
  当前快照不再存在的 fingerprint + ip + port。

port_changed
  同一个 relay fingerprint 和 IP 仍存在，但 ORPort 集合发生变化。
```
