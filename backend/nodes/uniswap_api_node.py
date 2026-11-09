"""Uniswap Trading API v1 operations, pinned to published OpenAPI 1.0.0.

Calldata is returned for the caller to sign and broadcast externally. Creating
an order submits an already signed UniswapX order; no private key is collected.
"""
from __future__ import annotations

from typing import Annotated, Literal, Union
import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret

from nodes.uniswap_api_operations import FIELD_SCHEMAS

BASE_URL = "https://trade-api.gateway.uniswap.org/v1"


class UniswapAPIKeyCredential(BaseModel):
    model_config = ConfigDict(
        title="Uniswap API Key",
        hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://developers.uniswap.org/dashboard",
            "x-credential-instructions": "Paste an API key from the Uniswap developer dashboard. NoClick sends it in x-api-key only to trade-api.gateway.uniswap.org. The connection check reads supported chains to verify key reachability, not account or wallet ownership. Your wallet private key is never required.",
        },
    )
    credential_type: Literal["uniswap_api_key"] = Field(
        "uniswap_api_key", json_schema_extra={"ui:hidden": True}
    )
    api_key: str = Field(
        ...,
        title="API Key",
        min_length=1,
        max_length=4096,
        repr=False,
        json_schema_extra={"ui:widget": "password"},
    )

    @field_validator("api_key", mode="before")
    @classmethod
    def key(cls, value):
        value = clean_secret(value, field_name="API Key")
        if any(ord(c) < 33 or ord(c) > 126 for c in value):
            raise ValueError("Paste the API key without a header or whitespace")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class CheckApproval(_Input):
    "Check swap approvals"
    operation: Literal["check_approval"] = Field(
        "check_approval",
        title="Check swap approvals",
        json_schema_extra={"ui:hidden": True},
    )
    x_permit2_disabled: bool | None = Field(None, strict=True)
    walletAddress: str = Field(
        ...,
        pattern="^0x[0-9a-fA-F]{40}$",
        description="The wallet address which will be used to send the token.",
    )
    token: str = Field(
        ...,
        pattern="^(0x)?[0-9a-fA-F]{40}$",
        description="The token which will be sent, specified by its token address. For a list of supported tokens, see the [FAQ](https://api-docs.uniswap.org/guides/faqs).",
    )
    amount: str = Field(
        ...,
        pattern="^[0-9]+$",
        description="The quantity of tokens denominated in the token's base units. (For example, for an ERC20 token one token is 1x10^18 base units. For one USDC token one token is 1x10^6 base units.) This value must be greater than 0.",
    )
    chainId: Literal[
        1,
        10,
        56,
        130,
        137,
        143,
        196,
        324,
        480,
        1868,
        4217,
        4326,
        4663,
        5042,
        8453,
        10143,
        42161,
        42220,
        43114,
        57073,
        59144,
        81457,
        7777777,
        1301,
        84532,
        11155111,
    ] = Field(
        ...,
        description="The unique ID of the blockchain. For a list of supported chains see the [FAQ](https://api-docs.uniswap.org/guides/faqs).",
    )
    urgency: Union[Literal["normal", "fast", "urgent"], dict] | None = Field(
        None,
        description='The urgency impacts the estimated gas price of the transaction. The higher the urgency, the higher the gas price, and the faster the transaction is likely to be selected from the mempool. Send the bare string form (e.g. `"normal"`) for the common case, or the object form `{ level, overrides }` to supply caller caps for `maxPriorityFeePerGas`, `maxFeePerGas`, and `gasLimit`.',
        json_schema_extra=FIELD_SCHEMAS["CheckApproval.urgency"],
    )
    includeGasInfo: bool | None = Field(
        None,
        description="If set to `true`, the response will include the estimated gas fee for the proposed transaction.",
        strict=True,
    )
    tokenOut: str | None = Field(
        None,
        pattern="^(0x)?[0-9a-fA-F]{40}$",
        description="The token which will be received, specified by its token address. For a list of supported tokens, see the [FAQ](https://api-docs.uniswap.org/guides/faqs).",
    )
    tokenOutChainId: Literal[
        1,
        10,
        56,
        130,
        137,
        143,
        196,
        324,
        480,
        1868,
        4217,
        4326,
        4663,
        5042,
        8453,
        10143,
        42161,
        42220,
        43114,
        57073,
        59144,
        81457,
        7777777,
        1301,
        84532,
        11155111,
    ] | None = Field(
        None,
        description="The unique ID of the blockchain. For a list of supported chains see the [FAQ](https://api-docs.uniswap.org/guides/faqs).",
    )


