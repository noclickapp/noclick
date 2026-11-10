"""FunTranslations Swagger 2.3 translation reads.

Contract: https://funtranslations.com/yaml/funtranslations.yaml
Only the published GET contract is implemented; no mutation or event API exists.
HTML API pages currently describe a different POST/Bearer API.
"""
from __future__ import annotations

from typing import Annotated, Literal, Union

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

NODE_TYPE = "automation-funtranslations"
CREDENTIAL_TYPE = "funtranslations_api_key"
BASE_URL = "https://api.funtranslations.com"
TRANSLATORS = ('yoda', 'pirate', 'shakespeare', 'minion', 'morse', 'morse2english', 'braille', 'sith', 'cheunh', 'gungan', 'mandalorian', 'huttese', 'vulcan', 'klingon', 'sindarin', 'valspeak', 'piglatin', 'dothraki', 'valyrian', 'chef', 'oldenglish', 'us2uk', 'uk2us')
# Exact input texts from the published Swagger response examples, used only for connection reads.
CHECK_TEXT = {'yoda': 'Master Obiwan has lost a planet.', 'pirate': 'Hello sir! my mother goes with me to the ocean.', 'shakespeare': 'You gave Mr. Tim a hearty meal, but unfortunately what he ate made him die.', 'minion': 'Hello, I am hungry!', 'morse': 'Morse code is a dit and dah', 'morse2english': '-- --- .-. ... .     -.-. --- -.. .     .. ...     .-     -.. .. -     .- -. -..     -.. .- .... ', 'braille': 'Fun Translations has something for everyone.', 'sith': 'I went to coruscant which was ten parsec away!', 'cheunh': 'I went to coruscant which was ten parsec away!', 'gungan': 'You came to my home and I said okay!', 'mandalorian': "I'd like a pint of ale", 'huttese': 'Did you see the bounty hunter?', 'vulcan': 'May I say that I have not thoroughly enjoyed serving with humans? I find their illogic and foolish emotions a constant irritant.', 'klingon': 'Who do you work for? They are going to terminate you.', 'sindarin': 'The world is changed; I can feel it in the water, I can feel it in the earth, I can smell it in the air.', 'valspeak': 'Good Morning. Come on man, just saying!', 'piglatin': 'Pig Latin is used in schools to teach language constructs.', 'dothraki': 'Have you seen my lady’s dragon?', 'valyrian': 'I am Daenerys Stormborn of the House Targaryen, of the blood of Old Valyria. Valyrian is my mother tongue.', 'chef': 'Cooking is fun when you do it with a chef', 'oldenglish': 'Mr. Tim ate a hearty meal, but unfortunately what he ate made him die.', 'us2uk': 'He agonized over the aging armored cars.', 'uk2us': 'The artefacts of the behavioural elements cancelled the commercialised monotone.'}

