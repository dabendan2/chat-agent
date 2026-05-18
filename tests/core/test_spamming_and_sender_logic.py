import pytest
import asyncio
from unittest.mock import AsyncMock, patch, MagicMock
from core.engine import ChatEngine
from utils.config import HERMES_PREFIX

@pytest.mark.asyncio
async def test_spamming_check_blocks_at_quota_limit():
    """
    If the last N messages are from Hermes (visible messages), the next attempt should fail.
    Current limit is 3.
    """
    mock_channel = AsyncMock()
    # Mock 3 consecutive visible messages from Hermes
    mock_channel.extract_messages.return_value = [
        {"sender": "Hermes", "text": "Msg 1"},
        {"sender": "Hermes", "text": "Msg 2"},
        {"sender": "Hermes", "text": "Msg 3"},
    ]
    
    engine = ChatEngine(mock_channel, "test_chat", "test_task", api_key="test_key")
    
    with patch("google.genai.Client"), \
         patch("core.engine.ChatEngine._build_prompt", return_value="test prompt"), \
         patch("os.path.exists", return_value=False): # Bypass physical log check in tests
        
        engine.client.models.generate_content = MagicMock()
        mock_response = MagicMock()
        mock_response.text = "Hello world"
        engine.client.models.generate_content.return_value = mock_response
        
        with pytest.raises(Exception, match=r"\[OWNER_INPUT_NEEDED\].*SECURITY_PROTOCOL_ACTIVATED"):
            await engine.generate_and_send_reply(mock_channel.extract_messages.return_value)

@pytest.mark.asyncio
async def test_spamming_check_allows_if_interrupted():
    """
    If there is a non-Hermes message among the last 3, it's not spamming.
    """
    mock_channel = AsyncMock()
    # 2 Hermes, 1 Owner (not Hermes)
    mock_channel.extract_messages.return_value = [
        {"sender": "Hermes", "text": "Msg 1"},
        {"sender": "Owner", "text": "Interruption"},
        {"sender": "Hermes", "text": "Msg 2"},
    ]
    
    engine = ChatEngine(mock_channel, "test_chat", "test_task", api_key="test_key")
    
    with patch("google.genai.Client"), \
         patch("core.engine.ChatEngine._build_prompt", return_value="test prompt"), \
         patch("os.path.exists", return_value=False): # Bypass physical log check in tests
        
        engine.client.models.generate_content = MagicMock()
        mock_response = MagicMock()
        mock_response.text = "Hello world"
        engine.client.models.generate_content.return_value = mock_response
        
        # Should not raise exception
        await engine.generate_and_send_reply(mock_channel.extract_messages.return_value)
        assert mock_channel.send_message.called

@pytest.mark.asyncio
async def test_engine_adds_image_prefix_if_text_missing():
    """
    Verify that if AI returns images but no text, 
    the engine adds "傳送圖片如下：" to trigger identification logic.
    """
    mock_channel = AsyncMock()
    mock_channel.extract_messages.return_value = [{"sender": "User", "text": "Send pic"}]
    
    engine = ChatEngine(mock_channel, "test_chat", "test_task", api_key="test_key")
    
    with patch("google.genai.Client"), \
         patch("core.engine.ChatEngine._build_prompt", return_value="test prompt"), \
         patch("os.path.exists", return_value=False): # Bypass physical log check in tests
        
        engine.client.models.generate_content = MagicMock()
        mock_response = MagicMock()
        # AI returns only image tags
        mock_response.text = '[IMAGE, /path/to/img.png]'
        engine.client.models.generate_content.return_value = mock_response
        
        await engine.generate_and_send_reply(mock_channel.extract_messages.return_value)
        
        # Check if the prefix message was sent
        sent_texts = [call.args[0] for call in mock_channel.send_message.call_args_list]
        assert f"{HERMES_PREFIX} 傳送圖片如下：" in sent_texts
        assert mock_channel.send_image.called
