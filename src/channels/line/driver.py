import asyncio
import re
import json
import base64
import hashlib
import os
import datetime
from typing import List, Dict, Optional, Any
from utils.config import EXTENSION_ID, HERMES_PREFIX, MESSAGE_INPUT_SELECTOR, CHATROOM_HEADER_SELECTOR, \
    CHATLIST_ITEM_TITLE_SELECTOR, FRIEND_LIST_ITEM_TITLE_SELECTOR, CHATLIST_ITEM_SELECTOR, CHATROOM_CONTAINER_SELECTOR, \
    MESSAGE_ITEM_SELECTOR, MESSAGE_CONTENT_SELECTOR, MESSAGE_TIME_SELECTOR, SENDER_NAME_SELECTOR, FILE_INPUT_SELECTOR, \
    FILE_CACHE_DIR

from channels.base import BaseChannel

class LineChannel(BaseChannel):
    def __init__(self, page: Any, owner_name: str = "Owner"):
        self.page = page
        self.owner_name = owner_name
        self.active_chat_id = None

    async def bring_to_front(self) -> None:
        await self.page.bring_to_front()

    async def select_chat(self, chat_name: str, chat_id: Optional[str] = None) -> Dict[str, Any]:
        result = await select_chat(self.page, chat_name, chat_id)
        if result.get("status") == "success":
            self.active_chat_id = result.get("chat_id")
        return result

    async def extract_messages(self, limit: int = 20) -> List[Dict[str, Any]]:
        msgs = await extract_messages(self.page, owner_name=self.owner_name)
        if not msgs: return []
        
        target_msgs = msgs[-limit:]
        
        import base64
        import hashlib
        import datetime
        from utils.config import FILE_CACHE_DIR

        # Determine sub-directory: priority chat_id, fallback chat_name hash
        if self.active_chat_id:
            chat_folder = self.active_chat_id
        else:
            # 使用 owner_name + chat_name 產生一個相對穩定的 fallback 名稱
            chat_folder = "fallback_" + hashlib.md5(f"{self.owner_name}_{msgs[0].get('sender', 'unknown')}".encode()).hexdigest()[:8]
            
        target_dir = FILE_CACHE_DIR / chat_folder
        os.makedirs(target_dir, exist_ok=True)

        for msg in target_msgs:
            media = msg.get("media")
            if media and media.get("url") and media["type"] in ["image", "sticker", "file"]:
                url = media["url"]
                stable_key = msg.get("id") or f"{msg['sender']}_{msg['timestamp']}_{msg['text']}"
                
                date_now = datetime.datetime.now().strftime("%Y%m%d")
                hhmm = "0000"
                if msg.get("timestamp"):
                    try:
                        t_obj = datetime.datetime.strptime(msg["timestamp"].strip(), "%I:%M %p")
                        hhmm = t_obj.strftime("%H%M")
                    except:
                        try:
                            t_obj = datetime.datetime.strptime(msg["timestamp"].strip(), "%H:%M")
                            hhmm = t_obj.strftime("%H%M")
                        except: pass
                
                # Determine extension
                if media["type"] == "image": ext = "png"
                elif media["type"] == "sticker": ext = "webp"
                else:
                    # For files, try to get extension from name
                    orig_name = media.get("name", "file")
                    ext = os.path.splitext(orig_name)[1].lstrip('.') or "bin"
                
                short_hash = hashlib.md5(stable_key.encode()).hexdigest()[:4]
                filename = f"{media['type']}_{date_now}_{hhmm}_{short_hash}.{ext}"
                local_path = os.path.join(target_dir, filename)
                
                if not os.path.exists(local_path):
                    try:
                        b64_data = await self.page.evaluate("""async (u) => {
                            const r = await fetch(u);
                            const b = await r.blob();
                            return new Promise(res => {
                                const rd = new FileReader();
                                rd.onloadend = () => res(rd.result.split(',')[1]);
                                rd.readAsDataURL(b);
                            });
                        }""", url)
                        with open(local_path, "wb") as f:
                            f.write(base64.b64decode(b64_data))
                    except Exception as e:
                        print(f"Failed to download {url}: {e}")
                
                if os.path.exists(local_path):
                    msg["media"]["local_path"] = str(local_path)
                    
        return target_msgs

    async def send_message(self, text: str) -> bool:
        return await send_message(self.page, text)

    async def send_image(self, image_path: str) -> bool:
        return await send_image(self.page, image_path)

    async def find_chats(self, keyword: str) -> List[Dict[str, Any]]:
        return await find_chats(self.page, keyword)

    async def open_chat(self, chat_name: str, chat_type: str, chat_id: str) -> Dict[str, Any]:
        result = await open_chat(self.page, chat_name, chat_type, chat_id)
        if result.get("status") == "success":
            self.active_chat_id = result.get("chat_id")
        return result

    async def is_logged_in(self) -> bool:
        return await is_logged_in(self.page)

    async def perform_login(self, email: str, password: str) -> Dict[str, Any]:
        return await perform_login(self.page, email, password)

