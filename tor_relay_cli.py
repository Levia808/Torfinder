#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Tor 中继节点采集与本地 SQLite 管理工具。

数据源：Tor Metrics Onionoo details API。
用途：维护当前 Tor relay 的 OR 地址库，用于流量识别实验中的低误报匹配。
"""

from __future__ import annotations

import argparse
import csv
import ipaddress
import json
import os
import sqlite3
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")


APP_DIR = Path(__file__).resolve().parent
DEFAULT_DB = APP_DIR / "tor_relays.sqlite3"
LOGO_WIDTH = 94
DEFAULT_API_URL = (
    "https://onionoo.torproject.org/details"
    "?type=relay&running=true"
    "&fields=fingerprint,nickname,or_addresses,last_seen,running,flags,"
    "country,country_name,as,as_name,contact,platform,version,observed_bandwidth"
)

LOGO = r"""
'########::'#######::'########::'########:'####:'##::: ##:'########::'########:'########::
... ##..::'##.... ##: ##.... ##: ##.....::. ##:: ###:: ##: ##.... ##: ##.....:: ##.... ##:
::: ##:::: ##:::: ##: ##:::: ##: ##:::::::: ##:: ####: ##: ##:::: ##: ##::::::: ##:::: ##:
::: ##:::: ##:::: ##: ########:: ######:::: ##:: ## ## ##: ##:::: ##: ######::: ########::
::: ##:::: ##:::: ##: ##.. ##::: ##...::::: ##:: ##. ####: ##:::: ##: ##...:::: ##.. ##:::
::: ##:::: ##:::: ##: ##::. ##:: ##:::::::: ##:: ##:. ###: ##:::: ##: ##::::::: ##::. ##::
::: ##::::. #######:: ##:::. ##: ##:::::::'####: ##::. ##: ########:: ########: ##:::. ##:
:::..::::::.......:::..:::::..::..::::::::....::..::::..::........:::........::..:::::..::
"""

MENU_OPTIONS = [
    ("1", "初始化数据库"),
    ("2", "立即同步 Tor Relay 地址库"),
    ("3", "查看数据库统计"),
    ("4", "查询某个 IP 是否命中"),
    ("5", "列出当前 OR 地址"),
    ("6", "导出当前地址库"),
    ("7", "动态循环更新"),
    ("8", "查看命令行帮助"),
    ("0", "退出"),
]


def clear_screen() -> None:
    os.system("cls" if os.name == "nt" else "clear")


def default_export_path(export_format: str = "csv") -> Path:
    return Path.cwd() / f"tor_relay_or_addresses.{export_format}"


def log_event(message: str, level: str = "INFO") -> None:
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{timestamp}] [{level}] {message}")


def print_logo() -> None:
    print(LOGO)
    print("  名称：TORFINDER")
    print("  用途：Tor Relay IP / ORPort 地址采集、动态更新、查询与导出")
    print("=" * LOGO_WIDTH)


def pause(message: str = "按 Enter 返回主菜单...") -> None:
    try:
        input(message)
    except EOFError:
        pass


def prompt_text(label: str, default: str = "") -> str:
    suffix = f"（默认：{default}）" if default else ""
    try:
        value = input(f"{label}{suffix}: ").strip()
    except EOFError:
        return default
    return value or default


def prompt_int(label: str, default: int, min_value: int | None = None) -> int:
    while True:
        raw = prompt_text(label, str(default))
        try:
            value = int(raw)
        except ValueError:
            print("请输入数字。")
            continue
        if min_value is not None and value < min_value:
            print(f"请输入不小于 {min_value} 的数字。")
            continue
        return value


def read_menu_key() -> str:
    if os.name == "nt":
        import msvcrt

        key = msvcrt.getwch()
        if key in ("\x00", "\xe0"):
            key = msvcrt.getwch()
            if key == "H":
                return "up"
            if key == "P":
                return "down"
            return "other"
        if key == "\r":
            return "enter"
        if key == "\x1b":
            time.sleep(0.02)
            if msvcrt.kbhit() and msvcrt.getwch() == "[" and msvcrt.kbhit():
                seq_key = msvcrt.getwch()
                if seq_key == "A":
                    return "up"
                if seq_key == "B":
                    return "down"
            return "escape"
        return key

    import termios
    import tty

    fd = sys.stdin.fileno()
    old = termios.tcgetattr(fd)
    try:
        tty.setraw(fd)
        key = sys.stdin.read(1)
        if key == "\x1b":
            seq = sys.stdin.read(2)
            if seq == "[A":
                return "up"
            if seq == "[B":
                return "down"
            return "escape"
        if key in ("\r", "\n"):
            return "enter"
        return key
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old)


def print_menu(selected_index: int = 0) -> None:
    print_logo()
    print("使用 ↑ / ↓ 切换菜单，Enter 执行；也可以直接按数字键。Esc 退出。")
    print()
    for index, (key, label) in enumerate(MENU_OPTIONS):
        marker = ">" if index == selected_index else " "
        selected = "<<" if index == selected_index else "  "
        print(f" {marker} [{key}] {label:<24} {selected}")
    print()


def select_menu_choice(selected_index: int = 0) -> tuple[str, int]:
    option_keys = {key: index for index, (key, _) in enumerate(MENU_OPTIONS)}
    while True:
        clear_screen()
        print_menu(selected_index)
        key = read_menu_key()
        if key == "up":
            selected_index = (selected_index - 1) % len(MENU_OPTIONS)
        elif key == "down":
            selected_index = (selected_index + 1) % len(MENU_OPTIONS)
        elif key == "enter":
            return MENU_OPTIONS[selected_index][0], selected_index
        elif key == "escape":
            return "0", option_keys["0"]
        elif key in option_keys:
            return key, option_keys[key]


def print_runtime_error(title: str, message: str) -> None:
    print(title)
    print("-" * 40)
    print(message)


def handle_runtime_error(exc: Exception, db_path: Path) -> None:
    if isinstance(exc, (urllib.error.URLError, TimeoutError)):
        print_runtime_error(
            "同步失败",
            "问题步骤：连接 Tor Metrics Onionoo 数据源\n"
            f"错误原因：{exc}\n\n"
            "建议检查：\n"
            "  1. 当前网络是否可以访问 https://onionoo.torproject.org\n"
            "  2. 是否需要代理或放行网络访问权限\n"
            "  3. 稍后重新选择“立即同步”",
        )
    elif isinstance(exc, sqlite3.Error):
        print_runtime_error(
            "数据库操作失败",
            f"数据库路径：{db_path}\n错误原因：{exc}",
        )
    elif isinstance(exc, ValueError):
        print_runtime_error("数据处理失败", f"错误原因：{exc}")
    elif isinstance(exc, OSError):
        print_runtime_error("文件或系统操作失败", f"错误原因：{exc}")
    else:
        print_runtime_error("程序执行失败", f"错误原因：{exc}")


def interactive_menu(db_path: Path = DEFAULT_DB, api_url: str = DEFAULT_API_URL, timeout: int = 30) -> int:
    selected_index = 0
    while True:
        choice, selected_index = select_menu_choice(selected_index)
        clear_screen()

        if choice == "0":
            print_logo()
            log_event("用户选择退出。")
            print("已退出。")
            return 0

        try:
            with connect_db(db_path) as conn:
                if choice == "1":
                    print_logo()
                    log_event("开始初始化数据库。")
                    log_event(f"数据库路径：{db_path}")
                    init_db(conn)
                    log_event("数据库初始化完成。")
                elif choice == "2":
                    print_logo()
                    log_event("开始同步 Tor Relay 地址库。")
                    log_event(f"数据源：{api_url}")
                    result = sync_relays(conn, api_url, timeout)
                    log_event(f"同步完成：{result.relays} 个 relay，{result.addresses} 个 OR 地址。")
                    log_event(f"数据库路径：{db_path}")
                elif choice == "3":
                    print_logo()
                    log_event("开始读取数据库统计信息。")
                    print_stats(conn)
                    log_event("统计信息读取完成。")
                elif choice == "4":
                    print_logo()
                    ip = prompt_text("请输入要查询的 IPv4/IPv6 地址")
                    if ip:
                        print()
                        log_event(f"开始查询 IP：{ip}")
                        search_ip(conn, ip)
                        log_event("IP 查询完成。")
                    else:
                        log_event("未输入 IP，已取消查询。", "WARN")
                elif choice == "5":
                    print_logo()
                    args = argparse.Namespace(
                        country=prompt_text("国家/地区代码，留空表示不过滤"),
                        flag=prompt_text("Relay Flag，留空表示不过滤，例如 Guard、Exit"),
                        ip_version=None,
                        limit=prompt_int("显示条数", 20, 1),
                    )
                    ip_version = prompt_text("IP 版本，输入 4/6，留空表示全部")
                    if ip_version in {"4", "6"}:
                        args.ip_version = int(ip_version)
                    elif ip_version:
                        print("IP 版本输入无效，已按全部版本查询。")
                    print()
                    log_event(
                        "开始列出 OR 地址："
                        f"country={args.country or '全部'}, "
                        f"flag={args.flag or '全部'}, "
                        f"ip_version={args.ip_version or '全部'}, "
                        f"limit={args.limit}"
                    )
                    list_relays(conn, args)
                    log_event("OR 地址列表读取完成。")
                elif choice == "6":
                    print_logo()
                    export_format = prompt_text("导出格式 csv/json", "csv").lower()
                    if export_format not in {"csv", "json"}:
                        log_event("导出格式无效，已使用 csv。", "WARN")
                        export_format = "csv"
                    output = prompt_text("导出文件路径", str(default_export_path(export_format)))
                    args = argparse.Namespace(format=export_format, output=output)
                    print()
                    log_event(f"开始导出地址库：format={export_format}, output={output}")
                    export_addresses(conn, args)
                    log_event("地址库导出完成。")
                elif choice == "7":
                    print_logo()
                    interval = prompt_int("同步间隔，单位秒", 3600, 10)
                    args = argparse.Namespace(api_url=api_url, timeout=timeout, interval=interval)
                    log_event(f"启动动态循环更新：interval={interval}s")
                    run_loop(conn, args)
                elif choice == "8":
                    print_logo()
                    log_event("显示命令行帮助。")
                    build_parser().print_help()
                else:
                    print_logo()
                    log_event("无效选择，请使用方向键或数字键选择菜单项。", "WARN")
        except KeyboardInterrupt:
            print()
            log_event("当前操作已停止。", "WARN")
        except Exception as exc:
            log_event("执行过程中出现错误。", "ERROR")
            handle_runtime_error(exc, db_path)

        print()
        pause()


def shell_quote(value: str) -> str:
    if any(ch.isspace() for ch in value):
        return f'"{value}"'
    return value


def print_quick_usage(prog: str = "tor_relay_cli.py") -> None:
    python_exe = sys.executable or "python"
    command_prefix = f"{shell_quote(python_exe)} {shell_quote(prog)}"
    print("Tor 中继节点爬虫 CLI")
    print("-" * 40)
    print("你还没有指定要执行的操作。请选择下面任意一个命令：")
    print()
    print("  初始化数据库：")
    print(f"    {command_prefix} init")
    print()
    print("  立即同步 Tor relay 地址库：")
    print(f"    {command_prefix} sync")
    print()
    print("  查看统计信息：")
    print(f"    {command_prefix} stats")
    print()
    print("  查询某个 IP 是否命中：")
    print(f"    {command_prefix} search 1.2.3.4")
    print()
    print("  列出当前 Guard 节点地址：")
    print(f"    {command_prefix} list --flag Guard --limit 20")
    print()
    print("  每小时动态更新：")
    print(f"    {command_prefix} loop --interval 3600")
    print()
    print("  查看完整帮助：")
    print(f"    {command_prefix} --help")


def command_prefix(prog: str) -> str:
    python_exe = sys.executable or "python"
    return f"{shell_quote(python_exe)} {shell_quote(prog)}"


def translate_argparse_error(message: str, prog: str) -> str:
    if "the following arguments are required:" in message:
        missing = message.split(":", 1)[1].strip()
        if missing == "command":
            return "缺少操作命令：请在 init、sync、stats、list、search、export、loop 中选择一个。"
        if missing == "ip":
            return f"search 操作缺少 IP 参数。例如：{command_prefix(prog)} search 1.2.3.4"
        return f"缺少必填参数：{missing}"

    if "invalid choice:" in message:
        return "命令或参数值写错了。请先运行 --help 查看可用选项。"

    if message.startswith("unrecognized arguments:"):
        return "存在无法识别的参数：" + message.split(":", 1)[1].strip()

    if "expected one argument" in message:
        return "某个参数后面缺少取值，请检查命令格式。"

    return message


class ChineseArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        root_prog = sys.argv[0] if sys.argv else self.prog
        print("参数错误")
        print("-" * 40)
        print(translate_argparse_error(message, root_prog))
        print()
        print_quick_usage(root_prog)
        raise SystemExit(2)


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def connect_db(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS relays (
            fingerprint TEXT PRIMARY KEY,
            nickname TEXT,
            running INTEGER NOT NULL DEFAULT 0,
            flags_json TEXT NOT NULL DEFAULT '[]',
            country TEXT,
            country_name TEXT,
            as_number TEXT,
            as_name TEXT,
            contact TEXT,
            platform TEXT,
            version TEXT,
            observed_bandwidth INTEGER,
            onionoo_last_seen TEXT,
            first_seen_at TEXT NOT NULL,
            last_seen_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS or_addresses (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            fingerprint TEXT NOT NULL REFERENCES relays(fingerprint) ON DELETE CASCADE,
            ip TEXT NOT NULL,
            port INTEGER NOT NULL,
            ip_version INTEGER NOT NULL,
            is_current INTEGER NOT NULL DEFAULT 1,
            first_seen_at TEXT NOT NULL,
            last_seen_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE(fingerprint, ip, port)
        );

        CREATE TABLE IF NOT EXISTS sync_runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            started_at TEXT NOT NULL,
            completed_at TEXT,
            status TEXT NOT NULL,
            relay_count INTEGER NOT NULL DEFAULT 0,
            address_count INTEGER NOT NULL DEFAULT 0,
            message TEXT
        );

        CREATE INDEX IF NOT EXISTS idx_or_addresses_ip_port
            ON or_addresses(ip, port);
        CREATE INDEX IF NOT EXISTS idx_or_addresses_current
            ON or_addresses(is_current);
        CREATE INDEX IF NOT EXISTS idx_relays_country
            ON relays(country);
        """
    )
    conn.commit()


