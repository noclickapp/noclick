"""
Mock Stripe module for testing.

This module prevents actual Stripe API calls during tests.
"""

import sys
from unittest.mock import MagicMock, Mock
import logging

logger = logging.getLogger(__name__)

# Create mock stripe module to prevent actual API calls
mock_stripe = MagicMock()
mock_stripe.api_key = None

# Mock billing module
mock_billing = MagicMock()
mock_meter = Mock()
mock_meter_event = Mock()

# Configure meter mock
mock_meter.list = Mock(return_value=Mock(data=[]))
mock_meter_event.create = Mock(return_value={'id': 'mock_meter_event_123'})

mock_billing.Meter = mock_meter
mock_billing.MeterEvent = mock_meter_event
mock_billing.CreditGrant = Mock()

mock_stripe.billing = mock_billing
mock_stripe.error = Mock()
mock_stripe.error.InvalidRequestError = Exception

# Install mock in sys.modules
sys.modules['stripe'] = mock_stripe

logger.debug("Stripe module mocked for testing")


def get_stripe_meter_event_calls():
    """Get the list of meter event creation calls."""
    return mock_billing.MeterEvent.create.call_args_list


def reset_stripe_mocks():
    """Reset all Stripe mock call history."""
    mock_billing.MeterEvent.create.reset_mock()
    mock_billing.Meter.list.reset_mock()
    logger.debug("Stripe mocks reset")