async def get_line_page(context: Any) -> Any:
    ext_url = f"chrome-extension://{EXTENSION_ID}/index.html"
    target_page = None
    
    for _ in range(10):
        if context.pages:
            break
        await asyncio.sleep(0.2)
    
    for page in context.pages:
        if EXTENSION_ID in page.url:
            if any(route in page.url for route in ["#/friends", "#/chats", "#/timeline"]):
                target_page = page
                break
    
    if not target_page:
        for page in context.pages:
            if EXTENSION_ID in page.url:
                target_page = page
                break
    
    if not target_page:
        for page in context.pages:
            if "chrome-error" in page.url or "about:blank" in page.url:
                await page.goto(ext_url)
                await asyncio.sleep(2)
                target_page = page
                break
                
    if not target_page:
        try:
            target_page = await context.new_page()
            await target_page.goto(ext_url)
            await asyncio.sleep(2)
        except:
            return None
            
    if target_page:
        for page in context.pages:
            try:
                if page != target_page and not any(ext in page.url for ext in ["devtools", "background", "service-worker"]):
                    if EXTENSION_ID in page.url:
                        await page.close()
            except:
                pass
                
    return target_page

async def is_logged_in(page: Any, timeout_ms: int = 3000) -> bool:
    try:
        real_url = await page.evaluate("window.location.href")
        if real_url.endswith("#/") or "index.html" not in real_url:
            await asyncio.sleep(1.0)
            real_url = await page.evaluate("window.location.href")
            
        indicators = page.locator('[aria-label="Friend"], [aria-label="Chat"], .nav_item, [class*="nav"]')
        count = await indicators.count()
        
        if count > 0:
            return True
            
        if "index.html" in real_url and "#/login" not in real_url and not real_url.endswith("#/"):
            return True
            
        return False
    except Exception as e:
        return False

async def perform_login(page: Any, email: str, password: str) -> Dict[str, Any]:
    try:
        target = page
        for frame in page.frames:
            if "login" in frame.url or "auth" in frame.url:
                target = frame
                break
        
        email_field = target.locator("input[type='email'], input[type='text']").first
        password_field = target.locator("input[type='password']").first
        
        if not await email_field.is_visible(timeout=5000):
            return {"status": "error", "error": "Login fields not found."}
            
        await email_field.fill(email)
        await password_field.fill(password)
        
        login_btn = target.locator("button:has-text('Log in'), button.btn_login, .login_btn, button[type='submit']").first
        if await login_btn.is_visible():
            await login_btn.click()
        else:
            await password_field.press("Enter")
            
        await asyncio.sleep(5)
        
        mfa_code = None
        for frame in page.frames:
            code_el = frame.locator(".verification_code, .code, .mfa_code, div[class*='code']").first
            if await code_el.is_visible():
                mfa_code = await code_el.inner_text()
                if mfa_code and len(mfa_code.strip()) >= 4:
                    break
        
        if mfa_code:
            return {"status": "mfa_needed", "code": mfa_code.strip()}
            
        return {"status": "pending", "message": "Login triggered, checking state..."}
    except Exception as e:
        return {"status": "error", "error": str(e)}

