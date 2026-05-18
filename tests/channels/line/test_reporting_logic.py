import pytest
from unittest.mock import MagicMock, patch, AsyncMock
import sys
import os

# Add src to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../src")))

from core.engine import ChatEngine

TEST_KEY_VALUE = "fake-api-key"

class MockResponse:
    def __init__(self, text):
        self.text = text

@pytest.mark.asyncio
async def test_summary_extraction():
    mock_channel = AsyncMock()
    # Mocking Client to avoid real API calls
    with patch("google.genai.Client"), \
         patch("core.history.HistoryManager.write_log"), \
         patch("os.path.exists", return_value=False):
        proxy = ChatEngine(channel=mock_channel, chat_name="test", task="測試彙整", api_key=TEST_KEY_VALUE)
        
        # Test case 1: Successful summary extraction
        res1 = MockResponse('任務完成。[CONVERSATION_ENDED, summary="1. 成功 2. 摘要內容"]')
        with patch.object(proxy.client.models, 'generate_content', return_value=res1):
            await proxy.generate_and_send_reply([])
            assert proxy.state.get("final_report") == '[CONVERSATION_ENDED] 1. 成功 2. 摘要內容'

@pytest.mark.asyncio
async def test_last_summary_overwrites():
    mock_channel = AsyncMock()
    mock_page = MagicMock()
    mock_page.bring_to_front = AsyncMock()
    
    with patch("channels.line.driver.send_message", new_callable=AsyncMock), \
         patch("channels.line.driver.extract_messages", new_callable=AsyncMock, return_value=[]), \
         patch("channels.line.driver.select_chat", new_callable=AsyncMock, return_value={"status": "success"}), \
         patch("google.genai.Client"), \
         patch("core.history.HistoryManager.write_log"), \
         patch("os.path.exists", return_value=False):
         
        proxy = ChatEngine(channel=mock_channel, chat_name="test", task="測試彙整覆蓋", api_key=TEST_KEY_VALUE)
        res1 = MockResponse('再見。[CONVERSATION_ENDED, summary="報告A"]')
        with patch.object(proxy.client.models, 'generate_content', return_value=res1):
            await proxy.generate_and_send_reply([])
            assert proxy.state.get("final_report") == '[CONVERSATION_ENDED] 報告A'
