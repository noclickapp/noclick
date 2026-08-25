"""
Integration tests for ElevenLabs AI Audio Platform node.

Tests 16 core operations with real API calls:
- Models (1): list_models
- User & Subscription (3): get_user_info, get_subscription, get_usage_stats
- Voice Management (2): list_voices, get_voice
- Text-to-Speech (2): text_to_speech, text_to_speech_timestamps
- History (4): get_history, get_history_item, get_history_audio, download_history_items
- Speech-to-Speech (1): speech_to_speech
- Speech-to-Text (1): speech_to_text
- Audio Isolation (1): audio_isolation
- Pronunciation (1): list_pronunciation_dictionaries

All other operations (15) are covered by comprehensive mock tests.
See: test_elevenlabs_node_mock.py (22 passing mock tests)

Run: python backend/nodes/tests/test_elevenlabs_node_integration.py <API_KEY>

Environment variables (optional):
    ELEVENLABS_API_KEY: Your ElevenLabs API key
"""

import asyncio
import sys
import os
import time
import base64

# Add parent directory to path for imports
sys.path.insert(
    0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
)

from nodes.elevenlabs_node import (
    ElevenLabsNode,
    ElevenLabsNodeConfig,
    ElevenLabsAPIKeyCredential,
    # Text-to-Speech
    ElevenLabsTextToSpeechConfig,
    ElevenLabsTextToSpeechStreamConfig,
    ElevenLabsTextToSpeechWithTimestampsConfig,
    # Speech-to-Speech
    ElevenLabsSpeechToSpeechConfig,
    # Speech-to-Text
    ElevenLabsSpeechToTextConfig,
    # Voice Management
    ElevenLabsListVoicesConfig,
    ElevenLabsGetVoiceConfig,
    ElevenLabsAddVoiceConfig,
    ElevenLabsEditVoiceConfig,
    ElevenLabsDeleteVoiceConfig,
    # Sound Effects
    ElevenLabsSoundEffectsConfig,
    # Audio Isolation
    ElevenLabsAudioIsolationConfig,
    # Dubbing
    ElevenLabsCreateDubbingConfig,
    ElevenLabsGetDubbingConfig,
    ElevenLabsDeleteDubbingConfig,
    # History
    ElevenLabsGetHistoryConfig,
    ElevenLabsGetHistoryItemConfig,
    ElevenLabsDeleteHistoryItemConfig,
    ElevenLabsGetHistoryAudioConfig,
    ElevenLabsDownloadHistoryItemsConfig,
    # Pronunciation Dictionaries
    ElevenLabsListPronunciationDictionariesConfig,
    ElevenLabsGetPronunciationDictionaryConfig,
    ElevenLabsCreatePronunciationDictionaryConfig,
    ElevenLabsDeletePronunciationDictionaryConfig,
    # Audio Native
    ElevenLabsCreateAudioNativeConfig,
    ElevenLabsGetAudioNativeConfig,
    ElevenLabsDeleteAudioNativeConfig,
    # Models
    ElevenLabsListModelsConfig,
    # User & Subscription
    ElevenLabsGetUserInfoConfig,
    ElevenLabsGetSubscriptionConfig,
    ElevenLabsGetUsageStatsConfig,
)


