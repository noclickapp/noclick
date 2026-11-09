"""Surf Data API operations pinned to AskSurf OpenAPI sha-6a07471.

Each operation performs one request. Lists return one offset page with provider
metadata. SQL submission/cancellation reports the provider job state, not completion.
"""
from __future__ import annotations

from typing import Annotated, Literal, Union
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

BASE_URL = "https://api.asksurf.ai"


class SurfApiKeyCredential(BaseModel):
    model_config = ConfigDict(title="Surf API Key", hide_input_in_errors=True, json_schema_extra={
        "x-credential-url": "https://agents.asksurf.ai",
        "x-credential-instructions": "Generate an API key in the Surf Dashboard and paste it here without the Bearer prefix. The free credit balance read verifies the key. Data calls spend Surf credits; SQL job submission starts a query and cancellation may be pending.",
    })
    credential_type: Literal["surf_api_key"] = Field("surf_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., title="API key", min_length=1, max_length=4096, repr=False,
        json_schema_extra={"ui:widget": "password"})

    @field_validator("api_key", mode="before")
    @classmethod
    def token(cls, value):
        value = clean_secret(value, field_name="API key")
        if not value.isascii() or any(c.isspace() for c in value):
            raise ValueError("Paste the API key without a Bearer prefix or whitespace")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    @model_validator(mode="before")
    @classmethod
    def editor_metadata(cls, value):
        if isinstance(value, dict) and "credentialIds" in value:
            return {key: item for key, item in value.items() if key != "credentialIds"}
        return value

    @model_validator(mode="after")
    def query_semantics(self):
        values = self.model_dump(by_alias=True)
        if self.operation == "get_price_history" and bool(values.get("from")) != bool(values.get("to")):
            raise ValueError("Provide both from and to for a custom price range")
        if self.operation == "get_project" and not any(values.get(k) for k in ("id", "q", "handle", "x_id")):
            raise ValueError("Provide a project ID, query, X handle or X ID")
        if self.operation == "get_defi_metrics" and not any(values.get(k) for k in ("id", "q")):
            raise ValueError("Provide a project ID or query")
        return self


class SurfGetFearGreedConfig(_Input):
    'Fear & Greed Index History'
    operation: Literal['get_fear_greed'] = Field('get_fear_greed', json_schema_extra={"ui:hidden": True})
    from_: str | None = Field(None, alias='from', description='Start of time range. Accepts Unix seconds or date string (YYYY-MM-DD)', examples=['2026-01-01'])
    to: str | None = Field(None, description='End of time range. Accepts Unix seconds or date string (YYYY-MM-DD)', examples=['2026-03-01'])


class SurfGetPriceHistoryConfig(_Input):
    'Token Price History'
    operation: Literal['get_price_history'] = Field('get_price_history', json_schema_extra={"ui:hidden": True})
    symbol: str = Field(..., min_length=1, description='Single token ticker symbol like `BTC`, `ETH`, or `SOL` (multi-symbol not supported)', examples=['BTC'])
    time_range: Literal['1d', '7d', '14d', '30d', '90d', '180d', '365d', 'max'] = Field('30d', description='Window of historical data to return: `1d`, `7d`, `14d`, `30d`, `90d`, `180d`, `365d`, or `max`. Ignored when `from`/`to` are set. This endpoint uses `time_range` only — it does NOT accept `interval`; bucket granularity is chosen server-side based on the window size.', examples=['30d'])
    from_: str | None = Field(None, alias='from', description='Start of custom date range (Unix timestamp or YYYY-MM-DD). Must be used together with `to`. Overrides `time_range` when set.', examples=['2025-01-01'])
    to: str | None = Field(None, description='End of custom date range (Unix timestamp or YYYY-MM-DD). Must be used together with `from`. Overrides `time_range` when set.', examples=['2025-03-01'])
    currency: str = Field('usd', description='Quote currency like `usd`, `eur`, or `btc`', examples=['usd'])


