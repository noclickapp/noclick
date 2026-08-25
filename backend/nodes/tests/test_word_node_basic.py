"""
Basic tests for Word node to verify core functionality.
Tests a representative sample of operations to ensure the node is working correctly.
"""

import pytest
import base64
from pathlib import Path
from unittest.mock import AsyncMock, patch, MagicMock
from dotenv import load_dotenv
from nodes.word_node import (
    WordNode,
    WordNodeConfig,
    WordOAuthCredential,
    WordListDocumentsConfig,
    WordGetDocumentConfig,
    WordDownloadDocumentConfig,
    WordConvertToPDFConfig,
    WordCreateSharingLinkConfig,
    WordGetThumbnailConfig,
)
from utils.ssrf import SSRFError

env_path = Path(__file__).parent.parent.parent / ".env"
load_dotenv(dotenv_path=env_path)


def create_node_mock(config):
    """Create a WordNode instance with mock credentials for testing."""
    mock_credentials = WordOAuthCredential(
        access_token="mock_access_token_12345",
        refresh_token="mock_refresh_token_67890",
        expires_at="2099-12-31T23:59:59Z",
        email="test@example.com",
    )

    node_config = WordNodeConfig(config=config, credentials=mock_credentials)
    return WordNode(
        node_id="test-word-node",
        node_type="automation-word",
        node_data={},
        config=node_config,
        sio=None,
        sid=None,
        workflow_id="test-workflow",
        user_id="test-user",
    )


@pytest.mark.asyncio
async def test_list_documents():
    """Test listing Word documents"""
    config = WordListDocumentsConfig(
        folder_id=None, folder_path=None, search_query="report", max_results=10
    )

    word_node = create_node_mock(config)

    mock_response = MagicMock()
    mock_response.json.return_value = {
        "value": [
            {"id": "doc1", "name": "report.docx", "size": 12345},
            {"id": "doc2", "name": "presentation.pptx", "size": 23456},
            {"id": "doc3", "name": "quarterly_report.docx", "size": 34567},
        ]
    }

    with patch.object(word_node, "_make_request", return_value=mock_response):
        result = await word_node.execute({})

    assert result["count"] == 2  # Only .docx files with 'report' in name
    assert len(result["documents"]) == 2


@pytest.mark.asyncio
async def test_get_document():
    """Test getting document metadata"""
    config = WordGetDocumentConfig(document_id="doc123", document_path=None)

    word_node = create_node_mock(config)

    mock_response = MagicMock()
    mock_response.json.return_value = {
        "id": "doc123",
        "name": "report.docx",
        "size": 12345,
    }

    with patch.object(word_node, "_make_request", return_value=mock_response):
        result = await word_node.execute({})

    assert result["id"] == "doc123"
    assert result["name"] == "report.docx"