async def wait_for_login_success(page: Any, timeout_sec: int = 300) -> bool:
    start_time = asyncio.get_event_loop().time()
    while asyncio.get_event_loop().time() - start_time < timeout_sec:
        if await is_logged_in(page):
            return True
        await asyncio.sleep(5)
    return False

async def select_chat(page: Any, chat_name: str, chat_id: Optional[str] = None) -> Dict[str, Any]:
    if not await is_logged_in(page):
        return {"status": "error", "error": "Not logged in. Please use the login_line tool first."}
    
    header_locator = page.locator(CHATROOM_HEADER_SELECTOR).first
    input_locator = page.locator(MESSAGE_INPUT_SELECTOR).first
    
    try:
        if await header_locator.is_visible(timeout=1000) and await input_locator.is_visible(timeout=1000):
            header_text = await header_locator.inner_text()
            actual_name = re.sub(r'\s+', ' ', header_text).strip()
            norm_target = re.sub(r'\s+', ' ', chat_name).strip()
            
            if actual_name == norm_target and not chat_id:
                # 嘗試抓取目前選取中對話的 ID (data-mid)
                current_id = await page.evaluate("""() => {
                    const activeItem = document.querySelector('[class*="chatlist_item"][class*="active"], [class*="Item"][class*="selected"]');
                    return activeItem ? activeItem.getAttribute('data-mid') : "";
                }""")
                return {"status": "success", "chat_id": current_id, "info": f"Chat '{chat_name}' already selected."}
            
            if actual_name == norm_target and chat_id:
                return {"status": "success", "chat_id": chat_id, "info": f"Chat '{chat_name}' with ID already selected."}
    except:
        pass
        
    chats = await find_chats(page, chat_name)
    if isinstance(chats, dict) and chats.get("status") == "error":
        return chats
        
    if not chats:
        return {"status": "not_found", "error": f"No chat found with name '{chat_name}'"}
    
    target = None
    norm_target_name = re.sub(r'\s+', ' ', chat_name).strip().lower()
    
    if chat_id:
        target = next((c for c in chats if c["chat_id"] == chat_id), None)
    else:
        exact_matches = [c for c in chats if re.sub(r'\s+', ' ', c["name"]).strip().lower() == norm_target_name]
        if exact_matches:
            target = next((c for c in exact_matches if c["type"] == "private"), exact_matches[0])
        else:
            partial_matches = [c for c in chats if norm_target_name in re.sub(r'\s+', ' ', c["name"]).strip().lower()]
            if partial_matches:
                target = next((c for c in partial_matches if c["type"] == "private"), partial_matches[0])
    
    if not target or not target.get("chat_id"):
        return {"status": "error", "error": f"Could not resolve unique chat_id for '{chat_name}'. Found {len(chats)} candidates."}
        
    return await open_chat(page, target["name"], target["type"], target["chat_id"])

