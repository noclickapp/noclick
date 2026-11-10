"""Wordnik v4 dictionary reads, pinned to the provider's published OpenAPI 4.0.

Wordnik publishes no mutation or webhook API, and its lists cannot filter or
order by creation/update time. Connection evidence proves key reachability.
"""
from __future__ import annotations

from typing import Annotated, Literal, Union
from urllib.parse import quote

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

BASE_URL = "https://api.wordnik.com/v4"


class WordnikAPIKeyCredential(BaseModel):
    model_config = ConfigDict(title="Wordnik API Key", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://developer.wordnik.com/",
            "x-credential-instructions": "Paste your Wordnik API key from the developer portal. NoClick checks it by reading the word of the day; this proves API reachability, not account identity.",
        })
    credential_type: Literal["wordnik_api_key"] = Field("wordnik_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., title="API Key", min_length=1, max_length=4096, repr=False,
        json_schema_extra={"ui:widget": "password"})

    @field_validator("api_key", mode="before")
    @classmethod
    def validate_key(cls, value):
        value = clean_secret(value, field_name="API key")
        if any(c.isspace() for c in value):
            raise ValueError("Paste the API key without whitespace")
        return value


class _Operation(BaseModel):
    model_config = ConfigDict(extra="forbid")


class WordnikGetDefinitionsConfig(_Operation):
    """Return definitions for a word."""
    operation: Literal['get_definitions'] = Field('get_definitions', title='Get Definitions', json_schema_extra={"ui:hidden": True})
    word: str = Field(..., description='Word to return definitions for', min_length=1)
    limit: int = Field(200, description='Maximum number of results to return')
    part_of_speech: Literal['noun', 'adjective', 'verb', 'adverb', 'interjection', 'pronoun', 'preposition', 'abbreviation', 'affix', 'article', 'auxiliary-verb', 'conjunction', 'definite-article', 'family-name', 'given-name', 'idiom', 'imperative', 'noun-plural', 'noun-posessive', 'past-participle', 'phrasal-prefix', 'proper-noun', 'proper-noun-plural', 'proper-noun-posessive', 'suffix', 'verb-intransitive', 'verb-transitive'] | None = Field(None, description='CSV list of part-of-speech types')
    include_related: Literal["false", "true"] = Field('false', description='Return related words with definitions')
    source_dictionaries: list[Literal['all', 'ahd-5', 'century', 'wiktionary', 'webster', 'wordnet']] | None = Field(None, description="Source dictionary to return definitions from.  If 'all' is received, results are returned from all sources. If multiple values are received (e.g. 'century,wiktionary'), results are returned from the first specified dictionary that has definitions. If left blank, results are returned from the first dictionary that has definitions. By default, dictionaries are searched in this order: ahd-5, wiktionary, webster, century, wordnet")
    use_canonical: Literal['false', 'true'] = Field('false', description="If true will try to return the correct word root ('cats' -> 'cat'). If false returns exactly what was requested.")
    include_tags: Literal['false', 'true'] = Field('false', description='Return a closed set of XML tags in response')

class WordnikGetExamplesConfig(_Operation):
    """Returns examples for a word."""
    operation: Literal['get_examples'] = Field('get_examples', title='Get Examples', json_schema_extra={"ui:hidden": True})
    word: str = Field(..., description='Word to return examples for', min_length=1)
    include_duplicates: Literal['false', 'true'] = Field('false', description='Show duplicate examples from different sources')
    use_canonical: Literal['false', 'true'] = Field('false', description="If true will try to return the correct word root ('cats' -> 'cat'). If false returns exactly what was requested.")
    skip: int = Field(0, description='Results to skip')
    limit: int = Field(5, description='Maximum number of results to return')

class WordnikGetRelatedWordsConfig(_Operation):
    """Given a word as a string, returns relationships from the Word Graph."""
    operation: Literal['get_related_words'] = Field('get_related_words', title='Get Related Words', json_schema_extra={"ui:hidden": True})
    word: str = Field(..., description='Word to fetch relationships for', min_length=1)
    use_canonical: Literal['false', 'true'] = Field('false', description="If true will try to return the correct word root ('cats' -> 'cat'). If false returns exactly what was requested.")
    relationship_types: Literal['synonym', 'antonym', 'variant', 'equivalent', 'cross-reference', 'related-word', 'rhyme', 'form', 'etymologically-related-term', 'hypernym', 'hyponym', 'inflected-form', 'primary', 'same-context', 'verb-form', 'verb-stem', 'has_topic'] | None = Field(None, description='Limits the total results per type of relationship type')
    limit_per_relationship_type: int = Field(10, description='Restrict to the supplied relationship types')