def fetch_json(url: str, timeout: int) -> dict[str, Any]:
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "tor-relay-cli/1.0 (+local research tool)",
            "Accept": "application/json",
        },
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        charset = resp.headers.get_content_charset() or "utf-8"
        return json.loads(resp.read().decode(charset))


def parse_or_address(value: str) -> tuple[str, int, int] | None:
    value = value.strip()
    if not value:
        return None

    if value.startswith("["):
        end = value.find("]")
        if end <= 0 or end + 2 > len(value) or value[end + 1] != ":":
            return None
        ip_text = value[1:end]
        port_text = value[end + 2 :]
    else:
        if ":" not in value:
            return None
        ip_text, port_text = value.rsplit(":", 1)

    try:
        ip_obj = ipaddress.ip_address(ip_text)
        port = int(port_text)
    except ValueError:
        return None

    if not (1 <= port <= 65535):
        return None
    return str(ip_obj), port, ip_obj.version


@dataclass(frozen=True)
class SyncResult:
    relays: int
    addresses: int
    started_at: str
    completed_at: str


def sync_relays(conn: sqlite3.Connection, api_url: str, timeout: int) -> SyncResult:
    init_db(conn)
    started_at = utc_now()
    run_id = conn.execute(
        "INSERT INTO sync_runs(started_at, status) VALUES (?, ?)",
        (started_at, "running"),
    ).lastrowid
    conn.commit()

    try:
        payload = fetch_json(api_url, timeout)
        relays = payload.get("relays", [])
        if not isinstance(relays, list):
            raise ValueError("Onionoo 响应中 relays 字段不是列表")

        now = utc_now()
        address_count = 0

        with conn:
            conn.execute("UPDATE or_addresses SET is_current = 0, updated_at = ?", (now,))

            for relay in relays:
                if not isinstance(relay, dict):
                    continue
                fingerprint = str(relay.get("fingerprint") or "").strip()
                if not fingerprint:
                    continue

                flags = relay.get("flags") or []
                if not isinstance(flags, list):
                    flags = []

                conn.execute(
                    """
                    INSERT INTO relays (
                        fingerprint, nickname, running, flags_json, country, country_name,
                        as_number, as_name, contact, platform, version, observed_bandwidth,
                        onionoo_last_seen, first_seen_at, last_seen_at, updated_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(fingerprint) DO UPDATE SET
                        nickname = excluded.nickname,
                        running = excluded.running,
                        flags_json = excluded.flags_json,
                        country = excluded.country,
                        country_name = excluded.country_name,
                        as_number = excluded.as_number,
                        as_name = excluded.as_name,
                        contact = excluded.contact,
                        platform = excluded.platform,
                        version = excluded.version,
                        observed_bandwidth = excluded.observed_bandwidth,
                        onionoo_last_seen = excluded.onionoo_last_seen,
                        last_seen_at = excluded.last_seen_at,
                        updated_at = excluded.updated_at
                    """,
                    (
                        fingerprint,
                        relay.get("nickname"),
                        1 if relay.get("running") else 0,
                        json.dumps(flags, ensure_ascii=False),
                        relay.get("country"),
                        relay.get("country_name"),
                        relay.get("as"),
                        relay.get("as_name"),
                        relay.get("contact"),
                        relay.get("platform"),
                        relay.get("version"),
                        relay.get("observed_bandwidth"),
                        relay.get("last_seen"),
                        now,
                        now,
                        now,
                    ),
                )

                for raw_addr in relay.get("or_addresses") or []:
                    parsed = parse_or_address(str(raw_addr))
                    if not parsed:
                        continue
                    ip, port, ip_version = parsed
                    address_count += 1
                    conn.execute(
                        """
                        INSERT INTO or_addresses (
                            fingerprint, ip, port, ip_version, is_current,
                            first_seen_at, last_seen_at, updated_at
                        )
                        VALUES (?, ?, ?, ?, 1, ?, ?, ?)
                        ON CONFLICT(fingerprint, ip, port) DO UPDATE SET
                            ip_version = excluded.ip_version,
                            is_current = 1,
                            last_seen_at = excluded.last_seen_at,
                            updated_at = excluded.updated_at
                        """,
                        (fingerprint, ip, port, ip_version, now, now, now),
                    )

            completed_at = utc_now()
            conn.execute(
                """
                UPDATE sync_runs
                SET completed_at = ?, status = ?, relay_count = ?, address_count = ?, message = ?
                WHERE id = ?
                """,
                (completed_at, "success", len(relays), address_count, "同步完成", run_id),
            )

        return SyncResult(len(relays), address_count, started_at, completed_at)
    except Exception as exc:
        completed_at = utc_now()
        with conn:
            conn.execute(
                """
                UPDATE sync_runs
                SET completed_at = ?, status = ?, message = ?
                WHERE id = ?
                """,
                (completed_at, "failed", str(exc), run_id),
            )
        raise