class CheckPermissions(_Input):
    "Check token KYC permissions"
    operation: Literal["check_permissions"] = Field(
        "check_permissions",
        title="Check token KYC permissions",
        json_schema_extra={"ui:hidden": True},
    )
    walletAddress: str = Field(
        ...,
        pattern="^0x[0-9a-fA-F]{40}$",
        description="The wallet address which will be used to send the token.",
    )
    tokens: list[str] = Field(
        ...,
        description="Tokens to check permissions for. Maximum of 2 per request.",
        json_schema_extra=FIELD_SCHEMAS["CheckPermissions.tokens"],
    )
    chainId: Literal[
        1,
        10,
        56,
        130,
        137,
        143,
        196,
        324,
        480,
        1868,
        4217,
        4326,
        4663,
        5042,
        8453,
        10143,
        42161,
        42220,
        43114,
        57073,
        59144,
        81457,
        7777777,
        1301,
        84532,
        11155111,
    ] = Field(
        ...,
        description="The unique ID of the blockchain. For a list of supported chains see the [FAQ](https://api-docs.uniswap.org/guides/faqs).",
    )


class GetQuote(_Input):
    "Get a quote"
    operation: Literal["get_quote"] = Field(
        "get_quote", title="Get a quote", json_schema_extra={"ui:hidden": True}
    )
    x_universal_router_version: Literal[
        "2.0", "2.1.1", "2.1.2", "2.2.0"
    ] | None = Field(
        None,
        description="Universal Router release line. An explicitly pinned version is served unchanged. `2.1.2` is a redeploy of `2.1.1` with identical calldata at its own per-chain address; callers that do not pin a version default to `2.1.2` on chains where it is deployed, and fall back to an older deployed version elsewhere (e.g. zkSync and Monad Testnet, which have no `2.1.2` deployment). `2.2.0` is the permissioned-pool router: it is required for swaps involving a permissioned token and rejected for any other swap. The `x-universal-router-version` response header reports the version actually served.",
    )
    x_erc20eth_enabled: bool | None = Field(None, strict=True)
    x_permit2_disabled: bool | None = Field(None, strict=True)
    type: Literal["EXACT_INPUT", "EXACT_OUTPUT"] = Field(
        ...,
        description="The handling of the `amount` field. `EXACT_INPUT` means the requester will send the specified `amount` of input tokens and get a quote with a variable quantity of output tokens. `EXACT_OUTPUT` means the requester will receive the specified `amount` of output tokens and get a quote with a variable quantity of input tokens.",
    )
    amount: str = Field(
        ...,
        pattern="^[0-9]+$",
        description="The quantity of tokens denominated in the token's base units. (For example, for an ERC20 token one token is 1x10^18 base units. For one USDC token one token is 1x10^6 base units.) This value must be greater than 0.",
    )
    tokenInChainId: Literal[
        1,
        10,
        56,
        130,
        137,
        143,
        196,
        324,
        480,
        1868,
        4217,
        4326,
        4663,
        5042,
        8453,
        10143,
        42161,
        42220,
        43114,
        57073,
        59144,
        81457,
        7777777,
        1301,
        84532,
        11155111,
    ] = Field(
        ...,
        description="The unique ID of the blockchain. For a list of supported chains see the [FAQ](https://api-docs.uniswap.org/guides/faqs).",
    )
    tokenOutChainId: Literal[
        1,
        10,
        56,
        130,
        137,
        143,
        196,
        324,
        480,
        1868,
        4217,
        4326,
        4663,
        5042,
        8453,
        10143,
        42161,
        42220,
        43114,
        57073,
        59144,
        81457,
        7777777,
        1301,
        84532,
        11155111,
    ] = Field(
        ...,
        description="The unique ID of the blockchain. For a list of supported chains see the [FAQ](https://api-docs.uniswap.org/guides/faqs).",
    )
    tokenIn: str = Field(
        ...,
        pattern="^(0x)?[0-9a-fA-F]{40}$",
        description="The token which will be sent, specified by its token address. For a list of supported tokens, see the [FAQ](https://api-docs.uniswap.org/guides/faqs).",
    )
    tokenOut: str = Field(
        ...,
        pattern="^(0x)?[0-9a-fA-F]{40}$",
        description="The token which will be received, specified by its token address. For a list of supported tokens, see the [FAQ](https://api-docs.uniswap.org/guides/faqs).",
    )
    generatePermitAsTransaction: bool | None = Field(
        None,
        description="Indicates whether you want to receive a permit2 transaction to sign and submit onchain, or a permit message to sign. When set to `true`, the quote response returns the Permit2 as a calldata which the user signs and broadcasts. When set to `false` (the default), the quote response returns the Permit2 as a message which the user signs but does not need to broadcast. When using a 7702-delegated wallet, set this field to `true`. Except for this scenario, it is recommended that this field is set to false. Note that a Permit2 calldata (e.g. `true`), will provide indefinite permission for Permit2 to spend a token, in contrast to a Permit2 message (e.g. `false`) which is only valid for 30 days. Further, a Permit2 calldata (e.g. `true`) requires the user to pay gas to submit the transaction, whereas the Permit2 message (e.g. `false` ) does not require the user to submit a transaction and requires no gas.",
        strict=True,
    )
    swapper: str = Field(
        ...,
        pattern="^0x[0-9a-fA-F]{40}$",
        description="The wallet address which will be used to send the token.",
    )
    slippageTolerance: float | None = Field(
        None,
        ge=0,
        le=100,
        description="The slippage tolerance as a percentage up to a maximum of two decimal places, between 0 and 100 (a value outside that range is rejected). This is the maximum acceptable output loss as a percentage: for exact-input trades, the minimum received is expectedOut × (1 - slippageTolerance); for exact-output trades, the maximum input is expectedIn × (1 + slippageTolerance).\n\nWhen submitting a quote, note that slippage tolerance works differently in UniswapX swaps where it does not set a limit on the Spread in an order. See [here](https://api-docs.uniswap.org/guides/faqs#why-do-uniswapx-quotes-have-more-slippage-than-the-tolerance-i-set) for more information.\n\nNote that if the trade type is `EXACT_INPUT`, then the slippage is in terms of the output token. If the trade type is `EXACT_OUTPUT`, then the slippage is in terms of the input token.\n\nWhen submitting a request, `slippageTolerance` may not be set when `autoSlippage` is defined. One of `slippageTolerance` or `autoSlippage` must be defined.",
    )
    autoSlippage: Literal["DEFAULT"] | None = Field(
        None,
        description="The auto slippage strategy to employ. For Uniswap Protocols (v2, v3, v4) the auto slippage will be automatically calculated when this field is set to `DEFAULT`. Auto slippage cannot be calculated for UniswapX swaps.\n\nNote that if the trade type is `EXACT_INPUT`, then the slippage is in terms of the output token. If the trade type is `EXACT_OUTPUT`, then the slippage is in terms of the input token.\n\nWhen submitting a request, `autoSlippage` may not be set when `slippageTolerance` is defined. One of `slippageTolerance` or `autoSlippage` must be defined.",
    )
    routingPreference: Literal["BEST_PRICE", "FASTEST"] | None = Field(
        None,
        description="The `routingPreference` specifies the preferred strategy to determine the quote. If the `routingPreference` is `BEST_PRICE`, then the quote will propose a route through the specified whitelisted protocols (or all, if none are specified) that provides the best price. When the `routingPreference` is `FASTEST`, the quote will propose the first route which is found to complete the swap.",
    )
    protocols: list[
        Literal[
            "V2",
            "V3",
            "V4",
            "UNISWAPX",
            "UNISWAPX_V2",
            "UNISWAPX_V3",
            "UNISWAPX_LATEST",
        ]
    ] | None = Field(
        None,
        description="The protocols to use for the swap/order. If the `protocols` field is defined, then you can only set the `routingPreference` to `BEST_PRICE`. Note that the value `UNISWAPX` is deprecated and will be removed in a future release.",
        json_schema_extra=FIELD_SCHEMAS["GetQuote.protocols"],
    )
    hooksOptions: Literal[
        "V4_HOOKS_INCLUSIVE", "V4_HOOKS_ONLY", "V4_NO_HOOKS"
    ] | None = Field(
        None,
        description="The hook options to use for V4 pool quotes. `V4_HOOKS_INCLUSIVE` will get quotes for V4 pools with or without hooks. `V4_HOOKS_ONLY` will only get quotes for V4 pools with hooks. `V4_NO_HOOKS` will only get quotes for V4 pools without hooks. Defaults to `V4_HOOKS_INCLUSIVE` if `V4` is included in `protocols` and `hookOptions` is not set. This field is ignored if `V4` is not passed in `protocols`.",
    )
    spreadOptimization: Literal["EXECUTION", "PRICE"] | None = Field(
        None,
        description="For UniswapX swaps, when set to `EXECUTION`, quotes optimize for looser spreads at higher fill rates. When set to `PRICE`, quotes optimize for tighter spreads at lower fill rates. This field is not applicable to Uniswap Protocols (v2, v3, v4), bridging, or wrapping/unwrapping and will be ignored if set.",
    )
    urgency: Union[Literal["normal", "fast", "urgent"], dict] | None = Field(
        None,
        description='The urgency impacts the estimated gas price of the transaction. The higher the urgency, the higher the gas price, and the faster the transaction is likely to be selected from the mempool. Send the bare string form (e.g. `"normal"`) for the common case, or the object form `{ level, overrides }` to supply caller caps for `maxPriorityFeePerGas`, `maxFeePerGas`, and `gasLimit`.',
        json_schema_extra=FIELD_SCHEMAS["GetQuote.urgency"],
    )
    permitAmount: Literal["FULL", "EXACT"] | None = Field(
        None,
        description="For Uniswap Protocols (v2, v3, v4) swaps, specify the input token spend allowance (e.g. quantity) to be set in the Permit2 permit. Applies to both the Permit2 message (`generatePermitAsTransaction: false`) and the Permit2 approval transaction (`generatePermitAsTransaction: true`). `FULL` can be used to specify an unlimited token quantity, and may prevent the wallet from needing to sign another permit for the same token in the future. `EXACT` bounds the allowance to the most the swap may spend: the input amount for exact-input trades, and the quoted input amount plus slippage tolerance for exact-output trades. Defaults to `FULL`.",
    )
    recipient: str | None = Field(
        None,
        pattern="^(0x)?[0-9a-fA-F]{40}$",
        description="(optional) The wallet address which will receive the output of the swap. If not provided, the output is returned to the `swapper`.",
    )
    integratorFees: list[dict] | None = Field(
        None,
        description="Optional integrator fees: up to 4 entries, on both UniswapX and classic (Universal Router) routes. Each recipient may appear at most once, and the `bips` summed across all entries must not exceed 500 (5%). Multi-entry fees on a Universal Router route require router version 2.1.1 or later and are exact-input only. Omitting the field or passing an empty array means no integrator fee. Invalid fees return a 400 with `errorCode` `IntegratorFeesTooManyEntriesError`, `IntegratorFeeEntryExceedsMaxError`, `IntegratorFeesTotalExceedsMaxError`, or `InvalidIntegratorFeesError`.",
        json_schema_extra=FIELD_SCHEMAS["GetQuote.integratorFees"],
    )
    swapSource: Literal["UNIVERSAL_ROUTER", "WALLET"] | None = Field(
        None,
        description='Where the input tokens come from. Leave unset (or send "WALLET") to pull them from the swapper\'s wallet as usual. Send "UNIVERSAL_ROUTER" to get calldata that swaps whatever balance of the input token the Universal Router holds when it runs, for bridge-and-swap flows where a bridge deposits into the router and executes the swap in the same transaction. In this mode, quote on the destination chain, use `amount` as your estimate of what will arrive, and put the end user in `swapper`. Exact-input, single-chain, AMM-only swaps: `protocols` defaults to V2/V3/V4 and a UniswapX protocol is rejected with a 400. With a native input, V4 is left out of the route whenever V2 or V3 is allowed: the router can only spend native ETH through a route that first wraps it to WETH, and a V4 pool that takes native ETH directly can\'t be encoded. A V4-only request is routed as asked. The returned transaction has no `from` (the executing filler is unknown) and a `value` of "0"; with a native input the filler must attach the delivered ETH as msg.value. The output floor is fixed at quote time from `amount` minus `slippageTolerance`: if less than `amount` arrives, the whole balance is still swapped and must clear that floor, so a delivery short by more than the tolerance reverts even without `enforceExactIn`. Use a conservative `amount` or widen `slippageTolerance`. `generatePermitAsTransaction` is rejected with a 400. Works on both /quote and /swap. A failed simulation only refuses the request when the verdict applies to a router-funded fill: a revert, or a simulation that could not run. A slippage flag, or a failure to pull from the quoted swapper, still returns calldata. Read the guide before using it: https://developers.uniswap.org/docs/trading/swapping-api/start-building/integration-guide#swapping-funds-already-in-the-universal-router',
    )
    enforceExactIn: bool | None = Field(
        None,
        description='Only with swapSource "UNIVERSAL_ROUTER". Set it to true when your bridge guarantees how much will arrive; the calldata then checks the router\'s balance and reverts if it holds less than `amount`. Leave it off if `amount` is just an estimate, or a good fill can revert over a small shortfall. Details: https://developers.uniswap.org/docs/trading/swapping-api/start-building/integration-guide#swapping-funds-already-in-the-universal-router',
        strict=True,
    )
    includeRouteCandidates: bool | None = Field(
        None,
        description="When true, uniroute-backed classic quotes include routeCandidates — the top alternative routes considered, each with its whole-route amounts.",
        strict=True,
    )


