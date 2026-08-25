"""
Mock implementations for LiteLLM components used in testing.

This module provides test-friendly mocks for LiteLLM to avoid actual LLM API calls
during testing while allowing configurable responses.
"""

from typing import Dict, Any, Optional
from unittest.mock import patch, MagicMock
import logging
import os
import threading

logger = logging.getLogger(__name__)

# Global state for configurable responses
_mock_llm_response_queue: list = []
_mock_llm_exception_queue: list = []  # Queue of exceptions to raise
_default_response = "Mock LLM response"
_global_mock_litellm = None  # Global mock instance for inspection
_response_trigger: Optional[threading.Semaphore] = None  # Semaphore for one-by-one response control
_call_started_event: Optional[threading.Event] = None  # Signal when LLM call starts (for test synchronization)


def configure_mock_llm_responses(responses=None, default: str = None, exceptions=None):
    """
    Configure LLM responses for testing.

    Args:
        responses: List of response strings (returned sequentially)
        default: Default response when queue is empty
        exceptions: List of exceptions to raise (checked before responses)

    Returns:
        Mock object that can be used for call verification in tests
    """
    global _mock_llm_response_queue, _mock_llm_exception_queue, _default_response, _global_mock_litellm, _response_trigger, _call_started_event

    _mock_llm_response_queue = responses or []
    _mock_llm_exception_queue = exceptions or []
    _response_trigger = None  # Clear any trigger from previous tests
    _call_started_event = None  # Clear any call_started event from previous tests
    if default:
        _default_response = default
    logger.debug(f"Mock LLM response queue configured: {len(_mock_llm_response_queue)} responses, {len(_mock_llm_exception_queue)} exceptions")

    # If we already have a global mock, reset its state and return it
    if _global_mock_litellm is not None:
        _global_mock_litellm.reset_mock()  # Clear call history
        _global_mock_litellm.captured_envs = []  # Reset captured environments
        _global_mock_litellm.captured_messages = []  # Reset captured messages
        return _global_mock_litellm

    # Stop any existing patcher before starting a new one
    if hasattr(configure_mock_llm_responses, '_patcher'):
        try:
            configure_mock_llm_responses._patcher.stop()
        except:
            pass  # Patcher might already be stopped

    # Create and return a mock object that patches the litellm function
    _global_mock_litellm = MagicMock(side_effect=mock_litellm_completion)
    _global_mock_litellm.captured_envs = []  # Initialize captured_envs list
    _global_mock_litellm.captured_messages = []  # Initialize captured_messages list
    _global_mock_litellm.captured_tools = []  # Initialize captured_tools list for MCP verification

    # Patch both litellm.completion (sync, legacy callers) and
    # litellm.acompletion (async, used by the OpenAI Agents SDK's
    # LitellmModel). The SDK awaits acompletion(stream=True) and then
    # iterates the result with `async for`, so the streaming branch of
    # our mock returns an async iterator wrapping the sync chunk
    # generator.
    patcher = patch('litellm.completion', _global_mock_litellm)
    patcher.start()
    acompletion_patcher = patch('litellm.acompletion', _async_mock_litellm_completion)
    acompletion_patcher.start()

    # Store patchers for cleanup if needed
    configure_mock_llm_responses._patcher = patcher
    configure_mock_llm_responses._patcher_acompletion = acompletion_patcher

    return _global_mock_litellm


def configure_mock_llm_with_trigger(responses, trigger: threading.Semaphore, call_started: Optional[threading.Event] = None):
    """
    Configure LLM responses that wait for an explicit trigger before returning.

    This allows tests to control exactly when the LLM responds, enabling
    precise timing control for testing race conditions.

    Uses a Semaphore to control responses one-by-one. Each LLM call will block
    until trigger.release() is called.

    Usage:
        trigger = threading.Semaphore(0)  # Start with count 0 (all calls block)
        call_started = threading.Event()  # Optional: know when LLM call starts
        mock_llm = configure_mock_llm_with_trigger(["R1", "R2", "R3"], trigger, call_started)

        # Send message - agent blocks at first LLM call
        await send_event(sio, sid, message)

        # Wait for LLM to actually be called
        await asyncio.wait_for(asyncio.to_thread(call_started.wait), timeout=5)

        # Release first response only
        trigger.release()  # Semaphore: 0 → 1 → 0 (acquired by waiting call)
        await asyncio.sleep(0.05)

        # Agent makes second call - blocks again
        call_started.clear()  # Reset for next call
        # ... send another message ...
        await asyncio.wait_for(asyncio.to_thread(call_started.wait), timeout=5)
        trigger.release()  # Release second response

    Args:
        responses: List of response strings (returned sequentially)
        trigger: threading.Semaphore that controls response timing (start with count 0)
        call_started: Optional threading.Event that is set when LLM call starts (for test synchronization)

    Returns:
        Mock object that can be used for call verification in tests
    """
    global _response_trigger, _call_started_event

    # Set trigger BEFORE calling configure_mock_llm_responses (which clears it!)
    _response_trigger = trigger
    _call_started_event = call_started

    # Configure responses
    mock_llm = configure_mock_llm_responses(responses)

    # Re-set trigger and call_started after configure_mock_llm_responses cleared them
    _response_trigger = trigger
    _call_started_event = call_started

    logger.info(f"Mock LLM configured with semaphore trigger - each response blocks until trigger.release()")

    return mock_llm