def print_stats(conn: sqlite3.Connection) -> None:
    init_db(conn)
    row = conn.execute(
        """
        SELECT
            (SELECT COUNT(*) FROM relays WHERE running = 1) AS running_relays,
            (SELECT COUNT(*) FROM or_addresses WHERE is_current = 1) AS current_addresses,
            (SELECT COUNT(*) FROM or_addresses WHERE is_current = 1 AND ip_version = 4) AS ipv4,
            (SELECT COUNT(*) FROM or_addresses WHERE is_current = 1 AND ip_version = 6) AS ipv6
        """
    ).fetchone()
    last_run = conn.execute(
        """
        SELECT started_at, completed_at, status, relay_count, address_count, message
        FROM sync_runs
        ORDER BY id DESC
        LIMIT 1
        """
    ).fetchone()
    flag_rows = conn.execute("SELECT flags_json FROM relays WHERE running = 1").fetchall()

    guard_count = 0
    exit_count = 0
    for flag_row in flag_rows:
        flags = json.loads(flag_row["flags_json"] or "[]")
        guard_count += 1 if "Guard" in flags else 0
        exit_count += 1 if "Exit" in flags else 0

    print("Tor 中继节点数据库统计")
    print("-" * 36)
    print(f"运行中 Relay 数量 : {row['running_relays']}")
    print(f"当前 OR 地址数量  : {row['current_addresses']}")
    print(f"IPv4 地址数量     : {row['ipv4']}")
    print(f"IPv6 地址数量     : {row['ipv6']}")
    print(f"Guard Relay 数量  : {guard_count}")
    print(f"Exit Relay 数量   : {exit_count}")
    if last_run:
        print("-" * 36)
        print(f"最近同步状态      : {last_run['status']}")
        print(f"最近同步开始      : {last_run['started_at']} UTC")
        print(f"最近同步结束      : {last_run['completed_at'] or '-'} UTC")
        print(f"最近同步 Relay    : {last_run['relay_count']}")
        print(f"最近同步地址      : {last_run['address_count']}")
        if last_run["message"]:
            print(f"说明              : {last_run['message']}")


