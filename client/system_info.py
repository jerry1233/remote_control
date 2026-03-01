import ctypes
import datetime
import getpass
import locale
import os
import platform
import re
import shutil
import socket
import subprocess
import time
import urllib.request
import uuid


def _run_command(args):
    try:
        out = subprocess.check_output(args, stderr=subprocess.DEVNULL, text=True)
        return out.strip()
    except Exception:
        return ""


def _format_bytes(num):
    if num is None:
        return "未知"
    units = ["B", "KB", "MB", "GB", "TB", "PB"]
    n = float(num)
    for unit in units:
        if n < 1024.0 or unit == units[-1]:
            return f"{n:.2f} {unit}"
        n /= 1024.0
    return f"{num} B"


def _get_public_ip():
    urls = ["https://api.ipify.org", "https://ifconfig.me/ip", "https://icanhazip.com"]
    for url in urls:
        try:
            with urllib.request.urlopen(url, timeout=3) as resp:
                ip = resp.read().decode("utf-8", errors="ignore").strip()
                if ip:
                    return ip
        except Exception:
            continue
    return "未知"


def _get_local_ip():
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.connect(("8.8.8.8", 80))
        ip = sock.getsockname()[0]
        sock.close()
        return ip
    except Exception:
        try:
            return socket.gethostbyname(socket.gethostname())
        except Exception:
            return "未知"


def _get_mac_address():
    mac = uuid.getnode()
    return ":".join(f"{(mac >> i) & 0xFF:02x}" for i in range(40, -1, -8))


def _get_uptime_seconds():
    system = platform.system()
    try:
        if system == "Windows":
            return int(ctypes.windll.kernel32.GetTickCount64() / 1000)
        if system == "Linux":
            with open("/proc/uptime", "r", encoding="utf-8") as f:
                return int(float(f.read().split()[0]))
        if system == "Darwin":
            out = _run_command(["sysctl", "-n", "kern.boottime"])
            # Example: { sec = 1700000000, usec = 0 } ...
            m = re.search(r"sec\s*=\s*(\d+)", out)
            if m:
                boot_ts = int(m.group(1))
                return int(time.time() - boot_ts)
    except Exception:
        pass
    return -1


def _format_uptime(seconds):
    if seconds is None or seconds < 0:
        return "未知"
    days, rem = divmod(seconds, 86400)
    hours, rem = divmod(rem, 3600)
    minutes, sec = divmod(rem, 60)
    return f"{days}天 {hours}小时 {minutes}分钟 {sec}秒"


def _is_admin():
    system = platform.system()
    try:
        if system == "Windows":
            return bool(ctypes.windll.shell32.IsUserAnAdmin())
        return os.geteuid() == 0
    except Exception:
        return False


def _get_cpu_model():
    system = platform.system()
    if system == "Linux":
        try:
            with open("/proc/cpuinfo", "r", encoding="utf-8", errors="ignore") as f:
                for line in f:
                    if line.lower().startswith("model name"):
                        return line.split(":", 1)[1].strip()
        except Exception:
            pass
    if system == "Darwin":
        out = _run_command(["sysctl", "-n", "machdep.cpu.brand_string"])
        if out:
            return out
    if system == "Windows":
        out = _run_command(["wmic", "cpu", "get", "Name"])
        lines = [x.strip() for x in out.splitlines() if x.strip() and x.strip().lower() != "name"]
        if lines:
            return lines[0]
        env = os.environ.get("PROCESSOR_IDENTIFIER", "")
        if env:
            return env
    return platform.processor() or "未知"