def mock_tool_call(tool_name: str, tool_args: dict, tool_call_id: str = "test-tool-call-id"):
    """
    Create a tool call response for the mock LLM.

    Args:
        tool_name: Name of the tool to call
        tool_args: Arguments to pass to the tool
        tool_call_id: Unique ID for the tool call (optional)

    Returns:
        Dict in the format expected by mock_litellm_completion for tool calls

    Example:
        >>> force_tool_call("list_database_tables", {})
        {
            'content': '',
            'tool_calls': [{
                'id': 'test-tool-call-id',
                'type': 'function',
                'function': {
                    'name': 'list_database_tables',
                    'arguments': '{}'
                }
            }]
        }
    """
    import json

    return {
        'content': '',
        'tool_calls': [{
            'id': tool_call_id,
            'type': 'function',
            'function': {
                'name': tool_name,
                'arguments': json.dumps(tool_args)
            }
        }]
    }
    
class MockLLMResponse(dict):
    """Hybrid dict/object for litellm compatibility.

    Returns ``None`` for any missing attribute access. LiteLLM's real
    response models (Pydantic) silently return ``None`` for optional
    fields they don't carry — the OpenAI Agents SDK relies on that
    (reading e.g. ``chunk.choices[0].logprobs`` or ``delta.tool_calls``
    on every chunk). Without this fallback every new SDK probe of an
    optional field would surface as ``AttributeError`` in tests.
    """

    def __init__(self, data):
        super().__init__(data)
        for key, value in data.items():
            if isinstance(value, dict):
                setattr(self, key, MockLLMResponse(value))
            elif isinstance(value, list):
                setattr(self, key, [MockLLMResponse(item) if isinstance(item, dict) else item for item in value])
            else:
                setattr(self, key, value)

    def __getattr__(self, name):
        # __getattr__ only fires when normal attribute lookup fails, so
        # explicitly-set attributes (via __init__ above) still win.
        return None