class CreateOrder(_Input):
    "Create a gasless order"
    operation: Literal["create_order"] = Field(
        "create_order",
        title="Create a gasless order",
        json_schema_extra={"ui:hidden": True},
    )
    x_erc20eth_enabled: bool | None = Field(None, strict=True)
    signature: str = Field(..., description="The signed permit.")
    quote: dict = Field(..., json_schema_extra=FIELD_SCHEMAS["CreateOrder.quote"])
    routing: Literal[
        "CLASSIC",
        "DUTCH_LIMIT",
        "DUTCH_V2",
        "DUTCH_V3",
        "BRIDGE",
        "LIMIT_ORDER",
        "PRIORITY",
        "WRAP",
        "UNWRAP",
        "CHAINED",
    ] = Field(..., description="The routing for the proposed transaction.")


class GetOrders(_Input):
    "Get gasless order status"
    operation: Literal["get_orders"] = Field(
        "get_orders",
        title="Get gasless order status",
        json_schema_extra={"ui:hidden": True},
    )
    orderType: Literal["Dutch_V2", "Dutch_V3", "Limit", "Priority"] | None = Field(None)
    orderId: str | None = Field(
        None, description="A unique ID for the order. Used to track the order's status."
    )
    orderIds: str | None = Field(None)
    limit: float | None = Field(None)
    orderStatus: Literal[
        "open",
        "expired",
        "error",
        "cancelled",
        "filled",
        "unverified",
        "insufficient-funds",
    ] | None = Field(
        None,
        description="The status of the order. Note that all of these are final states with the exception of Open, meaning that no further state changes will occur. \n Open - order is not yet filled by a filler.\n Expired - order has expired without being filled and is no longer fillable.\n Error - a catchall for other final states which are not otherwise specified, where the order will not be filled.\n Cancelled - order is cancelled. Note that to cancel an order, a new order must be placed with the same nonce as the prior open order and it must be placed within the same block as the original order.\n Filled - order is filled.\n Insufficient-funds - the swapper (you) do not have enough funds for the order to be completed and the order is cancelled and will not be filled.\n Unverified - order has not been verified yet.",
    )
    swapper: str | None = Field(None, pattern="^0x[0-9a-fA-F]{40}$")
    sortKey: Literal["createdAt"] | None = Field(None)
    sort: str | None = Field(None)
    filler: str | None = Field(None, pattern="^0x[0-9a-fA-F]{40}$")
    cursor: str | None = Field(None)