def list_relays(conn: sqlite3.Connection, args: argparse.Namespace) -> None:
    init_db(conn)
    where = ["a.is_current = 1"]
    params: list[Any] = []

    if args.country:
        where.append("LOWER(r.country) = LOWER(?)")
        params.append(args.country)
    if args.flag:
        where.append("r.flags_json LIKE ?")
        params.append(f'%"{args.flag}"%')
    if args.ip_version:
        where.append("a.ip_version = ?")
        params.append(args.ip_version)

    params.append(args.limit)
    rows = conn.execute(
        f"""
        SELECT r.nickname, r.fingerprint, r.country, r.as_name, r.flags_json,
               a.ip, a.port, a.ip_version
        FROM or_addresses a
        JOIN relays r ON r.fingerprint = a.fingerprint
        WHERE {' AND '.join(where)}
        ORDER BY r.country, r.nickname, a.ip, a.port
        LIMIT ?
        """,
        params,
    ).fetchall()

    if not rows:
        print("没有找到符合条件的中继节点。")
        return

    for row in rows:
        flags = ",".join(json.loads(row["flags_json"] or "[]"))
        print(
            f"{row['ip']}:{row['port']} | IPv{row['ip_version']} | "
            f"{row['country'] or '-'} | {row['nickname'] or '-'} | "
            f"{flags or '-'} | {row['as_name'] or '-'}"
        )


