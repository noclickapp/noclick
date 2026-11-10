"""Google Books v1 routes: https://books.googleapis.com/$discovery/rest?version=v1"""
from dataclasses import dataclass

@dataclass(frozen=True)
class Operation:
    method: str
    path: str
    contract: str
    fields: tuple[str, ...] = ()
    required: tuple[str, ...] = ()
    body: bool = False

OPERATIONS = {
    'search_volumes': Operation('GET', '/volumes', 'books.volumes.list', ('q', 'max_results', 'start_index', 'order_by', 'filter', 'lang_restrict', 'print_type', 'projection'), ('q',)),
    'get_volume': Operation('GET', '/volumes/{volume_id}', 'books.volumes.get', ('projection',)),
    'list_my_bookshelves': Operation('GET', '/mylibrary/bookshelves', 'books.mylibrary.bookshelves.list'),
    'get_my_bookshelf': Operation('GET', '/mylibrary/bookshelves/{shelf}', 'books.mylibrary.bookshelves.get'),
    'list_my_bookshelf_volumes': Operation('GET', '/mylibrary/bookshelves/{shelf}/volumes', 'books.mylibrary.bookshelves.volumes.list', ('max_results', 'start_index', 'q', 'projection')),
    'add_volume': Operation('POST', '/mylibrary/bookshelves/{shelf}/addVolume', 'books.mylibrary.bookshelves.addVolume', ('volume_id',), ('volume_id',)),
    'remove_volume': Operation('POST', '/mylibrary/bookshelves/{shelf}/removeVolume', 'books.mylibrary.bookshelves.removeVolume', ('volume_id',), ('volume_id',)),
    'move_volume': Operation('POST', '/mylibrary/bookshelves/{shelf}/moveVolume', 'books.mylibrary.bookshelves.moveVolume', ('volume_id', 'volume_position'), ('volume_id', 'volume_position')),
    'clear_bookshelf': Operation('POST', '/mylibrary/bookshelves/{shelf}/clearVolumes', 'books.mylibrary.bookshelves.clearVolumes'),
    'list_public_bookshelves': Operation('GET', '/users/{user_id}/bookshelves', 'books.bookshelves.list'),
    'get_public_bookshelf': Operation('GET', '/users/{user_id}/bookshelves/{shelf}', 'books.bookshelves.get'),
    'list_public_bookshelf_volumes': Operation('GET', '/users/{user_id}/bookshelves/{shelf}/volumes', 'books.bookshelves.volumes.list', ('max_results', 'start_index')),
    'list_annotations': Operation('GET', '/mylibrary/annotations', 'books.mylibrary.annotations.list', ('volume_id', 'layer_id', 'max_results', 'page_token', 'updated_min', 'updated_max')),
    'create_annotation': Operation('POST', '/mylibrary/annotations', 'books.mylibrary.annotations.insert', ('annotation',), ('annotation',), True),
    'update_annotation': Operation('PUT', '/mylibrary/annotations/{annotation_id}', 'books.mylibrary.annotations.update', ('annotation',), ('annotation',), True),
    'delete_annotation': Operation('DELETE', '/mylibrary/annotations/{annotation_id}', 'books.mylibrary.annotations.delete'),
    'get_reading_position': Operation('GET', '/mylibrary/readingpositions/{volume_id}', 'books.mylibrary.readingpositions.get', ('content_version',)),
    'set_reading_position': Operation('POST', '/mylibrary/readingpositions/{volume_id}/setPosition', 'books.mylibrary.readingpositions.setPosition', ('position', 'timestamp', 'content_version', 'action'), ('position', 'timestamp')),
    'list_my_books': Operation('GET', '/volumes/mybooks', 'books.volumes.mybooks.list', ('max_results', 'start_index')),
    'list_recommended_volumes': Operation('GET', '/volumes/recommended', 'books.volumes.recommended.list'),
    'rate_recommended_volume': Operation('POST', '/volumes/recommended/rate', 'books.volumes.recommended.rate', ('volume_id', 'rating'), ('volume_id', 'rating')),
}
WIRE_NAMES = {
    'volume_id': 'volumeId', 'user_id': 'userId', 'annotation_id': 'annotationId', 'max_results': 'maxResults',
    'start_index': 'startIndex', 'order_by': 'orderBy', 'lang_restrict': 'langRestrict', 'print_type': 'printType',
    'volume_position': 'volumePosition', 'layer_id': 'layerId', 'page_token': 'pageToken',
    'updated_min': 'updatedMin', 'updated_max': 'updatedMax', 'content_version': 'contentVersion',
}