class SurfListTokenRankingsConfig(_Input):
    'Token Rankings'
    operation: Literal['list_token_rankings'] = Field('list_token_rankings', json_schema_extra={"ui:hidden": True})
    sort_by: Literal['market_cap', 'change_24h', 'volume_24h'] = Field('market_cap', description='Field to sort by. `market_cap` sorts by total market capitalisation, `change_24h` sorts by 24-hour price change percentage (fetches top 250 by market cap then sorts client-side), `volume_24h` sorts by 24-hour trading volume.', examples=['market_cap'])
    order: Literal['asc', 'desc'] = Field('desc', description='Sort order: `desc` (default, highest first) or `asc` (lowest first).', examples=['desc'])
    category: Literal['MEME', 'AI', 'AI_AGENTS', 'L1', 'L2', 'DEFI', 'GAMING', 'STABLECOIN', 'RWA', 'DEPIN', 'SOL_ECO', 'BASE_ECO', 'LST'] | None = Field(None, description='Optional token category filter. When provided, results are limited to coins in that category. Supported values: MEME, AI, AI_AGENTS, L1, L2, DEFI, GAMING, STABLECOIN, RWA, DEPIN, SOL_ECO, BASE_ECO, LST.', examples=['MEME'])
    limit: int = Field(20, ge=1, le=100, description='Results per page', examples=[20], strict=True)
    offset: int = Field(0, ge=0, description='Pagination offset', examples=[0], strict=True)


class SurfGetCreditsConfig(_Input):
    'Credit Balance'
    operation: Literal['get_credits'] = Field('get_credits', json_schema_extra={"ui:hidden": True})


class SurfGetNewsConfig(_Input):
    'News Article Detail'
    operation: Literal['get_news'] = Field('get_news', json_schema_extra={"ui:hidden": True})
    id: str = Field(..., min_length=1, description='Article ID (returned as id in feed/search results)', examples=['e54e0ac4-1ef8-44d2-928e-52df465e2c81'])


class SurfListNewsConfig(_Input):
    'Crypto News Feed'
    operation: Literal['list_news'] = Field('list_news', json_schema_extra={"ui:hidden": True})
    source: Literal['coindesk', 'cointelegraph', 'theblock', 'decrypt', 'dlnews', 'blockbeats', 'bitcoincom', 'coinpedia', 'ambcrypto', 'cryptodaily', 'cryptopotato', 'phemex', 'panews', 'odaily', 'tradingview', 'chaincatcher', 'techflow'] | None = Field(None, description='Filter by news source', examples=['coindesk'])
    project: str | None = Field(None, description='Comma-separated project names to filter by', examples=['bitcoin,ethereum'])
    from_: str | None = Field(None, alias='from', description='Filter articles published on or after this time. Accepts Unix seconds or date string (2024-01-01)', examples=['2024-01-01'])
    to: str | None = Field(None, description='Filter articles published on or before this time. Accepts Unix seconds or date string (2024-02-01)', examples=['2024-02-01'])
    sort_by: Literal['recency', 'trending'] = Field('recency', description='Sort order: recency (newest first) or trending (deterministic newest-first alias until engagement ranking is available)', examples=['recency'])
    limit: int = Field(20, ge=1, le=50, description='Results per page (max 50)', examples=[20], strict=True)
    offset: int = Field(0, ge=0, description='Pagination offset', examples=[0], strict=True)


class SurfGetGasPriceConfig(_Input):
    'Current Gas Price'
    operation: Literal['get_gas_price'] = Field('get_gas_price', json_schema_extra={"ui:hidden": True})
    chain: Literal['ethereum', 'polygon', 'bsc', 'arbitrum', 'optimism', 'base', 'avalanche', 'fantom', 'linea', 'cyber'] = Field(..., min_length=1, description='Chain. Can be `ethereum`, `polygon`, `bsc`, `arbitrum`, `optimism`, `base`, `avalanche`, `fantom`, `linea`, or `cyber`.', examples=['ethereum'])


class SurfCreateSqlJobConfig(_Input):
    'Submit Asynchronous Blockchain SQL Job'
    operation: Literal['create_sql_job'] = Field('create_sql_job', json_schema_extra={"ui:hidden": True})
    idempotency_key: str | None = Field(None, alias='Idempotency-Key', max_length=200, description='Stable client-generated key. Reusing it returns the existing job without starting another query.')
    max_rows: int = Field(1000, ge=1, le=10000, description='Maximum number of result rows to retain', examples=[1000], strict=True)
    sql: str = Field(..., min_length=1, description='Exact read-only ClickHouse SQL to execute asynchronously. The submitted SQL and date range are preserved.', examples=['SELECT block_date, project, symbol, apy FROM agent.ethereum_yields_daily WHERE block_date >= today() - 30 ORDER BY apy DESC'])


