from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
from langchain_core.messages import AIMessage, HumanMessage

from graphs.build_app_agent_v3.agent import create_build_app_agent


@pytest.mark.asyncio
async def test_agent_integration_with_patch_tool() -> None:
    # 1. Prepare Mock Backend as AsyncMock
    mock_backend = AsyncMock()
    mock_backend.als_info.return_value = []  # Needed for SkillsMiddleware

    # Simulate hello.py exists
    mock_file_content = b"def hello():\n    return 0\n"
    mock_backend.adownload_files.return_value = [
        MagicMock(error=None, content=mock_file_content)
    ]
    mock_backend.aupload_files.return_value = [MagicMock(error=None)]

    # 2. Prepare Fake LLM responses
    # First response: call apply_patch tool
    # Second response: provide final answer
    patch_tool_call = {
        "name": "apply_patch",
        "args": {
            "patch": "*** Begin Patch\n*** Update File: hello.py\n<search>\n    return 0\n</search>\n<replace>\n    return 42\n</replace>\n*** End Patch"
        },
        "id": "call_123",
        "type": "tool_call",
    }

    responses = [
        AIMessage(content="I will update the file.", tool_calls=[patch_tool_call]),
        AIMessage(content="Successfully updated hello.py to return 42."),
    ]
    fake_model = FakeMessagesListChatModel(responses=responses)

    # 3. Create Agent with Fake Model
    # We patch the DockerBackend class so that when the middleware instantiates it (if it does)
    # or uses it, it returns/is our mock_backend.
    with patch(
        "graphs.build_app_agent_v3.agent.DockerBackend", return_value=mock_backend
    ) as mock_class:
        # If the middleware uses the class directly (e.g. DockerBackend.als_info), we also need to handle that.
        # But usually, it's passed as an instance or the class is used to call static/class methods.
        # Let's also point the class methods to our mock_backend methods if needed.
        mock_class.als_info = mock_backend.als_info
        mock_class.adownload_files = mock_backend.adownload_files
        mock_class.aupload_files = mock_backend.aupload_files

        agent_executor = create_build_app_agent(model=fake_model)

        # 4. Run Agent
        inputs = {"messages": [HumanMessage(content="Update hello.py to return 42")]}
        result = await agent_executor.ainvoke(inputs)

        # 5. Assertions
        assert "Successfully updated" in result["messages"][-1].content

        # Verify backend was called to download and upload
        assert mock_backend.adownload_files.called
        assert mock_backend.aupload_files.called

        # Verify the content uploaded matches our expectation
        uploaded_args = mock_backend.aupload_files.call_args[0][0]
        path, content = uploaded_args[0]
        assert path == "/workspace/hello.py"
        assert b"return 42" in content


@pytest.mark.asyncio
async def test_agent_integration_error_handling() -> None:
    # Test how agent handles a patch failure (e.g., file missing)
    mock_backend = AsyncMock()
    mock_backend.als_info.return_value = []
    mock_backend.adownload_files.return_value = [
        MagicMock(error="file_not_found", content=None)
    ]

    patch_tool_call = {
        "name": "apply_patch",
        "args": {
            "patch": "*** Begin Patch\n*** Update File: missing.py\n<search>\nold\n</search>\n<replace>\nnew\n</replace>\n*** End Patch"
        },
        "id": "call_err",
        "type": "tool_call",
    }

    responses = [
        AIMessage(content="Trying to patch...", tool_calls=[patch_tool_call]),
        AIMessage(content="It failed as expected."),
    ]
    fake_model = FakeMessagesListChatModel(responses=responses)

    with patch(
        "graphs.build_app_agent_v3.agent.DockerBackend", return_value=mock_backend
    ) as mock_class:
        mock_class.als_info = mock_backend.als_info
        mock_class.adownload_files = mock_backend.adownload_files

        agent_executor = create_build_app_agent(model=fake_model)
        inputs = {"messages": [HumanMessage(content="Patch missing.py")]}
        result = await agent_executor.ainvoke(inputs)

        # Verify tool output message contains the error code
        tool_output_msg = result["messages"][-2]
        assert "PATCH_TARGET_MISSING" in tool_output_msg.content
