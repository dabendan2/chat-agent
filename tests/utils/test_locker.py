import pytest
import os
import sys
import psutil
import time

sys.path.append(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))
from utils.locker import PIDLock

def test_lock_acquisition_and_release():
    lock_name = "test_lock_unique_123"
    lock = PIDLock(lock_name)
    
    # Force cleanup
    if os.path.exists(lock.lock_path):
        os.remove(lock.lock_path)
    
    # 1. First acquire should succeed
    success = lock.acquire()
    assert success is True, "First acquire should succeed"
    assert os.path.exists(lock.lock_path)
    
    # 2. Second acquire (same name) used to fail, but now it should SUCCEED by preempting
    # Note: In this test, it's the SAME PID (current process), so it might just overwrite.
    # To properly test preemption, we would need a separate process.
    lock2 = PIDLock(lock_name)
    success2 = lock2.acquire()
    assert success2 is True, "Second acquire should succeed (preemption/overwrite)"
    
    with open(lock.lock_path, "r") as f:
        assert int(f.read().strip()) == os.getpid()
    
    # 3. Release should remove file
    lock.release()
    assert not os.path.exists(lock.lock_path)

def test_stale_lock_recovery():
    lock_name = "stale_test_recover"
    lock = PIDLock(lock_name)
    
    # Cleanup
    if os.path.exists(lock.lock_path):
        os.remove(lock.lock_path)
        
    # Create a fake lock file with a PID that is definitely NOT running or not python
    # Using a very high PID is usually safe for "not running"
    fake_pid = 999999
    while psutil.pid_exists(fake_pid):
        fake_pid += 1
        
    os.makedirs(os.path.dirname(lock.lock_path), exist_ok=True)
    with open(lock.lock_path, "w") as f:
        f.write(str(fake_pid))
    
    # New instance should be able to recover because fake_pid is dead
    lock2 = PIDLock(lock_name)
    assert lock2.acquire() is True, "Should recover from stale lock"
    
    lock2.release()

def test_lock_preemption_real_process():
    import subprocess
    lock_name = "preemption_real_test"
    lock = PIDLock(lock_name)
    
    if os.path.exists(lock.lock_path):
        os.remove(lock.lock_path)
        
    # Start a dummy background process that looks like our agent
    # We use a simple python sleep command but include 'run_engine.py' in the args
    dummy_proc = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)", "run_engine.py"], 
                                 executable=sys.executable)
    
    # Manually create the lock file for this dummy process
    os.makedirs(os.path.dirname(lock.lock_path), exist_ok=True)
    with open(lock.lock_path, "w") as f:
        f.write(str(dummy_proc.pid))
        
    try:
        lock_taker = PIDLock(lock_name)
        assert lock_taker.acquire() is True, "Should preempt the dummy process"
        
        # Verify the dummy process was killed
        time.sleep(0.5) # Wait for signal and OS cleanup
        
        # If it's a child, it might be a zombie, so we wait()
        try:
            dummy_proc.wait(timeout=1)
        except:
            pass
            
        assert not psutil.pid_exists(dummy_proc.pid)
    finally:
        if psutil.pid_exists(dummy_proc.pid):
            dummy_proc.kill()
        lock.release()
