import asyncio
import collections.abc
from y_py import YDoc, YMap, YArray, YTransaction
from utils.await_utils import get_or_create_event_loop

###############################################################################
# Constants and message helpers
###############################################################################

class YMessageType:
    SYNC = 0
    AWARENESS = 1

class YSyncMessageType:
    SYNC_STEP1 = 0
    SYNC_STEP2 = 1
    SYNC_UPDATE = 2

def write_var_uint(num: int) -> bytes:
    res = []
    while num > 127:
        res.append(128 | (127 & num))
        num >>= 7
    res.append(num)
    return bytes(res)

def create_message(data: bytes, msg_type: int) -> bytes:
    return bytes([YMessageType.SYNC, msg_type]) + write_var_uint(len(data)) + data

def create_sync_step2_message(data: bytes) -> bytes:
    return create_message(data, YSyncMessageType.SYNC_STEP2)

def create_update_message(data: bytes) -> bytes:
    return create_message(data, YSyncMessageType.SYNC_UPDATE)

###############################################################################
# Helper: Convert Python dicts/lists to collaborative types recursively.
###############################################################################

def convert_to_y(value, txn):
    """
    Recursively converts Python native types (dict, list) into collaborative Y types.
    """
    if isinstance(value, dict):
        new_map = YMap({})
        for k, v in value.items():
            new_map.set(txn, k, convert_to_y(v, txn))
        return new_map
    elif isinstance(value, list):
        new_arr = YArray()
        converted_list = [convert_to_y(item, txn) for item in value]
        new_arr.insert_range(txn, 0, converted_list)
        return new_arr
    else:
        return value

###############################################################################
# 1) AsyncTransactionBatcher: an asyncio-based transaction batcher.
###############################################################################

class AsyncTransactionBatcher:
    """
    Manages a single shared transaction for ~1ms after each operation.
    If there is no further operation within that 1ms, it auto‐commits.

    All code runs in the same thread + same asyncio event loop, preventing the
    "unsendable transaction" panic.
    """

    def __init__(self, doc: YDoc, loop: asyncio.AbstractEventLoop = None, batch_time: float = 0.001):
        """
        :param doc:        The YDoc on which we'll create transactions.
        :param loop:       The asyncio event loop. Defaults to asyncio.get_event_loop() if None.
        :param batch_time: Auto‐commit delay in seconds. 0.001 = 1 ms.
        """
        self.doc = doc
        self.loop = loop or get_or_create_event_loop()
        self.batch_time = batch_time

        self._txn: YTransaction | None = None
        self._timer_handle: asyncio.TimerHandle | None = None

    def get_transaction(self) -> YTransaction:
        """
        Called by each operation (e.g., dict set, list append).
        1. If no transaction is open, open one now.
        2. Cancel the old timer if it exists and re‐schedule a new 1ms timer.
        3. Return the open transaction, to be reused by subsequent calls until timer fires.
        """
        if self._txn is None:
            self._txn = self.doc.begin_transaction()

        if self._timer_handle is not None:
            self._timer_handle.cancel()

        self._timer_handle = self.loop.call_later(self.batch_time, self._commit_and_close)
        return self._txn

    def _commit_and_close(self):
        if self._txn is not None:
            self._txn.commit()
            self._txn = None
        self._timer_handle = None

    def commit_now(self):
        if self._txn is not None:
            self._txn.commit()
            self._txn = None
        if self._timer_handle is not None:
            self._timer_handle.cancel()
            self._timer_handle = None

###############################################################################
# 2) YPathReference: Helper class to track paths and resolve current references
###############################################################################

class YPathReference:
    """Helper class to track paths and resolve current references"""
    def __init__(self, root_state, path=None):
        self.root_state = root_state
        self.path = path or []

    def resolve_reference(self):
        """Walk down the path from root to get current reference"""
        # Start with the root YMap instead of the SyncedState object
        if isinstance(self.root_state, SyncedState):
            current = self.root_state.ymap
        else:
            current = self.root_state
            
        for key in self.path:
            if isinstance(current, YArray):
                current = current[key]
            else:  # YMap
                current = current[key]
        return current

    def extend(self, key):
        """Create new path reference with additional key"""
        return YPathReference(self.root_state, self.path + [key])

###############################################################################
# 3) YArrayList: A Pythonic list interface for YArray.
###############################################################################