class CreateSwap(_Input):
    "Create swap calldata"
    operation: Literal["create_swap"] = Field(
        "create_swap",
        title="Create swap calldata",
        json_schema_extra={"ui:hidden": True},
    )
    x_universal_router_version: Literal[
        "2.0", "2.1.1", "2.1.2", "2.2.0"
    ] | None = Field(
        None,
        description="Universal Router release line. An explicitly pinned version is served unchanged. `2.1.2` is a redeploy of `2.1.1` with identical calldata at its own per-chain address; callers that do not pin a version default to `2.1.2` on chains where it is deployed, and fall back to an older deployed version elsewhere (e.g. zkSync and Monad Testnet, which have no `2.1.2` deployment). `2.2.0` is the permissioned-pool router: it is required for swaps involving a permissioned token and rejected for any other swap. The `x-universal-router-version` response header reports the version actually served.",
    )
    x_permit2_disabled: bool | None = Field(None, strict=True)
    quote: dict = Field(..., json_schema_extra=FIELD_SCHEMAS["CreateSwap.quote"])
    signature: str | None = Field(None, description="The signed permit.")
    includeGasInfo: bool | None = Field(
        None, description="Use `refreshGasPrice` instead.", strict=True
    )
    refreshGasPrice: bool | None = Field(
        None,
        description="If true, the gas price will be re-fetched from the network.",
        strict=True,
    )
    simulateTransaction: bool | None = Field(
        None,
        description="If true, the transaction will be simulated. If the simulation results on an onchain error, endpoint will return an error.",
        strict=True,
    )
    permitData: dict | None = Field(
        None, json_schema_extra=FIELD_SCHEMAS["CreateSwap.permitData"]
    )
    safetyMode: Literal["SAFE"] | None = Field(
        None,
        description="Swap safety mode will automatically sweep the transaction for the native token and return it to the sender wallet address. This is to prevent accidental loss of funds in the event that the token amount is set in the transaction value instead of as part of the calldata.",
    )
    deadline: float | None = Field(
        None,
        description="The unix timestamp at which the order will be reverted if not filled.",
    )
    urgency: Union[Literal["normal", "fast", "urgent"], dict] | None = Field(
        None,
        description='The urgency impacts the estimated gas price of the transaction. The higher the urgency, the higher the gas price, and the faster the transaction is likely to be selected from the mempool. Send the bare string form (e.g. `"normal"`) for the common case, or the object form `{ level, overrides }` to supply caller caps for `maxPriorityFeePerGas`, `maxFeePerGas`, and `gasLimit`.',
        json_schema_extra=FIELD_SCHEMAS["CreateSwap.urgency"],
    )
    swapSource: Literal["UNIVERSAL_ROUTER", "WALLET"] | None = Field(
        None,
        description='Where the input tokens come from. Leave unset (or send "WALLET") to pull them from the swapper\'s wallet as usual. Send "UNIVERSAL_ROUTER" to get calldata that swaps whatever balance of the input token the Universal Router holds when it runs, for bridge-and-swap flows where a bridge deposits into the router and executes the swap in the same transaction. In this mode, quote on the destination chain, use `amount` as your estimate of what will arrive, and put the end user in `swapper`. Exact-input, single-chain, AMM-only swaps: `protocols` defaults to V2/V3/V4 and a UniswapX protocol is rejected with a 400. With a native input, V4 is left out of the route whenever V2 or V3 is allowed: the router can only spend native ETH through a route that first wraps it to WETH, and a V4 pool that takes native ETH directly can\'t be encoded. A V4-only request is routed as asked. The returned transaction has no `from` (the executing filler is unknown) and a `value` of "0"; with a native input the filler must attach the delivered ETH as msg.value. The output floor is fixed at quote time from `amount` minus `slippageTolerance`: if less than `amount` arrives, the whole balance is still swapped and must clear that floor, so a delivery short by more than the tolerance reverts even without `enforceExactIn`. Use a conservative `amount` or widen `slippageTolerance`. `generatePermitAsTransaction` is rejected with a 400. Works on both /quote and /swap. A failed simulation only refuses the request when the verdict applies to a router-funded fill: a revert, or a simulation that could not run. A slippage flag, or a failure to pull from the quoted swapper, still returns calldata. Read the guide before using it: https://developers.uniswap.org/docs/trading/swapping-api/start-building/integration-guide#swapping-funds-already-in-the-universal-router',
    )
    enforceExactIn: bool | None = Field(
        None,
        description='Only with swapSource "UNIVERSAL_ROUTER". Set it to true when your bridge guarantees how much will arrive; the calldata then checks the router\'s balance and reverts if it holds less than `amount`. Leave it off if `amount` is just an estimate, or a good fill can revert over a small shortfall. Details: https://developers.uniswap.org/docs/trading/swapping-api/start-building/integration-guide#swapping-funds-already-in-the-universal-router',
        strict=True,
    )


