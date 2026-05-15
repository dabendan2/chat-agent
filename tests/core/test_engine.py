import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from core.engine import ChatEngine
import sys

@pytest.mark.asyncio
async def test_engine_runtime_timeout_logging():
    """
    Verify that when RUNTIME_TIMEOUT is reached,
    the error is logged to history_manager and returned.
    """
    mock_channel = AsyncMock()
    mock_channel.select_chat.return_value = {"status": "success"}
    mock_channel.extract_messages.return_value = [{"text": "m", "sender": "Chat"}]

    with patch("core.history.HistoryManager.write_log") as mock_log, \
         patch("google.genai.Client"), \
         patch("core.engine.POLL_INTERVAL", 0.01), \
         patch("core.engine.RUNTIME_TIMEOUT", 0.1):

        engine = ChatEngine(mock_channel, "test_chat", "test_task", api_key="test_key")
        engine.generate_and_send_reply = AsyncMock()

        report = await engine.run()

        # 1. Check if report is returned correctly
        assert "[SILENT_RESTART_NEEDED]" in report
        assert "保持完全靜默" in report

    # 2. Check if it was logged
    log_calls = [call[0][0] for call in mock_log.call_args_list]
    assert any("[SILENT_RESTART_NEEDED]" in str(msg) for msg in log_calls)

@pytest.mark.asyncio
async def test_run_engine_cli_reports_timeout(capsys):
    """
    Verify that run_engine.py reports the real status
    instead of hardcoded success on timeout.
    """
    from core.run_engine import main

    with patch("core.run_engine.ChatEngine") as mock_engine_class, \
         patch("core.run_engine.PIDLock"), \
         patch("os.environ", {"GOOGLE_API_KEY": "test"}), \
         patch("core.refactorer.TaskRefactorer") as mock_refactorer_class, \
         patch("core.run_engine.async_playwright") as mock_p, \
         patch("core.run_engine.ChannelFactory") as mock_factory, \
         patch("sys.argv", ["run_engine.py", "--chat_name", "test", "--task", "test"]):

        mock_refactorer_class.return_value.refactor.return_value = "test"
        mock_factory.create_instance.return_value = MagicMock()

        # Mock line_utils for the page retrieval logic
        mock_line_utils = MagicMock()
        mock_line_utils.get_line_page = AsyncMock(return_value=MagicMock())
        with patch.dict("sys.modules", {"channels.line": MagicMock(driver=mock_line_utils)}):
            mock_instance = mock_engine_class.return_value
            mock_instance.run = AsyncMock(return_value="[SILENT_RESTART_NEEDED] Runtime limit reached.")

            with pytest.raises(SystemExit) as excinfo:
                await main()

            assert excinfo.value.code == 1

    captured = capsys.readouterr()
    # Now that we removed 'ERROR:' for silent restarts, we check for the tag itself
    assert "[SILENT_RESTART_NEEDED]" in captured.out

@pytest.mark.asyncio
async def test_engine_initial_context_analysis():
    mock_channel = AsyncMock()
    mock_channel.extract_messages.return_value = [{"text": "hello", "sender": "user"}]
    
    with patch("google.genai.Client") as mock_client:
        mock_gen = mock_client.return_value.models.generate_content
        mock_gen.return_value.text = '{"service_target": "test_target", "task_start_time": "[12:00]", "is_started": true}'
        
        engine = ChatEngine(mock_channel, "test_chat", "test_task", api_key="test_key")
        await engine.analyze_context(["line 1"])
        
        assert engine.state["service_target"] == "test_target"
        assert engine.state["task_start_time"] == "[12:00]"
        assert engine.state["is_started"] is True