class WordnikGetWordOfTheDayConfig(_Operation):
    """Returns a specific WordOfTheDay."""
    operation: Literal['get_word_of_the_day'] = Field('get_word_of_the_day', title='Get Word Of The Day', json_schema_extra={"ui:hidden": True})
    date: str | None = Field(None, description='Fetches by date in yyyy-MM-dd')

class WordnikSearchWordsConfig(_Operation):
    """Searches words."""
    operation: Literal['search_words'] = Field('search_words', title='Search Words', json_schema_extra={"ui:hidden": True})
    allow_regex: Literal["false", "true"] = Field('false', description='Search term is a Regular Expression')
    query: str = Field(..., description='Search query', min_length=1)
    case_sensitive: Literal["false", "true"] = Field('true', description='Search case sensitive')
    include_part_of_speech: str | None = Field(None, description='Only include these comma-delimited parts of speech (allowable values are noun, adjective, verb, adverb, interjection, pronoun, preposition, abbreviation, affix, article, auxiliary-verb, conjunction, definite-article, family-name, given-name, idiom, imperative, noun-plural, noun-posessive, past-participle, phrasal-prefix, proper-noun, proper-noun-plural, proper-noun-posessive, suffix, verb-intransitive, verb-transitive)')
    exclude_part_of_speech: str | None = Field(None, description='Exclude these comma-delimited parts of speech (allowable values are noun, adjective, verb, adverb, interjection, pronoun, preposition, abbreviation, affix, article, auxiliary-verb, conjunction, definite-article, family-name, given-name, idiom, imperative, noun-plural, noun-posessive, past-participle, phrasal-prefix, proper-noun, proper-noun-plural, proper-noun-posessive, suffix, verb-intransitive, verb-transitive)')
    min_corpus_count: int = Field(5, description='Minimum corpus frequency for terms')
    max_corpus_count: int = Field(-1, description='Maximum corpus frequency for terms')
    min_dictionary_count: int = Field(1, description='Minimum number of dictionary entries for words returned')
    max_dictionary_count: int = Field(-1, description='Maximum dictionary definition count')
    min_length: int = Field(1, description='Minimum word length')
    max_length: int = Field(-1, description='Maximum word length')
    skip: int = Field(0, description='Results to skip')
    limit: int = Field(10, description='Maximum number of results to return')

class WordnikReverseDictionaryConfig(_Operation):
    """Reverse dictionary search."""
    operation: Literal['reverse_dictionary'] = Field('reverse_dictionary', title='Reverse Dictionary', json_schema_extra={"ui:hidden": True})
    query: str = Field(..., description='Search term', min_length=1)
    find_sense_for_word: str | None = Field(None, description='Restricts words and finds closest sense')
    include_source_dictionaries: Literal['ahd-5', 'century', 'cmu', 'macmillan', 'wiktionary', 'webster', 'wordnet'] | None = Field(None, description='Only include these comma-delimited source dictionaries')
    exclude_source_dictionaries: Literal['ahd-5', 'century', 'cmu', 'macmillan', 'wiktionary', 'webster', 'wordnet'] | None = Field(None, description='Exclude these comma-delimited source dictionaries')
    include_part_of_speech: str | None = Field(None, description='Only include these comma-delimited parts of speech (allowable values are noun, adjective, verb, adverb, interjection, pronoun, preposition, abbreviation, affix, article, auxiliary-verb, conjunction, definite-article, family-name, given-name, idiom, imperative, noun-plural, noun-posessive, past-participle, phrasal-prefix, proper-noun, proper-noun-plural, proper-noun-posessive, suffix, verb-intransitive, verb-transitive)')
    exclude_part_of_speech: str | None = Field(None, description='Exclude these comma-delimited parts of speech (allowable values are noun, adjective, verb, adverb, interjection, pronoun, preposition, abbreviation, affix, article, auxiliary-verb, conjunction, definite-article, family-name, given-name, idiom, imperative, noun-plural, noun-posessive, past-participle, phrasal-prefix, proper-noun, proper-noun-plural, proper-noun-posessive, suffix, verb-intransitive, verb-transitive)')
    min_corpus_count: int = Field(5, description='Minimum corpus frequency for terms')
    max_corpus_count: int = Field(-1, description='Maximum corpus frequency for terms')
    min_length: int = Field(1, description='Minimum word length')
    max_length: int = Field(-1, description='Maximum word length')
    expand_terms: str | None = Field(None, description='Expand terms')
    include_tags: Literal['false', 'true'] = Field('false', description='Return a closed set of XML tags in response')
    sort_by: Literal['alpha', 'count'] | None = Field(None, description='Attribute to sort by')
    sort_order: Literal['asc', 'desc'] | None = Field(None, description='Sort direction')
    skip: str = Field('0', description='Results to skip')
    limit: int = Field(10, description='Maximum number of results to return')

