"""
Mock tests for the Confluence Cloud REST API node.

Exercises every operation with mocked HTTP responses (no live API calls):
- Pages: list, get, create, update, delete, list in space, list children, versions, ancestors
- Blog posts: list, get, create, update, delete
- Spaces: list, get, create, list space labels
- Comments: list/create/update/delete footer & inline (pages + blog posts)
- Attachments: list, get, upload, delete
- Labels: list page labels, add label, remove label (v1)
- Content properties: list, create, update, delete
- Tasks: list, get, update
- Search & user: search, search content, current user (all v1)
- Error handling: API errors, missing credentials
- Dynamic options: space dropdown
- OAuth credential: token-refresh path + api.atlassian.com routing
"""

import pytest
from unittest.mock import AsyncMock, Mock, patch

from nodes.confluence_node import (
    ConfluenceNode,
    ConfluenceNodeConfig,
    ConfluenceApiTokenCredential,
    ConfluenceOAuthCredential,
    ConfluenceListPagesConfig,
    ConfluenceGetPageConfig,
    ConfluenceCreatePageConfig,
    ConfluenceUpdatePageConfig,
    ConfluenceDeletePageConfig,
    ConfluenceListPagesInSpaceConfig,
    ConfluenceListChildPagesConfig,
    ConfluenceGetPageVersionsConfig,
    ConfluenceGetPageAncestorsConfig,
    ConfluenceListBlogPostsConfig,
    ConfluenceGetBlogPostConfig,
    ConfluenceCreateBlogPostConfig,
    ConfluenceUpdateBlogPostConfig,
    ConfluenceDeleteBlogPostConfig,
    ConfluenceListSpacesConfig,
    ConfluenceGetSpaceConfig,
    ConfluenceCreateSpaceConfig,
    ConfluenceListSpaceLabelsConfig,
    ConfluenceListFooterCommentsConfig,
    ConfluenceCreateFooterCommentConfig,
    ConfluenceUpdateFooterCommentConfig,
    ConfluenceDeleteFooterCommentConfig,
    ConfluenceListBlogPostFooterCommentsConfig,
    ConfluenceListInlineCommentsConfig,
    ConfluenceCreateInlineCommentConfig,
    ConfluenceUpdateInlineCommentConfig,
    ConfluenceDeleteInlineCommentConfig,
    ConfluenceListBlogPostInlineCommentsConfig,
    ConfluenceListAttachmentsConfig,
    ConfluenceGetAttachmentConfig,
    ConfluenceUploadAttachmentConfig,
    ConfluenceDeleteAttachmentConfig,
    ConfluenceListPageLabelsConfig,
    ConfluenceAddLabelConfig,
    ConfluenceRemoveLabelConfig,
    ConfluenceListContentPropertiesConfig,
    ConfluenceCreateContentPropertyConfig,
    ConfluenceUpdateContentPropertyConfig,
    ConfluenceDeleteContentPropertyConfig,
    ConfluenceListTasksConfig,
    ConfluenceGetTaskConfig,
    ConfluenceUpdateTaskConfig,
    ConfluenceSearchConfig,
    ConfluenceSearchContentConfig,
    ConfluenceGetCurrentUserConfig,
    ConfluenceOnNewContentConfig,
)


@pytest.fixture
def api_token_credentials():
    return ConfluenceApiTokenCredential(
        email="ada@example.com",
        api_token="atatt_test_token",
        domain="acme.atlassian.net",
    )


def create_confluence_node(config):
    return ConfluenceNode(
        node_id="test-confluence-node",
        node_type="automation-confluence",
        node_data={},
        config=config,
        sio=Mock(),
        sid="test-sid",
        workflow_id="test-workflow",
        user_id="test-user",
    )


def create_mock_response(status_code=200, json_data=None):
    mock_response = Mock()
    mock_response.status_code = status_code
    mock_response.text = ""
    mock_response.json = lambda: (json_data if json_data is not None else {})
    return mock_response


def create_mock_client(status_code=200, json_data=None, capture=None):
    """Mock httpx.AsyncClient whose .request() returns the mock response and
    which works as an async context manager. ``capture`` (a dict) records the
    last request's url/method/json/params for assertion."""
    mock_response = create_mock_response(status_code, json_data)
    mock_client = Mock()

    async def async_request(*args, **kwargs):
        if capture is not None:
            capture.update(kwargs)
        return mock_response

    mock_client.request = async_request

    async def aenter(self):
        return mock_client

    async def aexit(self, *args):
        return None

    mock_client.__aenter__ = aenter
    mock_client.__aexit__ = aexit
    return mock_client


# ============================================================================
# Pages
# ============================================================================