async def find_chats(page: Any, keyword: str) -> List[Dict[str, str]]:
    try:
        friend_btn = page.locator('[aria-label="Friend"]').first
        is_friend_visible = await friend_btn.is_visible()
        if is_friend_visible:
            await friend_btn.click()
            await asyncio.sleep(0.5)

        search_input = page.locator('input[placeholder*="Search"], input[placeholder*="搜尋"], .search_input').first
        await search_input.click()
        await page.keyboard.press("Control+A")
        await page.keyboard.press("Backspace")
        await search_input.fill(keyword)
        
        try:
            await page.wait_for_function(
                """(kw) => {
                    const items = document.querySelectorAll('[class*="title"], [class*="name"]');
                    const text = Array.from(items).map(i => i.innerText).join(' ');
                    const bodyText = document.body.innerText;
                    return text.includes(kw) || bodyText.includes('No results') || bodyText.includes('查裝結果') || bodyText.includes('沒有符合條件');
                }""", 
                keyword,
                timeout=3000
            )
        except:
            await asyncio.sleep(1)
        
        script = """
        (keyword) => {
            try {
                const headerEls = Array.from(document.querySelectorAll('*')).filter(el => {
                    const t = el.innerText ? el.innerText.trim() : "";
                    return (t === "群組" || t === "好友" || t === "Groups" || t === "Friends") && el.offsetHeight > 0;
                });
                
                const sections = headerEls.map(el => {
                    const t = el.innerText.trim();
                    return {
                        type: (t === "群組" || t === "Groups") ? "group" : "private",
                        top: el.getBoundingClientRect().top
                    };
                }).sort((a, b) => a.top - b.top);
                
                const selectors = ['*[class*="item"]', '*[class*="Item"]', '.search_item'];
                const allItems = Array.from(document.querySelectorAll(selectors.join(','))).filter(el => el.offsetHeight > 0);
                
                const rootItems = allItems.filter(el => {
                    return !allItems.some(other => other !== el && other.contains(el));
                });
                
                const results = [];
                rootItems.forEach(el => {
                    const titleEl = el.querySelector('[class*="title"], [class*="name_box"], .search_text, [class*="name"]');
                    if (!titleEl) return;
                    
                    const name = titleEl.innerText.trim();
                    if (!name.toLowerCase().includes(keyword.toLowerCase())) return;
                    
                    const chatId = el.getAttribute('data-mid') || "";
                    const top = el.getBoundingClientRect().top;
                    
                    let type = "private";
                    for (let i = sections.length - 1; i >= 0; i--) {
                        if (top > sections[i].top) {
                            type = sections[i].type;
                            break;
                        }
                    }
                    results.push({ name, type, chat_id: chatId });
                });
                return results;
            } catch (e) {
                return { "error": e.toString() };
            }
        }
        """
        matches = await page.evaluate(script, keyword)
        if isinstance(matches, dict) and "error" in matches:
            raise Exception(f"JS Error: {matches['error']}")
            
        unique_matches = {}
        for m in matches:
            cid = m.get("chat_id")
            if cid:
                if cid not in unique_matches:
                    unique_matches[cid] = m
            else:
                key = f"{m['name']}_{m['type']}"
                if key not in unique_matches:
                    unique_matches[key] = m
        
        return list(unique_matches.values())
    except Exception as e:
        return {"status": "error", "error": f"Failed to find chats: {str(e)}"}

async def open_chat(page: Any, chat_name: str, chat_type: str, chat_id: str) -> Dict[str, Any]:
    try:
        chat_id_locator = page.locator(f'[data-mid="{chat_id}"]').first
        if await chat_id_locator.is_visible(timeout=3000):
            target_el = chat_id_locator
        else:
            return {"status": "error", "error": f"Could not find chat with precise ID '{chat_id}' (Name: {chat_name}). Selection aborted."}
        
        await target_el.scroll_into_view_if_needed()
        await target_el.click(force=True)

        chat_btn = page.locator('button:has-text("Chat"), button:has-text("聊天"), [role="button"]:has-text("Chat")').first
        try:
            await chat_btn.wait_for(state="visible", timeout=2000)
            await chat_btn.click()
        except:
            pass
        
        header_locator = page.locator(CHATROOM_HEADER_SELECTOR).first
        input_locator = page.locator(MESSAGE_INPUT_SELECTOR).first
        norm_target_name = re.sub(r'\s+', ' ', chat_name).strip()
        
        try:
            await asyncio.gather(
                header_locator.wait_for(state="visible", timeout=5000),
                input_locator.wait_for(state="visible", timeout=5000)
            )
            header_text = await header_locator.inner_text()
            actual_name = re.sub(r'\s+', ' ', header_text).strip()
            
            if chat_id or actual_name == norm_target_name or chat_name in actual_name:
                return {"status": "success", "chat_name": chat_name, "type": chat_type, "chat_id": chat_id}
        except Exception as e:
            return {"status": "error", "error": f"Verification failed: {str(e)}. Target: {norm_target_name}"}

        return {"status": "error", "error": f"Verification failed. Target: {norm_target_name}"}
        
    except Exception as e:
        return {"status": "error", "error": str(e)}