class WordnikGetRandomWordConfig(_Operation):
    """Returns a single random WordObject."""
    operation: Literal['get_random_word'] = Field('get_random_word', title='Get Random Word', json_schema_extra={"ui:hidden": True})
    has_dictionary_def: Literal["false", "true"] = Field('true', description='Only return words with dictionary definitions')
    include_part_of_speech: str | None = Field(None, description='CSV part-of-speech values to include (allowable values are noun, adjective, verb, adverb, interjection, pronoun, preposition, abbreviation, affix, article, auxiliary-verb, conjunction, definite-article, family-name, given-name, idiom, imperative, noun-plural, noun-posessive, past-participle, phrasal-prefix, proper-noun, proper-noun-plural, proper-noun-posessive, suffix, verb-intransitive, verb-transitive)')
    exclude_part_of_speech: str | None = Field(None, description='CSV part-of-speech values to exclude (allowable values are noun, adjective, verb, adverb, interjection, pronoun, preposition, abbreviation, affix, article, auxiliary-verb, conjunction, definite-article, family-name, given-name, idiom, imperative, noun-plural, noun-posessive, past-participle, phrasal-prefix, proper-noun, proper-noun-plural, proper-noun-posessive, suffix, verb-intransitive, verb-transitive)')
    min_corpus_count: int = Field(0, description='Minimum corpus frequency for terms')
    max_corpus_count: int = Field(-1, description='Maximum corpus frequency for terms')
    min_dictionary_count: int = Field(1, description='Minimum dictionary count')
    max_dictionary_count: int = Field(-1, description='Maximum dictionary count')
    min_length: int = Field(5, description='Minimum word length')
    max_length: int = Field(-1, description='Maximum word length')

class WordnikGetRandomWordsConfig(_Operation):
    """Returns an array of random WordObjects."""
    operation: Literal['get_random_words'] = Field('get_random_words', title='Get Random Words', json_schema_extra={"ui:hidden": True})
    has_dictionary_def: Literal["false", "true"] = Field('true', description='Only return words with dictionary definitions')
    include_part_of_speech: str | None = Field(None, description='CSV part-of-speech values to include (allowable values are noun, adjective, verb, adverb, interjection, pronoun, preposition, abbreviation, affix, article, auxiliary-verb, conjunction, definite-article, family-name, given-name, idiom, imperative, noun-plural, noun-posessive, past-participle, phrasal-prefix, proper-noun, proper-noun-plural, proper-noun-posessive, suffix, verb-intransitive, verb-transitive)')
    exclude_part_of_speech: str | None = Field(None, description='CSV part-of-speech values to exclude (allowable values are noun, adjective, verb, adverb, interjection, pronoun, preposition, abbreviation, affix, article, auxiliary-verb, conjunction, definite-article, family-name, given-name, idiom, imperative, noun-plural, noun-posessive, past-participle, phrasal-prefix, proper-noun, proper-noun-plural, proper-noun-posessive, suffix, verb-intransitive, verb-transitive)')
    min_corpus_count: int = Field(0, description='Minimum corpus frequency for terms')
    max_corpus_count: int = Field(-1, description='Maximum corpus frequency for terms')
    min_dictionary_count: int = Field(1, description='Minimum dictionary count')
    max_dictionary_count: int = Field(-1, description='Maximum dictionary count')
    min_length: int = Field(5, description='Minimum word length')
    max_length: int = Field(-1, description='Maximum word length')
    sort_by: Literal['alpha', 'count'] | None = Field(None, description='Attribute to sort by')
    sort_order: Literal['asc', 'desc'] | None = Field(None, description='Sort direction')
    limit: int = Field(10, description='Maximum number of results to return')

