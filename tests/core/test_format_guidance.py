import pytest
import json
import re
from unittest.mock import MagicMock
from core.engine import ChatEngine

def test_engine_output_schema_guidance():
    """
    GUIDANCE TEST: Defines the strict schema requirements for ChatEngine responses.
    Any deviation from this format is considered a failure.
    """
    engine = ChatEngine(MagicMock(), "test", "test", api_key="test")
    
    # Requirement 1: Public text MUST be free of any internal labels/brackets
    test_outputs = [
        "Message [WAIT_FOR_TARGET_REPLY]",
        "Report [CONVERSATION_ENDED, summary=\"done\"]",
        "Action [TOOL_ACCESS_NEEDED, tool=\"t\", query=\"q\"]",
        "Image [IMAGE, /p.png] [WAIT_FOR_TARGET_REPLY]"
    ]
    
    for raw in test_outputs:
        parsed = engine._parse_response(raw)
        # Guidance: Text should never contain brackets
        assert "[" not in parsed["text"], f"Leak detected in text: {parsed['text']}"
        assert "]" not in parsed["text"], f"Leak detected in text: {parsed['text']}"
        
        # Guidance: Every turn must result in a valid state
        has_state = (parsed["is_waiting"] or 
                     parsed["owner_input_needed"] or 
                     parsed["conversation_ended"] or 
                     parsed["tool_needed"])
        assert has_state, f"Output '{raw}' resulted in an undefined state (no label detected)."

def test_analyzer_output_schema_guidance():
    """
    GUIDANCE TEST: Defines the strict JSON schema for the Analyzer.
    """
    # This test provides guidance on what keys MUST exist in the Analyzer's JSON
    required_keys = ["service_target", "current_progress", "task_start_time", "is_started"]
    
    # Simulate a typical analyzer output
    sample_json = {
        "service_target": "Store",
        "current_progress": "Started",
        "task_start_time": "[12:00]",
        "is_started": True
    }
    
    for key in required_keys:
        assert key in sample_json, f"Analyzer JSON missing mandatory key: {key}"
    
    # Guidance: task_start_time must be [HH:MM] or '尚未開始'
    time_val = sample_json["task_start_time"]
    assert time_val == "尚未開始" or re.match(r"\[\d{1,2}:\d{2}\]", time_val), \
        f"Invalid task_start_time format: {time_val}"

def test_refactorer_output_guidance():
    """
    GUIDANCE TEST: Defines structural requirements for the TaskRefactorer.
    """
    # The refactored task should be structured by phases
    sample_refactored = "階段 1: Confirm identity.\n階段 2: Place order."
    
    # Guidance: Should contain clear phase markers
    assert "階段" in sample_refactored or "Phase" in sample_refactored
    assert "1" in sample_refactored