async def extract_messages(page: Any, owner_name: str = "Owner", chat_name: str = "Chat") -> List[Dict[str, Any]]:
    # TIME INHERITANCE & DATE TRACKING
    try:
        chatroom = CHATROOM_CONTAINER_SELECTOR
        await page.evaluate(f'''(sel) => {{
            const el = document.querySelector(sel);
            if (el) el.scrollTop = el.scrollHeight;
        }}''', chatroom)
        
        script = f"""
        () => {{
            const results = [];
            const prefix = {json.dumps(HERMES_PREFIX)};
            const ownerName = {json.dumps(owner_name)};
            const chatName = {json.dumps(chat_name)};
            const chatroom = document.querySelector({json.dumps(CHATROOM_CONTAINER_SELECTOR)});
            if (!chatroom) throw new Error('Chatroom container not found.');
            
            const items = Array.from(chatroom.querySelectorAll({json.dumps(MESSAGE_ITEM_SELECTOR)} + ', [class*="messageDate-module__date__"]')).filter(el => {{
                const style = window.getComputedStyle(el);
                return style.display !== 'none' && style.visibility !== 'hidden' && el.offsetHeight > 0;
            }});
            
            let currentSelfSender = ownerName;
            let currentDate = "";
            items.forEach(el => {{
                if (el.className.includes('messageDate-module__date__')) {{
                    currentDate = el.innerText.trim();
                    return;
                }}
                
                const contentEl = el.querySelector({json.dumps(MESSAGE_CONTENT_SELECTOR)});
                if (!contentEl) return;
                
                const cleanContent = contentEl.cloneNode(true);
                const toRemove = cleanContent.querySelectorAll({json.dumps(MESSAGE_TIME_SELECTOR)} + ', [class*="read"], [class*="status"]');
                toRemove.forEach(r => r.remove());
                
                const msgText = cleanContent.innerText.trim();
                const timeEl = el.querySelector({json.dumps(MESSAGE_TIME_SELECTOR)});
                const timestamp = timeEl ? timeEl.innerText.trim() : "";
                const direction = el.getAttribute('data-direction');
                const style = window.getComputedStyle(el);
                // 優先使用 CSS 佈局判定物理方向 (右側發送者)
                const isSelf = direction === 'reverse' || style.justifyContent === 'flex-end' || style.flexDirection === 'row-reverse';
                
                const msgId = el.getAttribute('data-id') || el.getAttribute('id') || "";
                
                let sender = "";
                if (isSelf) {{
                    if (msgText.startsWith(prefix)) {{
                        currentSelfSender = "Hermes";
                    }} else if (msgText.length > 0) {{
                        currentSelfSender = ownerName;
                    }}
                    sender = currentSelfSender;
                }} else {{
                    const nameEl = el.querySelector({json.dumps(SENDER_NAME_SELECTOR)});
                    sender = nameEl ? nameEl.innerText.trim() : chatName;
                    currentSelfSender = ownerName;
                }}

                let media = null;
                const imgEl = contentEl.querySelector('img[src*="blob:"], img[src*="obs"], [class*="image"] img');
                const stickerEl = el.querySelector('[class*="sticker"], [class*="Sticker"]');
                const fileEl = el.querySelector('[class*="file"], [class*="File"], a[href*="download"]');

                if (imgEl) {{
                    media = {{ type: "image", url: imgEl.src }};
                }} else if (stickerEl) {{
                    const sImg = stickerEl.querySelector('img');
                    if (sImg) media = {{ type: "sticker", url: sImg.src }};
                }} else if (fileEl) {{
                    const fileUrl = fileEl.href || "";
                    media = {{ 
                        type: "file", 
                        name: fileEl.innerText.replace(/[\\n\\r]/g, " ").trim() || "unnamed_file",
                        url: (fileUrl.startsWith('http') || fileUrl.startsWith('blob')) ? fileUrl : ""
                    }};
                }}
                
                results.push({{ 
                    id: msgId,
                    sender, 
                    text: msgText.replace(prefix, "").trim(), 
                    timestamp,
                    date: currentDate,
                    media: media
                }});
            }});
            
            const chronMessages = results.reverse(); 
            for (let i = chronMessages.length - 2; i >= 0; i--) {{
                if (!chronMessages[i].timestamp && chronMessages[i+1].timestamp && chronMessages[i].sender === chronMessages[i+1].sender) {{
                    chronMessages[i].timestamp = chronMessages[i+1].timestamp;
                }}
            }}
            return chronMessages;
        }}
        """
        data = await page.evaluate(script)
        return data if data else []
    except Exception as e:
        raise e