def _get_cpu_cores():
    logical = os.cpu_count() or 0
    physical = 0
    system = platform.system()
    try:
        if system == "Linux":
            core_pairs = set()
            physical_id = None
            core_id = None
            with open("/proc/cpuinfo", "r", encoding="utf-8", errors="ignore") as f:
                for raw in f:
                    line = raw.strip()
                    if not line:
                        if physical_id is not None and core_id is not None:
                            core_pairs.add((physical_id, core_id))
                        physical_id = None
                        core_id = None
                        continue
                    if line.startswith("physical id"):
                        physical_id = line.split(":", 1)[1].strip()
                    if line.startswith("core id"):
                        core_id = line.split(":", 1)[1].strip()
            if core_pairs:
                physical = len(core_pairs)
        elif system == "Darwin":
            out = _run_command(["sysctl", "-n", "hw.physicalcpu"])
            if out.isdigit():
                physical = int(out)
        elif system == "Windows":
            out = _run_command(["wmic", "cpu", "get", "NumberOfCores", "/value"])
            nums = re.findall(r"NumberOfCores=(\d+)", out)
            if nums:
                physical = sum(int(x) for x in nums)
    except Exception:
        pass
    if physical <= 0:
        physical = logical
    return physical, logical


def _get_gpu_model():
    system = platform.system()
    try:
        if system == "Windows":
            out = _run_command(["wmic", "path", "win32_VideoController", "get", "Name"])
            lines = [x.strip() for x in out.splitlines() if x.strip() and x.strip().lower() != "name"]
            if lines:
                return ", ".join(lines)
        elif system == "Darwin":
            out = _run_command(["system_profiler", "SPDisplaysDataType"])
            lines = []
            for line in out.splitlines():
                s = line.strip()
                if s.startswith("Chipset Model:"):
                    lines.append(s.split(":", 1)[1].strip())
            if lines:
                return ", ".join(lines)
        elif system == "Linux":
            out = _run_command(["lspci"])
            lines = []
            for line in out.splitlines():
                low = line.lower()
                if "vga compatible controller" in low or "3d controller" in low or "display controller" in low:
                    parts = line.split(":", 2)
                    lines.append(parts[-1].strip() if len(parts) >= 3 else line.strip())
            if lines:
                return ", ".join(lines)
    except Exception:
        pass
    return "未知"


def _get_memory_info():
    total = None
    used = None
    system = platform.system()
    try:
        if system == "Windows":
            class MEMORYSTATUSEX(ctypes.Structure):
                _fields_ = [
                    ("dwLength", ctypes.c_ulong),
                    ("dwMemoryLoad", ctypes.c_ulong),
                    ("ullTotalPhys", ctypes.c_ulonglong),
                    ("ullAvailPhys", ctypes.c_ulonglong),
                    ("ullTotalPageFile", ctypes.c_ulonglong),
                    ("ullAvailPageFile", ctypes.c_ulonglong),
                    ("ullTotalVirtual", ctypes.c_ulonglong),
                    ("ullAvailVirtual", ctypes.c_ulonglong),
                    ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
                ]

            stat = MEMORYSTATUSEX()
            stat.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
            ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(stat))
            total = int(stat.ullTotalPhys)
            used = int(stat.ullTotalPhys - stat.ullAvailPhys)
        elif system == "Linux":
            mem = {}
            with open("/proc/meminfo", "r", encoding="utf-8", errors="ignore") as f:
                for line in f:
                    key, value = line.split(":", 1)
                    mem[key.strip()] = int(value.strip().split()[0]) * 1024
            total = mem.get("MemTotal")
            avail = mem.get("MemAvailable")
            if total is not None and avail is not None:
                used = total - avail
        elif system == "Darwin":
            total_out = _run_command(["sysctl", "-n", "hw.memsize"])
            if total_out.isdigit():
                total = int(total_out)
            vm = _run_command(["vm_stat"])
            page_size = 4096
            m = re.search(r"page size of (\d+) bytes", vm)
            if m:
                page_size = int(m.group(1))
            free_pages = 0
            for line in vm.splitlines():
                if "Pages free" in line or "Pages inactive" in line or "Pages speculative" in line:
                    num = int(re.sub(r"[^\d]", "", line) or "0")
                    free_pages += num
            if total is not None:
                used = max(0, total - free_pages * page_size)
    except Exception:
        pass
    return {
        "total_bytes": total,
        "used_bytes": used,
        "total_human": _format_bytes(total),
        "used_human": _format_bytes(used),
    }


