"""A loopback-only scripted provider for testing real CLI protocol behavior."""
import asyncio
import json
import time
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.responses import StreamingResponse


def sse(kind, **data):
    return f"event: {kind}\ndata: {json.dumps({'type': kind, **data})}\n\n".encode()


class LocalModel:
    def __init__(self, *, call_tool=False):
        self.call_tool = call_tool
        self.tool_calls = []
        self.requests = []
        self.auxiliary_requests = []
        self.started = asyncio.Event()
        self.release = asyncio.Event()
        self.app = FastAPI()
        self.app.post('/v1/messages')(self.messages)
        self.app.post('/v1/responses')(self.responses)

    async def echo(self, node_id, arguments, agent_id):
        self.tool_calls.append((node_id, arguments, agent_id))
        return {'success': True, 'result': 'native-tool-result'}

    def selected_tool(self, body):
        # Select after the correction arrives; OpenClaw intentionally discards
        # a stale tool selected before a queued steering message.
        if not self.call_tool or len(self.requests) != 2:
            return None
        for tool in body.get('tools', []):
            if 'fixture_echo' in tool.get('name', ''):
                return {'name': tool['name']}
            for child in tool.get('tools', []):
                if 'fixture_echo' in child.get('name', ''):
                    return {'name': child['name'], 'namespace': tool['name']}
        raise AssertionError('The tool request did not advertise fixture_echo')

    async def record(self, request):
        body = await request.json()
        schema = ((body.get('output_config') or {}).get('format') or {}).get('schema') or {}
        if set(schema.get('properties') or {}) == {'title'}:
            self.auxiliary_requests.append(body)
            return body, '{"title":"Local test"}'
        self.requests.append(body)
        number = len(self.requests)
        self.started.set()
        if number == 1:
            await self.release.wait()
        return body, f'reply-{number}'

    async def messages(self, request: Request):
        body, text = await self.record(request)
        tool = self.selected_tool(body)
        message = {'id': 'msg_' + uuid4().hex, 'type': 'message', 'role': 'assistant',
                   'model': body['model'], 'content': [], 'stop_reason': None,
                   'stop_sequence': None, 'usage': {'input_tokens': 10, 'output_tokens': 0}}
        if not body.get('stream'):
            if tool:
                return {**message, 'content': [{'type': 'tool_use', 'id': 'toolu_echo', 'name': tool['name'], 'input': {}}], 'stop_reason': 'tool_use'}
            return {**message, 'content': [{'type': 'text', 'text': text}], 'stop_reason': 'end_turn'}
        async def stream():
            yield sse('message_start', message=message)
            if tool:
                yield sse('content_block_start', index=0, content_block={'type': 'tool_use', 'id': 'toolu_echo', 'name': tool['name'], 'input': {}})
                yield sse('content_block_delta', index=0, delta={'type': 'input_json_delta', 'partial_json': '{}'})
                yield sse('content_block_stop', index=0)
                yield sse('message_delta', delta={'stop_reason': 'tool_use', 'stop_sequence': None}, usage={'output_tokens': 5})
                yield sse('message_stop')
                return
            yield sse('content_block_start', index=0, content_block={'type': 'text', 'text': ''})
            yield sse('content_block_delta', index=0, delta={'type': 'text_delta', 'text': text})
            yield sse('content_block_stop', index=0)
            yield sse('message_delta', delta={'stop_reason': 'end_turn', 'stop_sequence': None}, usage={'output_tokens': 5})
            yield sse('message_stop')
        return StreamingResponse(stream(), media_type='text/event-stream')

    async def responses(self, request: Request):
        body, text = await self.record(request)
        tool = self.selected_tool(body)
        response = {'id': 'resp_' + uuid4().hex, 'object': 'response', 'model': body['model'],
                    'created_at': int(time.time()), 'status': 'in_progress', 'output': [], 'usage': None}
        item = {'id': 'msg_' + uuid4().hex, 'type': 'message', 'role': 'assistant',
                'status': 'in_progress', 'content': []}
        part = {'type': 'output_text', 'text': text, 'annotations': []}
        async def stream():
            yield sse('response.created', response=response)
            if tool:
                call = {'type': 'function_call', 'id': 'fc_echo', 'call_id': 'call_echo', 'arguments': '{}', **tool}
                yield sse('response.output_item.added', output_index=0, item={**call, 'arguments': ''})
                yield sse('response.function_call_arguments.delta', output_index=0, item_id=call['id'], delta='{}')
                yield sse('response.function_call_arguments.done', output_index=0, item_id=call['id'], arguments='{}')
                yield sse('response.output_item.done', output_index=0, item=call)
                yield sse('response.completed', response={**response, 'status': 'completed', 'output': [call],
                    'usage': {'input_tokens': 10, 'output_tokens': 5, 'total_tokens': 15}})
                return
            yield sse('response.output_item.added', output_index=0, item=item)
            yield sse('response.content_part.added', item_id=item['id'], output_index=0, content_index=0, part={**part, 'text': ''})
            yield sse('response.output_text.delta', item_id=item['id'], output_index=0, content_index=0, delta=text)
            yield sse('response.output_text.done', item_id=item['id'], output_index=0, content_index=0, text=text)
            yield sse('response.content_part.done', item_id=item['id'], output_index=0, content_index=0, part=part)
            completed = {**item, 'status': 'completed', 'content': [part]}
            yield sse('response.output_item.done', output_index=0, item=completed)
            yield sse('response.completed', response={**response, 'status': 'completed', 'output': [completed],
                'usage': {'input_tokens': 10, 'output_tokens': 5, 'total_tokens': 15}})
        return StreamingResponse(stream(), media_type='text/event-stream')