class GetSwaps(_Input):
    "Get swap status"
    operation: Literal["get_swaps"] = Field(
        "get_swaps", title="Get swap status", json_schema_extra={"ui:hidden": True}
    )
    txHashes: list[
        Annotated[str, Field(pattern=r"^(0x)?[0-9a-fA-F]{64}$")]
    ] | None = Field(None, json_schema_extra=FIELD_SCHEMAS["GetSwaps.txHashes"])
    userOpHashes: list[
        Annotated[str, Field(pattern=r"^(0x)?[0-9a-fA-F]{64}$")]
    ] | None = Field(None, json_schema_extra=FIELD_SCHEMAS["GetSwaps.userOpHashes"])
    chainId: Literal[
        1,
        10,
        56,
        130,
        137,
        143,
        196,
        324,
        480,
        1868,
        4217,
        4326,
        4663,
        5042,
        8453,
        10143,
        42161,
        42220,
        43114,
        57073,
        59144,
        81457,
        7777777,
        1301,
        84532,
        11155111,
    ] | None = Field(
        None,
        description="The unique ID of the blockchain. For a list of supported chains see the [FAQ](https://api-docs.uniswap.org/guides/faqs).",
    )

    @model_validator(mode="after")
    def hash_required(self):
        if not self.txHashes and not self.userOpHashes:
            raise ValueError("Supply transaction hashes or user operation hashes")
        return self


