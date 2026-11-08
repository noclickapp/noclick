"""Speechmatics Batch API v2 actions, pinned to the published batch.yaml.

Job submissions fetch an audio URL at the provider; each action makes one API call.
"""
from __future__ import annotations

import json
from datetime import date, datetime
from typing import Annotated, Literal, Union
from urllib.parse import quote, urlsplit

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from utils.ssrf import guarded_async_client

BASE = 'https://eu1.asr.api.speechmatics.com/v2'
HIDDEN = {'ui:hidden': True}


class SpeechmaticsCredential(BaseModel):
    model_config = ConfigDict(title='Speechmatics API Key')
    credential_type: Literal['speechmatics_api_key'] = Field('speechmatics_api_key', json_schema_extra=HIDDEN)
    api_key: str = Field(..., title='API Key', min_length=1, repr=False, description='Paste your Speechmatics API key without the Bearer prefix.', json_schema_extra={'ui:widget': 'password', 'x-credential-url': 'https://portal.speechmatics.com/settings/api-keys'})

    @field_validator('api_key')
    @classmethod
    def key(cls, value):
        value = value.strip()
        if any(c.isspace() or ord(c) < 33 for c in value) or value.lower().startswith('bearer '):
            raise ValueError('Paste only the API key')
        return value


class SubmitBase(BaseModel):
    audio_url: str = Field(..., title='Audio URL', description='Public or signed HTTPS audio URL fetched by Speechmatics.')
    language: str = Field('en', max_length=20, description='Language code, for example en; use auto for language identification.')
    title: str | None = Field(None, title='Job Title', max_length=1000)

    @field_validator('audio_url')
    @classmethod
    def url(cls, value):
        p = urlsplit(value)
        if p.scheme != 'https' or not p.hostname or p.username or p.password or any(c.isspace() for c in value):
            raise ValueError('Use an HTTPS audio URL')
        return value


class SubmitTranscription(SubmitBase):
    operation: Literal['submit_transcription'] = Field('submit_transcription', title='Submit Transcription', json_schema_extra=HIDDEN)


class SubmitSpeakerTranscription(SubmitBase):
    operation: Literal['submit_speaker_transcription'] = Field('submit_speaker_transcription', title='Submit Speaker Transcription', json_schema_extra=HIDDEN)


class SubmitTranslation(SubmitBase):
    operation: Literal['submit_translation'] = Field('submit_translation', title='Submit Transcription and Translation', json_schema_extra=HIDDEN)
    target_languages: list[str] = Field(..., min_length=1, max_length=5, title='Target Language Codes')


class SubmitSummarization(SubmitBase):
    operation: Literal['submit_summarization'] = Field('submit_summarization', title='Submit Transcription and Summary', json_schema_extra=HIDDEN)
    summary_length: Literal['brief', 'detailed'] = 'brief'
    summary_type: Literal['paragraphs', 'bullets'] = 'paragraphs'
    content_type: Literal['auto', 'informative', 'conversational'] = 'auto'


class ListJobs(BaseModel):
    operation: Literal['list_jobs'] = Field('list_jobs', title='List Jobs', json_schema_extra=HIDDEN)
    limit: int = Field(25, ge=1, le=100)
    created_before: datetime | None = Field(None, description='UTC timestamp cursor. Pass the oldest creation timestamp to retrieve an earlier page.')
    include_deleted: bool = False


class Job(BaseModel):
    job_id: str = Field(..., title='Job ID', min_length=1, max_length=256, pattern=r'^[A-Za-z0-9_-]+$')


class GetJob(Job):
    operation: Literal['get_job'] = Field('get_job', title='Get Job', json_schema_extra=HIDDEN)


class DeleteJob(Job):
    operation: Literal['delete_job'] = Field('delete_job', title='Delete Job', json_schema_extra=HIDDEN)
    force: bool = Field(False, description='Terminate a running job as well as deleting its data.')


class GetTranscript(Job):
    operation: Literal['get_transcript'] = Field('get_transcript', title='Get JSON Transcript', json_schema_extra=HIDDEN)


class GetTextTranscript(Job):
    operation: Literal['get_text_transcript'] = Field('get_text_transcript', title='Get Text Transcript', json_schema_extra=HIDDEN)


class GetSrtTranscript(Job):
    operation: Literal['get_srt_transcript'] = Field('get_srt_transcript', title='Get SRT Subtitles', json_schema_extra=HIDDEN)


