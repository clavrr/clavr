"""
System utilities for process management and port checking.
"""
import socket
import subprocess
import time
from typing import Tuple

def check_port_available(port: int, host: str = '0.0.0.0') -> Tuple[bool, int]:
    """
    Check if a port is available. Returns (is_available, pid_using_port).
    If port is in use, returns (False, pid). Otherwise returns (True, 0).
    """
    try:
        # Try to bind to the port
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        res = sock.bind((host, port))
        sock.close()
        return (True, 0)
    except OSError:
        # Port is in use, try to find the PID
        try:
            result = subprocess.run(
                ['lsof', '-ti', f':{port}'],
                capture_output=True,
                text=True,
                timeout=2
            )
            if result.returncode == 0 and result.stdout.strip():
                pid = int(result.stdout.strip().split('\n')[0])
                return (False, pid)
        except Exception:
            # lsof failed or not available
            return (False, 0)
        return (False, 0)


def kill_process_on_port(port: int) -> bool:
    """Kill the process using the specified port. Returns True if successful."""
    try:
        result = subprocess.run(
            ['lsof', '-ti', f':{port}'],
            capture_output=True,
            text=True,
            timeout=2
        )
        if result.returncode == 0 and result.stdout.strip():
            pid = result.stdout.strip().split('\n')[0]
            subprocess.run(['kill', '-9', pid], timeout=2)
            time.sleep(0.5)  # Give it a moment to die
            return True
    except Exception as e:
        # Log the error but continue (port might be free, lsof failed etc)
        pass
    return False