class YArrayList(collections.abc.MutableSequence):
    """
    Wrap a YArray with path tracking back to root state
    """
    def __init__(self, yarray: YArray, batcher: AsyncTransactionBatcher, path_ref: YPathReference):
        self._yarray = yarray
        self._batcher = batcher
        self._path_ref = path_ref

    def __len__(self):
        txn = self._batcher.get_transaction()
        current = self._path_ref.resolve_reference()
        return len(current)

    def __getitem__(self, index):
        txn = self._batcher.get_transaction()
        current = self._path_ref.resolve_reference()
        
        if isinstance(index, slice):
            raw_items = current[index]
            wrapped_items = []
            for i, item in enumerate(raw_items):
                idx = index.start + i if index.start is not None else i
                if isinstance(item, YMap):
                    wrapped_items.append(YMapDict(item, self._batcher, self._path_ref.extend(idx)))
                elif isinstance(item, YArray):
                    wrapped_items.append(YArrayList(item, self._batcher, self._path_ref.extend(idx)))
                else:
                    wrapped_items.append(item)
            return wrapped_items
        else:
            item = current[index]
            if isinstance(item, YMap):
                return YMapDict(item, self._batcher, self._path_ref.extend(index))
            elif isinstance(item, YArray):
                return YArrayList(item, self._batcher, self._path_ref.extend(index))
            else:
                return item

    def __setitem__(self, index, value):
        txn = self._batcher.get_transaction()
        current = self._path_ref.resolve_reference()
        
        if isinstance(index, int):
            current.delete(txn, index)
            converted = convert_to_y(value, txn)
            current.insert(txn, index, converted)
        else:
            start, stop, step = index.indices(len(current))
            length = len(range(start, stop, step))
            current.delete_range(txn, start, length)
            converted = [convert_to_y(v, txn) for v in value]
            current.insert_range(txn, start, converted)

    def __delitem__(self, index):
        txn = self._batcher.get_transaction()
        current = self._path_ref.resolve_reference()
        
        if isinstance(index, int):
            current.delete(txn, index)
        else:
            start, stop, step = index.indices(len(current))
            length = len(range(start, stop, step))
            current.delete_range(txn, start, length)

    def insert(self, index, value):
        txn = self._batcher.get_transaction()
        current = self._path_ref.resolve_reference()
        converted = convert_to_y(value, txn)
        current.insert(txn, index, converted)

    def append(self, value):
        txn = self._batcher.get_transaction()
        current = self._path_ref.resolve_reference()
        converted = convert_to_y(value, txn)
        current.append(txn, converted)

    def sort(self, *, key=None, reverse=False):
        txn = self._batcher.get_transaction()
        current = self._path_ref.resolve_reference()
        items = list(self)
        items.sort(key=key, reverse=reverse)
        current.delete_range(txn, 0, len(current))
        converted = [convert_to_y(item, txn) for item in items]
        current.insert_range(txn, 0, converted)

    def __iter__(self):
        for i in range(len(self)):
            yield self[i]

    def __repr__(self):
        return f"YArrayList({list(self)})"

###############################################################################
# 4) YMapDict: A Pythonic dict interface for YMap.
###############################################################################

class YMapDict(collections.abc.MutableMapping):
    """
    Wrap a YMap with path tracking back to root state
    """
    def __init__(self, ymap: YMap, batcher: AsyncTransactionBatcher, path_ref: YPathReference):
        self._ymap = ymap
        self._batcher = batcher
        self._path_ref = path_ref

    def __getitem__(self, key):
        txn = self._batcher.get_transaction()
        current = self._path_ref.resolve_reference()
        raw_value = current[key]
        
        if isinstance(raw_value, YMap):
            return YMapDict(raw_value, self._batcher, self._path_ref.extend(key))
        elif isinstance(raw_value, YArray):
            return YArrayList(raw_value, self._batcher, self._path_ref.extend(key))
        else:
            return raw_value

    def __setitem__(self, key, value):
        txn = self._batcher.get_transaction()
        current = self._path_ref.resolve_reference()
        converted = convert_to_y(value, txn)
        current.set(txn, key, converted)

    def __delitem__(self, key):
        txn = self._batcher.get_transaction()
        current = self._path_ref.resolve_reference()
        old_val = current.pop(txn, key, None)
        if old_val is None:
            raise KeyError(key)

    def __contains__(self, key):
        txn = self._batcher.get_transaction()
        current = self._path_ref.resolve_reference()
        return key in current

    def __len__(self):
        txn = self._batcher.get_transaction()
        current = self._path_ref.resolve_reference()
        return len(current)

    def __iter__(self):
        txn = self._batcher.get_transaction()
        current = self._path_ref.resolve_reference()
        return iter(list(current.keys()))

    def __repr__(self):
        txn = self._batcher.get_transaction()
        current = self._path_ref.resolve_reference()
        items = {}
        for k in current.keys():
            v = current[k]
            if isinstance(v, YArray):
                items[k] = list(YArrayList(v, self._batcher, self._path_ref.extend(k)))
            elif isinstance(v, YMap):
                items[k] = dict(YMapDict(v, self._batcher, self._path_ref.extend(k)))
            else:
                items[k] = v
        return f"YMapDict({items})"

###############################################################################
# Message Decoder
###############################################################################

def read_message(stream: bytes) -> bytes:
    message = Decoder(stream).read_message()
    assert message is not None
    return message

class Decoder:
    """
    Decode Y messages from bytes.
    """
    def __init__(self, stream: bytes):
        self.stream = stream
        self.length = len(stream)
        self.i0 = 0

    def read_var_uint(self) -> int:
        if self.length <= 0:
            raise RuntimeError("Y protocol error")
        uint = 0
        i = 0
        while True:
            byte = self.stream[self.i0]
            uint += (byte & 127) << i
            i += 7
            self.i0 += 1
            self.length -= 1
            if byte < 128:
                break
        return uint

    def read_message(self) -> bytes | None:
        if self.length == 0:
            return None
        length = self.read_var_uint()
        if length == 0:
            return b""
        i1 = self.i0 + length
        message = self.stream[self.i0 : i1]
        self.i0 = i1
        self.length -= length
        return message

    def read_messages(self):
        while True:
            message = self.read_message()
            if message is None:
                return
            yield message

    def read_var_string(self):
        message = self.read_message()
        if message is None:
            return ""
        return message.decode("utf-8")

###############################################################################
# SyncedState: A collaborative state based on YMapDict.
###############################################################################

class SyncedState(YMapDict):
    def __init__(self, loop: asyncio.AbstractEventLoop = None, batch_timeout: float = 0.001):
        self.ydoc = YDoc()
        
        # Add property to track YDoc changes
        object.__setattr__(self, '_real_ydoc', self.ydoc)
        
        self.ymap = self.ydoc.get_map("state")
        self.loop = loop or get_or_create_event_loop()
        self.batcher = AsyncTransactionBatcher(self.ydoc, loop=self.loop, batch_time=batch_timeout)
        path_ref = YPathReference(self)
        super().__init__(self.ymap, self.batcher, path_ref)