def search_ip(conn: sqlite3.Connection, ip_text: str) -> None:
    init_db(conn)
    try:
        ip = str(ipaddress.ip_address(ip_text))
    except ValueError:
        print(f"IP 格式不正确：{ip_text}")
        raise SystemExit(2)

    rows = conn.execute(
        """
        SELECT r.nickname, r.fingerprint, r.country, r.country_name, r.as_name,
               r.flags_json, a.ip, a.port, a.is_current, a.first_seen_at, a.last_seen_at
        FROM or_addresses a
        JOIN relays r ON r.fingerprint = a.fingerprint
        WHERE a.ip = ?
        ORDER BY a.is_current DESC, a.port
        """,
        (ip,),
    ).fetchall()

    if not rows:
        print(f"未命中：{ip} 不在本地 Tor Relay OR 地址库中。")
        return

    print(f"命中 {len(rows)} 条记录：{ip}")
    print("-" * 36)
    for row in rows:
        flags = ",".join(json.loads(row["flags_json"] or "[]"))
        state = "当前" if row["is_current"] else "历史"
        print(f"{state} | {row['ip']}:{row['port']} | {row['nickname'] or '-'}")
        print(f"国家/地区：{row['country_name'] or row['country'] or '-'}")
        print(f"运营方 AS：{row['as_name'] or '-'}")
        print(f"Flags    ：{flags or '-'}")
        print(f"指纹     ：{row['fingerprint']}")
        print(f"首次/最近：{row['first_seen_at']} UTC / {row['last_seen_at']} UTC")
        print("-" * 36)