class SurfCancelSqlJobConfig(_Input):
    'Cancel Asynchronous Blockchain SQL Job'
    operation: Literal['cancel_sql_job'] = Field('cancel_sql_job', json_schema_extra={"ui:hidden": True})
    job_id: UUID = Field(..., description='Asynchronous SQL job identifier')


class SurfGetSqlJobConfig(_Input):
    'Get Asynchronous Blockchain SQL Job'
    operation: Literal['get_sql_job'] = Field('get_sql_job', json_schema_extra={"ui:hidden": True})
    job_id: UUID = Field(..., description='Asynchronous SQL job identifier')


class SurfPreflightSqlConfig(_Input):
    'Preflight Blockchain SQL Query'
    operation: Literal['preflight_sql'] = Field('preflight_sql', json_schema_extra={"ui:hidden": True})
    max_rows: int = Field(1000, ge=1, le=10000, description='Maximum result rows in the final server-bounded execution plan', examples=[1000], strict=True)
    sql: str = Field(..., min_length=1, description='Read-only ClickHouse SELECT/WITH query to validate and estimate without executing it', examples=['SELECT block_date, project, apy, tvl_usd FROM agent.ethereum_yields_daily WHERE block_date >= today() - 7 LIMIT 100'])


class SurfGetDefiMetricsConfig(_Input):
    'Project DeFi Metrics'
    operation: Literal['get_defi_metrics'] = Field('get_defi_metrics', json_schema_extra={"ui:hidden": True})
    id: str | None = Field(None, description='Surf project UUID. PREFERRED — always use this when available from a previous response (e.g. project_id from /fund/portfolio or id from /search/project). Takes priority over q.', examples=['25c6612a-395c-4974-94eb-3b5f9f4b2ed7'])
    q: str | None = Field(None, description="Fuzzy entity name search. Only use when 'id' is not available. May return unexpected results for ambiguous names.", examples=['uniswap'])
    metric: Literal['volume', 'fee', 'fees', 'revenue', 'tvl', 'users'] = Field('tvl', description='Metric to query. Can be `volume`, `fees` (or `fee` alias), `revenue`, `tvl`, or `users`. Defaults to tvl.', examples=['tvl'])
    from_: str | None = Field(None, alias='from', description='Start of time range. Accepts Unix seconds (`1704067200`) or date string (`2024-01-01`)', examples=['2024-01-01'])
    to: str | None = Field(None, description='End of time range. Accepts Unix seconds (`1706745600`) or date string (`2024-02-01`)', examples=['2024-02-01'])
    chain: Literal['ethereum', 'polygon', 'bsc', 'arbitrum', 'optimism', 'base', 'avalanche', 'fantom', 'solana'] | None = Field(None, description='Filter by chain. Can be `ethereum`, `polygon`, `bsc`, `arbitrum`, `optimism`, `base`, `avalanche`, `fantom`, or `solana`.', examples=['ethereum'])
    limit: int = Field(20, ge=1, le=100, description='Results per page', examples=[20], strict=True)
    offset: int = Field(0, ge=0, description='Pagination offset', examples=[0], strict=True)


class SurfGetProjectConfig(_Input):
    'Aggregated Project Detail'
    operation: Literal['get_project'] = Field('get_project', json_schema_extra={"ui:hidden": True})
    id: str | None = Field(None, description='Surf project UUID. PREFERRED — always use this when available from a previous response (e.g. project_id from /fund/portfolio or id from /search/project). Takes priority over q.', examples=['25c6612a-395c-4974-94eb-3b5f9f4b2ed7'])
    x_id: str | None = Field(None, description='Numeric X (Twitter) account ID. Resolves to the associated project.', examples=['984188226826010624'])
    handle: str | None = Field(None, description='X (Twitter) handle without @. Resolves to the associated project via twitter account lookup.', examples=['uniswap'])
    q: str | None = Field(None, description="Fuzzy entity name search. Only use when 'id' is not available. May return unexpected results for ambiguous names.", examples=['ethereum'])
    fields: str = Field('overview,token_info,tokenomics,funding,team,contracts,social,tge_status', description='Comma-separated sub-resources to include. Can be `overview`, `token_info`, `tokenomics`, `funding`, `team`, `contracts`, `social`, or `tge_status`.', examples=['overview,token_info,funding'])