def _get_mount_points():
    system = platform.system()
    mounts = []
    if system == "Windows":
        for ch in "ABCDEFGHIJKLMNOPQRSTUVWXYZ":
            root = f"{ch}:\\"
            if os.path.exists(root):
                mounts.append(root)
        return mounts

    if os.path.exists("/proc/mounts"):
        skip_types = {
            "proc", "sysfs", "tmpfs", "devtmpfs", "devpts", "cgroup", "cgroup2",
            "overlay", "squashfs", "pstore", "securityfs", "tracefs", "configfs",
            "fusectl", "mqueue", "hugetlbfs", "debugfs", "rpc_pipefs", "autofs",
        }
        try:
            with open("/proc/mounts", "r", encoding="utf-8", errors="ignore") as f:
                for line in f:
                    parts = line.split()
                    if len(parts) >= 3:
                        mnt = parts[1]
                        fstype = parts[2]
                        if fstype not in skip_types and mnt.startswith("/"):
                            mounts.append(mnt)
        except Exception:
            pass
    if not mounts:
        out = _run_command(["mount"])
        for line in out.splitlines():
            if " on " in line:
                right = line.split(" on ", 1)[1]
                mnt = right.split(" (", 1)[0].strip()
                if mnt.startswith("/"):
                    mounts.append(mnt)
    mounts = sorted(set(mounts))
    if not mounts:
        mounts = ["/"]
    return mounts


def _get_disk_info():
    mounts = _get_mount_points()
    details = []
    total_sum = 0
    used_sum = 0
    for mnt in mounts:
        try:
            usage = shutil.disk_usage(mnt)
            total_sum += usage.total
            used = usage.total - usage.free
            used_sum += used
            details.append(
                {
                    "mount": mnt,
                    "total_bytes": usage.total,
                    "used_bytes": used,
                    "total_human": _format_bytes(usage.total),
                    "used_human": _format_bytes(used),
                }
            )
        except Exception:
            continue
    return {
        "total_bytes": total_sum if total_sum > 0 else None,
        "used_bytes": used_sum if total_sum > 0 else None,
        "total_human": _format_bytes(total_sum if total_sum > 0 else None),
        "used_human": _format_bytes(used_sum if total_sum > 0 else None),
        "mounts": details,
    }


def collect_system_info():
    now = datetime.datetime.now().astimezone()
    lang = locale.getlocale()[0] or os.environ.get("LANG", "").split(".")[0] or "未知"
    arch = platform.architecture()[0]
    os_name = f"{platform.system()} {platform.release()} ({arch})"
    mem = _get_memory_info()
    disk = _get_disk_info()
    physical, logical = _get_cpu_cores()

    return {
        "basic": {
            "hostname": socket.gethostname(),
            "public_ip": _get_public_ip(),
            "local_ip": _get_local_ip(),
            "mac": _get_mac_address(),
            "timezone": str(now.tzinfo),
            "time": now.strftime("%Y-%m-%d %H:%M:%S"),
            "language": lang,
            "os": os_name,
            "kernel": platform.version() if platform.version() else platform.release(),
            "uptime": _format_uptime(_get_uptime_seconds()),
            "user": getpass.getuser(),
            "privilege": "管理员" if _is_admin() else "普通用户",
        },
        "hardware": {
            "cpu_model": _get_cpu_model(),
            "cpu_cores_physical": physical,
            "cpu_cores_logical": logical,
            "gpu_model": _get_gpu_model(),
            "memory_total": mem["total_human"],
            "memory_used": mem["used_human"],
            "disk_total": disk["total_human"],
            "disk_used": disk["used_human"],
            "mounts": disk["mounts"],
        },
    }