@pytest.mark.asyncio
async def test_download_document():
    """Test downloading document content resolves to a stored file reference"""
    config = WordDownloadDocumentConfig(document_id="doc123", return_format="base64")

    word_node = create_node_mock(config)

    test_content = b"This is the document content"
    mock_response = MagicMock()
    mock_response.content = test_content

    resource_ref = {
        "download_url": "https://r2.example.com/doc123.docx",
        "mime_type": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "name": "doc123.docx",
        "size_bytes": len(test_content),
    }

    with patch.object(word_node, "_make_request", return_value=mock_response), patch(
        "nodes.core.binary_output.create_resource_from_bytes",
        new=AsyncMock(return_value=resource_ref),
    ) as mock_store:
        result = await word_node.run({})

    assert "content_base64" not in result
    assert result["content"]["url"] == resource_ref["download_url"]
    assert result["content"]["size_bytes"] == len(test_content)
    # The exact downloaded bytes were handed to the resolver, not base64.
    assert mock_store.call_args.kwargs["body"] == test_content
    assert (
        mock_store.call_args.kwargs["content_type"]
        == "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    )


@pytest.mark.asyncio
async def test_convert_to_pdf():
    """Test converting document to PDF resolves to a stored file reference"""
    config = WordConvertToPDFConfig(document_id="doc123", return_format="base64")

    word_node = create_node_mock(config)

    test_pdf_content = b"%PDF-1.4 test content"
    mock_response = MagicMock()
    mock_response.content = test_pdf_content

    resource_ref = {
        "download_url": "https://r2.example.com/doc123.pdf",
        "mime_type": "application/pdf",
        "name": "doc123.pdf",
        "size_bytes": len(test_pdf_content),
    }

    with patch.object(word_node, "_make_request", return_value=mock_response), patch(
        "nodes.core.binary_output.create_resource_from_bytes",
        new=AsyncMock(return_value=resource_ref),
    ) as mock_store:
        result = await word_node.run({})

    assert "pdf_content_base64" not in result
    assert result["pdf"]["url"] == resource_ref["download_url"]
    assert result["pdf"]["mime_type"] == "application/pdf"
    # metadata preserved alongside the resolved reference
    assert result["pdf"]["note"] == "PDF generated from Word document"
    assert mock_store.call_args.kwargs["body"] == test_pdf_content
    assert mock_store.call_args.kwargs["content_type"] == "application/pdf"


@pytest.mark.asyncio
async def test_create_sharing_link():
    """Test creating a sharing link"""
    config = WordCreateSharingLinkConfig(
        document_id="doc123",
        link_type="view",
        scope="anonymous",
        expiration_datetime=None,
    )

    word_node = create_node_mock(config)

    mock_response = MagicMock()
    mock_response.json.return_value = {
        "link": {"webUrl": "https://example.com/share/doc123", "type": "view"}
    }

    with patch.object(word_node, "_make_request", return_value=mock_response):
        result = await word_node.execute({})

    assert result["link"]["webUrl"] == "https://example.com/share/doc123"


@pytest.mark.asyncio
async def test_load_field_options_documents():
    """Test loading document options for dropdown"""
    credential_data = {
        "access_token": "test_token",
        "refresh_token": "test_refresh",
        "expires_at": "2099-12-31T23:59:59Z",
        "email": "test@example.com",
    }

    mock_response = MagicMock()
    mock_response.json.return_value = {
        "value": [
            {
                "id": "doc1",
                "name": "report.docx",
                "lastModifiedDateTime": "2024-01-01T00:00:00Z",
            },
            {
                "id": "doc2",
                "name": "presentation.pptx",
                "lastModifiedDateTime": "2024-01-02T00:00:00Z",
            },
            {
                "id": "doc3",
                "name": "notes.docx",
                "lastModifiedDateTime": "2024-01-03T00:00:00Z",
            },
        ]
    }

    with patch("httpx.AsyncClient") as mock_client:
        mock_client.return_value.__aenter__.return_value.get = AsyncMock(
            return_value=mock_response
        )
        mock_response.raise_for_status = MagicMock()

        result = await WordNode.load_field_options(
            field_name="document_id",
            credential_data=credential_data,
            context=None,
            page_token=None,
        )

    assert "options" in result
    # Should only return .docx files
    assert len(result["options"]) == 2


@pytest.mark.asyncio
async def test_dynamic_graph_page_cannot_exfiltrate_bearer():
    with patch("httpx.AsyncClient") as client:
        with pytest.raises(SSRFError, match="outside"):
            await WordNode._graph_fetch_page(
                "https://graph.microsoft.com/v1.0/me/drive/root/children",
                {"Authorization": "Bearer secret"},
                "https://evil.example/steal",
                item_to_option=lambda item: item,
            )
    client.assert_not_called()


@pytest.mark.asyncio
async def test_server_thumbnail_url_is_ssrf_guarded():
    node = create_node_mock(
        WordGetThumbnailConfig(
            document_id="doc123",
            size="medium",
            return_format="base64",
        )
    )
    response = MagicMock()
    response.json.return_value = {
        "value": [
            {
                "medium": {
                    "url": "http://169.254.169.254/latest/meta-data",
                    "width": 320,
                    "height": 180,
                }
            }
        ]
    }
    with patch.object(node, "_make_request", new=AsyncMock(return_value=response)):
        with pytest.raises(SSRFError, match="non-public address"):
            await node._get_thumbnail(node._config.config, "secret-bearer")