def export_addresses(conn: sqlite3.Connection, args: argparse.Namespace) -> None:
    init_db(conn)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)

    rows = conn.execute(
        """
        SELECT a.ip, a.port, a.ip_version, r.fingerprint, r.nickname, r.country,
               r.country_name, r.as_number, r.as_name, r.flags_json, a.last_seen_at
        FROM or_addresses a
        JOIN relays r ON r.fingerprint = a.fingerprint
        WHERE a.is_current = 1
        ORDER BY a.ip_version, a.ip, a.port
        """
    ).fetchall()

    if args.format == "json":
        data = [dict(row) for row in rows]
        for item in data:
            item["flags"] = json.loads(item.pop("flags_json") or "[]")
        output.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    else:
        with output.open("w", encoding="utf-8", newline="") as fh:
            writer = csv.writer(fh)
            writer.writerow(
                [
                    "ip",
                    "port",
                    "ip_version",
                    "fingerprint",
                    "nickname",
                    "country",
                    "country_name",
                    "as_number",
                    "as_name",
                    "flags",
                    "last_seen_at_utc",
                ]
            )
            for row in rows:
                writer.writerow(
                    [
                        row["ip"],
                        row["port"],
                        row["ip_version"],
                        row["fingerprint"],
                        row["nickname"],
                        row["country"],
                        row["country_name"],
                        row["as_number"],
                        row["as_name"],
                        ",".join(json.loads(row["flags_json"] or "[]")),
                        row["last_seen_at"],
                    ]
                )

    print(f"已导出 {len(rows)} 条当前 OR 地址：{output}")