class GetLog(Job):
    operation: Literal['get_log'] = Field('get_log', title='Get Job Log', json_schema_extra=HIDDEN)


class GetUsage(BaseModel):
    operation: Literal['get_usage'] = Field('get_usage', title='Get Usage', json_schema_extra=HIDDEN)
    since: date | None = None
    until: date | None = None


Operation = Annotated[Union[SubmitTranscription, SubmitSpeakerTranscription, SubmitTranslation, SubmitSummarization, ListJobs, GetJob, DeleteJob, GetTranscript, GetTextTranscript, GetSrtTranscript, GetLog, GetUsage], Field(discriminator='operation')]


class SpeechmaticsConfig(NodeConfig[Operation, SpeechmaticsCredential]):
    pass


class SpeechmaticsNode(WorkflowNode):
    integration_type = 'automation-speechmatics'
    connection_evidence = ConnectionEvidence(operation='list_jobs', noun='Speechmatics jobs')

    @classmethod
    def get_config_model(cls):
        return SpeechmaticsConfig

    async def execute(self, inputs):
        c = self.config.config
        credential = self.config.credentials
        if not credential:
            raise ValueError('Connect a Speechmatics API key')
        op = c.operation
        method, path, params, kwargs = 'GET', '/jobs', {}, {}
        text = False
        if isinstance(c, SubmitBase):
            method = 'POST'
            job = {'type': 'transcription', 'fetch_data': {'url': c.audio_url}, 'transcription_config': {'language': c.language}}
            if isinstance(c, SubmitSpeakerTranscription):
                job['transcription_config']['diarization'] = 'speaker'
            if isinstance(c, SubmitTranslation):
                job['translation_config'] = {'target_languages': c.target_languages}
            if isinstance(c, SubmitSummarization):
                job['summarization_config'] = {k: getattr(c, k) for k in ('summary_length', 'summary_type', 'content_type')}
            if c.title is not None:
                job['tracking'] = {'title': c.title}
            kwargs['files'] = {'config': (None, json.dumps(job), 'application/json')}
        elif isinstance(c, ListJobs):
            params = {'limit': c.limit, 'include_deleted': str(c.include_deleted).lower()}
            if c.created_before is not None:
                params['created_before'] = c.created_before.isoformat()
        elif isinstance(c, GetUsage):
            path = '/usage'
            params = {k: getattr(c, k).isoformat() for k in ('since', 'until') if getattr(c, k) is not None}
        else:
            path = '/jobs/' + quote(c.job_id, safe='')
            if isinstance(c, DeleteJob):
                method, params = 'DELETE', {'force': str(c.force).lower()}
            elif isinstance(c, GetJob):
                params = {'wait': 0}
            elif isinstance(c, GetLog):
                path += '/log'
                text = True
            else:
                path += '/transcript'
                fmt = 'txt' if isinstance(c, GetTextTranscript) else 'srt' if isinstance(c, GetSrtTranscript) else 'json-v2'
                params = {'format': fmt, 'wait': 0}
                text = fmt != 'json-v2'
        headers = {'Authorization': 'Bearer ' + credential.api_key, 'Accept': 'text/plain' if text else 'application/json'}
        try:
            async with guarded_async_client(timeout=60, follow_redirects=False, trust_env=False) as client:
                response = await client.request(method, BASE + path, headers=headers, params=params, **kwargs)
            if response.status_code != (201 if method == 'POST' else 200):
                try:
                    error = response.json()
                    message = error.get('detail') or error.get('error') or 'Speechmatics request failed'
                except (ValueError, AttributeError):
                    message = 'Speechmatics request failed'
                return {'status': 'error', 'http_status': response.status_code, 'error': str(message)}
            if text:
                return {'status': 'success', 'text': response.text}
            body = response.json()
            if not isinstance(body, dict) or 'error' in body:
                raise ValueError('Invalid Speechmatics response')
            required = 'id' if method == 'POST' else 'jobs' if isinstance(c, ListJobs) else 'job' if isinstance(c, (GetJob, DeleteJob)) else 'summary' if isinstance(c, GetUsage) else 'results'
            if required not in body:
                raise ValueError('Incomplete Speechmatics response')
            return {'status': 'success', 'data': body}
        except (httpx.HTTPError, ValueError) as exc:
            return {'status': 'error', 'error': 'Speechmatics request could not be completed' if isinstance(exc, httpx.HTTPError) else str(exc)}
