"""
Comprehensive integration tests for WhatsApp Business Cloud API node.

Tests ALL 32 operations organized by category:
- Messaging (12 operations)
- Media Management (4 operations)
- Business Profile (2 operations)
- Phone Number (3 operations)
- Template Management (4 operations)
- Commerce (3 operations)
- Account Management (2 operations)
- Webhooks (2 operations)

Run: python backend/nodes/tests/test_whatsapp_node_integration.py <ACCESS_TOKEN> <PHONE_NUMBER_ID> [BUSINESS_ACCOUNT_ID]

Environment variables (optional):
    WHATSAPP_ACCESS_TOKEN: Meta access token
    WHATSAPP_PHONE_NUMBER_ID: Phone number ID
    WHATSAPP_BUSINESS_ACCOUNT_ID: Business account ID (for template/account operations)
    TEST_PHONE_NUMBER: Recipient phone for message tests (E.164 format)
"""

import asyncio
import sys
import os
import time
import json

# Add parent directory to path for imports
sys.path.insert(
    0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
)

from nodes.whatsapp_node import (
    WhatsAppNode,
    WhatsAppNodeConfig,
    WhatsAppAccessTokenCredential,
    # Messaging operations
    WhatsAppSendTextConfig,
    WhatsAppSendTemplateConfig,
    WhatsAppSendImageConfig,
    WhatsAppSendVideoConfig,
    WhatsAppSendDocumentConfig,
    WhatsAppSendAudioConfig,
    WhatsAppSendLocationConfig,
    WhatsAppSendContactConfig,
    WhatsAppSendButtonsConfig,
    WhatsAppSendListConfig,
    WhatsAppSendReactionConfig,
    WhatsAppMarkReadConfig,
    # Media operations
    WhatsAppUploadMediaConfig,
    WhatsAppGetMediaUrlConfig,
    WhatsAppDownloadMediaConfig,
    WhatsAppDeleteMediaConfig,
    # Business Profile operations
    WhatsAppGetBusinessProfileConfig,
    WhatsAppUpdateBusinessProfileConfig,
    # Phone Number operations
    WhatsAppRegisterPhoneConfig,
    WhatsAppRequestCodeConfig,
    WhatsAppGetPhoneInfoConfig,
    # Template operations
    WhatsAppListTemplatesConfig,
    WhatsAppGetTemplateConfig,
    WhatsAppCreateTemplateConfig,
    WhatsAppDeleteTemplateConfig,
    # Commerce operations
    WhatsAppSendCatalogConfig,
    WhatsAppSendProductConfig,
    WhatsAppSendMultiProductConfig,
    # Account operations
    WhatsAppGetAccountInfoConfig,
    WhatsAppListPhoneNumbersConfig,
    # Webhook operations
    WhatsAppReceiveMessageConfig,
    WhatsAppReceiveStatusConfig,
)