class GetSwappableTokens(_Input):
    "Get bridgable tokens"
    operation: Literal["get_swappable_tokens"] = Field(
        "get_swappable_tokens",
        title="Get bridgable tokens",
        json_schema_extra={"ui:hidden": True},
    )
    tokenIn: str = Field(..., pattern="^0x[0-9a-fA-F]{40}$")
    tokenInChainId: Literal[
        1,
        10,
        56,
        130,
        137,
        143,
        196,
        324,
        480,
        1868,
        4217,
        4326,
        4663,
        5042,
        8453,
        10143,
        42161,
        42220,
        43114,
        57073,
        59144,
        81457,
        7777777,
        1301,
        84532,
        11155111,
    ] = Field(
        ...,
        description="The unique ID of the blockchain. For a list of supported chains see the [FAQ](https://api-docs.uniswap.org/guides/faqs).",
    )


class GetSupportedChains(_Input):
    "Get supported chains"
    operation: Literal["get_supported_chains"] = Field(
        "get_supported_chains",
        title="Get supported chains",
        json_schema_extra={"ui:hidden": True},
    )


class GetTokens(_Input):
    "Get tokens"
    operation: Literal["get_tokens"] = Field(
        "get_tokens", title="Get tokens", json_schema_extra={"ui:hidden": True}
    )
    sort: Literal["default", "tvl", "volume_24h", "bridgeable"] | None = Field(
        None,
        description="How tokens are selected and ordered. `tvl`: largest TVL first. `volume_24h`: highest 24h volume first. `default`: the Uniswap default token list (tokens.uniswap.org). `bridgeable`: tokens bridgeable via Uniswap.",
    )
    limit: int | None = Field(None, ge=1, le=1000)
    chainId: Literal[
        1,
        10,
        56,
        130,
        137,
        143,
        196,
        324,
        480,
        1868,
        4217,
        4326,
        4663,
        5042,
        8453,
        10143,
        42161,
        42220,
        43114,
        57073,
        59144,
        81457,
        7777777,
        1301,
        84532,
        11155111,
    ] | None = Field(
        None,
        description="The unique ID of the blockchain. For a list of supported chains see the [FAQ](https://api-docs.uniswap.org/guides/faqs).",
    )