class WordnikGetTextPronunciationsConfig(_Operation):
    """Returns text pronunciations for a given word."""
    operation: Literal['get_text_pronunciations'] = Field('get_text_pronunciations', title='Get Text Pronunciations', json_schema_extra={"ui:hidden": True})
    word: str = Field(..., description='Word to get pronunciations for', min_length=1)
    use_canonical: Literal['false', 'true'] = Field('false', description="If true will try to return a correct word root ('cats' -> 'cat'). If false returns exactly what was requested.")
    source_dictionary: Literal['ahd-5', 'century', 'cmu', 'macmillan', 'wiktionary', 'webster', 'wordnet'] | None = Field(None, description='Get from a single dictionary')
    type_format: Literal['ahd-5', 'arpabet', 'gcide-diacritical', 'IPA'] | None = Field(None, description='Text pronunciation type')
    limit: int = Field(50, description='Maximum number of results to return')

class WordnikGetAudioConfig(_Operation):
    """Fetches audio metadata for a word.."""
    operation: Literal['get_audio'] = Field('get_audio', title='Get Audio', json_schema_extra={"ui:hidden": True})
    word: str = Field(..., description='Word to get audio for.', min_length=1)
    use_canonical: Literal['false', 'true'] = Field('false', description="If true will try to return the correct word root ('cats' -> 'cat'). If false returns exactly what was requested.")
    limit: int = Field(50, description='Maximum number of results to return')

class WordnikGetEtymologiesConfig(_Operation):
    """Fetches etymology data."""
    operation: Literal['get_etymologies'] = Field('get_etymologies', title='Get Etymologies', json_schema_extra={"ui:hidden": True})
    word: str = Field(..., description='Word to return', min_length=1)
    use_canonical: Literal['false', 'true'] = Field('false', description="If true will try to return the correct word root ('cats' -> 'cat'). If false returns exactly what was requested.")

class WordnikGetHyphenationConfig(_Operation):
    """Returns syllable information for a word."""
    operation: Literal['get_hyphenation'] = Field('get_hyphenation', title='Get Hyphenation', json_schema_extra={"ui:hidden": True})
    word: str = Field(..., description='Word to get syllables for', min_length=1)
    use_canonical: Literal['false', 'true'] = Field('false', description="If true will try to return a correct word root ('cats' -> 'cat'). If false returns exactly what was requested.")
    source_dictionary: Literal['ahd-5', 'century', 'wiktionary', 'webster', 'wordnet'] | None = Field(None, description='Get from a single dictionary. Valid options: ahd-5, century, wiktionary, webster, and wordnet.')
    limit: int = Field(50, description='Maximum number of results to return')

class WordnikGetWordFrequencyConfig(_Operation):
    """Returns word usage over time."""
    operation: Literal['get_word_frequency'] = Field('get_word_frequency', title='Get Word Frequency', json_schema_extra={"ui:hidden": True})
    word: str = Field(..., description='Word to return', min_length=1)
    use_canonical: Literal['false', 'true'] = Field('false', description="If true will try to return the correct word root ('cats' -> 'cat'). If false returns exactly what was requested.")
    start_year: int = Field(1800, description='Starting Year')
    end_year: int = Field(2012, description='Ending Year')

class WordnikGetPhrasesConfig(_Operation):
    """Fetches bi-gram phrases for a word."""
    operation: Literal['get_phrases'] = Field('get_phrases', title='Get Phrases', json_schema_extra={"ui:hidden": True})
    word: str = Field(..., description='Word to fetch phrases for', min_length=1)
    limit: int = Field(5, description='Maximum number of results to return')
    wlmi: int = Field(0, description='Minimum WLMI for the phrase')
    use_canonical: Literal['false', 'true'] = Field('false', description="If true will try to return the correct word root ('cats' -> 'cat'). If false returns exactly what was requested.")

class WordnikGetTopExampleConfig(_Operation):
    """Returns a top example for a word."""
    operation: Literal['get_top_example'] = Field('get_top_example', title='Get Top Example', json_schema_extra={"ui:hidden": True})
    word: str = Field(..., description='Word to fetch examples for', min_length=1)
    use_canonical: Literal['false', 'true'] = Field('false', description="If true will try to return the correct word root ('cats' -> 'cat'). If false returns exactly what was requested.")

class WordnikGetScrabbleScoreConfig(_Operation):
    """Returns the Scrabble score for a word."""
    operation: Literal['get_scrabble_score'] = Field('get_scrabble_score', title='Get Scrabble Score', json_schema_extra={"ui:hidden": True})
    word: str = Field(..., description='Word to get scrabble score for.', min_length=1)


