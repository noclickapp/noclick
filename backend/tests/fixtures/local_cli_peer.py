"""Deterministic CLI protocol peer: real pipes/processes, externally gated turns."""
import json
import os
import sys
import threading
import time
from pathlib import Path

kind = sys.argv[1]
lock = threading.RLock()
active = None
queued = []
turn_count = 0


def record(data):
    with lock, open('.wire', 'a') as f:
        f.write(json.dumps({'pid': os.getpid(), **data}) + '\n')


def emit(data):
    with lock:
        print(json.dumps(data), flush=True)


def run_turn(turn):
    record({'model': turn['id'], 'inputs': list(turn['inputs'])})
    while not Path('release-' + str(turn['number'])).exists():
        time.sleep(.01)
    global active
    with lock:
        if kind == 'codex':
            text = '|'.join(turn['inputs'])
            emit({'method': 'item/completed', 'params': {'turnId': turn['id'], 'item': {'type': 'agentMessage', 'text': text}}})
            emit({'method': 'turn/completed', 'params': {'turn': {'id': turn['id'], 'status': 'completed'}}})
        else:
            for item in turn['items']:
                emit({'type': 'user', 'isReplay': True, 'uuid': item['uuid'], 'message': item['message']})
            emit({'type': 'result', 'subtype': 'success', 'result': '|'.join(turn['inputs']),
                  'user_message_uuids': [item['uuid'] for item in turn['items']]})
        active = None
        if queued:
            items, queued[:] = list(queued), []
            begin(items)


def begin(items):
    global active, turn_count
    turn_count += 1
    active = {'id': 'turn-' + str(turn_count), 'number': turn_count,
              'inputs': [x['message']['content'] for x in items], 'items': items}
    threading.Thread(target=run_turn, args=(active,), daemon=True).start()
    return active['id']


record({'started': True})
for line in sys.stdin:
    event = json.loads(line)
    record(event)
    with lock:
        if kind == 'claude_code':
            if active:
                queued.append(event)
            else:
                begin([event])
            continue
        method = event.get('method')
        rid = event.get('id')
        params = event.get('params') or {}
        if method == 'initialize':
            result = {}
        elif method in ('thread/start', 'thread/resume'):
            result = {'thread': {'id': params.get('threadId') or 'thread-1'}}
        elif method == 'turn/start':
            text = params['input'][0]['text']
            result = {'turn': {'id': begin([{'message': {'content': text}}])}}
        elif method == 'turn/steer':
            if not active:
                emit({'id': rid, 'error': {'code': -32600, 'message': 'No active turn'}})
                continue
            active['inputs'].append(params['input'][0]['text'])
            result = {'turnId': active['id']}
        elif rid is None:
            continue
        else:
            raise RuntimeError(method)
        emit({'id': rid, 'result': result})