class SurfSearchProjectsConfig(_Input):
    'Project Search'
    operation: Literal['search_projects'] = Field('search_projects', json_schema_extra={"ui:hidden": True})
    q: str = Field(..., max_length=100, min_length=1, description='Search keyword — project name or ticker like `uniswap`, `bitcoin`, or `ETH`', examples=['bitcoin'])
    limit: int = Field(20, ge=1, le=100, description='Results per page', examples=[20], strict=True)
    offset: int = Field(0, ge=0, description='Pagination offset', examples=[0], strict=True)


class SurfSearchTokensConfig(_Input):
    'Token Symbol Resolution'
    operation: Literal['search_tokens'] = Field('search_tokens', json_schema_extra={"ui:hidden": True})
    q: str = Field(..., max_length=50, min_length=1, description='Exact token ticker symbol to resolve (case-insensitive), like `USDC` or `PEPE`. NOT a contract address, trading pair, or fuzzy token name.', examples=['USDC'])
    chain: Literal['ethereum', 'base', 'bsc', 'arbitrum', 'solana', 'polygon', 'optimism', 'avalanche', 'fantom', 'tron', 'linea', 'mantle', 'blast', 'gnosis', 'zksync', 'scroll'] | None = Field(None, description='Restrict resolution to one supported chain. Omit to search all supported chains.', examples=['solana'])
    limit: int = Field(20, ge=1, le=100, description='Results per page', examples=[20], strict=True)
    offset: int = Field(0, ge=0, description='Pagination offset', examples=[0], strict=True)


class SurfSearchWebConfig(_Input):
    'Web Search'
    operation: Literal['search_web'] = Field('search_web', json_schema_extra={"ui:hidden": True})
    q: str = Field(..., min_length=1, description='Search query like `bitcoin price prediction 2026`', examples=['bitcoin price prediction 2026'])
    limit: int = Field(20, ge=1, le=100, description='Results per page', examples=[20], strict=True)
    offset: int = Field(0, ge=0, description='Pagination offset', examples=[0], strict=True)
    site: str | None = Field(None, description='Comma-separated domain filter like `coindesk.com` or `cointelegraph.com`', examples=['coindesk.com,cointelegraph.com'])
    include_content: bool = Field(False, description="When false (default), search returns title/url/description only — fast (~2-3s) URL discovery. Set true to also include full markdown content for each result (~5-30KB per result, ~10-15s for limit=5). Use true only when the caller needs page content inline and won't follow up with `/web/fetch`.", examples=[False], strict=True)


class SurfListTokenHoldersConfig(_Input):
    'Token Holders'
    operation: Literal['list_token_holders'] = Field('list_token_holders', json_schema_extra={"ui:hidden": True})
    address: str = Field(..., min_length=1, description='Token CONTRACT ADDRESS — 0x-prefixed hex for EVM chains, base58 for Solana. This is NOT a ticker symbol (e.g. do NOT pass `USDC` or `BTC`). To resolve a ticker symbol to a contract address, call GET /v1/search/token?q={symbol}&chain={chain} and use the `address` whose `chain` is supported by this endpoint. This endpoint has no `symbol` parameter.', examples=['0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48'])
    chain: Literal['ethereum', 'polygon', 'bsc', 'solana', 'avalanche', 'arbitrum', 'optimism', 'base'] = Field(..., min_length=1, description='Chain. Can be `ethereum`, `polygon`, `bsc`, `solana`, `avalanche`, `arbitrum`, `optimism`, or `base`.', examples=['ethereum'])
    limit: int = Field(20, ge=1, le=100, description='Results per page', examples=[20], strict=True)
    offset: int = Field(0, ge=0, description='Pagination offset', examples=[0], strict=True)
    include: str | None = Field(None, description='Comma-separated enrichments to attach to each holder. Currently valid: `labels` — adds a full `label` record alongside the flat `entity_name` / `entity_type` fields.', examples=['labels'])