def run_loop(conn: sqlite3.Connection, args: argparse.Namespace) -> None:
    print(f"开始动态更新：每 {args.interval} 秒同步一次。按 Ctrl+C 停止。")
    while True:
        try:
            result = sync_relays(conn, args.api_url, args.timeout)
            print(
                f"[{result.completed_at} UTC] 同步成功："
                f"{result.relays} 个 relay，{result.addresses} 个 OR 地址"
            )
        except (urllib.error.URLError, TimeoutError) as exc:
            print(f"[{utc_now()} UTC] 网络请求失败：{exc}")
        except Exception as exc:
            print(f"[{utc_now()} UTC] 同步失败：{exc}")

        time.sleep(args.interval)


def build_parser() -> argparse.ArgumentParser:
    parser = ChineseArgumentParser(
        description="Tor 中继节点 IP 爬取、入库、动态更新与查询 CLI",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--db", type=Path, default=DEFAULT_DB, help="SQLite 数据库路径")
    parser.add_argument("--api-url", default=DEFAULT_API_URL, help="Onionoo API 地址")
    parser.add_argument("--timeout", type=int, default=30, help="网络请求超时时间，单位秒")

    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("init", help="初始化数据库")
    subparsers.add_parser("stats", help="查看数据库统计信息")

    sync_parser = subparsers.add_parser("sync", help="立即同步 Tor relay 数据")
    sync_parser.add_argument("--quiet", action="store_true", help="只输出最少信息")

    loop_parser = subparsers.add_parser("loop", help="循环动态更新")
    loop_parser.add_argument("--interval", type=int, default=3600, help="同步间隔，单位秒")

    list_parser = subparsers.add_parser("list", help="列出当前 OR 地址")
    list_parser.add_argument("--country", help="按国家/地区代码过滤，例如 us、de、cn")
    list_parser.add_argument("--flag", help="按 relay flag 过滤，例如 Guard、Exit、Running")
    list_parser.add_argument("--ip-version", type=int, choices=[4, 6], help="只看 IPv4 或 IPv6")
    list_parser.add_argument("--limit", type=int, default=30, help="最多显示条数")

    search_parser = subparsers.add_parser("search", help="查询某个 IP 是否命中本地地址库")
    search_parser.add_argument("ip", help="要查询的 IPv4/IPv6 地址")

    export_parser = subparsers.add_parser("export", help="导出当前 OR 地址库")
    export_parser.add_argument("--format", choices=["csv", "json"], default="csv", help="导出格式")
    export_parser.add_argument("--output", default=str(default_export_path("csv")), help="导出文件")

    return parser


def main(argv: list[str] | None = None) -> int:
    if argv is None:
        argv = sys.argv[1:]

    if not argv:
        return interactive_menu()

    parser = build_parser()
    args = parser.parse_args(argv)

    conn = connect_db(args.db)
    try:
        if args.command == "init":
            log_event("开始初始化数据库。")
            log_event(f"数据库路径：{args.db}")
            init_db(conn)
            log_event("数据库初始化完成。")
        elif args.command == "sync":
            log_event("开始同步 Tor Relay 地址库。")
            log_event(f"数据源：{args.api_url}")
            result = sync_relays(conn, args.api_url, args.timeout)
            if not args.quiet:
                log_event(f"同步完成：{result.relays} 个 relay，{result.addresses} 个 OR 地址。")
                log_event(f"数据库路径：{args.db}")
        elif args.command == "loop":
            log_event(f"启动动态循环更新：interval={args.interval}s")
            run_loop(conn, args)
        elif args.command == "stats":
            log_event("开始读取数据库统计信息。")
            print_stats(conn)
            log_event("统计信息读取完成。")
        elif args.command == "list":
            log_event(
                "开始列出 OR 地址："
                f"country={args.country or '全部'}, "
                f"flag={args.flag or '全部'}, "
                f"ip_version={args.ip_version or '全部'}, "
                f"limit={args.limit}"
            )
            list_relays(conn, args)
            log_event("OR 地址列表读取完成。")
        elif args.command == "search":
            log_event(f"开始查询 IP：{args.ip}")
            search_ip(conn, args.ip)
            log_event("IP 查询完成。")
        elif args.command == "export":
            log_event(f"开始导出地址库：format={args.format}, output={args.output}")
            export_addresses(conn, args)
            log_event("地址库导出完成。")
        else:
            parser.print_help()
            return 2
    except KeyboardInterrupt:
        print()
        log_event("操作已停止。", "WARN")
        return 130
    except (urllib.error.URLError, TimeoutError) as exc:
        log_event("同步失败。", "ERROR")
        print("同步失败")
        print("-" * 40)
        print("问题步骤：连接 Tor Metrics Onionoo 数据源")
        print(f"错误原因：{exc}")
        print()
        print("建议检查：")
        print("  1. 当前网络是否可以访问 https://onionoo.torproject.org")
        print("  2. 是否需要代理或放行网络访问权限")
        print("  3. 稍后重试：python .\\tor_relay_cli.py sync")
        return 1
    except sqlite3.Error as exc:
        log_event("数据库操作失败。", "ERROR")
        print("数据库操作失败")
        print("-" * 40)
        print(f"数据库路径：{args.db}")
        print(f"错误原因：{exc}")
        return 1
    except ValueError as exc:
        log_event("数据处理失败。", "ERROR")
        print("数据处理失败")
        print("-" * 40)
        print(f"错误原因：{exc}")
        return 1
    except OSError as exc:
        log_event("文件或系统操作失败。", "ERROR")
        print("文件或系统操作失败")
        print("-" * 40)
        print(f"错误原因：{exc}")
        return 1
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