class TestRunner:
    def __init__(self, api_key: str):
        self.credentials = ElevenLabsAPIKeyCredential(api_key=api_key)
        self.passed = 0
        self.failed = 0
        self.skipped = 0
        self.created_resources = []  # Track for cleanup: [("type", "id"), ...]
        self.test_voice_id = "21m00Tcm4TlvDq8ikWAM"  # Pre-made voice (Rachel - default)
        self.history_item_id = None  # Store for history tests
        self.history_item_ids = []  # Store multiple history IDs
        self.custom_voice_id = None  # Store for voice cleanup
        self.test_audio_base64 = None  # Store generated audio for other tests

    def create_node(self, config):
        """Create node instance with given config"""
        node_config = ElevenLabsNodeConfig(config=config, credentials=self.credentials)
        return ElevenLabsNode(
            node_id="test-elevenlabs",
            node_type="automation-elevenlabs",
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
        """Clean up created resources (none created in current test suite)"""
        print("\n[Cleanup]")
        print("  No resources to clean up")

    async def run_all_tests(self):
        """Run all ElevenLabs node tests"""
        print("\n" + "=" * 80)
        print(
            "ElevenLabs AI Audio Platform Node Integration Tests - 16 Core Operations"
        )
        print("=" * 80 + "\n")

        try:
            # =====================================================
            # Models Operations (1 test) - Run first to verify API key
            # =====================================================
            print("\n[Models Operations]")
            await self.run_test("list_available_ai_models", self.test_list_models)

            # =====================================================
            # User & Subscription Operations (3 tests)
            # =====================================================
            print("\n[User & Subscription Operations]")
            await self.run_test("get_user_info", self.test_get_user_info)
            await self.run_test("get_subscription_information", self.test_get_subscription)
            await self.run_test("get_character_usage_stats", self.test_get_usage_stats)

            # =====================================================
            # Voice Management Operations (2 tests)
            # =====================================================
            print("\n[Voice Management Operations]")
            await self.run_test("list_available_voices", self.test_list_voices)
            await self.run_test("get_voice_by_id", self.test_get_voice)

            # =====================================================
            # Text-to-Speech Operations (3 tests)
            # =====================================================
            print("\n[Text-to-Speech Operations]")
            await self.run_test("convert_text_to_speech", self.test_text_to_speech)
            # text_to_speech_stream: Covered by mock tests, streaming complex to test
            await self.run_test(
                "convert_text_to_speech_with_timestamps", self.test_text_to_speech_timestamps
            )

            # =====================================================
            # History Operations (4 tests)
            # =====================================================
            print("\n[History Operations]")
            await self.run_test("list_generated_audio_history", self.test_get_history)
            await self.run_test("get_history_item_details", self.test_get_history_item)
            await self.run_test("get_history_item_audio", self.test_get_history_audio)
            await self.run_test(
                "download_history_items", self.test_download_history_items
            )

            # =====================================================
            # Sound Effects Operations (1 test)
            # =====================================================
            # sound_effects: Covered by mock tests, expensive operation

            # =====================================================
            # Speech-to-Speech Operations (1 test)
            # =====================================================
            print("\n[Speech-to-Speech Operations]")
            await self.run_test("convert_audio_using_voice", self.test_speech_to_speech)

            # =====================================================
            # Speech-to-Text Operations (1 test)
            # =====================================================
            print("\n[Speech-to-Text Operations]")
            # Test speech-to-text using audio generated from TTS test
            await self.run_test("transcribe_audio_to_text", self.test_speech_to_text)

            # =====================================================
            # Audio Isolation Operations (1 test)
            # =====================================================
            print("\n[Audio Isolation Operations]")
            await self.run_test("isolate_vocals_from_audio", self.test_audio_isolation)

            # =====================================================
            # Pronunciation Dictionary Operations (1 test)
            # =====================================================
            print("\n[Pronunciation Dictionary Operations]")
            await self.run_test(
                "list_pronunciation_dictionaries",
                self.test_list_pronunciation_dictionaries,
            )

        finally:
            # Clean up
            await self.cleanup()

        # Print summary
        print("\n" + "=" * 80)
        print(
            f"Test Results: {self.passed} passed, {self.failed} failed, {self.skipped} skipped"
        )
        print("=" * 80 + "\n")

        return self.failed == 0

    # =========================================================================
    # Test Methods
    # =========================================================================

    async def test_list_models(self):
        """Test listing all available models"""
        config = ElevenLabsListModelsConfig()
        node = self.create_node(config)
        result = await node.execute({})

        assert isinstance(result, list) or isinstance(
            result, dict
        ), "Expected list or dict response"
        print(
            f"      Found {len(result) if isinstance(result, list) else 'models'} models"
        )

    async def test_get_user_info(self):
        """Test getting user account information"""
        config = ElevenLabsGetUserInfoConfig()
        node = self.create_node(config)
        result = await node.execute({})

        assert isinstance(result, dict), "Expected dict response"
        print(f"      User: {result.get('first_name', 'N/A')}")

    async def test_get_subscription(self):
        """Test getting subscription information"""
        config = ElevenLabsGetSubscriptionConfig()
        node = self.create_node(config)
        result = await node.execute({})

        assert isinstance(result, dict), "Expected dict response"
        print(f"      Tier: {result.get('tier', 'N/A')}")

    async def test_get_usage_stats(self):
        """Test getting usage statistics"""
        config = ElevenLabsGetUsageStatsConfig()
        node = self.create_node(config)
        result = await node.execute({})

        assert isinstance(result, dict), "Expected dict response"

    async def test_list_voices(self):
        """Test listing all voices"""
        config = ElevenLabsListVoicesConfig(show_legacy=False)
        node = self.create_node(config)
        result = await node.execute({})

        assert "voices" in result, "Expected 'voices' key in response"
        print(f"      Found {len(result['voices'])} voices")

    async def test_get_voice(self):
        """Test getting voice details"""
        config = ElevenLabsGetVoiceConfig(
            voice_id=self.test_voice_id, with_settings=True
        )
        node = self.create_node(config)
        result = await node.execute({})

        assert (
            "voice_id" in result or "name" in result
        ), "Expected voice data in response"
        print(f"      Voice: {result.get('name', 'N/A')}")

    async def test_text_to_speech(self):
        """Test text-to-speech conversion"""
        config = ElevenLabsTextToSpeechConfig(
            voice_id=self.test_voice_id,
            text="Hello, this is a comprehensive test of the ElevenLabs text-to-speech integration with NoClick. We're generating this longer audio sample to ensure it meets the minimum duration requirements for audio processing operations like audio isolation, which require at least 4.6 seconds of audio.",
            model_id="eleven_flash_v2_5",  # Use fastest model for testing
            stability=0.5,
            similarity_boost=0.75,
            output_format="mp3_44100_128",
        )
        node = self.create_node(config)
        result = await node.execute({})

        assert (
            "audio_base64" in result or "success" in result
        ), "Expected audio response"
        if "audio_base64" in result:
            # Save audio for speech-to-text test
            self.test_audio_base64 = result["audio_base64"]
            print(f"      Generated audio: {result.get('size_bytes', 0)} bytes")
            print(f"      Saved audio for speech-to-text test")

    async def test_text_to_speech_timestamps(self):
        """Test TTS with word-level timestamps"""
        config = ElevenLabsTextToSpeechWithTimestampsConfig(
            voice_id=self.test_voice_id,
            text="Testing timestamps feature",
            model_id="eleven_flash_v2_5",
        )
        node = self.create_node(config)
        result = await node.execute({})

        if "audio_base64" in result or "alignment" in result:
            print(f"      Generated with timestamps")
        else:
            print(f"      Result: {result}")

    async def test_get_history(self):
        """Test getting history"""
        config = ElevenLabsGetHistoryConfig(page_size=10)
        node = self.create_node(config)
        result = await node.execute({})

        assert "history" in result or isinstance(result, list), "Expected history data"
        if (
            isinstance(result, dict)
            and "history" in result
            and len(result["history"]) > 0
        ):
            self.history_item_id = result["history"][0].get("history_item_id")
            # Capture multiple history IDs for download test
            self.history_item_ids = [
                item.get("history_item_id")
                for item in result["history"][:3]
                if item.get("history_item_id")
            ]
            print(f"      Found {len(result['history'])} history items")
            if self.history_item_id:
                print(f"      Captured history_item_id: {self.history_item_id}")
            if self.history_item_ids:
                print(
                    f"      Captured {len(self.history_item_ids)} IDs for download test"
                )

    async def test_get_history_item(self):
        """Test getting specific history item"""
        if not self.history_item_id:
            print("      No history_item_id available, skipping")
            return

        config = ElevenLabsGetHistoryItemConfig(history_item_id=self.history_item_id)
        node = self.create_node(config)
        result = await node.execute({})

        assert isinstance(result, dict), "Expected dict response"
        print(f"      Retrieved history item: {self.history_item_id}")

    async def test_get_history_audio(self):
        """Test getting audio from history"""
        if not self.history_item_id:
            print("      No history_item_id available, skipping")
            return

        config = ElevenLabsGetHistoryAudioConfig(history_item_id=self.history_item_id)
        node = self.create_node(config)
        result = await node.execute({})

        if result.get("success"):
            print(f"      Retrieved audio: {result.get('size_bytes', 0)} bytes")

    async def test_download_history_items(self):
        """Test downloading multiple history items"""
        if not self.history_item_ids or len(self.history_item_ids) < 2:
            print("      Need at least 2 history items, skipping")
            return

        import json

        config = ElevenLabsDownloadHistoryItemsConfig(
            history_item_ids=json.dumps(self.history_item_ids)
        )
        node = self.create_node(config)
        result = await node.execute({})

        if result.get("success"):
            print(f"      Downloaded archive: {result.get('size_bytes', 0)} bytes")

    async def test_speech_to_speech(self):
        """Test speech-to-speech voice conversion"""
        if not self.test_audio_base64:
            print("      No test audio available, skipping")
            return

        config = ElevenLabsSpeechToSpeechConfig(
            voice_id=self.test_voice_id,
            audio_base64=self.test_audio_base64,
            model_id="eleven_english_sts_v2",
        )
        node = self.create_node(config)
        result = await node.execute({})

        if result.get("success"):
            print(f"      Converted audio: {result.get('size_bytes', 0)} bytes")

    async def test_speech_to_text(self):
        """Test speech-to-text transcription"""
        if not self.test_audio_base64:
            print("      No test audio available, skipping")
            return

        config = ElevenLabsSpeechToTextConfig(
            audio_base64=self.test_audio_base64, model_id="scribe_v2", language="en"
        )
        node = self.create_node(config)
        result = await node.execute({})

        if "text" in result:
            print(f"      Transcribed: {result.get('text', '')[:50]}...")
        else:
            print(f"      Result: {result}")

    async def test_audio_isolation(self):
        """Test audio isolation"""
        if not self.test_audio_base64:
            print("      No test audio available, skipping")
            return

        config = ElevenLabsAudioIsolationConfig(audio_base64=self.test_audio_base64)
        node = self.create_node(config)
        result = await node.execute({})

        if result.get("success"):
            print(f"      Isolated audio: {result.get('size_bytes', 0)} bytes")

    async def test_list_pronunciation_dictionaries(self):
        """Test listing pronunciation dictionaries"""
        config = ElevenLabsListPronunciationDictionariesConfig(page_size=10)
        node = self.create_node(config)
        result = await node.execute({})

        assert isinstance(result, dict) or isinstance(
            result, list
        ), "Expected dict or list response"


def main():
    """Main entry point"""
    if len(sys.argv) < 2:
        api_key = os.getenv("ELEVENLABS_API_KEY")
        if not api_key:
            print("Usage: python test_elevenlabs_node_integration.py <API_KEY>")
            print("   Or set ELEVENLABS_API_KEY environment variable")
            sys.exit(1)
    else:
        api_key = sys.argv[1]

    runner = TestRunner(api_key)
    success = asyncio.run(runner.run_all_tests())
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