class FunTranslationsAPIKeyCredential(BaseModel):
    model_config = ConfigDict(
        title="FunTranslations API Key", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://funtranslations.com/api",
            "x-credential-instructions": "Paste your FunTranslations API key and choose a translator included in your subscription. Connecting makes one translation request and uses your API quota. This integration uses the published Swagger 2.3 API with the X-Funtranslations-Api-Secret header. A successful read proves reachability, not account ownership; the public free tier may also accept a request.",
        },
    )
    credential_type: Literal["funtranslations_api_key"] = Field("funtranslations_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., title="API key", min_length=1, repr=False, json_schema_extra={"ui:widget": "password"})
    check_translator: Literal['yoda', 'pirate', 'shakespeare', 'minion', 'morse', 'morse2english', 'braille', 'sith', 'cheunh', 'gungan', 'mandalorian', 'huttese', 'vulcan', 'klingon', 'sindarin', 'valspeak', 'piglatin', 'dothraki', 'valyrian', 'chef', 'oldenglish', 'us2uk', 'uk2us'] = Field("yoda", title="Translator for connection check", description="Choose one included in your subscription.")

    @field_validator("api_key", mode="before")
    @classmethod
    def validate_key(cls, value):
        value = clean_secret(value, field_name="API key")
        if not value.isascii() or any(c.isspace() or ord(c) < 33 or ord(c) == 127 for c in value):
            raise ValueError("Paste the API key without a header or whitespace")
        return value


class _TranslationInput(BaseModel):
    text: str = Field(..., min_length=1, title="Text", description="Text to translate; Morse to English expects Morse code.")

    @field_validator("text")
    @classmethod
    def nonblank(cls, value):
        if not value.strip():
            raise ValueError("Enter text to translate")
        return value


class FunTranslationsCheckConnectionConfig(BaseModel):
    """Check the chosen translator using a documented sample; consumes one API call."""
    operation: Literal["check_connection"] = Field("check_connection", json_schema_extra={"ui:hidden": True})


class FunTranslationsYodaConfig(_TranslationInput):
    """Translate from English to Yoda Speak."""
    operation: Literal["translate_yoda"] = Field("translate_yoda", title="Translate: Yoda", json_schema_extra={"ui:hidden": True})


class FunTranslationsPirateConfig(_TranslationInput):
    """Translate from English to Pirate Speak."""
    operation: Literal["translate_pirate"] = Field("translate_pirate", title="Translate: Pirate", json_schema_extra={"ui:hidden": True})


class FunTranslationsShakespeareConfig(_TranslationInput):
    """Translate from English to Shakespeare English."""
    operation: Literal["translate_shakespeare"] = Field("translate_shakespeare", title="Translate: Shakespeare", json_schema_extra={"ui:hidden": True})


class FunTranslationsMinionConfig(_TranslationInput):
    """Translate from English to Minion Speak."""
    operation: Literal["translate_minion"] = Field("translate_minion", title="Translate: Minion", json_schema_extra={"ui:hidden": True})


class FunTranslationsMorseConfig(_TranslationInput):
    """Translate from English to morse code."""
    operation: Literal["translate_morse"] = Field("translate_morse", title="Translate: Morse Code", json_schema_extra={"ui:hidden": True})


class FunTranslationsMorse2EnglishConfig(_TranslationInput):
    """Translate from Morse code to English."""
    operation: Literal["translate_morse2english"] = Field("translate_morse2english", title="Translate: Morse Code to English", json_schema_extra={"ui:hidden": True})


class FunTranslationsBrailleConfig(_TranslationInput):
    """Translate from English to Braille. This is what you use if you have a braille display. This API translates the English text into characters that a braille display understands and you can feed the translated text directly to the display."""
    operation: Literal["translate_braille"] = Field("translate_braille", title="Translate: Braille Display", json_schema_extra={"ui:hidden": True})


class FunTranslationsSithConfig(_TranslationInput):
    """Translate from English to Sith Speak."""
    operation: Literal["translate_sith"] = Field("translate_sith", title="Translate: Sith", json_schema_extra={"ui:hidden": True})


class FunTranslationsCheunhConfig(_TranslationInput):
    """Translate from English to Starwars cheunh."""
    operation: Literal["translate_cheunh"] = Field("translate_cheunh", title="Translate: Cheunh", json_schema_extra={"ui:hidden": True})


class FunTranslationsGunganConfig(_TranslationInput):
    """Translate from English to Starwars Gungan Language."""
    operation: Literal["translate_gungan"] = Field("translate_gungan", title="Translate: Gungan", json_schema_extra={"ui:hidden": True})


class FunTranslationsMandalorianConfig(_TranslationInput):
    """Translate from English to Starwars Mandalorian Language."""
    operation: Literal["translate_mandalorian"] = Field("translate_mandalorian", title="Translate: Mandalorian", json_schema_extra={"ui:hidden": True})


class FunTranslationsHutteseConfig(_TranslationInput):
    """Translate from English to Starwars Huttese Language."""
    operation: Literal["translate_huttese"] = Field("translate_huttese", title="Translate: Huttese", json_schema_extra={"ui:hidden": True})


class FunTranslationsVulcanConfig(_TranslationInput):
    """Translate from English to Startrek Vulcan Language."""
    operation: Literal["translate_vulcan"] = Field("translate_vulcan", title="Translate: Vulcan", json_schema_extra={"ui:hidden": True})


class FunTranslationsKlingonConfig(_TranslationInput):
    """Translate from English to Startrek Klingon Language."""
    operation: Literal["translate_klingon"] = Field("translate_klingon", title="Translate: Klingon", json_schema_extra={"ui:hidden": True})


class FunTranslationsSindarinConfig(_TranslationInput):
    """Translate from English to Elvish Sindarin Language."""
    operation: Literal["translate_sindarin"] = Field("translate_sindarin", title="Translate: Sindarin", json_schema_extra={"ui:hidden": True})


class FunTranslationsValspeakConfig(_TranslationInput):
    """Translate from English to Valley Speak."""
    operation: Literal["translate_valspeak"] = Field("translate_valspeak", title="Translate: Valley Speak", json_schema_extra={"ui:hidden": True})


class FunTranslationsPiglatinConfig(_TranslationInput):
    """Translate from English to Pig Latin."""
    operation: Literal["translate_piglatin"] = Field("translate_piglatin", title="Translate: Pig Latin", json_schema_extra={"ui:hidden": True})


class FunTranslationsDothrakiConfig(_TranslationInput):
    """Translate from English to Dothraki."""
    operation: Literal["translate_dothraki"] = Field("translate_dothraki", title="Translate: Dothraki", json_schema_extra={"ui:hidden": True})


class FunTranslationsValyrianConfig(_TranslationInput):
    """Translate from English to Valyrian."""
    operation: Literal["translate_valyrian"] = Field("translate_valyrian", title="Translate: Valyrian", json_schema_extra={"ui:hidden": True})


class FunTranslationsChefConfig(_TranslationInput):
    """Translate from English to Swedish Chef speak."""
    operation: Literal["translate_chef"] = Field("translate_chef", title="Translate: Swedish Chef", json_schema_extra={"ui:hidden": True})


class FunTranslationsOldenglishConfig(_TranslationInput):
    """Translate from English to Old English."""
    operation: Literal["translate_oldenglish"] = Field("translate_oldenglish", title="Translate: Old English", json_schema_extra={"ui:hidden": True})


class FunTranslationsUs2UkConfig(_TranslationInput):
    """Translate from US English to UK English."""
    operation: Literal["translate_us2uk"] = Field("translate_us2uk", title="Translate: US to UK English", json_schema_extra={"ui:hidden": True})


class FunTranslationsUk2UsConfig(_TranslationInput):
    """Translate from UK English to US English."""
    operation: Literal["translate_uk2us"] = Field("translate_uk2us", title="Translate: UK to US English", json_schema_extra={"ui:hidden": True})


FunTranslationsOperation = Annotated[Union[
    FunTranslationsCheckConnectionConfig,
    FunTranslationsYodaConfig,
    FunTranslationsPirateConfig,
    FunTranslationsShakespeareConfig,
    FunTranslationsMinionConfig,
    FunTranslationsMorseConfig,
    FunTranslationsMorse2EnglishConfig,
    FunTranslationsBrailleConfig,
    FunTranslationsSithConfig,
    FunTranslationsCheunhConfig,
    FunTranslationsGunganConfig,
    FunTranslationsMandalorianConfig,
    FunTranslationsHutteseConfig,
    FunTranslationsVulcanConfig,
    FunTranslationsKlingonConfig,
    FunTranslationsSindarinConfig,
    FunTranslationsValspeakConfig,
    FunTranslationsPiglatinConfig,
    FunTranslationsDothrakiConfig,
    FunTranslationsValyrianConfig,
    FunTranslationsChefConfig,
    FunTranslationsOldenglishConfig,
    FunTranslationsUs2UkConfig,
    FunTranslationsUk2UsConfig
], Field(discriminator="operation")]


class FunTranslationsFullConfig(NodeConfig[FunTranslationsOperation, FunTranslationsAPIKeyCredential]):
    pass


class FunTranslationsNode(WorkflowNode):
    integration_type = "automation-funtranslations"
    connection_evidence = ConnectionEvidence(
        noun="translation service", operation="check_connection", proves="reachability",
    )

    @classmethod
    def get_config_model(cls):
        return FunTranslationsFullConfig

    async def execute(self, inputs):
        config = self.config.config
        credential = self.config.credentials
        if credential is None:
            raise ValueError("Connect a FunTranslations API key")
        translator = credential.check_translator if config.operation == "check_connection" else config.operation.removeprefix("translate_")
        if translator not in TRANSLATORS:
            raise ValueError("Unsupported FunTranslations translator")
        text = CHECK_TEXT[translator] if config.operation == "check_connection" else config.text
        async with guarded_async_client(timeout=30, follow_redirects=False, trust_env=False) as client:
            response = await client.get(
                BASE_URL + "/translate/" + translator,
                params={"text": text},
                headers={"X-Funtranslations-Api-Secret": credential.api_key, "Accept": "application/json"},
            )
        try:
            body = response.json()
        except ValueError:
            raise ValueError("FunTranslations returned a non-JSON response") from None
        if response.status_code >= 300 or isinstance(body, dict) and "error" in body:
            error = body.get("error") if isinstance(body, dict) else None
            message = error.get("message") if isinstance(error, dict) else None
            safe_message = message.replace(credential.api_key, "[redacted]") if isinstance(message, str) else "FunTranslations rejected the request"
            return {"status": "error", "http_status": response.status_code, "error": safe_message}
        if not isinstance(body, dict) or not isinstance(body.get("contents"), dict):
            raise ValueError("FunTranslations response is missing translation contents")
        contents = body["contents"]
        if not isinstance(contents.get("translated"), str) or not isinstance(contents.get("text"), str):
            raise ValueError("FunTranslations response is missing translated or original text")
        translation = contents.get("translation")
        if not isinstance(translation, (str, dict)):
            raise ValueError("FunTranslations response is missing translation metadata")
        output = {"contents": {"translated": contents["translated"], "text": contents["text"], "translation": translation}}
        await self.emit(output)
        return output
