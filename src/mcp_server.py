import os
import sys
import asyncio

# Automatically add current directory to sys.path to ensure absolute imports work
# This allows calling the script from the project root without setting PYTHONPATH
current_dir = os.path.dirname(os.path.abspath(__file__))
if current_dir not in sys.path:
    sys.path.insert(0, current_dir)

from typing import List, Dict, Any, Optional
import json
import subprocess
from mcp.server.fastmcp import FastMCP
from utils.browser import BrowserManager
from core.engine import ChatEngine
from channels.factory import ChannelFactory
from playwright.async_api import async_playwright
from utils.config import CDP_PORT, DEFAULT_PROFILE, DEFAULT_MODEL, LOG_DIR, SCREENSHOT_DIR, \
    ENV_PATH, VIEWPORT_WIDTH, VIEWPORT_HEIGHT, SEARCH_INPUT_SELECTOR, SEARCH_TIMEOUT, OWNER_NAME

mcp = FastMCP("Chat Agent")

async def get_channel_instance(channel_name: str, port: int = CDP_PORT):
    async with async_playwright() as p:
        browser = await p.chromium.connect_over_cdp(f"http://localhost:{port}")
        context = browser.contexts[0]
        
        # This part still has some platform-specific logic for page retrieval
        # In a fully mature version, this would be part of the factory/driver
        page = None
        if channel_name.lower() == "line":
            from channels.line import driver as line_utils
            page = await line_utils.get_line_page(context)
        else:
            raise ValueError(f"Page retrieval for channel '{channel_name}' not implemented.")
            
        if not page:
            return None, None
            
        return ChannelFactory.create_instance(channel_name, page=page, owner_name=OWNER_NAME), page

@mcp.tool()
async def login(channel: str = "line", port: int = CDP_PORT) -> str:
    """Performs automated login for the specified channel using credentials from environment."""
    email_env = f"{channel.upper()}_EMAIL"
    pass_env = f"{channel.upper()}_PASSWORD"
    email = os.environ.get(email_env)
    password = os.environ.get(pass_env)
    
    if not email or not password:
        return f"Error: {email_env} or {pass_env} not found in environment."
        
    async with async_playwright() as p:
        try:
            browser = await p.chromium.connect_over_cdp(f"http://localhost:{port}")
            context = browser.contexts[0]
            
            # TODO: Move get_page into Channel instance
            page = None
            if channel.lower() == "line":
                from channels.line import driver as line_utils
                page = await line_utils.get_line_page(context)
            
            if not page: return f"Error: {channel.upper()} extension page not found."
            
            channel_inst = ChannelFactory.create_instance(channel, page=page, owner_name=OWNER_NAME)
            
            if await channel_inst.is_logged_in():
                return json.dumps({"status": "success", "message": f"Already logged in to {channel}."})
            
            login_result = await channel_inst.perform_login(email, password)
            
            if login_result.get("status") == "mfa_needed":
                print(f"MFA_CODE_FOUND:{login_result['code']}")
                # LINE specific MFA wait logic (might need generalization)
                if channel.lower() == "line":
                    from channels.line import driver as line_utils
                    success = await line_utils.wait_for_login_success(page, timeout_sec=300)
                else:
                    success = await channel_inst.is_logged_in() # Basic wait
                
                if success:
                    return json.dumps({"status": "success", "message": "Login successful after MFA."})
                else:
                    screenshot_path = SCREENSHOT_DIR / f"{channel}_login_timeout.png"
                    await page.screenshot(path=screenshot_path)
                    return json.dumps({"status": "error", "error": "Login timed out waiting for MFA.", "screenshot": str(screenshot_path)})
            
            elif login_result.get("status") == "pending":
                # General success check
                for _ in range(6):
                    await asyncio.sleep(5)
                    if await channel_inst.is_logged_in():
                        return json.dumps({"status": "success", "message": "Login successful."})
                return json.dumps({"status": "error", "error": "Login triggered but could not verify success."})
            
            return json.dumps(login_result)
        except Exception as e:
            return f"Error: {str(e)}"

@mcp.tool()
async def prepare_line_instance(port: int = CDP_PORT, profile_name: str = DEFAULT_PROFILE) -> str:
    """[LEGACY] Use prepare_instance instead. Prepares a browser instance for LINE."""
    bm = BrowserManager(port=port, profile_name=profile_name)
    result = bm.prepare_instance()
    return json.dumps(result)

