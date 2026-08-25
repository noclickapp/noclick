"""
Base class for workflow builders.

This module defines the abstract interface that all workflow builders must implement,
enabling different generation strategies to be used
interchangeably while maintaining a consistent API.
"""

import uuid
import logging
from abc import ABC, abstractmethod
from typing import Dict, Optional, Any, AsyncIterator, Callable

from .schema import BuilderInput, BuilderOutput, BuilderEvent

logger = logging.getLogger(__name__)


class BaseWorkflowBuilder(ABC):
    """
    Abstract base class for workflow builders.

    All workflow builders should inherit from
    this class and implement the abstract methods. This ensures a consistent
    interface for workflow generation regardless of the underlying strategy.

    Each implementation is responsible for its own configuration and can define
    the strategy-specific settings it needs.

    Attributes:
        generation_id: Unique ID for this generation session
        debug_callback: Optional callback for emitting debug events
    """

    def __init__(
        self,
        generation_id: Optional[str] = None,
        debug_callback: Optional[Callable[[Dict[str, Any]], Any]] = None,
    ):
        """
        Initialize the workflow builder.

        Args:
            generation_id: Unique ID for this generation session. Auto-generated if not provided.
            debug_callback: Optional async callback for emitting debug/observability events.
        """
        self.generation_id = generation_id or str(uuid.uuid4())
        self.debug_callback = debug_callback

    @abstractmethod
    async def generate(self, input: BuilderInput) -> AsyncIterator[BuilderEvent]:
        """
        Generate a workflow from the given input.

        This is the main entry point for workflow generation. Implementations
        should yield BuilderEvent objects as generation progresses, enabling
        real-time UI updates.

        Args:
            input: The builder input containing the user's prompt and optional context.

        Yields:
            BuilderEvent objects representing generation progress.

        Example:
            ```python
            builder = SomeWorkflowBuilder()
            async for event in builder.generate(BuilderInput(prompt="...")):
                # Handle event for real-time UI update
                await send_to_frontend(event)
            result = builder.get_result()
            ```
        """
        pass

    @abstractmethod
    def get_result(self) -> BuilderOutput:
        """
        Get the final workflow result after generation completes.

        This should be called after the generate() async iterator is exhausted.
        It returns the complete BuilderOutput with all nodes, edges, and inputs.

        Returns:
            BuilderOutput containing the complete generated workflow.

        Raises:
            RuntimeError: If called before generation is complete.
        """
        pass

    async def _emit_debug(self, event_data: Dict[str, Any]) -> None:
        """
        Emit a debug event if callback is configured.

        This helper method wraps the debug callback with error handling,
        ensuring that debug failures don't crash the generation process.

        Args:
            event_data: Dictionary of debug event data to emit.
        """
        if self.debug_callback:
            try:
                result = self.debug_callback(event_data)
                # Handle both sync and async callbacks
                if hasattr(result, '__await__'):
                    await result
            except Exception as e:
                logger.warning(f"[{self.__class__.__name__}] Debug callback error: {e}")

    def generate_from_prompt(self, prompt: str) -> AsyncIterator[BuilderEvent]:
        """
        Convenience method to generate from a simple prompt string.

        This is a shorthand for:
            builder.generate(BuilderInput(prompt=prompt))

        Args:
            prompt: Natural language description of the desired workflow.

        Returns:
            Async iterator of BuilderEvent objects.
        """
        return self.generate(BuilderInput(prompt=prompt, generation_id=self.generation_id))


