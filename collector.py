import json
import os
import platform
import threading
import time
import ctypes
from ctypes import wintypes
import csv
import psutil

from db import get_connection

INTERVAL = max(1, int(os.getenv("MONITOR_INTERVAL_SECONDS", "5")))

_stop_event = threading.Event()
_thread = None
_last_net = None
_last_net_time = None
IGNORED_PROCESS_NAMES = {
    "aggregatorhost.exe",
    "atiesrxx.exe",
    "atieclxx.exe",
    "audiodg.exe",
    "backgroundtaskhost.exe",
    "conhost.exe",
    "csrss.exe",
    "ctfmon.exe",
    "dashost.exe",
    "dllhost.exe",
    "fontdrvhost.exe",
    "lsaiso.exe",
    "lsass.exe",
    "memory compression",
    "registry",
    "runtimebroker.exe",
    "searchfilterhost.exe",
    "searchindexer.exe",
    "searchprotocolhost.exe",
    "secure system",
    "securityhealthservice.exe",
    "services.exe",
    "sihost.exe",
    "smss.exe",
    "spoolsv.exe",
    "registry",
    "system",
    "system idle process",
    "taskhostw.exe",
    "wininit.exe",
    "winlogon.exe",
    "wmiprvse.exe",
    "wudfhost.exe",
}

USER_APP_KEYWORDS = {
    "acrobat",
    "calculator",
    "canva",
    "chatgpt",
    "chrome",
    "cmd",
    "code",
    "discord",
    "excel",
    "explorer",
    "firefox",
    "messenger",
    "mspaint",
    "msedge",
    "notepad",
    "onenote",
    "opera",
    "photos",
    "photoshop",
    "powerpnt",
    "powershell",
    "spotify",
    "steam",
    "teams",
    "telegram",
    "vlc",
    "winword",
    "wps",
    "zoom",
}

EnumWindowsProc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
user32 = ctypes.WinDLL("user32", use_last_error=True)
user32.EnumWindows.argtypes = [EnumWindowsProc, wintypes.LPARAM]
user32.EnumWindows.restype = wintypes.BOOL
user32.IsWindowVisible.argtypes = [wintypes.HWND]
user32.IsWindowVisible.restype = wintypes.BOOL
user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]


def bytes_to_gb(value):
    return round(value / (1024**3), 2)


def bytes_to_mb(value):
    return round(value / (1024**2), 2)


def collect_network_metrics():
    global _last_net, _last_net_time

    current = psutil.net_io_counters()
    now = time.monotonic()

    upload_kbps = 0
    download_kbps = 0

    if _last_net and _last_net_time:
        elapsed = max(0.1, now - _last_net_time)
        upload_kbps = ((current.bytes_sent - _last_net.bytes_sent) / 1024) / elapsed
        download_kbps = ((current.bytes_recv - _last_net.bytes_recv) / 1024) / elapsed

    _last_net = current
    _last_net_time = now

    return {
        "net_upload_kbps": round(max(0, upload_kbps), 2),
        "net_download_kbps": round(max(0, download_kbps), 2),
        "net_sent_mb": bytes_to_mb(current.bytes_sent),
        "net_recv_mb": bytes_to_mb(current.bytes_recv),
    }


def get_visible_application_pids():
    pids = set()

    def callback(hwnd, lparam):
        if user32.IsWindowVisible(hwnd):
            pid = wintypes.DWORD()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            if pid.value:
                pids.add(pid.value)
        return True

    user32.EnumWindows(EnumWindowsProc(callback), 0)
    return pids


def save_application_activity():
    visible_pids = get_visible_application_pids()

    with get_connection() as conn:
        with conn.cursor() as cur:
            for proc in psutil.process_iter(["pid", "name", "memory_percent"]):
                try:
                    process_name = proc.info.get("name") or "Unknown"
                    normalized_name = process_name.lower()

                    if normalized_name in IGNORED_PROCESS_NAMES:
                        continue

                    if not any(keyword in normalized_name for keyword in USER_APP_KEYWORDS):
                        continue

                    if visible_pids and proc.pid not in visible_pids:
                        continue

                    if not visible_pids and (proc.info.get("memory_percent") or 0) < 0.05:
                        continue

                    cur.execute(
                        """
                        UPDATE application_activity
                        SET last_seen = NOW(),
                            sample_count = sample_count + 1
                        WHERE process_name = %s AND pid = %s
                        """,
                        (process_name, proc.pid),
                    )

                    if cur.rowcount == 0:
                        cur.execute(
                            """
                            INSERT INTO application_activity (process_name, pid)
                            VALUES (%s, %s)
                            """,
                            (process_name, proc.pid),
                        )
                except (psutil.AccessDenied, psutil.NoSuchProcess):
                    continue
        conn.commit()


