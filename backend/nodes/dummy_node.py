"""
Dummy node for testing config parsing.

This node exists solely for testing purposes to verify config parsing
without coupling tests to production nodes that may change.
"""

import time
import asyncio
import os
import logging
from typing import Dict, Any, Optional, Union, Type
from pydantic import BaseModel, Field
from nodes.core.base import WorkflowNode, NodeConfig

logger = logging.getLogger(__name__)


# ============================================================================
# Dummy Node Configuration Models (for testing only)
# ============================================================================

class StringConfig(BaseModel):
    """Config variant that requires a string field"""
    stringValue: str = Field(
        min_length=1,
        title="String Value",
        description="A required string value"
    )
    optionalNumber: int = Field(
        default=42,
        title="Optional Number",
        description="An optional number with default"
    )


class NumberConfig(BaseModel):
    """Config variant that requires a number field"""
    numberValue: float = Field(
        ge=0,
        le=100,
        title="Number Value",
        description="A number between 0 and 100"
    )
    optionalString: str = Field(
        default="default",
        title="Optional String",
        description="An optional string with default"
    )


class BooleanConfig(BaseModel):
    """Config variant that requires a boolean field"""
    booleanValue: bool = Field(
        title="Boolean Value",
        description="A required boolean value"
    )
    metadata: str = Field(
        default="",
        title="Metadata",
        description="Optional metadata"
    )


# Union generates anyOf by default, but we need oneOf for mutual exclusivity
# The base class converts anyOf -> oneOf in get_config_schema()
DummyConfig = Union[StringConfig, NumberConfig, BooleanConfig]


class DummyNodeConfig(NodeConfig[DummyConfig, None]):
    """Full configuration for Dummy node (no credentials needed)"""
    pass


# ============================================================================
# Dummy Node Implementation (for testing only)
# ============================================================================

class DummyNode(WorkflowNode):
    """
    Dummy workflow node for testing config parsing.

    This node is intentionally simple and stable to avoid coupling
    config parsing tests to production nodes that may change.
    """

    @classmethod
    def get_config_model(cls) -> Optional[Union[Type, type]]:
        """Get Pydantic config model for Dummy node"""
        return DummyNodeConfig

    async def execute(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        """
        Execute dummy node (just returns config info).

        Args:
            inputs: Output data from upstream nodes

        Returns:
            Dict containing config info
        """
        logger.info(f"[DummyNode] Executing node {self.node_id}")

        # Get node config - required for this node
        node_config = self.config
        if not node_config:
            raise ValueError(f"[DummyNode] Configuration is required but not provided for node {self.node_id}")

        if not isinstance(node_config, DummyNodeConfig):
            raise ValueError(f"[DummyNode] Invalid config type: {type(node_config)}, expected DummyNodeConfig")

        # Extract the actual config from the NodeConfig wrapper
        config = node_config.config

        # Handle different config types
        output = {
            'type': 'dummy',
            'timestamp': time.time(),
        }

        if isinstance(config, StringConfig):
            logger.info(f"[DummyNode] StringConfig: {config.stringValue}")
            output.update({
                'config_type': 'string',
                'stringValue': config.stringValue,
                'optionalNumber': config.optionalNumber,
            })
        elif isinstance(config, NumberConfig):
            logger.info(f"[DummyNode] NumberConfig: {config.numberValue}")
            output.update({
                'config_type': 'number',
                'numberValue': config.numberValue,
                'optionalString': config.optionalString,
            })
        elif isinstance(config, BooleanConfig):
            logger.info(f"[DummyNode] BooleanConfig: {config.booleanValue}")
            output.update({
                'config_type': 'boolean',
                'booleanValue': config.booleanValue,
                'metadata': config.metadata,
            })
        else:
            raise ValueError(f"Unexpected config type: {type(config)}")

        # Emit output to frontend
        await self.emit(output)

        # Simulate processing time (can be disabled for testing)
        sleep_time = 0.0 if os.getenv('WORKFLOW_TEST_MODE') else 0.5
        if sleep_time > 0:
            await asyncio.sleep(sleep_time)

        return output