WordnikOperation = Annotated[Union[
    WordnikGetDefinitionsConfig,
    WordnikGetExamplesConfig,
    WordnikGetRelatedWordsConfig,
    WordnikGetWordOfTheDayConfig,
    WordnikSearchWordsConfig,
    WordnikReverseDictionaryConfig,
    WordnikGetRandomWordConfig,
    WordnikGetRandomWordsConfig,
    WordnikGetTextPronunciationsConfig,
    WordnikGetAudioConfig,
    WordnikGetEtymologiesConfig,
    WordnikGetHyphenationConfig,
    WordnikGetWordFrequencyConfig,
    WordnikGetPhrasesConfig,
    WordnikGetTopExampleConfig,
    WordnikGetScrabbleScoreConfig
], Field(discriminator="operation")]


class WordnikConfig(NodeConfig[WordnikOperation, WordnikAPIKeyCredential]):
    pass


ROUTES = {'get_definitions': '/word.json/{word}/definitions',
 'get_examples': '/word.json/{word}/examples',
 'get_related_words': '/word.json/{word}/relatedWords',
 'get_word_of_the_day': '/words.json/wordOfTheDay',
 'search_words': '/words.json/search/{query}',
 'reverse_dictionary': '/words.json/reverseDictionary',
 'get_random_word': '/words.json/randomWord',
 'get_random_words': '/words.json/randomWords',
 'get_text_pronunciations': '/word.json/{word}/pronunciations',
 'get_audio': '/word.json/{word}/audio',
 'get_etymologies': '/word.json/{word}/etymologies',
 'get_hyphenation': '/word.json/{word}/hyphenation',
 'get_word_frequency': '/word.json/{word}/frequency',
 'get_phrases': '/word.json/{word}/phrases',
 'get_top_example': '/word.json/{word}/topExample',
 'get_scrabble_score': '/word.json/{word}/scrabbleScore'}

PARAMETERS = {'get_definitions': {'word': 'word',
                     'limit': 'limit',
                     'part_of_speech': 'partOfSpeech',
                     'include_related': 'includeRelated',
                     'source_dictionaries': 'sourceDictionaries',
                     'use_canonical': 'useCanonical',
                     'include_tags': 'includeTags'},
 'get_examples': {'word': 'word',
                  'include_duplicates': 'includeDuplicates',
                  'use_canonical': 'useCanonical',
                  'skip': 'skip',
                  'limit': 'limit'},
 'get_related_words': {'word': 'word',
                       'use_canonical': 'useCanonical',
                       'relationship_types': 'relationshipTypes',
                       'limit_per_relationship_type': 'limitPerRelationshipType'},
 'get_word_of_the_day': {'date': 'date'},
 'search_words': {'allow_regex': 'allowRegex',
                  'query': 'query',
                  'case_sensitive': 'caseSensitive',
                  'include_part_of_speech': 'includePartOfSpeech',
                  'exclude_part_of_speech': 'excludePartOfSpeech',
                  'min_corpus_count': 'minCorpusCount',
                  'max_corpus_count': 'maxCorpusCount',
                  'min_dictionary_count': 'minDictionaryCount',
                  'max_dictionary_count': 'maxDictionaryCount',
                  'min_length': 'minLength',
                  'max_length': 'maxLength',
                  'skip': 'skip',
                  'limit': 'limit'},
 'reverse_dictionary': {'query': 'query',
                        'find_sense_for_word': 'findSenseForWord',
                        'include_source_dictionaries': 'includeSourceDictionaries',
                        'exclude_source_dictionaries': 'excludeSourceDictionaries',
                        'include_part_of_speech': 'includePartOfSpeech',
                        'exclude_part_of_speech': 'excludePartOfSpeech',
                        'min_corpus_count': 'minCorpusCount',
                        'max_corpus_count': 'maxCorpusCount',
                        'min_length': 'minLength',
                        'max_length': 'maxLength',
                        'expand_terms': 'expandTerms',
                        'include_tags': 'includeTags',
                        'sort_by': 'sortBy',
                        'sort_order': 'sortOrder',
                        'skip': 'skip',
                        'limit': 'limit'},
 'get_random_word': {'has_dictionary_def': 'hasDictionaryDef',
                     'include_part_of_speech': 'includePartOfSpeech',
                     'exclude_part_of_speech': 'excludePartOfSpeech',
                     'min_corpus_count': 'minCorpusCount',
                     'max_corpus_count': 'maxCorpusCount',
                     'min_dictionary_count': 'minDictionaryCount',
                     'max_dictionary_count': 'maxDictionaryCount',
                     'min_length': 'minLength',
                     'max_length': 'maxLength'},
 'get_random_words': {'has_dictionary_def': 'hasDictionaryDef',
                      'include_part_of_speech': 'includePartOfSpeech',
                      'exclude_part_of_speech': 'excludePartOfSpeech',
                      'min_corpus_count': 'minCorpusCount',
                      'max_corpus_count': 'maxCorpusCount',
                      'min_dictionary_count': 'minDictionaryCount',
                      'max_dictionary_count': 'maxDictionaryCount',
                      'min_length': 'minLength',
                      'max_length': 'maxLength',
                      'sort_by': 'sortBy',
                      'sort_order': 'sortOrder',
                      'limit': 'limit'},
 'get_text_pronunciations': {'word': 'word',
                             'use_canonical': 'useCanonical',
                             'source_dictionary': 'sourceDictionary',
                             'type_format': 'typeFormat',
                             'limit': 'limit'},
 'get_audio': {'word': 'word', 'use_canonical': 'useCanonical', 'limit': 'limit'},
 'get_etymologies': {'word': 'word', 'use_canonical': 'useCanonical'},
 'get_hyphenation': {'word': 'word',
                     'use_canonical': 'useCanonical',
                     'source_dictionary': 'sourceDictionary',
                     'limit': 'limit'},
 'get_word_frequency': {'word': 'word',
                        'use_canonical': 'useCanonical',
                        'start_year': 'startYear',
                        'end_year': 'endYear'},
 'get_phrases': {'word': 'word', 'limit': 'limit', 'wlmi': 'wlmi', 'use_canonical': 'useCanonical'},
 'get_top_example': {'word': 'word', 'use_canonical': 'useCanonical'},
 'get_scrabble_score': {'word': 'word'}}

