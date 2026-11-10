"""Books OAuth scope: https://developers.google.com/books/docs/v1/using#auth"""
from nodes.core.oauth_scopes import ScopeRegistry, ScopeRequirement
from nodes.google_books_operations import OPERATIONS

BOOKS = 'https://www.googleapis.com/auth/books'
GOOGLE_BOOKS_SCOPES = ScopeRegistry(provider='google-books', requirements={
    name: ScopeRequirement((BOOKS,)) for name in (*OPERATIONS, 'on_annotation_updated')})
