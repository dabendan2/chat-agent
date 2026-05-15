import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from core.engine import ChatEngine

def test_parse_response_with_image():
    engine = ChatEngine(channel=MagicMock(), chat_name="Test", task="Test Task")
    
    # Case 1: Multiple images
    text = "Here are the pics [IMAGE, /path/1.jpg] [IMAGE, /path/2.jpg] [WAIT_FOR_TARGET_REPLY]"
    res = engine._parse_response(text)
    assert res["text"] == "Here are the pics"
    assert res["images"] == ["/path/1.jpg", "/path/2.jpg"]
    assert res["is_waiting"] is True

    # Case 2: No images
    text = "No images here [WAIT_FOR_TARGET_REPLY]"
    res = engine._parse_response(text)
    assert res["text"] == "No images here"
    assert res["images"] == []
    assert res["is_waiting"] is True

@pytest.mark.asyncio
async def test_generate_and_send_reply_with_image():
    # Mock history
    mock_history = MagicMock()
    mock_history.get_full_context.return_value = ["User: Hello"]
    
    # Create engine with mocked components
    mock_channel = AsyncMock()
    engine = ChatEngine(channel=mock_channel, chat_name="Test", task="Test Task")
    engine.history = mock_history
    engine.client = MagicMock()

    # Mock AI response
    mock_ai_resp = MagicMock()
    mock_ai_resp.text = "Look at this [IMAGE, /tmp/test.jpg] [WAIT_FOR_TARGET_REPLY]"
    engine.client.models.generate_content.return_value = mock_ai_resp

    await engine.generate_and_send_reply([])

    # Verify message sent
    mock_channel.send_message.assert_called_with("Look at this")
    mock_channel.send_image.assert_called_with("/tmp/test.jpg")
    
    # Verify state updated
    assert "Look at this" in engine.state["sent_messages"]
    assert "[IMAGE: /tmp/test.jpg]" in engine.state["sent_messages"]

@pytest.mark.asyncio
async def test_ai_outputs_image_tag_when_asked():
    """Integration test to ensure the AI actually uses the [IMAGE, ...] tag when appropriate."""
    from utils.config import DEFAULT_MODEL
    import os
    api_key = os.environ.get("GOOGLE_API_KEY")
    if not api_key:
        pytest.skip("GOOGLE_API_KEY not found")
        
    mock_channel = AsyncMock()
    engine = ChatEngine(
        channel=mock_channel,
        chat_name="Test",
        task="對方想要看我的工作證截圖，截圖放在 /home/ubuntu/id_card.png，請傳送給他。",
        api_key=api_key
    )
    
    # Force a very simple history
    history = [{"text": "可以給我看你的工作證嗎？", "sender": "User", "timestamp": "12:00"}]
    
    # Mocking history manager to avoid file IO
    engine.history = MagicMock()
    engine.history.get_full_context.return_value = ["[12:00] User: 可以給我看你的工作證嗎？"]
    
    await engine.generate_and_send_reply([])
    
    # Check if any call to send_image was made or if the tag is in sent_messages
    # This is non-deterministic but with gemini-pro it should work
    found_tag = any("[IMAGE: /home/ubuntu/id_card.png]" in msg for msg in engine.state["sent_messages"])
    assert found_tag, f"AI failed to output image tag. Sent: {engine.state['sent_messages']}"