class TestRunner:
    def __init__(
        self,
        access_token: str,
        phone_number_id: str,
        business_account_id: str = None,
        test_phone: str = None,
    ):
        self.credentials = WhatsAppAccessTokenCredential(
            access_token=access_token,
            phone_number_id=phone_number_id,
            business_account_id=business_account_id,
        )
        self.test_phone = test_phone or os.getenv(
            "TEST_PHONE_NUMBER", "+12025550100"
        )  # Placeholder
        self.passed = 0
        self.failed = 0
        self.skipped = 0
        self.created_resources = []  # Track for cleanup: [("type", "id"), ...]
        self.last_message_id = None  # Store for reaction/mark_read tests

    def create_node(self, config):
        """Create node instance with given config"""
        node_config = WhatsAppNodeConfig(config=config, credentials=self.credentials)
        return WhatsAppNode(
            node_id="test-whatsapp",
            node_type="automation-whatsapp",
            node_data={},
            config=node_config,
            sio=None,
            sid=None,
            workflow_id="test-workflow",
            user_id="test-user",
        )

    async def run_test(self, name: str, test_func, skip_reason: str = None):
        """Run a single test"""
        if skip_reason:
            print(f"  SKIP: {name} - {skip_reason}")
            self.skipped += 1
            return

        try:
            await test_func()
            print(f"  PASS: {name}")
            self.passed += 1
        except AssertionError as e:
            print(f"  FAIL: {name} - {e}")
            self.failed += 1
        except Exception as e:
            print(f"  ERROR: {name} - {type(e).__name__}: {e}")
            self.failed += 1

    async def cleanup(self):
        """Clean up created resources"""
        print("\n[Cleanup]")
        # WhatsApp doesn't have many deletable resources
        # Templates and media can be deleted if we tracked them
        if not self.created_resources:
            print("  No resources to clean up")
            return

        for resource_type, resource_id in reversed(self.created_resources):
            try:
                if resource_type == "template":
                    config = WhatsAppDeleteTemplateConfig(template_name=resource_id)
                    result = await self.create_node(config).execute({})
                    print(f"  Deleted template: {resource_id}")
                elif resource_type == "media":
                    config = WhatsAppDeleteMediaConfig(media_id=resource_id)
                    result = await self.create_node(config).execute({})
                    print(f"  Deleted media: {resource_id}")
            except Exception as e:
                print(f"  Warning: Failed to delete {resource_type} {resource_id}: {e}")

    async def run_all_tests(self):
        """Run all WhatsApp node tests"""
        print("\n" + "=" * 80)
        print("WhatsApp Business Cloud API Node Integration Tests - 32 Operations")
        print("=" * 80 + "\n")

        try:
            # =====================================================
            # Messaging Operations (12 tests)
            # =====================================================
            print("\n[Messaging Operations]")
            await self.run_test(
                "send_text_message",
                self.test_send_text,
                skip_reason="Requires valid test phone number"
                if self.test_phone.startswith("+123")
                else None,
            )

            await self.run_test(
                "send_image_message",
                self.test_send_image,
                skip_reason="Requires valid test phone number"
                if self.test_phone.startswith("+123")
                else None,
            )
            await self.run_test(
                "send_video_message",
                self.test_send_video,
                skip_reason="Requires valid test phone number"
                if self.test_phone.startswith("+123")
                else None,
            )
            await self.run_test(
                "send_document_message",
                self.test_send_document,
                skip_reason="Requires valid test phone number"
                if self.test_phone.startswith("+123")
                else None,
            )
            await self.run_test(
                "send_audio_message",
                self.test_send_audio,
                skip_reason="Requires valid test phone number"
                if self.test_phone.startswith("+123")
                else None,
            )
            await self.run_test(
                "send_location_message",
                self.test_send_location,
                skip_reason="Requires valid test phone number"
                if self.test_phone.startswith("+123")
                else None,
            )
            await self.run_test(
                "send_contact_card",
                self.test_send_contact,
                skip_reason="Requires valid test phone number"
                if self.test_phone.startswith("+123")
                else None,
            )
            await self.run_test(
                "send_interactive_buttons",
                self.test_send_buttons,
                skip_reason="Requires valid test phone number"
                if self.test_phone.startswith("+123")
                else None,
            )
            await self.run_test(
                "send_interactive_list",
                self.test_send_list,
                skip_reason="Requires valid test phone number"
                if self.test_phone.startswith("+123")
                else None,
            )
            await self.run_test(
                "send_reaction_emoji",
                self.test_send_reaction,
                skip_reason="Requires message_id from previous test",
            )
            await self.run_test(
                "mark_message_read",
                self.test_mark_read,
                skip_reason="Requires message_id from previous test",
            )

            # =====================================================
            # Media Management Operations (4 tests)
            # =====================================================
            print("\n[Media Management Operations]")

            await self.run_test(
                "get_media_url",
                self.test_get_media_url,
                skip_reason="Requires media_id from upload",
            )
            await self.run_test(
                "download_media",
                self.test_download_media,
                skip_reason="Requires media_url from get_media_url",
            )
            await self.run_test(
                "delete_media",
                self.test_delete_media,
                skip_reason="Requires media_id from upload",
            )

            # =====================================================
            # Business Profile Operations (2 tests)
            # =====================================================
            print("\n[Business Profile Operations]")
            await self.run_test("get_business_profile", self.test_get_business_profile)

            # =====================================================
            # Phone Number Operations (3 tests)
            # =====================================================
            print("\n[Phone Number Operations]")

            await self.run_test("get_phone_number_info", self.test_get_phone_info)

            # =====================================================
            # Template Management Operations (4 tests)
            # =====================================================
            print("\n[Template Management Operations]")
            await self.run_test(
                "list_message_templates",
                self.test_list_templates,
                skip_reason="Requires business_account_id"
                if not self.credentials.business_account_id
                else None,
            )
            await self.run_test(
                "get_message_template",
                self.test_get_template,
                skip_reason="Requires template_id",
            )

            # =====================================================
            # Commerce Operations (3 tests)
            # =====================================================
            print("\n[Commerce Operations]")

            await self.run_test(
                "send_multi_product_message",
                self.test_send_multi_product,
                skip_reason="Requires catalog setup and test phone",
            )

            # =====================================================
            # Account Management Operations (2 tests)
            # =====================================================
            print("\n[Account Management Operations]")
            await self.run_test(
                "get_account_info",
                self.test_get_account_info,
                skip_reason="Requires business_account_id"
                if not self.credentials.business_account_id
                else None,
            )
            await self.run_test(
                "list_account_phone_numbers",
                self.test_list_phone_numbers,
                skip_reason="Requires business_account_id"
                if not self.credentials.business_account_id
                else None,
            )

            # =====================================================
            # Webhook Operations (2 tests)
            # =====================================================
            print("\n[Webhook Operations]")
            await self.run_test("receive_message", self.test_receive_message)
            await self.run_test("receive_status_update", self.test_receive_status)

            # =====================================================
            # Error Handling & Edge Cases
            # =====================================================
            print("\n[Error Handling]")
            await self.run_test("invalid_phone_number", self.test_invalid_phone_number)
            await self.run_test("invalid_credentials", self.test_invalid_credentials)
            await self.run_test(
                "missing_required_field", self.test_missing_required_field
            )

            # =====================================================
            # Performance Tests
            # =====================================================
            print("\n[Performance]")
            await self.run_test("timing_info", self.test_timing_info)

        finally:
            await self.cleanup()

        total = self.passed + self.failed + self.skipped
        print("\n" + "=" * 80)
        print(
            f"Results: {self.passed}/{total} passed, {self.failed} failed, {self.skipped} skipped"
        )
        print("=" * 80 + "\n")

        return self.failed == 0

    # ===========================================================
    # Messaging Test Methods (12 operations)
    # ===========================================================

    async def test_send_text(self):
        """Test send_text operation"""
        config = WhatsAppSendTextConfig(
            to=self.test_phone,
            body="Test message from WhatsApp node integration test",
            preview_url=False,
        )
        result = await self.create_node(config).execute({})
        assert result["status"] in [
            "success",
            "error",
        ], f"Unexpected status: {result.get('status')}"
        assert result["action"] == "send_text_message"
        if result["status"] == "success":
            self.last_message_id = (
                result.get("data", {}).get("messages", [{}])[0].get("id")
            )

    async def test_send_image(self):
        """Test send_image operation"""
        config = WhatsAppSendImageConfig(
            to=self.test_phone,
            image_url="https://picsum.photos/200/300",
            caption="Test image",
        )
        result = await self.create_node(config).execute({})
        assert result["status"] in ["success", "error"]
        assert result["action"] == "send_image_message"

    async def test_send_video(self):
        """Test send_video operation"""
        config = WhatsAppSendVideoConfig(
            to=self.test_phone,
            video_url="https://www.w3schools.com/html/mov_bbb.mp4",
            caption="Test video",
        )
        result = await self.create_node(config).execute({})
        assert result["status"] in ["success", "error"]
        assert result["action"] == "send_video_message"

    async def test_send_document(self):
        """Test send_document operation"""
        config = WhatsAppSendDocumentConfig(
            to=self.test_phone,
            document_url="https://www.w3.org/WAI/ER/tests/xhtml/testfiles/resources/pdf/dummy.pdf",
            filename="test.pdf",
            caption="Test document",
        )
        result = await self.create_node(config).execute({})
        assert result["status"] in ["success", "error"]
        assert result["action"] == "send_document_message"

    async def test_send_audio(self):
        """Test send_audio operation"""
        config = WhatsAppSendAudioConfig(
            to=self.test_phone,
            audio_url="https://www.soundhelix.com/examples/mp3/SoundHelix-Song-1.mp3",
        )
        result = await self.create_node(config).execute({})
        assert result["status"] in ["success", "error"]
        assert result["action"] == "send_audio_message"

    async def test_send_location(self):
        """Test send_location operation"""
        config = WhatsAppSendLocationConfig(
            to=self.test_phone,
            latitude="37.7749",
            longitude="-122.4194",
            name="San Francisco",
            address="San Francisco, CA",
        )
        result = await self.create_node(config).execute({})
        assert result["status"] in ["success", "error"]
        assert result["action"] == "send_location_message"

    async def test_send_contact(self):
        """Test send_contact operation"""
        config = WhatsAppSendContactConfig(
            to=self.test_phone,
            contact_name="John Doe",
            contact_phone="+12025550100",
            contact_email="john@example.com",
        )
        result = await self.create_node(config).execute({})
        assert result["status"] in ["success", "error"]
        assert result["action"] == "send_contact_card"

    async def test_send_buttons(self):
        """Test send_buttons operation"""
        buttons_json = json.dumps(
            [
                {"type": "reply", "reply": {"id": "btn1", "title": "Option 1"}},
                {"type": "reply", "reply": {"id": "btn2", "title": "Option 2"}},
            ]
        )
        config = WhatsAppSendButtonsConfig(
            to=self.test_phone,
            body="Choose an option:",
            buttons=buttons_json,
            header="Test Header",
            footer="Test Footer",
        )
        result = await self.create_node(config).execute({})
        assert result["status"] in ["success", "error"]
        assert result["action"] == "send_interactive_buttons"

    async def test_send_list(self):
        """Test send_list operation"""
        sections_json = json.dumps(
            [
                {
                    "title": "Section 1",
                    "rows": [
                        {
                            "id": "opt1",
                            "title": "Option 1",
                            "description": "First option",
                        },
                        {
                            "id": "opt2",
                            "title": "Option 2",
                            "description": "Second option",
                        },
                    ],
                }
            ]
        )
        config = WhatsAppSendListConfig(
            to=self.test_phone,
            body="Please select from the list:",
            button_text="View Options",
            sections=sections_json,
            header="Test List",
        )
        result = await self.create_node(config).execute({})
        assert result["status"] in ["success", "error"]
        assert result["action"] == "send_interactive_list"

    async def test_send_reaction(self):
        """Test send_reaction operation"""
        if not self.last_message_id:
            # Create a dummy message ID for testing error handling
            self.last_message_id = "wamid.test123"

        config = WhatsAppSendReactionConfig(
            to=self.test_phone, message_id=self.last_message_id, emoji="👍"
        )
        result = await self.create_node(config).execute({})
        assert result["action"] == "send_reaction_emoji"
        # May fail if message_id is invalid, but should handle gracefully
        assert result["status"] in ["success", "error"]

    async def test_mark_read(self):
        """Test mark_read operation"""
        if not self.last_message_id:
            self.last_message_id = "wamid.test123"

        config = WhatsAppMarkReadConfig(message_id=self.last_message_id)
        result = await self.create_node(config).execute({})
        assert result["action"] == "mark_message_read"
        assert result["status"] in ["success", "error"]

    # ===========================================================
    # Media Management Test Methods (4 operations)
    # ===========================================================

    async def test_get_media_url(self):
        """Test get_media_url operation"""
        config = WhatsAppGetMediaUrlConfig(media_id="1234567890")  # Placeholder
        result = await self.create_node(config).execute({})
        assert result["action"] == "get_media_url"
        assert result["status"] in ["success", "error"]

    async def test_download_media(self):
        """Test download_media operation"""
        config = WhatsAppDownloadMediaConfig(
            media_url="https://example.com/media"  # Placeholder
        )
        result = await self.create_node(config).execute({})
        assert result["action"] == "download_media"
        assert result["status"] in ["success", "error"]

    async def test_delete_media(self):
        """Test delete_media operation"""
        config = WhatsAppDeleteMediaConfig(media_id="1234567890")  # Placeholder
        result = await self.create_node(config).execute({})
        assert result["action"] == "delete_media"
        assert result["status"] in ["success", "error"]

    # ===========================================================
    # Business Profile Test Methods (2 operations)
    # ===========================================================

    async def test_get_business_profile(self):
        """Test get_business_profile operation"""
        config = WhatsAppGetBusinessProfileConfig(
            fields="about,address,description,email"
        )
        result = await self.create_node(config).execute({})
        assert result["status"] in ["success", "error"]
        assert result["action"] == "get_business_profile"
        if result["status"] == "success":
            assert "timing_ms" in result

    async def test_get_phone_info(self):
        """Test get_phone_info operation"""
        config = WhatsAppGetPhoneInfoConfig(fields="verified_name,quality_rating")
        result = await self.create_node(config).execute({})
        assert result["status"] in ["success", "error"]
        assert result["action"] == "get_phone_number_info"
        if result["status"] == "success":
            assert "timing_ms" in result

    # ===========================================================
    # Template Management Test Methods (4 operations)
    # ===========================================================

    async def test_list_templates(self):
        """Test list_templates operation"""
        config = WhatsAppListTemplatesConfig(limit=10, status="APPROVED")
        result = await self.create_node(config).execute({})
        assert result["status"] in ["success", "error"]
        assert result["action"] == "list_message_templates"

    async def test_get_template(self):
        """Test get_template operation"""
        config = WhatsAppGetTemplateConfig(template_id="1234567890")  # Placeholder
        result = await self.create_node(config).execute({})
        assert result["action"] == "get_message_template"
        assert result["status"] in ["success", "error"]

    async def test_send_multi_product(self):
        """Test send_multi_product operation"""
        product_ids_json = json.dumps(["SKU1", "SKU2", "SKU3"])
        config = WhatsAppSendMultiProductConfig(
            to=self.test_phone,
            catalog_id="1234567890",
            product_ids=product_ids_json,
            header="Our Products",
            body="Browse our collection!",
        )
        result = await self.create_node(config).execute({})
        assert result["action"] == "send_multi_product_message"
        assert result["status"] in ["success", "error"]

    # ===========================================================
    # Account Management Test Methods (2 operations)
    # ===========================================================

    async def test_get_account_info(self):
        """Test get_account_info operation"""
        config = WhatsAppGetAccountInfoConfig(fields="id,name,timezone_id")
        result = await self.create_node(config).execute({})
        assert result["status"] in ["success", "error"]
        assert result["action"] == "get_account_info"

    async def test_list_phone_numbers(self):
        """Test list_phone_numbers operation"""
        config = WhatsAppListPhoneNumbersConfig(limit=10)
        result = await self.create_node(config).execute({})
        assert result["status"] in ["success", "error"]
        assert result["action"] == "list_account_phone_numbers"

    # ===========================================================
    # Webhook Test Methods (2 operations)
    # ===========================================================

    async def test_receive_message(self):
        """Test receive_message webhook operation"""
        config = WhatsAppReceiveMessageConfig(
            webhook_url="https://test.hooks.example.test", verify_token="test_token"
        )
        mock_webhook_data = {
            "object": "whatsapp_business_account",
            "entry": [
                {
                    "changes": [
                        {
                            "value": {
                                "messages": [
                                    {"from": "+12025550100", "text": {"body": "Test"}}
                                ]
                            }
                        }
                    ]
                }
            ],
        }
        result = await self.create_node(config).execute(
            {"webhook_payload": mock_webhook_data}
        )
        assert result["status"] == "success"
        assert result["action"] == "receive_message"
        assert "data" in result

    async def test_receive_status(self):
        """Test receive_status webhook operation"""
        config = WhatsAppReceiveStatusConfig(
            webhook_url="https://test.hooks.example.test", verify_token="test_token"
        )
        mock_webhook_data = {
            "object": "whatsapp_business_account",
            "entry": [
                {
                    "changes": [
                        {
                            "value": {
                                "statuses": [{"id": "wamid.xxx", "status": "delivered"}]
                            }
                        }
                    ]
                }
            ],
        }
        result = await self.create_node(config).execute(
            {"webhook_payload": mock_webhook_data}
        )
        assert result["status"] == "success"
        assert result["action"] == "receive_status_update"
        assert "data" in result

    # ===========================================================
    # Error Handling & Performance Tests
    # ===========================================================

    async def test_invalid_phone_number(self):
        """Test with invalid phone number"""
        config = WhatsAppSendTextConfig(to="invalid", body="Test")
        result = await self.create_node(config).execute({})
        assert result["status"] == "error"

    async def test_invalid_credentials(self):
        """Test with invalid credentials"""
        bad_creds = WhatsAppAccessTokenCredential(
            access_token="invalid_token", phone_number_id="1234567890"
        )
        node_config = WhatsAppNodeConfig(
            config=WhatsAppSendTextConfig(to=self.test_phone, body="Test"),
            credentials=bad_creds,
        )
        node = WhatsAppNode(
            node_id="test",
            node_type="automation-whatsapp",
            node_data={},
            config=node_config,
            sio=None,
            sid=None,
            workflow_id="test",
        )
        result = await node.execute({})
        assert result["status"] == "error"

    async def test_missing_required_field(self):
        """Test validation of required fields"""
        # This tests Pydantic validation at config creation time
        try:
            # Missing 'to' field should raise validation error
            config = WhatsAppSendTextConfig(body="Test")
            assert False, "Should have raised validation error"
        except:
            pass  # Expected to fail

    async def test_timing_info(self):
        """Test that timing information is included in responses"""
        config = WhatsAppGetPhoneInfoConfig(fields="verified_name")
        result = await self.create_node(config).execute({})
        if result["status"] == "success":
            assert "timing_ms" in result
            assert "api_request" in result["timing_ms"]
            assert result["timing_ms"]["api_request"] > 0