UniswapConfig = Annotated[
    Union[
        CheckApproval,
        CheckPermissions,
        GetQuote,
        CreateOrder,
        GetOrders,
        CreateSwap,
        GetSwaps,
        GetSwappableTokens,
        GetSupportedChains,
        GetTokens,
    ],
    Field(discriminator="operation"),
]


class UniswapFullConfig(NodeConfig[UniswapConfig, UniswapAPIKeyCredential]):
    pass


OPERATIONS = {
    "check_approval": (
        "POST",
        "/check_approval",
        [],
        {"x_permit2_disabled": "x-permit2-disabled"},
    ),
    "check_permissions": ("POST", "/permissions", [], {}),
    "get_quote": (
        "POST",
        "/quote",
        [],
        {
            "x_universal_router_version": "x-universal-router-version",
            "x_erc20eth_enabled": "x-erc20eth-enabled",
            "x_permit2_disabled": "x-permit2-disabled",
        },
    ),
    "create_order": (
        "POST",
        "/order",
        [],
        {"x_erc20eth_enabled": "x-erc20eth-enabled"},
    ),
    "get_orders": (
        "GET",
        "/orders",
        [
            "orderType",
            "orderId",
            "orderIds",
            "limit",
            "orderStatus",
            "swapper",
            "sortKey",
            "sort",
            "filler",
            "cursor",
        ],
        {},
    ),
    "create_swap": (
        "POST",
        "/swap",
        [],
        {
            "x_universal_router_version": "x-universal-router-version",
            "x_permit2_disabled": "x-permit2-disabled",
        },
    ),
    "get_swaps": ("GET", "/swaps", ["txHashes", "userOpHashes", "chainId"], {}),
    "get_swappable_tokens": (
        "GET",
        "/swappable_tokens",
        ["tokenIn", "tokenInChainId"],
        {},
    ),
    "get_supported_chains": ("GET", "/supported_chains", [], {}),
    "get_tokens": ("GET", "/tokens", ["sort", "limit", "chainId"], {}),
}


