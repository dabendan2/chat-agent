import os
import sys
import psutil

class PIDLock:
    def __init__(self, chat_name):
        lock_dir = os.path.expanduser("~/.chat-agent/locks")
        os.makedirs(lock_dir, exist_ok=True)
        # Use sanitized chat name for filename
        safe_name = "".join([c if c.isalnum() else "_" for c in chat_name])
        self.lock_path = os.path.join(lock_dir, f"{safe_name}.pid")
        self.chat_name = chat_name

    def acquire(self):
        """Checks for existing lock, terminates previous instance if found, and acquires lock."""
        if os.path.exists(self.lock_path):
            try:
                with open(self.lock_path, "r") as f:
                    old_pid = int(f.read().strip())
                
                if psutil.pid_exists(old_pid) and old_pid != os.getpid():
                    proc = psutil.Process(old_pid)
                    # Verify it's related to our agent before killing
                    cmd_str = " ".join(proc.cmdline())
                    if "run_engine.py" in cmd_str or "chat-agent" in proc.name():
                        print(f"[LOCK] Found existing instance (PID {old_pid}) for '{self.chat_name}'. Terminating it to take over.")
                        import signal
                        proc.send_signal(signal.SIGKILL)
                        # Wait a moment for OS to clean up
                        import time
                        time.sleep(0.5)
            except (ValueError, psutil.NoSuchProcess, psutil.AccessDenied, Exception) as e:
                print(f"[LOCK] Warning during pre-emption check: {e}")
        
        # Always attempt to (re)acquire
        try:
            with open(self.lock_path, "w") as f:
                f.write(str(os.getpid()))
            return True
        except Exception as e:
            print(f"[LOCK] Failed to write lock file: {e}")
            return False

    def release(self):
        """Removes the lock file."""
        try:
            if os.path.exists(self.lock_path):
                os.remove(self.lock_path)
        except Exception as e:
            print(f"[LOCK] Error releasing lock: {e}")
