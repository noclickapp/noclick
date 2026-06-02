"""Unit tests for trigger_source detection at the webhook entry point."""

from utils.webhook_routes import _webhook_trigger_source


class TestWebhookTriggerSource:
    def test_cron_trigger_node_is_cron(self):
        nodes = [{"id": "t", "type": "trigger-cron"}]
        assert _webhook_trigger_source(nodes, "t") == "cron"

    def test_webhook_trigger_node_is_webhook(self):
        nodes = [{"id": "t", "type": "trigger-webhook"}]
        assert _webhook_trigger_source(nodes, "t") == "webhook"

    def test_no_start_node_is_webhook(self):
        assert _webhook_trigger_source([], None) == "webhook"

    def test_unknown_start_node_is_webhook(self):
        assert _webhook_trigger_source([{"id": "x", "type": "trigger-cron"}], "t") == "webhook"