class UniswapAPINode(WorkflowNode):
    integration_type = "automation-uniswap-api"
    connection_evidence = ConnectionEvidence(
        operation="get_supported_chains",
        noun="supported Uniswap chains",
        proves="reachability",
    )

    @classmethod
    def get_config_model(cls):
        return UniswapFullConfig

    async def execute(self, inputs):
        if not self.config or not self.config.credentials:
            raise ValueError("Connect a Uniswap API key")
        config = self.config.config
        token = self.config.credentials.api_key
        method, path, query_fields, header_fields = OPERATIONS[config.operation]
        values = config.model_dump(
            mode="json", exclude_none=True, exclude={"operation"}
        )
        headers = {"x-api-key": token, "Accept": "application/json"}
        for field, header in header_fields.items():
            if field in values:
                value = values.pop(field)
                headers[header] = (
                    str(value).lower() if isinstance(value, bool) else str(value)
                )
        params = {}
        for field in query_fields:
            if field in values:
                value = values.pop(field)
                # OpenAPI form arrays use explode=false for hash and order IDs.
                params[field] = (
                    ",".join(map(str, value)) if isinstance(value, list) else value
                )
        async with httpx.AsyncClient(
            timeout=30, follow_redirects=False, trust_env=False
        ) as client:
            response = await client.request(
                method,
                BASE_URL + path,
                headers=headers,
                params=params,
                **({"json": values} if method == "POST" else {}),
            )
        if response.status_code >= 300:
            # Preserve the provider rejection for connection evidence, but never echo the key.
            message = response.text.replace(token, "[redacted]")[:2000]
            return {
                "status": "error",
                "http_status": response.status_code,
                "error": message or "Uniswap rejected the request",
            }
        try:
            body = response.json()
        except ValueError:
            raise ValueError("Uniswap returned a non-JSON response") from None
        if not isinstance(body, dict):
            raise ValueError("Uniswap returned an unexpected response shape")
        # Keep the provider envelope intact: quotes, permitData, cursors and
        # transaction calldata can be passed directly to the next operation.
        result = {"status": "success", "data": body}
        await self.emit(result)
        return result
