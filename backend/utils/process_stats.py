"""Cheap process measurements for hot paths."""


def get_rss_mb() -> float:
    """Resident set size in MB from one line of /proc/self/status; ru_maxrss
    where there is no procfs (macOS reports it in bytes, Linux in KB)."""
    try:
        with open("/proc/self/status") as f:
            for line in f:
                if line.startswith("VmRSS:"):
                    return int(line.split()[1]) / 1024
    except FileNotFoundError:
        import platform
        import resource

        usage = resource.getrusage(resource.RUSAGE_SELF)
        divisor = 1024 * 1024 if platform.system() == "Darwin" else 1024
        return usage.ru_maxrss / divisor
    return 0