RESPONSE_TYPES = {'get_definitions': 'array',
 'get_examples': 'object',
 'get_related_words': 'array',
 'get_word_of_the_day': 'object',
 'search_words': 'object',
 'reverse_dictionary': 'object',
 'get_random_word': 'object',
 'get_random_words': 'array',
 'get_text_pronunciations': 'array',
 'get_audio': 'array',
 'get_etymologies': 'array',
 'get_hyphenation': 'array',
 'get_word_frequency': 'object',
 'get_phrases': 'array',
 'get_top_example': 'object',
 'get_scrabble_score': 'integer'}


class WordnikNode(WorkflowNode):
    integration_type = "automation-wordnik"
    connection_evidence = ConnectionEvidence(
        operation="get_word_of_the_day", noun="word of the day", proves="reachability")

    @classmethod
    def get_config_model(cls):
        return WordnikConfig

    async def execute(self, inputs):
        if self.config is None or self.config.credentials is None:
            raise ValueError("Connect a Wordnik API key")
        config = self.config.config
        key = self.config.credentials.api_key
        route = ROUTES[config.operation]
        params = {"api_key": key}
        for name, wire in PARAMETERS[config.operation].items():
            value = getattr(config, name)
            if value is None:
                continue
            if "{" + wire + "}" in route:
                # Dot segments have URL semantics even when percent-encoded.
                if value in {".", ".."}:
                    raise ValueError("Use a word or search query, not a dot segment")
                route = route.replace("{" + wire + "}", quote(value, safe=""))
            else:
                params[wire] = ",".join(value) if isinstance(value, list) else value
        try:
            async with guarded_async_client(timeout=30, follow_redirects=False, trust_env=False) as client:
                response = await client.request("GET", BASE_URL + route,
                    params=params, headers={"Accept": "application/json"})
        except httpx.HTTPError:
            raise ValueError("Wordnik could not be reached") from None
        if response.status_code != 200:
            message = "Wordnik rejected the request"
            try:
                error = response.json()
                if isinstance(error, dict) and isinstance(error.get("message"), str):
                    message = error["message"].replace(key, "[redacted]")
            except ValueError:
                pass
            return {"status": "error", "http_status": response.status_code, "error": message}
        try:
            data = response.json()
        except ValueError:
            raise ValueError("Wordnik returned invalid JSON") from None
        expected = {"array": list, "object": dict, "integer": int}[RESPONSE_TYPES[config.operation]]
        if not isinstance(data, expected) or isinstance(data, bool):
            raise ValueError("Wordnik returned an unexpected response shape")
        # Preserve the documented response without interpreting dictionary HTML,
        # fetching audio URLs, or losing object/array/scalar boundaries.
        output = {"status": "success", "operation": config.operation, "data": data}
        await self.emit(output)
        return output
