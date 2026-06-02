# TORFINDER

TORFINDER 是一个中文友好的 Tor Relay 地址库采集工具。它从 Tor Metrics Onionoo 接口获取当前运行中的 Tor relay OR 地址，将数据保存到本地 SQLite 数据库，并支持动态更新、查询、统计和导出。

项目定位：为 Tor Browser 流量识别实验提供低误报地址库。推荐使用 `目的 IP + 目的端口 ORPort` 同时命中作为高置信判据，不建议只按 IP、端口或 TLS 长连接单独判定。

## 功能特性

- 中文交互式 CLI
- ASCII Logo 启动界面
- 支持 `↑ / ↓` 方向键切换菜单
- 支持数字键快速选择
- 执行过程输出时间戳日志
- SQLite 本地数据库
- 当前 relay OR 地址动态同步
- IP 命中查询
- Guard / Exit / 国家地区 / IPv4 / IPv6 过滤
- CSV / JSON 导出
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

立即同步：

```powershell
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

每小时动态更新：

```powershell
python .\tor_relay_cli.py loop --interval 3600
```

导出当前地址库：

```powershell
python .\tor_relay_cli.py export --format csv
python .\tor_relay_cli.py export --format json
```

导出默认保存到当前工作目录。通过 `start_torfinder.bat` 或 `启动Tor爬虫.bat` 启动时，默认保存到批处理文件所在目录。

## 数据文件

程序运行后会自动生成：

```text
tor_relays.sqlite3
tor_relay_or_addresses.csv
tor_relay_or_addresses.json
```

这些是运行产物，已经被 `.gitignore` 排除，不建议上传到 GitHub。

## 低误报匹配建议

推荐强判条件：

```text
目的 IP 命中当前 or_addresses.ip
+ 目的端口命中当前 or_addresses.port
+ 连接方向为用户侧主动外联
+ 连接行为符合 Tor 长连接 / 稳定重连模式
```

不建议只用以下单一特征判定：

```text
只命中 IP
只命中端口 443/9001
只有长连接
只有 TLS
只有无 DNS 对应关系
```

## 数据来源

TORFINDER 使用 Tor Metrics Onionoo details API：

```text
https://onionoo.torproject.org/details?type=relay&running=true
```

## GitHub 上传说明

建议上传以下文件：

```text
tor_relay_cli.py
start_torfinder.bat
启动Tor爬虫.bat
README.md
requirements.txt
LICENSE
.gitignore
```

不要上传运行生成的数据库、CSV/JSON 导出文件和 `__pycache__`。

## License

MIT License