def collect_metrics():
    cpu_percent = psutil.cpu_percent(interval=0.4)
    per_core = psutil.cpu_percent(interval=0.2, percpu=True)

    freq = psutil.cpu_freq()
    freq_mhz = round(freq.current, 2) if freq else None

    memory_percent = psutil.virtual_memory().percent
    process_count = len(psutil.pids())
    disk = psutil.disk_usage(os.getenv("MONITOR_DISK_PATH", os.path.abspath(os.sep)))
    network = collect_network_metrics()

    return {
        "cpu_percent": round(cpu_percent, 2),
        "per_core": [round(x, 2) for x in per_core],
        "cpu_frequency_mhz": freq_mhz,
        "memory_percent": round(memory_percent, 2),
        "process_count": process_count,
        "disk_percent": round(disk.percent, 2),
        "disk_used_gb": bytes_to_gb(disk.used),
        "disk_free_gb": bytes_to_gb(disk.free),
        "disk_total_gb": bytes_to_gb(disk.total),
        **network,
    }


def save_metrics(metrics):
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO cpu_metrics
                    (
                        cpu_percent,
                        per_core,
                        cpu_frequency_mhz,
                        memory_percent,
                        process_count,
                        disk_percent,
                        disk_used_gb,
                        disk_free_gb,
                        disk_total_gb,
                        net_upload_kbps,
                        net_download_kbps,
                        net_sent_mb,
                        net_recv_mb
                    )
                VALUES (%s, %s::jsonb, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    metrics["cpu_percent"],
                    json.dumps(metrics["per_core"]),
                    metrics["cpu_frequency_mhz"],
                    metrics["memory_percent"],
                    metrics["process_count"],
                    metrics["disk_percent"],
                    metrics["disk_used_gb"],
                    metrics["disk_free_gb"],
                    metrics["disk_total_gb"],
                    metrics["net_upload_kbps"],
                    metrics["net_download_kbps"],
                    metrics["net_sent_mb"],
                    metrics["net_recv_mb"],
                ),
            )
        conn.commit()


def collector_loop():
    # Warm up psutil's CPU percentage measurement.
    psutil.cpu_percent(interval=None)
    psutil.cpu_percent(interval=None, percpu=True)

    while not _stop_event.is_set():
        try:
            metrics = collect_metrics()
            save_metrics(metrics)
            save_application_activity()
        except Exception as exc:
            print(f"[collector] {type(exc).__name__}: {exc}")

        _stop_event.wait(INTERVAL)


def start_collector():
    global _thread

    if _thread and _thread.is_alive() and not _stop_event.is_set():
        return

    if _thread and _thread.is_alive():
        _thread.join(timeout=1)

    _stop_event.clear()
    _thread = threading.Thread(
        target=collector_loop,
        daemon=True,
        name="cpu-monitor-collector",
    )
    _thread.start()


def stop_collector():
    _stop_event.set()


def is_collector_running():
    return bool(_thread and _thread.is_alive() and not _stop_event.is_set())


def get_system_info():
    return {
        "hostname": platform.node() or "Unknown",
        "platform": platform.platform(),
        "processor": platform.processor() or "Unknown",
        "physical_cores": psutil.cpu_count(logical=False),
        "logical_cores": psutil.cpu_count(logical=True),
    }


def get_top_processes(limit=8):
    processes = []
    logical_cores = psutil.cpu_count(logical=True) or 1

    candidates = list(psutil.process_iter(["pid", "name", "memory_percent"]))

    for proc in candidates:
        try:
            proc.cpu_percent(interval=None)
        except (psutil.AccessDenied, psutil.NoSuchProcess):
            continue

    time.sleep(0.1)

    for proc in candidates:
        try:
            name = proc.info.get("name") or "Unknown"
            if proc.pid == 0 or name.lower() == "system idle process":
                continue

            processes.append(
                {
                    "pid": proc.pid,
                    "name": name,
                    "cpu_percent": round(
                        proc.cpu_percent(interval=None) / logical_cores, 2
                    ),
                    "memory_percent": round(proc.info.get("memory_percent") or 0, 2),
                }
            )
        except (psutil.AccessDenied, psutil.NoSuchProcess):
            continue

    return sorted(
        processes,
        key=lambda item: (item["cpu_percent"], item["memory_percent"]),
        reverse=True,
    )[:limit]

def export_metrics_to_csv(monitoring_logs_dir):
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT *
                FROM public.cpu_metrics
                ORDER BY id ASC
                """
            )
            rows = cur.fetchall()
            column_names = [desc[0] for desc in cur.description]

    with open(file_path, mode='w', newline='') as csv_file:
        writer = csv.writer(csv_file)
        writer.writerow(column_names)
        writer.writerows(rows)