class SurfGetWalletConfig(_Input):
    'Aggregated Wallet Detail'
    operation: Literal['get_wallet'] = Field('get_wallet', json_schema_extra={"ui:hidden": True})
    address: str = Field(..., min_length=1, description='Wallet address (0x hex for EVM, base58 for Solana)', examples=['0xd8dA6BF26964aF9D7eEd9e03E53415D37aA96045'])
    chain: Literal['ethereum', 'polygon', 'bsc', 'avalanche', 'arbitrum', 'optimism', 'fantom', 'base', 'solana'] | None = Field(None, description='Chain filter for `tokens`, `nft`, and `approvals`. When omitted, inferred from address format: 0x addresses query all EVM chains, base58 addresses query Solana.', examples=['ethereum'])
    fields: str = Field('balance,tokens,labels,nft', description='Comma-separated sub-resources to include. Valid: `balance`, `tokens`, `labels`, `nft`, `approvals`. The `active_chains` field is always returned. `approvals` is opt-in (not in default) as it triggers additional upstream calls.', examples=['balance,labels,approvals'])


class SurfListWalletTransfersConfig(_Input):
    'Wallet Transfer History'
    operation: Literal['list_wallet_transfers'] = Field('list_wallet_transfers', json_schema_extra={"ui:hidden": True})
    address: str = Field(..., min_length=1, description='Wallet address — must be a raw address (0x-prefixed hex for EVM, base58 for Solana). ENS names like `vitalik.eth` are not supported; resolve to a 0x address first.', examples=['0xd8dA6BF26964aF9D7eEd9e03E53415D37aA96045'])
    chain: Literal['ethereum', 'base', 'solana', 'tron', 'bsc', 'arbitrum'] = Field('ethereum', description='Chain. Can be `ethereum`, `base`, `solana`, `tron`, `bsc`, or `arbitrum`.', examples=['ethereum'])
    flow: Literal['in', 'out'] | None = Field(None, description='Filter by transfer direction relative to the queried wallet. `in` for incoming, `out` for outgoing. Omit for both directions.', examples=['in'])
    token: str | None = Field(None, description='Filter by token contract address. Use `0x0000000000000000000000000000000000000000` for native token transfers. Omit for all tokens.', examples=['0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48'])
    limit: int = Field(20, ge=1, le=100, description='Results per page. Default 20, max 100. NOTE: Solana (`chain=solana`) is hard-capped at 40 per call by the upstream Solscan API — values above 40 return at most 40 items. Check `meta.has_more` and paginate with `offset` to fetch beyond the first page.', examples=[20], strict=True)
    offset: int = Field(0, ge=0, description="Pagination offset. For Solana, this maps to Solscan's 1-indexed `page` parameter (page = offset/page_size + 1).", examples=[0], strict=True)
    include: str | None = Field(None, description='Comma-separated enrichments to attach to each transfer. Currently valid: `labels` — adds `from_label` and `to_label` fields with entity information for each counterparty address.', examples=['labels'])


class SurfFetchWebPageConfig(_Input):
    'Web Page Fetch'
    operation: Literal['fetch_web_page'] = Field('fetch_web_page', json_schema_extra={"ui:hidden": True})
    url: str = Field(..., min_length=1, description='URL to fetch and parse', examples=['https://ethereum.org'])
    target_selector: str | None = Field(None, description='CSS selector to extract specific content', examples=['article.main-content'])
    remove_selector: str | None = Field(None, description='CSS selector to remove unwanted elements', examples=['nav,footer,.ads'])
    wait_for_selector: str | None = Field(None, description='CSS selector to wait for before extracting', examples=['.content-loaded'])
    timeout: int = Field(30000, ge=1000, le=60000, description='Request timeout in milliseconds', examples=[5000], strict=True)


SurfConfig = Annotated[Union[
    SurfGetFearGreedConfig,
    SurfGetPriceHistoryConfig,
    SurfListTokenRankingsConfig,
    SurfGetCreditsConfig,
    SurfGetNewsConfig,
    SurfListNewsConfig,
    SurfGetGasPriceConfig,
    SurfCreateSqlJobConfig,
    SurfCancelSqlJobConfig,
    SurfGetSqlJobConfig,
    SurfPreflightSqlConfig,
    SurfGetDefiMetricsConfig,
    SurfGetProjectConfig,
    SurfSearchProjectsConfig,
    SurfSearchTokensConfig,
    SurfSearchWebConfig,
    SurfListTokenHoldersConfig,
    SurfGetWalletConfig,
    SurfListWalletTransfersConfig,
    SurfFetchWebPageConfig
], Field(discriminator="operation")]


class SurfFullConfig(NodeConfig[SurfConfig, SurfApiKeyCredential]):
    pass


