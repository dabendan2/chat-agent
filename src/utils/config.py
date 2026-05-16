import os
from pathlib import Path
from dotenv import load_dotenv

# Paths
DATA_DIR = Path.home() / ".chat-agent"
LOG_DIR = DATA_DIR / "logs"
FILE_CACHE_DIR = DATA_DIR / "file-cache"
SCREENSHOT_DIR = DATA_DIR
ENV_PATH = Path.home() / ".hermes" / ".env"

# Load environment variables
load_dotenv(ENV_PATH)

# Ensure directories exist
os.makedirs(LOG_DIR, exist_ok=True)
os.makedirs(FILE_CACHE_DIR, exist_ok=True)

# Browser Configuration
CDP_PORT = 9222
DEFAULT_PROFILE = "line_booking_session"
EXTENSION_ID = "ophjlpahpchlmihnnnihgmmeilfjmjjc"
VIEWPORT_WIDTH = 1600
VIEWPORT_HEIGHT = 1000

# AI Configuration
DEFAULT_MODEL = os.environ.get("LINE_DEFAULT_MODEL", "gemini-3-flash-preview")
OWNER_NAME = os.environ.get("LINE_OWNER_NAME", "Owner")
LINE_EMAIL = os.environ.get("LINE_EMAIL")
LINE_PASSWORD = os.environ.get("LINE_PASSWORD")
HERMES_PREFIX = "[Hermes]"
INTRO_PHRASE = "您好，我是 {{OWNER_NAME}} 的AI代理 Hermes。"

# Timing and Timeouts
SEARCH_TIMEOUT = 10000
POLL_INTERVAL = 5
OWNER_INPUT_WAIT = 120
CONVERSATION_END_WAIT = 120
TOOL_WAIT = 60
HERMES_API_URL = os.environ.get("HERMES_API_URL", "http://127.0.0.1:8642")

# Runtime Timeout: 50 minutes (3000 seconds)
RUNTIME_TIMEOUT = 3000

# DOM Selectors
SEARCH_INPUT_SELECTOR = "input[placeholder*='Search'], input[placeholder*='搜尋'], .search_input, input[type='text']"
MESSAGE_INPUT_SELECTOR = '.message_input, [contenteditable="true"], textarea, textarea-ex'
CHATROOM_HEADER_SELECTOR = '[class*="chatroomHeader-module__name"]'
CHATLIST_ITEM_TITLE_SELECTOR = '[class*="chatlistItem-module__title"]'
FRIEND_LIST_ITEM_TITLE_SELECTOR = '[class*="friendlistItem-module__name_box"]'
CHATLIST_ITEM_SELECTOR = 'xpath=ancestor::div[contains(@class, "chatlist_item")] | ancestor::button'

# Extraction Selectors - CRITICAL FIX BASED ON DOM SCAN
CHATROOM_CONTAINER_SELECTOR = 'DIV.chatroom-module__chatroom__eVUaK, [class*="chatroomContent-module__content_area"]'
MESSAGE_ITEM_SELECTOR = 'DIV.message-module__message__7odk3, [class*="messageLayout-module__message"]'
MESSAGE_CONTENT_SELECTOR = '[class*="content_inner"], [class*="textMessageContent-module__text"]'
MESSAGE_TIME_SELECTOR = '[class*="time"], [class*="metaInfo-module__time"]'
SENDER_NAME_SELECTOR = '[class*="username-module__username"], [class*="sender"]'
FILE_INPUT_SELECTOR = 'input[type="file"]'