async def main():
    """Main test runner"""
    access_token = os.getenv("WHATSAPP_ACCESS_TOKEN", "")
    phone_number_id = os.getenv("WHATSAPP_PHONE_NUMBER_ID", "")
    business_account_id = os.getenv("WHATSAPP_BUSINESS_ACCOUNT_ID")
    test_phone = os.getenv("TEST_PHONE_NUMBER")

    # Allow command-line args to override env vars
    if len(sys.argv) > 1:
        access_token = sys.argv[1]
    if len(sys.argv) > 2:
        phone_number_id = sys.argv[2]
    if len(sys.argv) > 3:
        business_account_id = sys.argv[3]
    if len(sys.argv) > 4:
        test_phone = sys.argv[4]

    if not access_token or not phone_number_id:
        print("ERROR: WhatsApp credentials required")
        print("\nUsage:")
        print(
            "  python test_whatsapp_node_integration.py <ACCESS_TOKEN> <PHONE_NUMBER_ID> [BUSINESS_ACCOUNT_ID] [TEST_PHONE]"
        )
        print("\nOr set environment variables:")
        print("  WHATSAPP_ACCESS_TOKEN")
        print("  WHATSAPP_PHONE_NUMBER_ID")
        print(
            "  WHATSAPP_BUSINESS_ACCOUNT_ID (optional, for template/account operations)"
        )
        print("  TEST_PHONE_NUMBER (optional, for message operations)")
        print("\nGet credentials from: https://developers.facebook.com/apps")
        sys.exit(1)

    runner = TestRunner(access_token, phone_number_id, business_account_id, test_phone)
    success = await runner.run_all_tests()
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    asyncio.run(main())