@mcp.tool()
async def prepare_instance(channel: str = "line", port: int = CDP_PORT, profile_name: str = DEFAULT_PROFILE) -> str:
    """Prepares a browser instance for the specified channel."""
    # In the future, BrowserManager can be initialized with channel-specific extension IDs
    bm = BrowserManager(port=port, profile_name=profile_name)
    result = bm.prepare_instance()
    return json.dumps(result)

@mcp.tool()
async def find_chats(keyword: str, channel: str = "line", port: int = CDP_PORT) -> str:
    """Search for chats in the specified channel by keyword."""
    async with async_playwright() as p:
        try:
            browser = await p.chromium.connect_over_cdp(f"http://localhost:{port}")
            context = browser.contexts[0]
            
            page = None
            if channel.lower() == "line":
                from channels.line import driver as line_utils
                page = await line_utils.get_line_page(context)
            
            if not page: return f"Error: {channel.upper()} extension page not found."
            await page.bring_to_front()
            
            channel_inst = ChannelFactory.create_instance(channel, page=page, owner_name=OWNER_NAME)
            
            if not await channel_inst.is_logged_in():
                return json.dumps({"status": "error", "error": f"Not logged in to {channel}. Please call 'login' first."})
                
            matches = await channel_inst.find_chats(keyword)
            screenshot_path = SCREENSHOT_DIR / f"find_chats_{channel}_{keyword}.png"
            
            if not matches:
                await page.screenshot(path=screenshot_path)
            
            return json.dumps({
                "status": "success", 
                "channel": channel,
                "keyword": keyword, 
                "count": len(matches), 
                "chats": matches,
                "screenshot": str(screenshot_path) if not matches else None
            })
        except Exception as e: return f"Error: {str(e)}"

@mcp.tool()
async def open_chat(chat_name: str, chat_type: str, chat_id: str, channel: str = "line", port: int = CDP_PORT) -> str:
    """Opens a specific chat by unique chat_id in the specified channel."""
    async with async_playwright() as p:
        try:
            browser = await p.chromium.connect_over_cdp(f"http://localhost:{port}")
            context = browser.contexts[0]
            
            page = None
            if channel.lower() == "line":
                from channels.line import driver as line_utils
                page = await line_utils.get_line_page(context)
            
            if not page: return f"Error: {channel.upper()} extension page not found."
            await page.bring_to_front()
            await page.set_viewport_size({"width": VIEWPORT_WIDTH, "height": VIEWPORT_HEIGHT})
            
            channel_inst = ChannelFactory.create_instance(channel, page=page, owner_name=OWNER_NAME)
            
            if not await channel_inst.is_logged_in():
                return json.dumps({"status": "error", "error": f"Not logged in to {channel}. Please call 'login' first."})
                
            result = await channel_inst.open_chat(chat_name, chat_type, chat_id)
            screenshot_path = SCREENSHOT_DIR / f"open_chat_{channel}_{chat_name}.png"
            await page.screenshot(path=screenshot_path)
            result["screenshot"] = str(screenshot_path)
            return json.dumps(result)
        except Exception as e: return f"Error: {str(e)}"

@mcp.tool()
async def get_line_messages(chat_name: str, limit: int = 10, chat_id: Optional[str] = None, port: int = CDP_PORT) -> str:
    """[LEGACY] Use get_messages instead. Retrieves message history from a LINE chat."""
    return await get_messages(chat_name, limit, chat_id, channel="line", port=port)

@mcp.tool()
async def get_messages(chat_name: str, limit: int = 10, chat_id: Optional[str] = None, channel: str = "line", port: int = CDP_PORT) -> str:
    """Retrieves message history from a chat in the specified channel."""
    async with async_playwright() as p:
        try:
            browser = await p.chromium.connect_over_cdp(f"http://localhost:{port}")
            context = browser.contexts[0]
            
            page = None
            if channel.lower() == "line":
                from channels.line import driver as line_utils
                page = await line_utils.get_line_page(context)
            
            if not page: return f"Error: {channel.upper()} extension page not found."
            await page.bring_to_front()
            
            channel_inst = ChannelFactory.create_instance(channel, page=page, owner_name=OWNER_NAME)
            
            selection = await channel_inst.select_chat(chat_name, chat_id)
            if selection.get("status") != "success": return json.dumps(selection)
            
            messages = await channel_inst.extract_messages(limit=limit)
            response = {
                "status": "success", 
                "channel": channel, 
                "chat": chat_name, 
                "owner_name": OWNER_NAME,
                "count": len(messages), 
                "messages": messages
            }
            if len(messages) == 0:
                screenshot_path = SCREENSHOT_DIR / f"empty_chat_{channel}_{chat_name}.png"
                await page.screenshot(path=screenshot_path)
                response["screenshot"] = str(screenshot_path)
            return json.dumps(response)
        except Exception as e: return f"Error: {str(e)}"