class TestConfluencePagesMock:
    @pytest.mark.asyncio
    async def test_list_pages(self, api_token_credentials):
        config = ConfluenceNodeConfig(
            config=ConfluenceListPagesConfig(space_id="123", status="current"),
            credentials=api_token_credentials,
        )
        node = create_confluence_node(config)
        capture: dict = {}
        mock_client = create_mock_client(
            200, {"results": [{"id": "p1"}, {"id": "p2"}]}, capture
        )
        with patch("nodes.confluence_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "list_pages"
        assert len(result["data"]["results"]) == 2
        # Basic-auth routes to the site domain, v2 path
        assert capture["url"] == "https://acme.atlassian.net/wiki/api/v2/pages"
        assert capture["params"]["space-id"] == "123"

    @pytest.mark.asyncio
    async def test_get_page(self, api_token_credentials):
        config = ConfluenceNodeConfig(
            config=ConfluenceGetPageConfig(page_id="555", body_format="storage"),
            credentials=api_token_credentials,
        )
        node = create_confluence_node(config)
        capture: dict = {}
        mock_client = create_mock_client(200, {"id": "555", "title": "Runbook"}, capture)
        with patch("nodes.confluence_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "get_page"
        assert result["data"]["id"] == "555"
        assert capture["params"]["body-format"] == "storage"

    @pytest.mark.asyncio
    async def test_create_page(self, api_token_credentials):
        config = ConfluenceNodeConfig(
            config=ConfluenceCreatePageConfig(
                space_id="123", title="New Page", body="<p>hi</p>", parent_id="9"
            ),
            credentials=api_token_credentials,
        )
        node = create_confluence_node(config)
        capture: dict = {}
        mock_client = create_mock_client(200, {"id": "777", "title": "New Page"}, capture)
        with patch("nodes.confluence_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "create_page"
        assert result["data"]["id"] == "777"
        assert capture["json"]["spaceId"] == "123"
        assert capture["json"]["body"] == {"representation": "storage", "value": "<p>hi</p>"}
        assert capture["json"]["parentId"] == "9"

    @pytest.mark.asyncio
    async def test_update_page(self, api_token_credentials):
        config = ConfluenceNodeConfig(
            config=ConfluenceUpdatePageConfig(
                page_id="555", version_number="3", title="Runbook", body="<p>v2</p>"
            ),
            credentials=api_token_credentials,
        )
        node = create_confluence_node(config)
        capture: dict = {}
        mock_client = create_mock_client(200, {"id": "555", "version": {"number": 3}}, capture)
        with patch("nodes.confluence_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "update_page"
        assert capture["json"]["version"]["number"] == 3

    @pytest.mark.asyncio
    async def test_delete_page(self, api_token_credentials):
        config = ConfluenceNodeConfig(
            config=ConfluenceDeletePageConfig(page_id="555", purge="true"),
            credentials=api_token_credentials,
        )
        node = create_confluence_node(config)
        capture: dict = {}
        mock_client = create_mock_client(204, None, capture)
        with patch("nodes.confluence_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "delete_page"
        assert capture["params"]["purge"] == "true"

    @pytest.mark.asyncio
    async def test_list_pages_in_space(self, api_token_credentials):
        config = ConfluenceNodeConfig(
            config=ConfluenceListPagesInSpaceConfig(space_id="123"),
            credentials=api_token_credentials,
        )
        node = create_confluence_node(config)
        capture: dict = {}
        mock_client = create_mock_client(200, {"results": [{"id": "p1"}]}, capture)
        with patch("nodes.confluence_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "list_pages_in_space"
        assert capture["url"].endswith("/spaces/123/pages")

    @pytest.mark.asyncio
    async def test_list_child_pages(self, api_token_credentials):
        config = ConfluenceNodeConfig(
            config=ConfluenceListChildPagesConfig(page_id="555"),
            credentials=api_token_credentials,
        )
        node = create_confluence_node(config)
        capture: dict = {}
        mock_client = create_mock_client(200, {"results": []}, capture)
        with patch("nodes.confluence_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "list_child_pages"
        assert capture["url"].endswith("/pages/555/children")

    @pytest.mark.asyncio
    async def test_get_page_versions(self, api_token_credentials):
        config = ConfluenceNodeConfig(
            config=ConfluenceGetPageVersionsConfig(page_id="555"),
            credentials=api_token_credentials,
        )
        node = create_confluence_node(config)
        capture: dict = {}
        mock_client = create_mock_client(200, {"results": [{"number": 1}]}, capture)
        with patch("nodes.confluence_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "get_page_versions"
        assert capture["url"].endswith("/pages/555/versions")


# ============================================================================
# Blog posts
# ============================================================================


class TestConfluenceBlogPostsMock:
    @pytest.mark.asyncio
    async def test_list_blog_posts(self, api_token_credentials):
        config = ConfluenceNodeConfig(
            config=ConfluenceListBlogPostsConfig(space_id="123"),
            credentials=api_token_credentials,
        )
        node = create_confluence_node(config)
        mock_client = create_mock_client(200, {"results": [{"id": "b1"}]})
        with patch("nodes.confluence_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "list_blog_posts"

    @pytest.mark.asyncio
    async def test_get_blog_post(self, api_token_credentials):
        config = ConfluenceNodeConfig(
            config=ConfluenceGetBlogPostConfig(blog_post_id="b1"),
            credentials=api_token_credentials,
        )
        node = create_confluence_node(config)
        mock_client = create_mock_client(200, {"id": "b1", "title": "News"})
        with patch("nodes.confluence_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "get_blog_post"
        assert result["data"]["id"] == "b1"

    @pytest.mark.asyncio
    async def test_create_blog_post(self, api_token_credentials):
        config = ConfluenceNodeConfig(
            config=ConfluenceCreateBlogPostConfig(
                space_id="123", title="Launch", body="<p>ship</p>"
            ),
            credentials=api_token_credentials,
        )
        node = create_confluence_node(config)
        capture: dict = {}
        mock_client = create_mock_client(200, {"id": "b2"}, capture)
        with patch("nodes.confluence_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "create_blog_post"
        assert capture["json"]["spaceId"] == "123"

    @pytest.mark.asyncio
    async def test_update_blog_post(self, api_token_credentials):
        config = ConfluenceNodeConfig(
            config=ConfluenceUpdateBlogPostConfig(
                blog_post_id="b1", version_number="2", title="Launch"
            ),
            credentials=api_token_credentials,
        )
        node = create_confluence_node(config)
        capture: dict = {}
        mock_client = create_mock_client(200, {"id": "b1"}, capture)
        with patch("nodes.confluence_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "update_blog_post"
        assert capture["json"]["version"]["number"] == 2

    @pytest.mark.asyncio
    async def test_delete_blog_post(self, api_token_credentials):
        config = ConfluenceNodeConfig(
            config=ConfluenceDeleteBlogPostConfig(blog_post_id="b1"),
            credentials=api_token_credentials,
        )
        node = create_confluence_node(config)
        mock_client = create_mock_client(204, None)
        with patch("nodes.confluence_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "delete_blog_post"


# ============================================================================
# Spaces
# ============================================================================


class TestConfluenceSpacesMock:
    @pytest.mark.asyncio
    async def test_list_spaces(self, api_token_credentials):
        config = ConfluenceNodeConfig(
            config=ConfluenceListSpacesConfig(keys="DEV,OPS", type="global"),
            credentials=api_token_credentials,
        )
        node = create_confluence_node(config)
        capture: dict = {}
        mock_client = create_mock_client(200, {"results": [{"id": "s1"}]}, capture)
        with patch("nodes.confluence_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "list_spaces"
        assert capture["params"]["keys"] == ["DEV", "OPS"]

    @pytest.mark.asyncio
    async def test_get_space(self, api_token_credentials):
        config = ConfluenceNodeConfig(
            config=ConfluenceGetSpaceConfig(space_id="123"),
            credentials=api_token_credentials,
        )
        node = create_confluence_node(config)
        mock_client = create_mock_client(200, {"id": "123", "key": "DEV"})
        with patch("nodes.confluence_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "get_space"
        assert result["data"]["key"] == "DEV"

    @pytest.mark.asyncio
    async def test_list_space_labels(self, api_token_credentials):
        config = ConfluenceNodeConfig(
            config=ConfluenceListSpaceLabelsConfig(space_id="123"),
            credentials=api_token_credentials,
        )
        node = create_confluence_node(config)
        capture: dict = {}
        mock_client = create_mock_client(200, {"results": [{"name": "team"}]}, capture)
        with patch("nodes.confluence_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "list_space_labels"
        assert capture["url"].endswith("/spaces/123/labels")


# ============================================================================
# Comments
# ============================================================================


class TestConfluenceCommentsMock:
    @pytest.mark.asyncio
    async def test_list_footer_comments(self, api_token_credentials):
        config = ConfluenceNodeConfig(
            config=ConfluenceListFooterCommentsConfig(page_id="555"),
            credentials=api_token_credentials,
        )
        node = create_confluence_node(config)
        capture: dict = {}
        mock_client = create_mock_client(200, {"results": []}, capture)
        with patch("nodes.confluence_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "list_footer_comments"
        assert capture["url"].endswith("/pages/555/footer-comments")

    @pytest.mark.asyncio
    async def test_create_footer_comment(self, api_token_credentials):
        config = ConfluenceNodeConfig(
            config=ConfluenceCreateFooterCommentConfig(page_id="555", body="Nice work"),
            credentials=api_token_credentials,
        )
        node = create_confluence_node(config)
        capture: dict = {}
        mock_client = create_mock_client(200, {"id": "c1"}, capture)
        with patch("nodes.confluence_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "create_footer_comment"
        assert capture["json"]["pageId"] == "555"
        assert capture["json"]["body"]["value"] == "Nice work"

    @pytest.mark.asyncio
    async def test_list_inline_comments(self, api_token_credentials):
        config = ConfluenceNodeConfig(
            config=ConfluenceListInlineCommentsConfig(page_id="555"),
            credentials=api_token_credentials,
        )
        node = create_confluence_node(config)
        capture: dict = {}
        mock_client = create_mock_client(200, {"results": []}, capture)
        with patch("nodes.confluence_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "list_inline_comments"
        assert capture["url"].endswith("/pages/555/inline-comments")

    @pytest.mark.asyncio
    async def test_create_inline_comment(self, api_token_credentials):
        config = ConfluenceNodeConfig(
            config=ConfluenceCreateInlineCommentConfig(
                page_id="555", body="typo here", selection_text="teh"
            ),
            credentials=api_token_credentials,
        )
        node = create_confluence_node(config)
        capture: dict = {}
        # The handler first GETs the page body to count anchor-text occurrences,
        # then POSTs the comment; the mock body contains the selection once.
        mock_client = create_mock_client(
            200,
            {"id": "c2", "body": {"storage": {"value": "the teh typo"}}},
            capture,
        )
        with patch("nodes.confluence_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "create_inline_comment"
        props = capture["json"]["inlineCommentProperties"]
        assert props["textSelection"] == "teh"
        # Both match fields are now mandatory in the v2 payload.
        assert props["textSelectionMatchCount"] == 1
        assert props["textSelectionMatchIndex"] == 0


# ============================================================================
# Attachments
# ============================================================================


class TestConfluenceAttachmentsMock:
    @pytest.mark.asyncio
    async def test_list_attachments(self, api_token_credentials):
        config = ConfluenceNodeConfig(
            config=ConfluenceListAttachmentsConfig(page_id="555"),
            credentials=api_token_credentials,
        )
        node = create_confluence_node(config)
        capture: dict = {}
        mock_client = create_mock_client(200, {"results": [{"id": "att1"}]}, capture)
        with patch("nodes.confluence_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "list_attachments"
        assert capture["url"].endswith("/pages/555/attachments")

    @pytest.mark.asyncio
    async def test_get_attachment(self, api_token_credentials):
        config = ConfluenceNodeConfig(
            config=ConfluenceGetAttachmentConfig(attachment_id="att1"),
            credentials=api_token_credentials,
        )
        node = create_confluence_node(config)
        mock_client = create_mock_client(
            200, {"id": "att1", "downloadLink": "/download/att1"}
        )
        with patch("nodes.confluence_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "get_attachment"
        assert result["data"]["downloadLink"] == "/download/att1"


# ============================================================================
# Labels
# ============================================================================


class TestConfluenceLabelsMock:
    @pytest.mark.asyncio
    async def test_list_page_labels(self, api_token_credentials):
        config = ConfluenceNodeConfig(
            config=ConfluenceListPageLabelsConfig(page_id="555"),
            credentials=api_token_credentials,
        )
        node = create_confluence_node(config)
        capture: dict = {}
        mock_client = create_mock_client(200, {"results": [{"name": "bug"}]}, capture)
        with patch("nodes.confluence_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "list_page_labels"
        assert capture["url"].endswith("/pages/555/labels")

    @pytest.mark.asyncio
    async def test_add_label_uses_v1(self, api_token_credentials):
        config = ConfluenceNodeConfig(
            config=ConfluenceAddLabelConfig(content_id="555", label="reviewed"),
            credentials=api_token_credentials,
        )
        node = create_confluence_node(config)
        capture: dict = {}
        mock_client = create_mock_client(200, [{"name": "reviewed"}], capture)
        with patch("nodes.confluence_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "add_label"
        # add-label lives on the v1 surface
        assert capture["url"] == "https://acme.atlassian.net/wiki/rest/api/content/555/label"
        assert capture["json"] == [{"prefix": "global", "name": "reviewed"}]


# ============================================================================
# Content properties
# ============================================================================


class TestConfluencePropertiesMock:
    @pytest.mark.asyncio
    async def test_list_content_properties(self, api_token_credentials):
        config = ConfluenceNodeConfig(
            config=ConfluenceListContentPropertiesConfig(page_id="555"),
            credentials=api_token_credentials,
        )
        node = create_confluence_node(config)
        capture: dict = {}
        mock_client = create_mock_client(200, {"results": []}, capture)
        with patch("nodes.confluence_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "list_content_properties"
        assert capture["url"].endswith("/pages/555/properties")

    @pytest.mark.asyncio
    async def test_create_content_property_parses_json_value(self, api_token_credentials):
        config = ConfluenceNodeConfig(
            config=ConfluenceCreateContentPropertyConfig(
                page_id="555", property_key="sync", property_value='{"enabled": true}'
            ),
            credentials=api_token_credentials,
        )
        node = create_confluence_node(config)
        capture: dict = {}
        mock_client = create_mock_client(200, {"id": "prop1"}, capture)
        with patch("nodes.confluence_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "create_content_property"
        # JSON literal is parsed into an object, not left as a string
        assert capture["json"]["value"] == {"enabled": True}


# ============================================================================
# Search & user (v1)
# ============================================================================


class TestConfluenceSearchMock:
    @pytest.mark.asyncio
    async def test_search(self, api_token_credentials):
        config = ConfluenceNodeConfig(
            config=ConfluenceSearchConfig(cql='text~"release"'),
            credentials=api_token_credentials,
        )
        node = create_confluence_node(config)
        capture: dict = {}
        mock_client = create_mock_client(200, {"results": [{"title": "Release"}]}, capture)
        with patch("nodes.confluence_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "search"
        assert capture["url"] == "https://acme.atlassian.net/wiki/rest/api/search"
        assert capture["params"]["cql"] == 'text~"release"'

    @pytest.mark.asyncio
    async def test_search_content(self, api_token_credentials):
        config = ConfluenceNodeConfig(
            config=ConfluenceSearchContentConfig(cql="type=page"),
            credentials=api_token_credentials,
        )
        node = create_confluence_node(config)
        capture: dict = {}
        mock_client = create_mock_client(200, {"results": []}, capture)
        with patch("nodes.confluence_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "search_content"
        assert capture["url"].endswith("/wiki/rest/api/content/search")

    @pytest.mark.asyncio
    async def test_get_current_user(self, api_token_credentials):
        config = ConfluenceNodeConfig(
            config=ConfluenceGetCurrentUserConfig(),
            credentials=api_token_credentials,
        )
        node = create_confluence_node(config)
        capture: dict = {}
        mock_client = create_mock_client(200, {"accountId": "acc1"}, capture)
        with patch("nodes.confluence_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "get_current_user"
        assert capture["url"].endswith("/wiki/rest/api/user/current")
        assert result["data"]["accountId"] == "acc1"


# ============================================================================
# OAuth credential routing + token refresh
# ============================================================================


class TestConfluenceOAuthMock:
    @pytest.mark.asyncio
    async def test_oauth_routes_through_api_atlassian(self):
        config = ConfluenceNodeConfig(
            config=ConfluenceGetPageConfig(page_id="555"),
            credentials=ConfluenceOAuthCredential(
                access_token="tok",
                refresh_token="ref",
                expires_at="2999-01-01T00:00:00Z",
                cloud_id="cloud-abc",
            ),
        )
        node = create_confluence_node(config)
        capture: dict = {}
        mock_client = create_mock_client(200, {"id": "555"}, capture)
        # Patch the refresh path so the test stays offline; token is unexpired
        # but execute() still calls _ensure_fresh_token.
        async def _noop_refresh(**kwargs):
            return None

        with patch(
            "nodes.core.oauth_refresh.ensure_fresh_oauth_token", new=_noop_refresh
        ), patch("nodes.confluence_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        # OAuth goes through api.atlassian.com/ex/confluence/{cloudid}
        assert capture["url"] == (
            "https://api.atlassian.com/ex/confluence/cloud-abc/wiki/api/v2/pages/555"
        )
        assert capture["headers"]["Authorization"] == "Bearer tok"


# ============================================================================
# Error handling
# ============================================================================


class TestConfluenceErrorHandlingMock:
    @pytest.mark.asyncio
    async def test_api_error(self, api_token_credentials):
        config = ConfluenceNodeConfig(
            config=ConfluenceGetPageConfig(page_id="missing"),
            credentials=api_token_credentials,
        )
        node = create_confluence_node(config)
        mock_client = create_mock_client(
            404, {"errors": [{"title": "Page not found", "status": 404}]}
        )
        with patch("nodes.confluence_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "error"
        assert result["status_code"] == 404
        assert "not found" in str(result["error"]).lower()

    @pytest.mark.asyncio
    async def test_missing_credentials(self):
        config = ConfluenceNodeConfig(
            config=ConfluenceGetCurrentUserConfig(), credentials=None
        )
        node = create_confluence_node(config)
        with pytest.raises(ValueError, match="Credentials are required"):
            await node.execute({})


# ============================================================================
# Dynamic options (spaces)
# ============================================================================


class TestConfluenceDynamicOptionsMock:
    @pytest.mark.asyncio
    async def test_load_space_options(self):
        cred_data = {
            "credential_type": "confluence_api_token",
            "email": "ada@example.com",
            "api_token": "tok",
            "domain": "acme.atlassian.net",
        }
        with patch(
            "nodes.confluence_node._confluence_request",
            return_value={
                "status": "success",
                "data": {"results": [{"id": "10", "name": "Dev", "key": "DEV"}]},
            },
        ):
            # Non-trigger operation: returns numeric space ID as value.
            result = await ConfluenceNode.load_field_options(
                "space_id", credential_data=cred_data, context={"operation": "list_pages"}
            )
        assert "options" in result
        assert result["options"][0]["value"] == "10"
        assert "DEV" in result["options"][0]["label"]

    @pytest.mark.asyncio
    async def test_load_space_options_trigger_returns_numeric_id(self):
        """on_new_content operation: dropdown returns numeric space ID (v2 API requires it)."""
        cred_data = {
            "credential_type": "confluence_api_token",
            "email": "ada@example.com",
            "api_token": "tok",
            "domain": "acme.atlassian.net",
        }
        with patch(
            "nodes.confluence_node._confluence_request",
            return_value={
                "status": "success",
                "data": {"results": [{"id": "10", "name": "Dev", "key": "DEV"}]},
            },
        ):
            result = await ConfluenceNode.load_field_options(
                "space_id", credential_data=cred_data, context={"operation": "on_new_content"}
            )
        assert result["options"][0]["value"] == "10"  # numeric ID, not key

    @pytest.mark.asyncio
    async def test_load_space_options_search_filter(self):
        """search param filters options by label or key (case-insensitive)."""
        cred_data = {
            "credential_type": "confluence_api_token",
            "email": "ada@example.com",
            "api_token": "tok",
            "domain": "acme.atlassian.net",
        }
        with patch(
            "nodes.confluence_node._confluence_request",
            return_value={
                "status": "success",
                "data": {"results": [
                    {"id": "10", "name": "Dev Space", "key": "DEV"},
                    {"id": "20", "name": "Marketing", "key": "MKT"},
                ]},
            },
        ):
            result = await ConfluenceNode.load_field_options(
                "space_id", credential_data=cred_data, context={}, search="dev"
            )
        assert len(result["options"]) == 1
        assert result["options"][0]["value"] == "10"


# ============================================================================
# Trigger (poll-based: on_new_content)
# ============================================================================


def _v2_page_results(*ids):
    """Build a mocked v2 pages/blogposts response with plain objects, newest-first."""
    return {"results": [{"id": cid, "title": f"Item {cid}", "type": "page"} for cid in ids]}


class TestConfluenceTriggerPayloadResolution:
    def test_resolve_trigger_payload_returns_none_for_poll_op(self):
        # Poll-based trigger: payload (the webhook wake-up) is suppressed so
        # execute() runs and polls the API.
        out = ConfluenceNode.resolve_trigger_payload(
            {"foo": "bar"}, {"operation": "on_new_content"}
        )
        assert out is None

    def test_resolve_trigger_payload_passthrough_for_normal_op(self):
        # Non-trigger ops keep the default push-through behavior.
        payload = {"foo": "bar"}
        out = ConfluenceNode.resolve_trigger_payload(
            payload, {"operation": "list_pages"}
        )
        assert out == payload


def _bind_confluence_state(node, initial=None):
    """Back the node's break-cursor with an in-memory node-state store (the
    cursor now lives in workflow_node_state, not config)."""
    store = dict(initial or {})

    async def _update(mutator, *, max_retries=4, skip_result=None):
        new_state, result = mutator(dict(store))
        if new_state is not None:
            store.clear()
            store.update(new_state)
        return result

    node._update_node_state = _update
    return store


class TestConfluenceTriggerPollMock:
    @pytest.mark.asyncio
    async def test_first_poll_baselines_without_emitting(self, api_token_credentials):
        # No cursor yet -> baseline on the newest item, emit nothing (no backlog).
        config = ConfluenceNodeConfig(
            config=ConfluenceOnNewContentConfig(content_type="page"),
            credentials=api_token_credentials,
        )
        node = create_confluence_node(config)
        store = _bind_confluence_state(node)
        capture: dict = {}
        mock_client = create_mock_client(200, _v2_page_results("300", "200", "100"), capture)
        with patch("nodes.confluence_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["operation"] == "on_new_content"
        assert result["first_poll"] is True
        assert result["new_count"] == 0
        assert result["items"] == []
        # Cursor advances to the newest item (highest id) so next poll has a
        # boundary — and persists to node state, not config.
        assert result["last_seen_id"] == "300"
        assert store == {"last_seen_id": "300"}
        # Uses v2 pages endpoint with created-date sort.
        assert "/wiki/api/v2/pages" in capture["url"]
        assert capture["params"]["sort"] == "-created-date"

    @pytest.mark.asyncio
    async def test_emits_only_new_items_since_cursor(self, api_token_credentials):
        # Cursor at "100": items 300,200,100 -> emit 300,200 (stop at cursor).
        config = ConfluenceNodeConfig(
            config=ConfluenceOnNewContentConfig(content_type="page"),
            credentials=api_token_credentials,
        )
        node = create_confluence_node(config)
        store = _bind_confluence_state(node, {"last_seen_id": "100"})
        mock_client = create_mock_client(200, _v2_page_results("300", "200", "100"))
        with patch("nodes.confluence_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["first_poll"] is False
        assert result["new_count"] == 2
        emitted_ids = [it["id"] for it in result["items"]]
        assert emitted_ids == ["300", "200"]
        assert result["last_seen_id"] == "300"
        assert store == {"last_seen_id": "300"}

    @pytest.mark.asyncio
    async def test_dedupes_when_nothing_new(self, api_token_credentials):
        # Cursor already at the newest item -> emit nothing.
        config = ConfluenceNodeConfig(
            config=ConfluenceOnNewContentConfig(content_type="page"),
            credentials=api_token_credentials,
        )
        node = create_confluence_node(config)
        _bind_confluence_state(node, {"last_seen_id": "300"})
        mock_client = create_mock_client(200, _v2_page_results("300", "200", "100"))
        with patch("nodes.confluence_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["new_count"] == 0
        assert result["items"] == []
        assert result["last_seen_id"] == "300"

    @pytest.mark.asyncio
    async def test_all_content_type_polls_pages_and_blogposts(self, api_token_credentials):
        # content_type="all" fires two concurrent requests (pages + blogposts).
        config = ConfluenceNodeConfig(
            config=ConfluenceOnNewContentConfig(
                content_type="all", space_id="1146889"
            ),
            credentials=api_token_credentials,
        )
        node = create_confluence_node(config)
        _bind_confluence_state(node, {"last_seen_id": "1"})
        # Both calls return the same mock body; the implementation merges + dedupes by id.
        mock_client = create_mock_client(200, _v2_page_results("300", "200"))
        with patch("nodes.confluence_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        # Both pages (300,200) and blogposts (300,200) fetched; merged and cursor-filtered.
        # After sort by id desc and dedup, new_count >= 2.
        assert result["new_count"] >= 2

    @pytest.mark.asyncio
    async def test_space_filter_passed_as_space_id_param(self, api_token_credentials):
        # When space_id is set, it's passed as the space-id query param (numeric).
        config = ConfluenceNodeConfig(
            config=ConfluenceOnNewContentConfig(
                content_type="page", space_id="1146889", last_seen_id="999"
            ),
            credentials=api_token_credentials,
        )
        node = create_confluence_node(config)
        capture: dict = {}
        mock_client = create_mock_client(200, _v2_page_results("1000"), capture)
        with patch("nodes.confluence_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert capture["params"]["space-id"] == "1146889"

    @pytest.mark.asyncio
    async def test_load_field_value_provisions_webhook_and_schedule(
        self, api_token_credentials
    ):
        import uuid as _uuid

        async def _get_or_create(**kwargs):
            return {"webhook_id": "wh-1", "webhook_url": "https://hook.example/abc"}

        async def _create_schedule(**kwargs):
            return {"id": "sch-1", "next_run": "2026-07-01T00:00:00Z"}

        with patch(
            "utils.webhook_manager.WebhookManager.get_or_create_webhook",
            new=_get_or_create,
        ), patch(
            "utils.cron_scheduler_client.is_cron_scheduler_enabled", return_value=True
        ), patch(
            "utils.cron_scheduler_client.create_schedule", new=_create_schedule
        ):
            out = await ConfluenceNode.load_field_value(
                "webhook_url",
                user_id="user-1",
                workflow_id=_uuid.uuid4(),
                node_id="node-1",
                pool=Mock(),
                context={"schedule": {"frequency": "minutes", "interval": 5}},
            )
        vals = out["values"]
        assert vals["webhook_id"] == "wh-1"
        assert vals["webhook_url"] == "https://hook.example/abc"
        assert vals["schedule_id"] == "sch-1"
        assert vals["next_run"] == "2026-07-01T00:00:00Z"
        # minutes/5 -> 300_000 ms
        assert vals["interval_ms"] == 5 * 60 * 1000
        assert vals["is_active"] is True


# ============================================================================
# New operations — comments (update/delete/blog)
# ============================================================================


class TestConfluenceNewCommentsMock:
    @pytest.mark.asyncio
    async def test_update_footer_comment(self, api_token_credentials):
        config = ConfluenceNodeConfig(
            config=ConfluenceUpdateFooterCommentConfig(
                comment_id="c-1", version_number="2", body="Updated body"
            ),
            credentials=api_token_credentials,
        )
        node = create_confluence_node(config)
        capture: dict = {}
        mock_client = create_mock_client(200, {"id": "c-1"}, capture)
        with patch("nodes.confluence_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert capture["method"] == "PUT"
        assert "/footer-comments/c-1" in capture["url"]
        assert capture["json"]["version"]["number"] == 2

    @pytest.mark.asyncio
    async def test_delete_footer_comment(self, api_token_credentials):
        config = ConfluenceNodeConfig(
            config=ConfluenceDeleteFooterCommentConfig(comment_id="c-2"),
            credentials=api_token_credentials,
        )
        node = create_confluence_node(config)
        mock_client = create_mock_client(204, None)
        with patch("nodes.confluence_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"

    @pytest.mark.asyncio
    async def test_update_inline_comment(self, api_token_credentials):
        config = ConfluenceNodeConfig(
            config=ConfluenceUpdateInlineCommentConfig(
                comment_id="ic-1", version_number="3", body="New body"
            ),
            credentials=api_token_credentials,
        )
        node = create_confluence_node(config)
        capture: dict = {}
        mock_client = create_mock_client(200, {"id": "ic-1"}, capture)
        with patch("nodes.confluence_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert "/inline-comments/ic-1" in capture["url"]

    @pytest.mark.asyncio
    async def test_delete_inline_comment(self, api_token_credentials):
        config = ConfluenceNodeConfig(
            config=ConfluenceDeleteInlineCommentConfig(comment_id="ic-2"),
            credentials=api_token_credentials,
        )
        node = create_confluence_node(config)
        mock_client = create_mock_client(204, None)
        with patch("nodes.confluence_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"

    @pytest.mark.asyncio
    async def test_list_blog_post_footer_comments(self, api_token_credentials):
        config = ConfluenceNodeConfig(
            config=ConfluenceListBlogPostFooterCommentsConfig(blog_post_id="bp-1"),
            credentials=api_token_credentials,
        )
        node = create_confluence_node(config)
        capture: dict = {}
        mock_client = create_mock_client(200, {"results": []}, capture)
        with patch("nodes.confluence_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert "/blogposts/bp-1/footer-comments" in capture["url"]

    @pytest.mark.asyncio
    async def test_list_blog_post_inline_comments(self, api_token_credentials):
        config = ConfluenceNodeConfig(
            config=ConfluenceListBlogPostInlineCommentsConfig(blog_post_id="bp-2"),
            credentials=api_token_credentials,
        )
        node = create_confluence_node(config)
        capture: dict = {}
        mock_client = create_mock_client(200, {"results": []}, capture)
        with patch("nodes.confluence_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert "/blogposts/bp-2/inline-comments" in capture["url"]


# ============================================================================
# New operations — attachments (upload/delete)
# ============================================================================


class TestConfluenceNewAttachmentsMock:
    @pytest.mark.asyncio
    async def test_upload_attachment(self, api_token_credentials):
        import base64
        content = base64.b64encode(b"PDF content here").decode()
        config = ConfluenceNodeConfig(
            config=ConfluenceUploadAttachmentConfig(
                page_id="p-1",
                filename="report.pdf",
                file_content_base64=content,
                mime_type="application/pdf",
            ),
            credentials=api_token_credentials,
        )
        node = create_confluence_node(config)
        # upload_attachment uses a direct httpx.AsyncClient (not _confluence_request)
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json = lambda: {"results": [{"id": "att-1"}]}
        mock_client = Mock()

        async def async_post(*args, **kwargs):
            return mock_response

        mock_client.post = async_post

        async def aenter(self):
            return mock_client

        async def aexit(self, *args):
            return None

        mock_client.__aenter__ = aenter
        mock_client.__aexit__ = aexit
        with patch("nodes.confluence_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "upload_attachment"

    @pytest.mark.asyncio
    async def test_upload_attachment_invalid_base64(self, api_token_credentials):
        config = ConfluenceNodeConfig(
            config=ConfluenceUploadAttachmentConfig(
                page_id="p-1",
                filename="report.pdf",
                file_content_base64="not-valid-base64!!!",
            ),
            credentials=api_token_credentials,
        )
        node = create_confluence_node(config)
        mock_client = create_mock_client(200, {})
        with patch("nodes.confluence_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "error"
        assert "base64" in result["error"]

    @pytest.mark.asyncio
    async def test_delete_attachment(self, api_token_credentials):
        config = ConfluenceNodeConfig(
            config=ConfluenceDeleteAttachmentConfig(attachment_id="att-5"),
            credentials=api_token_credentials,
        )
        node = create_confluence_node(config)
        capture: dict = {}
        mock_client = create_mock_client(204, None, capture)
        with patch("nodes.confluence_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert "/attachments/att-5" in capture["url"]


# ============================================================================
# New operations — labels (remove)
# ============================================================================


class TestConfluenceNewLabelsMock:
    @pytest.mark.asyncio
    async def test_remove_label_uses_v1(self, api_token_credentials):
        config = ConfluenceNodeConfig(
            config=ConfluenceRemoveLabelConfig(content_id="p-1", label="needs-review"),
            credentials=api_token_credentials,
        )
        node = create_confluence_node(config)
        capture: dict = {}
        mock_client = create_mock_client(204, None, capture)
        with patch("nodes.confluence_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert "/rest/api/content/p-1/label" in capture["url"]
        assert capture["method"] == "DELETE"
        assert capture["params"]["name"] == "needs-review"


# ============================================================================
# New operations — content properties (update/delete)
# ============================================================================


class TestConfluenceNewPropertiesMock:
    @pytest.mark.asyncio
    async def test_update_content_property(self, api_token_credentials):
        config = ConfluenceNodeConfig(
            config=ConfluenceUpdateContentPropertyConfig(
                page_id="p-1",
                property_id="prop-1",
                property_key="my-key",
                property_value='"new value"',
                version_number="2",
            ),
            credentials=api_token_credentials,
        )
        node = create_confluence_node(config)
        capture: dict = {}
        mock_client = create_mock_client(200, {"id": "prop-1"}, capture)
        with patch("nodes.confluence_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert "/pages/p-1/properties/prop-1" in capture["url"]
        assert capture["method"] == "PUT"
        assert capture["json"]["version"]["number"] == 2

    @pytest.mark.asyncio
    async def test_delete_content_property(self, api_token_credentials):
        config = ConfluenceNodeConfig(
            config=ConfluenceDeleteContentPropertyConfig(page_id="p-1", property_id="prop-1"),
            credentials=api_token_credentials,
        )
        node = create_confluence_node(config)
        capture: dict = {}
        mock_client = create_mock_client(204, None, capture)
        with patch("nodes.confluence_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert capture["method"] == "DELETE"


# ============================================================================
# New operations — tasks
# ============================================================================


class TestConfluenceTasksMock:
    @pytest.mark.asyncio
    async def test_list_tasks(self, api_token_credentials):
        config = ConfluenceNodeConfig(
            config=ConfluenceListTasksConfig(status="incomplete", limit="10"),
            credentials=api_token_credentials,
        )
        node = create_confluence_node(config)
        capture: dict = {}
        mock_client = create_mock_client(200, {"results": [{"id": "t-1"}]}, capture)
        with patch("nodes.confluence_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert "/api/v2/tasks" in capture["url"]
        assert capture["params"]["status"] == "incomplete"

    @pytest.mark.asyncio
    async def test_get_task(self, api_token_credentials):
        config = ConfluenceNodeConfig(
            config=ConfluenceGetTaskConfig(task_id="t-42"),
            credentials=api_token_credentials,
        )
        node = create_confluence_node(config)
        capture: dict = {}
        mock_client = create_mock_client(200, {"id": "t-42"}, capture)
        with patch("nodes.confluence_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert "/tasks/t-42" in capture["url"]

    @pytest.mark.asyncio
    async def test_update_task_complete(self, api_token_credentials):
        config = ConfluenceNodeConfig(
            config=ConfluenceUpdateTaskConfig(task_id="t-42", status="complete"),
            credentials=api_token_credentials,
        )
        node = create_confluence_node(config)
        capture: dict = {}
        mock_client = create_mock_client(200, {"id": "t-42", "status": "complete"}, capture)
        with patch("nodes.confluence_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert capture["method"] == "PUT"
        assert capture["json"]["status"] == "complete"


# ============================================================================
# New operations — spaces (create) + pages (ancestors)
# ============================================================================


class TestConfluenceNewSpacesPagesMock:
    @pytest.mark.asyncio
    async def test_create_space(self, api_token_credentials):
        config = ConfluenceNodeConfig(
            config=ConfluenceCreateSpaceConfig(
                name="Engineering", key="ENG", description="Engineering team space"
            ),
            credentials=api_token_credentials,
        )
        node = create_confluence_node(config)
        capture: dict = {}
        mock_client = create_mock_client(200, {"id": "s-1", "key": "ENG"}, capture)
        with patch("nodes.confluence_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert capture["method"] == "POST"
        assert "/spaces" in capture["url"]
        assert capture["json"]["key"] == "ENG"

    @pytest.mark.asyncio
    async def test_get_page_ancestors(self, api_token_credentials):
        # The implementation walks parentId chain: p-10 → parent-1 → root (no parent).
        # Each hop is a separate /pages/{id} GET, so we need sequential responses.
        config = ConfluenceNodeConfig(
            config=ConfluenceGetPageAncestorsConfig(page_id="p-10"),
            credentials=api_token_credentials,
        )
        node = create_confluence_node(config)

        responses = [
            create_mock_response(200, {"id": "p-10", "parentId": "parent-1", "parentType": "page"}),
            create_mock_response(200, {"id": "parent-1", "parentId": "root-1", "parentType": "page"}),
            create_mock_response(200, {"id": "root-1", "parentId": None}),
        ]
        call_index = {"i": 0}

        async def async_request(*args, **kwargs):
            resp = responses[min(call_index["i"], len(responses) - 1)]
            call_index["i"] += 1
            return resp

        mock_client = Mock()
        mock_client.request = async_request
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        with patch("nodes.confluence_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})

        assert result["status"] == "success"
        ancestors = result["data"]["results"]
        # root first (reversed), then parent, child page itself is not in the list
        assert len(ancestors) == 2
        assert ancestors[0]["id"] == "root-1"
        assert ancestors[1]["id"] == "parent-1"


# ============================================================================
# CQL space filter verification
# ============================================================================


