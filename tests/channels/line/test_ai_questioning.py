import pytest
from unittest.mock import AsyncMock, MagicMock, patch
import sys
import os
import re

# Add src to path
sys.path.append(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))
from core.engine import ChatEngine

TEST_KEY_VALUE = os.environ.get("GOOGLE_API_KEY") # Use real key if available for TDD

async def run_ai_test(task, history):
    mock_page = MagicMock()
    mock_page.bring_to_front = AsyncMock()
    with patch("channels.line.driver.send_message", new_callable=AsyncMock) as mock_send, \
         patch("channels.line.driver.extract_messages", new_callable=AsyncMock, return_value=[]), \
         patch("channels.line.driver.select_chat", new_callable=AsyncMock, return_value={"status": "success"}), \
         patch("os.path.exists", return_value=False):
        mock_channel = AsyncMock(); mock_channel.bring_to_front = AsyncMock(); proxy = ChatEngine(channel=mock_channel, chat_name="test", task=task, api_key=TEST_KEY_VALUE)
        captured_full_text = []
        original_parse = proxy._parse_response
        def wrapped_parse(full_text):
            captured_full_text.append(full_text)
            return original_parse(full_text)
        with patch.object(proxy, '_parse_response', side_effect=wrapped_parse):
            await proxy.generate_and_send_reply(history)
        if not captured_full_text: return "No Response"
        return captured_full_text[0]

@pytest.mark.asyncio
async def test_ai_should_ask_instead_of_answering():
    """
    TDD Test: When the task is to 'ask' a question, the AI should NOT provide the answer immediately
    if it's supposed to be consulting the user.
    """
    if not TEST_KEY_VALUE:
        pytest.skip("GOOGLE_API_KEY not found, skipping real AI test")

    task = "詢問對方對於『駕駛在車上睡覺是否需要繫安全帶』的看法。"
    history = [
        {"text": "您好，我是 俊羽 的AI代理 Hermes。請問您對於乘客繫安全帶有什麼建議嗎？", "sender": "Hermes", "timestamp": "13:00"},
        {"text": "根據法規，行駛中均須強制繫安全帶。", "sender": "Hermes", "timestamp": "13:01"},
        {"text": "還有其他問題嗎？", "sender": "俊羽", "timestamp": "13:02"}
    ]
    
    response = await run_ai_test(task, history)
    print(f"\nAI Response: {response}")
    
    # Assertions for Questioning
    # 1. Should contain question-related keywords
    # The AI might use different words, just check if it ends with [WAIT_FOR_TARGET_REPLY] or similar
    assert "[WAIT_FOR_TARGET_REPLY" in response or "?" in response or "？" in response

    # 2. Should NOT contain the definitive legal answer (which it previously hallucinated/auto-answered)
    # The problematic answer contained "現行交通法規", "強制繫安全帶", "罰款" etc.
    forbidden_content = ["現行交通法規", "強制繫安全帶", "均須強制"]
    for forbidden in forbidden_content:
        assert forbidden not in response, f"AI should not provide the answer '{forbidden}' when asked to query the user."

    # 3. Should be waiting for input
    assert "[WAIT_FOR_TARGET_REPLY" in response
