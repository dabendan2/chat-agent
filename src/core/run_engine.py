import argparse
import asyncio
import os
import sys

# Automatically add src/ to sys.path to ensure absolute imports work regardless of execution location
# This project expects 'src' to be the root for imports like 'from channels...'
current_dir = os.path.dirname(os.path.abspath(__file__))
src_root = os.path.abspath(os.path.join(current_dir, ".."))
if src_root not in sys.path:
    sys.path.insert(0, src_root)

from playwright.async_api import async_playwright
from channels.factory import ChannelFactory
from core.engine import ChatEngine
from utils.locker import PIDLock
from utils.config import CDP_PORT, DEFAULT_MODEL, OWNER_NAME

try:
    from setproctitle import setproctitle
except ImportError:
    setproctitle = None

async def main():
    parser = argparse.ArgumentParser(description="Chat Agent Proxy Engine CLI")
    parser.add_argument("--channel", default="line", help="Communication channel (e.g., line, messenger)")
    parser.add_argument("--chat_name", required=True, help="Name of the chat to manage")
    parser.add_argument("--chat_id", help="Unique ID of the chat")
    parser.add_argument("--task", required=True, help="Task description for the AI")
    parser.add_argument("--port", type=int, default=CDP_PORT, help="CDP port")
    parser.add_argument("--model", default=DEFAULT_MODEL, help="Gemini model name")
    args = parser.parse_args()

    # Set process title for reliable identification by remove_task
    if setproctitle:
        setproctitle(f"chat-agent:{args.channel}:{args.chat_name}")

    api_key = os.environ.get("GOOGLE_API_KEY")
    if not api_key:
        print("Error: GOOGLE_API_KEY not found in environment.")
        sys.exit(1)

    # Refactor task using Stepped Communication logic
    from core.refactorer import TaskRefactorer
    refactorer = TaskRefactorer(api_key=api_key, model_name=args.model)
    refactored_task = refactorer.refactor(args.task)
    print(f"DEBUG: Refactored Task:\n{refactored_task}")

    # Unique lock per channel and chat
    lock_name = f"{args.channel}_{args.chat_name}"
    lock = PIDLock(lock_name)
    if not lock.acquire():
        print(f"Error: Chat '{args.chat_name}' on {args.channel} is already being managed.")
        sys.exit(1)

    async with async_playwright() as p:
        try:
            browser = await p.chromium.connect_over_cdp(f"http://localhost:{args.port}")
            context = browser.contexts[0]
            
            # Platform specific page retrieval logic
            # Future improvement: move this into ChannelFactory or BaseChannel
            page = None
            if args.channel.lower() == "line":
                from channels.line import driver as line_utils
                page = await line_utils.get_line_page(context)
            else:
                # Placeholder for other channels
                # page = await messenger_utils.get_messenger_page(context)
                print(f"Error: Channel '{args.channel}' page retrieval not implemented.")
                lock.release()
                sys.exit(1)
            
            if not page:
                print(f"Error: {args.channel.upper()} page not found.")
                lock.release()
                sys.exit(1)

            channel_instance = ChannelFactory.create_instance(args.channel, page=page, owner_name=OWNER_NAME)
            
            engine = ChatEngine(
                channel=channel_instance,
                chat_name=args.chat_name,
                chat_id=args.chat_id,
                task=refactored_task,
                model_name=args.model,
                api_key=api_key
            )
            engine.lock = lock
            
            final_report = await engine.run()
            if final_report and "[SILENT_RESTART_NEEDED]" in final_report:
                # 靜默重啟不使用 ERROR 前綴，直接輸出指令標籤
                print(final_report)
                sys.exit(1)
            elif final_report and ("[OWNER_INPUT_NEEDED]" in final_report or "Error" in final_report or "Failed" in final_report):
                print(f"ERROR: {final_report}")
                sys.exit(1)
            elif final_report is None:
                print("ERROR: Engine session concluded without a final report (unexpected termination).")
                sys.exit(1)
            else:
                print(f"Success: Task for '{args.chat_name}' on {args.channel} completed. Status: {final_report}")
        except Exception as e:
            print(f"Error: {str(e)}")
            lock.release()
            sys.exit(1)

if __name__ == '__main__':
    asyncio.run(main())