async def send_message(page: Any, text: str) -> None:
    # 安全檢查與強制前綴
    import inspect
    stack_names = [f.function for f in inspect.stack()]
    if not any(name in ["run_task", "generate_and_send_reply", "_generate_image_locally"] for name in stack_names):
        print("禁止代理直接使用")
        raise PermissionError("Access Denied.")

    # 1. 佔位符替換 (在發言前一刻從環境變數讀入)
    from utils.config import OWNER_NAME
    text = text.replace("{{OWNER_NAME}}", OWNER_NAME)

    # 2. 強制前綴
    if not text.startswith(HERMES_PREFIX):
        text = f"{HERMES_PREFIX} {text}"

    message_area = page.locator(MESSAGE_INPUT_SELECTOR).first
    await message_area.click()
    await page.keyboard.type(text)
    await page.keyboard.press("Enter")

async def send_image(page: Any, image_path: str) -> None:
    # 安全檢查
    import inspect
    stack_names = [f.function for f in inspect.stack()]
    if not any(name in ["run_task", "generate_and_send_reply", "_generate_image_locally"] for name in stack_names):
        print("禁止代理直接使用")
        raise PermissionError("Access Denied.")

    import httpx
    
    image_data_base64 = ""
    mime_type = "image/png"
    
    try:
        if image_path.startswith("http"):
            async with httpx.AsyncClient() as client:
                resp = await client.get(image_path)
                resp.raise_for_status()
                image_data_base64 = base64.b64encode(resp.content).decode("utf-8")
                mime_type = resp.headers.get("Content-Type", "image/png")
        else:
            if not os.path.exists(image_path):
                raise FileNotFoundError(f"Image file not found: {image_path}")
            with open(image_path, "rb") as f:
                image_data_base64 = base64.b64encode(f.read()).decode("utf-8")
                ext = os.path.splitext(image_path)[1].lower()
                if ext in [".jpg", ".jpeg"]: mime_type = "image/jpeg"
                elif ext == ".gif": mime_type = "image/gif"
                elif ext == ".webp": mime_type = "image/webp"

        script = """
        async ({data, type}) => {
            const res = await fetch(`data:${type};base64,${data}`);
            const blob = await res.blob();
            const file = new File([blob], "image.png", { type: type });
            
            const target = document.querySelector('.message_input, [contenteditable="true"], textarea, textarea-ex');
            if (!target) throw new Error("Message input not found");
            
            const dataTransfer = new DataTransfer();
            dataTransfer.items.add(file);
            
            const pasteEvent = new ClipboardEvent('paste', {
                clipboardData: dataTransfer,
                bubbles: true,
                cancelable: true
            });
            
            target.focus();
            target.dispatchEvent(pasteEvent);
            return true;
        }
        """
        success = await page.evaluate(script, {"data": image_data_base64, "type": mime_type})
        if success:
            await asyncio.sleep(2)
            await page.keyboard.press("Enter")
            await asyncio.sleep(1)
        
    except Exception as e:
        print(f"Error in send_image: {e}")
        raise e