@mcp.tool()
async def run_task(chat_name: str, task: str, channel: str = "line", chat_id: Optional[str] = None, port: int = CDP_PORT, model: str = DEFAULT_MODEL) -> str:
    """Runs an AI-driven task for a specific chat on a specified channel."""
    # Safety Check: Require confirmation for long-running task awareness
    if not os.environ.get("ONE_HOUR_TIMEOUT_SET_CONFIRMED"):
        chat_id_arg = f" chat_id:\"{chat_id}\"" if chat_id else ""
        error_msg = (
            "Error: ONE_HOUR_TIMEOUT_SET_CONFIRMED not set in environment.\n"
            "This tool can run for up to 1 hour. AI Agents MUST set a 1-hour timeout and use background mode.\n"
            "Example usage via terminal tool:\n"
            "terminal(\n"
            f"    command=\"export ONE_HOUR_TIMEOUT_SET_CONFIRMED=YES && mcporter call chat_agent.run_task channel:\\\"{channel}\\\" chat_name:\\\"{chat_name}\\\"{chat_id_arg} task:\\\"{task}\\\" --timeout 3600000\",\n"
            "    background=true,\n"
            "    notify_on_complete=true\n"
            ")"
        )
        return error_msg

    api_key = os.environ.get("GOOGLE_API_KEY")
    if not api_key: return "Error: GOOGLE_API_KEY not found."
    venv_python = sys.executable
    run_script = os.path.join(os.path.dirname(__file__), "core/run_engine.py")
    cmd = [venv_python, run_script, "--channel", channel, "--chat_name", chat_name, "--task", task, "--port", str(port), "--model", model]
    if chat_id:
        cmd.extend(["--chat_id", chat_id])
    try:
        # Working directory set to src so internal logic can find local resources
        working_dir = os.path.dirname(__file__)
        
        result = subprocess.run(cmd, capture_output=True, text=True, check=False, cwd=working_dir)
        return json.dumps({
            "status": "completed" if result.returncode == 0 else "failed", 
            "channel": channel,
            "exit_code": result.returncode, 
            "stdout": result.stdout, 
            "stderr": result.stderr
        })
    except Exception as e: return f"Error running task: {str(e)}"

@mcp.tool()
async def remove_task(chat_name: str, channel: str = "line") -> str:
    """Safely terminates any background tasks associated with a specific chat name and cleans up locks."""
    import signal
    import psutil
    
    results = {"status": "success", "terminated_pids": [], "cleaned_locks": []}
    target_title = f"chat-agent:{channel}:{chat_name}"
    
    # 1. Terminate matching processes
    try:
        for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
            try:
                # 優先使用精確的 Process Title 識別
                proc_name = proc.name()
                cmdline = proc.info.get('cmdline') or []
                cmd_str = " ".join(cmdline)
                
                is_match = (proc_name == target_title or 
                           (target_title in proc_name) or
                           ("run_engine.py" in cmd_str and chat_name in cmd_str and channel in cmd_str))
                
                if is_match:
                    pid = proc.info['pid']
                    proc.send_signal(signal.SIGKILL)
                    results["terminated_pids"].append(pid)
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
    except Exception as e:
        return json.dumps({"status": "error", "error": f"Failed to kill processes: {str(e)}"})

    # 2. Cleanup PID locks
    lock_name = f"{channel}_{chat_name}.pid".replace(" ", "_")
    from utils.config import DATA_DIR
    lock_path = DATA_DIR / "locks" / lock_name
    
    if lock_path.exists():
        try:
            lock_path.unlink()
            results["cleaned_locks"].append(str(lock_path))
        except Exception as e:
            results["lock_cleanup_error"] = str(e)

    return json.dumps(results)

if __name__ == "__main__":
    mcp.run()