def mock_litellm_completion(*args, **kwargs):
    """Mock litellm completion function with sequential responses."""
    global _mock_llm_response_queue, _mock_llm_exception_queue, _global_mock_litellm, _response_trigger

    # Capture environment variables at the time of the call for test verification
    captured_env = dict(os.environ)

    # Store captured environment in the mock for test verification
    if _global_mock_litellm:
        if not hasattr(_global_mock_litellm, 'captured_envs'):
            _global_mock_litellm.captured_envs = []
        _global_mock_litellm.captured_envs.append(captured_env)

        # Also capture messages for sequence preservation tests
        if not hasattr(_global_mock_litellm, 'captured_messages'):
            _global_mock_litellm.captured_messages = []
        if 'messages' in kwargs:
            _global_mock_litellm.captured_messages.append(kwargs['messages'])

        # Capture tools parameter for MCP testing
        if not hasattr(_global_mock_litellm, 'captured_tools'):
            _global_mock_litellm.captured_tools = []
        if 'tools' in kwargs:
            _global_mock_litellm.captured_tools.append(kwargs['tools'])
        else:
            logger.info(f"MOCK LITELLM: No 'tools' parameter in kwargs")

    # Signal that the call has started (for test synchronization)
    if _call_started_event is not None:
        logger.info(f"Mock LLM setting call_started event (id={id(_call_started_event)})")
        _call_started_event.set()
        logger.info(f"Mock LLM set call_started event, is_set={_call_started_event.is_set()}")

    # If trigger is configured, wait for explicit release before proceeding
    if _response_trigger is not None:
        logger.info("Mock LLM waiting for trigger.release()...")
        acquired = _response_trigger.acquire(timeout=1)  # 1s timeout to prevent hanging tests
        if not acquired:
            logger.error("Mock LLM trigger timeout after 1s!")
            raise TimeoutError("Mock LLM trigger was not released within 1 seconds")
        logger.info("Mock LLM trigger acquired, proceeding with response")

    # Check for exceptions first (checked before responses)
    if _mock_llm_exception_queue:
        exception = _mock_llm_exception_queue.pop(0)
        logger.debug(f"Raising queued exception: {type(exception).__name__}, {len(_mock_llm_exception_queue)} exceptions remaining")
        raise exception

    # Get the next response from the queue
    if _mock_llm_response_queue:
        response_content = _mock_llm_response_queue.pop(0)
        if isinstance(response_content, list):
            logger.debug(f"Using queued structured response with {len(response_content)} items, {len(_mock_llm_response_queue)} remaining")
        else:
            logger.debug(f"Using queued text response: '{str(response_content)[:50]}...', {len(_mock_llm_response_queue)} remaining")
    else:
        response_content = _default_response
        logger.debug(f"Queue empty, using default response: '{str(response_content)[:50]}...'")

    # Calculate token count based on content type
    if isinstance(response_content, list):
        # For structured content, estimate tokens from text items
        token_count = 5  # Base tokens
        for item in response_content:
            if isinstance(item, dict) and item.get('type') == 'text':
                text = item.get('text', '')
                token_count += len(text.split()) if text else 1
    elif isinstance(response_content, str):
        token_count = len(response_content.split()) if response_content else 5
    else:
        token_count = 5

    # Handle streaming vs non-streaming
    if kwargs.get('stream', False):
        # Return a generator for streaming
        return _create_streaming_chunks(response_content, kwargs.get('model', 'gpt-4o'))

    # Create mock response in litellm format (non-streaming)
    # Check for special response formats
    if isinstance(response_content, dict) and 'tool_calls' in response_content:
        # Tool call response format
        message_dict = {
            'content': response_content.get('content', ''),
            'role': 'assistant',
            'tool_calls': response_content['tool_calls']
        }
    elif isinstance(response_content, dict) and 'provider_specific_fields' in response_content:
        # Special format to simulate provider-specific image responses
        message_dict = {
            'content': response_content.get('content', ''),
            'role': 'assistant',
            'provider_specific_fields': response_content['provider_specific_fields']
        }
    else:
        # Standard response format
        message_dict = {
            'content': response_content,  # Can be string or list
            'role': 'assistant'
        }

    # Determine finish_reason based on response type
    finish_reason = 'tool_calls' if 'tool_calls' in message_dict else 'stop'

    mock_response = MockLLMResponse({
        'choices': [{
            'message': message_dict,
            'finish_reason': finish_reason
        }],
        'usage': {
            'prompt_tokens': 10,  # Fixed values for testing
            'completion_tokens': token_count,
            'total_tokens': 10 + token_count
        },
        'model': kwargs.get('model', 'gpt-4o'),  # Use the model from kwargs if provided
        'id': 'mock-response',
        '_hidden_params': {
            'response_cost': 0.01  # Mock cost for testing (1 cent)
        }
    })
    
    return mock_response


async def _async_mock_litellm_completion(*args, **kwargs):
    """Async wrapper around ``mock_litellm_completion``.

    The OpenAI Agents SDK's LitellmModel calls
    ``await litellm.acompletion(stream=True, ...)`` and then iterates the
    returned stream with ``async for``. The legacy ``litellm.completion``
    mock returns a sync generator for streaming and a dict for non-streaming;
    we keep all that logic by delegating, then wrap the result so it
    satisfies the SDK's async-iterator expectation.

    Two paths:
      - ``stream=True``: wrap the sync chunk generator in an ``async for``-
        compatible iterator. ``__anext__`` yields one chunk per call until
        StopAsyncIteration.
      - ``stream=False``: return the dict directly (already an awaitable
        result via the surrounding ``async def`` so the caller's
        ``await`` just unwraps it).
    """
    result = mock_litellm_completion(*args, **kwargs)
    if not kwargs.get("stream", False):
        return result

    # Streaming path: result is a sync generator yielding MockLLMResponse
    # chunks. Wrap it.
    class _AsyncStreamWrapper:
        def __init__(self, sync_gen):
            self._gen = sync_gen

        def __aiter__(self):
            return self

        async def __anext__(self):
            try:
                return next(self._gen)
            except StopIteration:
                raise StopAsyncIteration

    return _AsyncStreamWrapper(result)