ROUTES = {
    'get_fear_greed': ('GET', '/gateway/v1/market/fear-greed', 'list'),
    'get_price_history': ('GET', '/gateway/v1/market/price', 'list'),
    'list_token_rankings': ('GET', '/gateway/v1/market/ranking', 'list'),
    'get_credits': ('GET', '/gateway/v1/me/credits', 'object'),
    'get_news': ('GET', '/gateway/v1/news/detail', 'object'),
    'list_news': ('GET', '/gateway/v1/news/feed', 'list'),
    'get_gas_price': ('GET', '/gateway/v1/onchain/gas-price', 'object'),
    'create_sql_job': ('POST', '/gateway/v1/onchain/sql/jobs', 'object'),
    'cancel_sql_job': ('DELETE', '/gateway/v1/onchain/sql/jobs/{job_id}', 'object'),
    'get_sql_job': ('GET', '/gateway/v1/onchain/sql/jobs/{job_id}', 'object'),
    'preflight_sql': ('POST', '/gateway/v1/onchain/sql/preflight', 'object'),
    'get_defi_metrics': ('GET', '/gateway/v1/project/defi/metrics', 'list'),
    'get_project': ('GET', '/gateway/v1/project/detail', 'object'),
    'search_projects': ('GET', '/gateway/v1/search/project', 'list'),
    'search_tokens': ('GET', '/gateway/v1/search/token', 'list'),
    'search_web': ('GET', '/gateway/v1/search/web', 'list'),
    'list_token_holders': ('GET', '/gateway/v1/token/holders', 'list'),
    'get_wallet': ('GET', '/gateway/v1/wallet/detail', 'object'),
    'list_wallet_transfers': ('GET', '/gateway/v1/wallet/transfers', 'list'),
    'fetch_web_page': ('GET', '/gateway/v1/web/fetch', 'object'),
}


class SurfNode(WorkflowNode):
    integration_type = "automation-surf"
    connection_evidence = ConnectionEvidence(operation="get_credits", noun="Surf workspace credit balance")

    @classmethod
    def get_config_model(cls):
        return SurfFullConfig

    async def execute(self, inputs):
        if not self.config.credentials:
            raise ValueError("Connect a Surf API key")
        op = self.config.config
        token = self.config.credentials.api_key
        method, path, shape = ROUTES[op.operation]
        values = op.model_dump(mode="json", by_alias=True, exclude_none=True, exclude={"operation"})
        headers = {"Authorization": "Bearer " + token, "Accept": "application/json"}
        if "job_id" in values:
            path = path.replace("{job_id}", str(UUID(values.pop("job_id"))))
        if "Idempotency-Key" in values:
            headers["Idempotency-Key"] = values.pop("Idempotency-Key")
        kwargs = {"json": values} if method == "POST" else {"params": {
            key: str(value).lower() if isinstance(value, bool) else value for key, value in values.items()
        }}
        async with guarded_async_client(timeout=90, trust_env=False, follow_redirects=False) as client:
            response = await client.request(method, BASE_URL + path, headers=headers, **kwargs)
        if len(response.content) > 10_000_000:
            raise ValueError("Surf response exceeds 10 MB")
        if response.headers.get("content-type", "").split(";", 1)[0] != "application/json":
            raise ValueError("Surf did not return JSON")
        body = response.json()
        if not isinstance(body, dict):
            raise ValueError("Surf returned an invalid response envelope")
        if not 200 <= response.status_code < 300 or body.get("error"):
            error = body.get("error")
            message = error.get("message") if isinstance(error, dict) else None
            return {"status": "error", "http_status": response.status_code,
                "error": (message if isinstance(message, str) else "Surf request failed").replace(token, "[redacted]")}
        if "data" not in body or not isinstance(body.get("meta"), dict):
            raise ValueError("Surf response lacks data or metadata")
        data = body["data"]
        if shape == "list" and data is not None and not isinstance(data, list):
            raise ValueError("Surf list response is invalid")
        if shape == "object" and not isinstance(data, dict):
            raise ValueError("Surf object response is invalid")
        if op.operation == "get_credits" and type(data.get("credit_balance")) is not int:
            raise ValueError("Surf response lacks the workspace credit balance")
        evidence = {"items": [{"label": f"{data['credit_balance']} Surf credits remaining"}]} if op.operation == "get_credits" else {}
        return {**body, **evidence, "status": "success", "operation": op.operation}