def _create_streaming_chunks(content: str, model: str):
    """
    Create streaming chunks that simulate litellm streaming response.

    Splits content into character-level chunks to simulate progressive streaming.
    Includes realistic delays between chunks to test real-time emission.
    """
    import time

    if isinstance(content, str):
        # Split into chunks (simulate character-by-character streaming)
        chunk_size = 5  # Characters per chunk
        for i in range(0, len(content), chunk_size):
            chunk_text = content[i:i+chunk_size]
            is_final = (i + chunk_size >= len(content))

            # Add delay between chunks to simulate realistic streaming (50ms)
            # This helps test that callbacks execute in real-time, not batched at end
            if i > 0:  # Don't delay before first chunk
                time.sleep(0.05)

            yield MockLLMResponse({
                'id': 'mock-stream-chunk',
                'object': 'chat.completion.chunk',
                'choices': [{
                    'delta': {
                        'content': chunk_text,
                        'role': 'assistant' if i == 0 else None  # Role only in first chunk
                    },
                    'finish_reason': 'stop' if is_final else None,
                    'index': 0,
                    'logprobs': None,
                }],
                'model': model,
                'created': 1234567890,
                '_hidden_params': {
                    'created_at': 1234567890
                }
            })
    else:
        # For non-string content, return as single chunk
        yield MockLLMResponse({
            'id': 'mock-stream-chunk',
            'object': 'chat.completion.chunk',
            'choices': [{
                'delta': {
                    'content': str(content),
                    'role': 'assistant'
                },
                'finish_reason': 'stop',
                'index': 0,
                'logprobs': None,
            }],
            'model': model,
            'created': 1234567890,
            '_hidden_params': {
                'created_at': 1234567890
            }
        })


def patch_litellm_components():
    """
    Patch LiteLLM components with test-friendly mocks.
    
    Call this function in test setup to replace LiteLLM calls with mocks
    that don't require actual API calls.
    """
    global _global_mock_litellm
    
    # Always re-apply patch to ensure it's active
    # (tests might have stopped it)
    
    # Stop any existing patcher before starting a new one
    if hasattr(patch_litellm_components, '_patcher'):
        try:
            patch_litellm_components._patcher.stop()
        except:
            pass  # Patcher might already be stopped
    
    # Create the global mock if not exists
    _global_mock_litellm = MagicMock(side_effect=mock_litellm_completion)
    
    # Patch both litellm.completion and litellm.acompletion (the async
    # variant the OpenAI Agents SDK's LitellmModel uses for streaming).
    patcher = patch('litellm.completion', _global_mock_litellm)
    patcher.start()
    acompletion_patcher = patch('litellm.acompletion', _async_mock_litellm_completion)
    acompletion_patcher.start()

    # Store patcher reference for potential cleanup
    patch_litellm_components._patcher = patcher
    patch_litellm_components._patcher_acompletion = acompletion_patcher
    
    logger.info("LiteLLM components patched for testing")


def cleanup_litellm_mocks():
    """
    Stop all active LiteLLM patches.
    
    Call this in test teardown to ensure patches are cleaned up properly.
    """
    # Clean up configure_mock_llm_responses patcher
    if hasattr(configure_mock_llm_responses, '_patcher'):
        try:
            configure_mock_llm_responses._patcher.stop()
            del configure_mock_llm_responses._patcher
        except:
            pass
    if hasattr(configure_mock_llm_responses, '_patcher_acompletion'):
        try:
            configure_mock_llm_responses._patcher_acompletion.stop()
            del configure_mock_llm_responses._patcher_acompletion
        except:
            pass
    # Clean up patch_litellm_components patcher
    if hasattr(patch_litellm_components, '_patcher'):
        try:
            patch_litellm_components._patcher.stop()
            del patch_litellm_components._patcher
        except:
            pass
    
    # Reset global state
    global _mock_llm_response_queue, _mock_llm_exception_queue, _default_response, _global_mock_litellm, _response_trigger, _call_started_event
    _mock_llm_response_queue = []
    _mock_llm_exception_queue = []
    _default_response = "Mock LLM response"
    _global_mock_litellm = None
    _response_trigger = None
    _call_started_event = None

    logger.debug("LiteLLM mocks cleaned up")