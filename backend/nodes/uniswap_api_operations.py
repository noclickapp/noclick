"""Public structured request fields from Uniswap Trading OpenAPI 1.0.0.

Source: https://trade-api.gateway.uniswap.org/v1/api.json
Internal-only fields are excluded. The provider's quote variants overlap, so
editor schemas use anyOf to accept its documented classic quote payloads.
The immutable provider contract remains unchanged in conformance checks.
"""

FIELD_SCHEMAS = {
    "CheckApproval.urgency": {
        "anyOf": [
            {"type": "string", "enum": ["normal", "fast", "urgent"]},
            {
                "type": "object",
                "description": "High-level fee tier selection with optional "
                "caller-supplied caps. Use this form when you need to "
                "override one or more gas fields; otherwise send the "
                "bare `Urgency` string.",
                "properties": {
                    "level": {"type": "string", "enum": ["normal", "fast", "urgent"]},
                    "overrides": {
                        "type": "object",
                        "description": "Caller-supplied caps "
                        "applied on top of the gas "
                        "service's computed quote. "
                        "All fields are absolute "
                        "wei (decimal string). "
                        "`maxPriorityFeePerGas` "
                        "and `maxFeePerGas` are "
                        "treated as caps - they "
                        "lower the quote, never "
                        "raise it. `gasLimit`, if "
                        "set, replaces the limit "
                        "calculation entirely.",
                        "properties": {
                            "maxPriorityFeePerGas": {
                                "type": "string",
                                "description": "Maximum "
                                "priority "
                                "fee "
                                "in "
                                "wei "
                                "(decimal "
                                "string).",
                            },
                            "maxFeePerGas": {
                                "type": "string",
                                "description": "Maximum "
                                "total "
                                "fee "
                                "per "
                                "gas "
                                "in "
                                "wei "
                                "(decimal "
                                "string).",
                            },
                            "gasLimit": {
                                "type": "string",
                                "description": "Gas "
                                "limit "
                                "cap "
                                "(in "
                                "gas "
                                "units, "
                                "decimal "
                                "string).",
                            },
                        },
                    },
                },
                "required": ["level"],
            },
        ],
        "description": "The urgency impacts the estimated gas price of the transaction. "
        "The higher the urgency, the higher the gas price, and the faster "
        "the transaction is likely to be selected from the mempool. Send "
        'the bare string form (e.g. `"normal"`) for the common case, or '
        "the object form `{ level, overrides }` to supply caller caps for "
        "`maxPriorityFeePerGas`, `maxFeePerGas`, and `gasLimit`.",
    },
    "CheckPermissions.tokens": {
        "type": "array",
        "minItems": 1,
        "maxItems": 2,
        "items": {
            "type": "string",
            "description": "The token which will be sent, specified by its token "
            "address. For a list of supported tokens, see the "
            "[FAQ](https://api-docs.uniswap.org/guides/faqs).",
            "pattern": "^(0x)?[0-9a-fA-F]{40}$",
        },
        "description": "Tokens to check permissions for. Maximum of 2 per request.",
    },
    "GetQuote.protocols": {
        "type": "array",
        "items": {
            "type": "string",
            "enum": [
                "V2",
                "V3",
                "V4",
                "UNISWAPX",
                "UNISWAPX_V2",
                "UNISWAPX_V3",
                "UNISWAPX_LATEST",
            ],
            "description": "The protocol to use for the swap/order. Use "
            "`UNISWAPX_LATEST` to route through the latest UniswapX "
            "protocol supported on the request chain.",
        },
        "description": "The protocols to use for the swap/order. If the `protocols` field is "
        "defined, then you can only set the `routingPreference` to "
        "`BEST_PRICE`. Note that the value `UNISWAPX` is deprecated and will "
        "be removed in a future release.",
    },
    "GetQuote.urgency": {
        "anyOf": [
            {"type": "string", "enum": ["normal", "fast", "urgent"]},
            {
                "type": "object",
                "description": "High-level fee tier selection with optional caller-supplied "
                "caps. Use this form when you need to override one or more "
                "gas fields; otherwise send the bare `Urgency` string.",
                "properties": {
                    "level": {"type": "string", "enum": ["normal", "fast", "urgent"]},
                    "overrides": {
                        "type": "object",
                        "description": "Caller-supplied caps applied "
                        "on top of the gas service's "
                        "computed quote. All fields are "
                        "absolute wei (decimal string). "
                        "`maxPriorityFeePerGas` and "
                        "`maxFeePerGas` are treated as "
                        "caps - they lower the quote, "
                        "never raise it. `gasLimit`, if "
                        "set, replaces the limit "
                        "calculation entirely.",
                        "properties": {
                            "maxPriorityFeePerGas": {
                                "type": "string",
                                "description": "Maximum "
                                "priority "
                                "fee "
                                "in "
                                "wei "
                                "(decimal "
                                "string).",
                            },
                            "maxFeePerGas": {
                                "type": "string",
                                "description": "Maximum "
                                "total "
                                "fee "
                                "per "
                                "gas "
                                "in "
                                "wei "
                                "(decimal "
                                "string).",
                            },
                            "gasLimit": {
                                "type": "string",
                                "description": "Gas "
                                "limit "
                                "cap "
                                "(in "
                                "gas "
                                "units, "
                                "decimal "
                                "string).",
                            },
                        },
                    },
                },
                "required": ["level"],
            },
        ],
        "description": "The urgency impacts the estimated gas price of the transaction. The "
        "higher the urgency, the higher the gas price, and the faster the "
        "transaction is likely to be selected from the mempool. Send the bare "
        'string form (e.g. `"normal"`) for the common case, or the object form '
        "`{ level, overrides }` to supply caller caps for "
        "`maxPriorityFeePerGas`, `maxFeePerGas`, and `gasLimit`.",
    },
    "GetQuote.integratorFees": {
        "type": "array",
        "description": "Optional integrator fees: up to 4 entries, on both UniswapX and "
        "classic (Universal Router) routes. Each recipient may appear at "
        "most once, and the `bips` summed across all entries must not "
        "exceed 500 (5%). Multi-entry fees on a Universal Router route "
        "require router version 2.1.1 or later and are exact-input only. "
        "Omitting the field or passing an empty array means no "
        "integrator fee. Invalid fees return a 400 with `errorCode` "
        "`IntegratorFeesTooManyEntriesError`, "
        "`IntegratorFeeEntryExceedsMaxError`, "
        "`IntegratorFeesTotalExceedsMaxError`, or "
        "`InvalidIntegratorFeesError`.",
        "items": {
            "type": "object",
            "description": "A fee configuration specifying the fee amount in "
            "basis points and the recipient address.",
            "properties": {
                "bips": {
                    "type": "number",
                    "description": "Fee amount in basis points (1 "
                    "bip = 0.01%). Must be greater "
                    "than 0 and at most 500.",
                    "minimum": 0,
                    "exclusiveMinimum": True,
                    "maximum": 500,
                },
                "recipient": {
                    "type": "string",
                    "description": "Ethereum address that " "receives the fee.",
                    "pattern": "^0x[a-fA-F0-9]{40}$",
                },
            },
            "required": ["bips", "recipient"],
        },
        "maxItems": 4,
    },
    "CreateOrder.quote": {
        "anyOf": [
            {
                "title": "UniswapX V2 Quote",
                "type": "object",
                "properties": {
                    "encodedOrder": {
                        "type": "string",
                        "description": "An encoded copy of the "
                        "order details which will "
                        "be submitted to the filler "
                        "network along with the "
                        "signed permit.",
                    },
                    "orderId": {
                        "type": "string",
                        "description": "A unique ID for the order. Used "
                        "to track the order's status.",
                    },
                    "orderInfo": {
                        "type": "object",
                        "properties": {
                            "chainId": {
                                "description": "The "
                                "unique "
                                "ID "
                                "of "
                                "the "
                                "blockchain. "
                                "For "
                                "a "
                                "list "
                                "of "
                                "supported "
                                "chains "
                                "see "
                                "the "
                                "[FAQ](https://api-docs.uniswap.org/guides/faqs).",
                                "type": "number",
                                "enum": [
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
                                ],
                                "default": 1,
                            },
                            "nonce": {
                                "type": "string",
                                "description": "A "
                                "unique "
                                "nonce "
                                "for "
                                "this "
                                "order.",
                            },
                            "reactor": {
                                "type": "string",
                                "description": "The "
                                "address "
                                "of "
                                "a "
                                "contract "
                                "which "
                                "will "
                                "be "
                                "used "
                                "to "
                                "facilitate "
                                "the "
                                "swap.",
                                "pattern": "^(0x)?[0-9a-fA-F]{40}$",
                            },
                            "swapper": {
                                "type": "string",
                                "description": "(optional) "
                                "The "
                                "wallet "
                                "address "
                                "which "
                                "will "
                                "receive "
                                "the "
                                "output "
                                "of "
                                "the "
                                "swap. "
                                "If "
                                "not "
                                "provided, "
                                "the "
                                "output "
                                "is "
                                "returned "
                                "to "
                                "the "
                                "`swapper`.",
                                "pattern": "^(0x)?[0-9a-fA-F]{40}$",
                            },
                            "deadline": {
                                "type": "number",
                                "description": "The "
                                "unix "
                                "timestamp "
                                "at "
                                "which "
                                "the "
                                "order "
                                "will "
                                "be "
                                "reverted "
                                "if "
                                "not "
                                "filled.",
                            },
                            "additionalValidationContract": {
                                "type": "string",
                                "default": "0x0000000000000000000000000000000000000000",
                                "description": "Unused " "and " "deprecated.",
                                "deprecated": True,
                            },
                            "additionalValidationData": {
                                "type": "string",
                                "default": "0x",
                                "description": "Unused " "and " "deprecated.",
                                "deprecated": True,
                            },
                            "input": {
                                "type": "object",
                                "properties": {
                                    "startAmount": {
                                        "type": "string",
                                        "description": "The "
                                        "intended "
                                        "execution "
                                        "quantity "
                                        "of "
                                        "tokens "
                                        "resulting "
                                        "from "
                                        "this "
                                        "swap.",
                                    },
                                    "endAmount": {
                                        "type": "string",
                                        "description": "The "
                                        "worst "
                                        "case "
                                        "quantity "
                                        "of "
                                        "tokens "
                                        "resulting "
                                        "from "
                                        "this "
                                        "swap.",
                                    },
                                    "token": {
                                        "type": "string",
                                        "description": "The "
                                        "token "
                                        "which "
                                        "will "
                                        "be "
                                        "sent, "
                                        "specified "
                                        "by "
                                        "its "
                                        "token "
                                        "address. "
                                        "For "
                                        "a "
                                        "list "
                                        "of "
                                        "supported "
                                        "tokens, "
                                        "see "
                                        "the "
                                        "[FAQ](https://api-docs.uniswap.org/guides/faqs).",
                                        "pattern": "^(0x)?[0-9a-fA-F]{40}$",
                                    },
                                },
                                "required": ["startAmount", "endAmount", "type"],
                            },
                            "outputs": {
                                "type": "array",
                                "items": {
                                    "type": "object",
                                    "properties": {
                                        "startAmount": {
                                            "type": "string",
                                            "description": "The "
                                            "intended "
                                            "execution "
                                            "quantity "
                                            "of "
                                            "tokens "
                                            "resulting "
                                            "from "
                                            "this "
                                            "swap.",
                                        },
                                        "endAmount": {
                                            "type": "string",
                                            "description": "The "
                                            "worst "
                                            "case "
                                            "quantity "
                                            "of "
                                            "tokens "
                                            "resulting "
                                            "from "
                                            "this "
                                            "swap.",
                                        },
                                        "token": {
                                            "type": "string",
                                            "description": "The "
                                            "token "
                                            "which "
                                            "will "
                                            "be "
                                            "received, "
                                            "specified "
                                            "by "
                                            "its "
                                            "token "
                                            "address. "
                                            "For "
                                            "a "
                                            "list "
                                            "of "
                                            "supported "
                                            "tokens, "
                                            "see "
                                            "the "
                                            "[FAQ](https://api-docs.uniswap.org/guides/faqs).",
                                            "pattern": "^(0x)?[0-9a-fA-F]{40}$",
                                        },
                                        "recipient": {
                                            "type": "string",
                                            "description": "(optional) "
                                            "The "
                                            "wallet "
                                            "address "
                                            "which "
                                            "will "
                                            "receive "
                                            "the "
                                            "output "
                                            "of "
                                            "the "
                                            "swap. "
                                            "If "
                                            "not "
                                            "provided, "
                                            "the "
                                            "output "
                                            "is "
                                            "returned "
                                            "to "
                                            "the "
                                            "`swapper`.",
                                            "pattern": "^(0x)?[0-9a-fA-F]{40}$",
                                        },
                                    },
                                    "required": [
                                        "startAmount",
                                        "endAmount",
                                        "token",
                                        "recipient",
                                    ],
                                },
                            },
                            "cosigner": {
                                "type": "string",
                                "description": "The "
                                "address "
                                "of "
                                "a "
                                "cosigner "
                                "who "
                                "will "
                                "run "
                                "the "
                                "auction "
                                "and "
                                "ensure "
                                "the "
                                "best "
                                "executable "
                                "price "
                                "within "
                                "the "
                                "given "
                                "parameters. "
                                "Currently "
                                "the "
                                "cosigner "
                                "is "
                                "always "
                                "Uniswap "
                                "Labs.",
                                "pattern": "^(0x)?[0-9a-fA-F]{40}$",
                            },
                        },
                        "required": [
                            "chainId",
                            "nonce",
                            "reactor",
                            "swapper",
                            "deadline",
                            "validationContract",
                            "validationData",
                            "startTime",
                            "endTime",
                            "exclusiveFiller",
                            "exclusivityOverrideBps",
                            "input",
                            "outputs",
                        ],
                    },
                    "input": {
                        "type": "object",
                        "properties": {
                            "amount": {
                                "type": "string",
                                "description": "The "
                                "quantity "
                                "of "
                                "tokens "
                                "denominated "
                                "in the "
                                "token's "
                                "base "
                                "units. "
                                "(For "
                                "example, "
                                "for an "
                                "ERC20 "
                                "token "
                                "one "
                                "token "
                                "is "
                                "1x10^18 "
                                "base "
                                "units. "
                                "For one "
                                "USDC "
                                "token "
                                "one "
                                "token "
                                "is "
                                "1x10^6 "
                                "base "
                                "units.) "
                                "This "
                                "value "
                                "must be "
                                "greater "
                                "than 0.",
                                "pattern": "^[0-9]+$",
                            },
                            "token": {
                                "type": "string",
                                "description": "The "
                                "token "
                                "which "
                                "will be "
                                "sent, "
                                "specified "
                                "by its "
                                "token "
                                "address. "
                                "For a "
                                "list of "
                                "supported "
                                "tokens, "
                                "see the "
                                "[FAQ](https://api-docs.uniswap.org/guides/faqs).",
                                "pattern": "^(0x)?[0-9a-fA-F]{40}$",
                            },
                            "maximumAmount": {
                                "type": "string",
                                "description": "The "
                                "quantity "
                                "of "
                                "tokens "
                                "denominated "
                                "in "
                                "the "
                                "token's "
                                "base "
                                "units. "
                                "(For "
                                "example, "
                                "for "
                                "an "
                                "ERC20 "
                                "token "
                                "one "
                                "token "
                                "is "
                                "1x10^18 "
                                "base "
                                "units. "
                                "For "
                                "one "
                                "USDC "
                                "token "
                                "one "
                                "token "
                                "is "
                                "1x10^6 "
                                "base "
                                "units.) "
                                "This "
                                "value "
                                "must "
                                "be "
                                "greater "
                                "than "
                                "0.",
                                "pattern": "^[0-9]+$",
                            },
                        },
                    },
                    "output": {
                        "type": "object",
                        "properties": {
                            "amount": {
                                "type": "string",
                                "description": "The "
                                "quantity "
                                "of "
                                "tokens "
                                "denominated "
                                "in the "
                                "token's "
                                "base "
                                "units. "
                                "(For "
                                "example, "
                                "for an "
                                "ERC20 "
                                "token "
                                "one "
                                "token "
                                "is "
                                "1x10^18 "
                                "base "
                                "units. "
                                "For "
                                "one "
                                "USDC "
                                "token "
                                "one "
                                "token "
                                "is "
                                "1x10^6 "
                                "base "
                                "units.) "
                                "This "
                                "value "
                                "must "
                                "be "
                                "greater "
                                "than "
                                "0.",
                                "pattern": "^[0-9]+$",
                            },
                            "token": {
                                "type": "string",
                                "description": "The "
                                "token "
                                "which "
                                "will be "
                                "received, "
                                "specified "
                                "by its "
                                "token "
                                "address. "
                                "For a "
                                "list of "
                                "supported "
                                "tokens, "
                                "see the "
                                "[FAQ](https://api-docs.uniswap.org/guides/faqs).",
                                "pattern": "^(0x)?[0-9a-fA-F]{40}$",
                            },
                            "recipient": {
                                "type": "string",
                                "description": "(optional) "
                                "The "
                                "wallet "
                                "address "
                                "which "
                                "will "
                                "receive "
                                "the "
                                "output "
                                "of "
                                "the "
                                "swap. "
                                "If "
                                "not "
                                "provided, "
                                "the "
                                "output "
                                "is "
                                "returned "
                                "to "
                                "the "
                                "`swapper`.",
                                "pattern": "^(0x)?[0-9a-fA-F]{40}$",
                            },
                            "minimumAmount": {
                                "type": "string",
                                "description": "The "
                                "quantity "
                                "of "
                                "tokens "
                                "denominated "
                                "in "
                                "the "
                                "token's "
                                "base "
                                "units. "
                                "(For "
                                "example, "
                                "for "
                                "an "
                                "ERC20 "
                                "token "
                                "one "
                                "token "
                                "is "
                                "1x10^18 "
                                "base "
                                "units. "
                                "For "
                                "one "
                                "USDC "
                                "token "
                                "one "
                                "token "
                                "is "
                                "1x10^6 "
                                "base "
                                "units.) "
                                "This "
                                "value "
                                "must "
                                "be "
                                "greater "
                                "than "
                                "0.",
                                "pattern": "^[0-9]+$",
                            },
                        },
                    },
                    "quoteId": {
                        "type": "string",
                        "description": "A unique ID for the quote.",
                    },
                    "slippageTolerance": {
                        "description": "The slippage "
                        "tolerance as a "
                        "percentage up to a "
                        "maximum of two "
                        "decimal places, "
                        "between 0 and 100 (a "
                        "value outside that "
                        "range is rejected). "
                        "This is the maximum "
                        "acceptable output "
                        "loss as a percentage: "
                        "for exact-input "
                        "trades, the minimum "
                        "received is "
                        "expectedOut × (1 - "
                        "slippageTolerance); "
                        "for exact-output "
                        "trades, the maximum "
                        "input is expectedIn × "
                        "(1 + "
                        "slippageTolerance).\n"
                        "\n"
                        "When submitting a "
                        "quote, note that "
                        "slippage tolerance "
                        "works differently in "
                        "UniswapX swaps where "
                        "it does not set a "
                        "limit on the Spread "
                        "in an order. See "
                        "[here](https://api-docs.uniswap.org/guides/faqs#why-do-uniswapx-quotes-have-more-slippage-than-the-tolerance-i-set) "
                        "for more "
                        "information.\n"
                        "\n"
                        "Note that if the "
                        "trade type is "
                        "`EXACT_INPUT`, then "
                        "the slippage is in "
                        "terms of the output "
                        "token. If the trade "
                        "type is "
                        "`EXACT_OUTPUT`, then "
                        "the slippage is in "
                        "terms of the input "
                        "token.\n"
                        "\n"
                        "When submitting a "
                        "request, "
                        "`slippageTolerance` "
                        "may not be set when "
                        "`autoSlippage` is "
                        "defined. One of "
                        "`slippageTolerance` "
                        "or `autoSlippage` "
                        "must be defined.",
                        "type": "number",
                        "minimum": 0,
                        "maximum": 100,
                        "pattern": "^[0-9]{0,3}\\.?[0-9]{0,2}$",
                    },
                    "deadlineBufferSecs": {"type": "number"},
                    "classicGasUseEstimateUSD": {
                        "description": "The gas fee "
                        "you would pay "
                        "if you opted "
                        "for a CLASSIC "
                        "swap over a "
                        "Uniswap X "
                        "order in terms "
                        "of USD.",
                        "type": "string",
                    },
                    "aggregatedOutputs": {
                        "type": "array",
                        "items": {
                            "description": "An array of "
                            "all outputs "
                            "of the "
                            "proposed "
                            "transaction. "
                            "This "
                            "includes "
                            "the swap as "
                            "well as any "
                            "fees "
                            "collected "
                            "by the API "
                            "integrator. "
                            "This does "
                            "not include "
                            "pool fees "
                            "when "
                            "routing is "
                            "through a "
                            "Uniswap "
                            "Protocol "
                            "pool.",
                            "type": "object",
                            "properties": {
                                "token": {
                                    "type": "string",
                                    "description": "The "
                                    "token "
                                    "which "
                                    "will "
                                    "be "
                                    "received, "
                                    "specified "
                                    "by "
                                    "its "
                                    "token "
                                    "address. "
                                    "For "
                                    "a "
                                    "list "
                                    "of "
                                    "supported "
                                    "tokens, "
                                    "see "
                                    "the "
                                    "[FAQ](https://api-docs.uniswap.org/guides/faqs).",
                                    "pattern": "^(0x)?[0-9a-fA-F]{40}$",
                                },
                                "amount": {
                                    "type": "string",
                                    "description": "The "
                                    "quantity "
                                    "of "
                                    "tokens "
                                    "denominated "
                                    "in "
                                    "the "
                                    "token's "
                                    "base "
                                    "units. "
                                    "(For "
                                    "example, "
                                    "for "
                                    "an "
                                    "ERC20 "
                                    "token "
                                    "one "
                                    "token "
                                    "is "
                                    "1x10^18 "
                                    "base "
                                    "units. "
                                    "For "
                                    "one "
                                    "USDC "
                                    "token "
                                    "one "
                                    "token "
                                    "is "
                                    "1x10^6 "
                                    "base "
                                    "units.) "
                                    "This "
                                    "value "
                                    "must "
                                    "be "
                                    "greater "
                                    "than "
                                    "0.",
                                    "pattern": "^[0-9]+$",
                                },
                                "recipient": {
                                    "type": "string",
                                    "description": "(optional) "
                                    "The "
                                    "wallet "
                                    "address "
                                    "which "
                                    "will "
                                    "receive "
                                    "the "
                                    "output "
                                    "of "
                                    "the "
                                    "swap. "
                                    "If "
                                    "not "
                                    "provided, "
                                    "the "
                                    "output "
                                    "is "
                                    "returned "
                                    "to "
                                    "the "
                                    "`swapper`.",
                                    "pattern": "^(0x)?[0-9a-fA-F]{40}$",
                                },
                                "bps": {
                                    "type": "number",
                                    "multipleOf": 0.01,
                                    "description": "The "
                                    "portion "
                                    "of "
                                    "the "
                                    "swap "
                                    "stated "
                                    "in "
                                    "basis "
                                    "points. "
                                    "Fractional "
                                    "basis "
                                    "points "
                                    "are "
                                    "supported "
                                    "with "
                                    "up "
                                    "to "
                                    "two "
                                    "decimal "
                                    "places "
                                    "(e.g. "
                                    "12.5).",
                                },
                                "minAmount": {
                                    "type": "string",
                                    "description": "The "
                                    "minimum "
                                    "portion "
                                    "of "
                                    "the "
                                    "swap, "
                                    "stated "
                                    "in "
                                    "the "
                                    "base "
                                    "unit "
                                    "of "
                                    "the "
                                    "token, "
                                    "which "
                                    "will "
                                    "be "
                                    "output "
                                    "to "
                                    "the "
                                    "recipient.",
                                },
                                "fee": {
                                    "type": "string",
                                    "enum": ["INTEGRATOR"],
                                    "description": "Set "
                                    "to "
                                    "INTEGRATOR "
                                    "when "
                                    "this "
                                    "output "
                                    "is "
                                    "an "
                                    "integrator "
                                    "fee "
                                    "(as "
                                    "specified "
                                    "by "
                                    "the "
                                    "`integratorFees` "
                                    "array "
                                    "in "
                                    "the "
                                    "/quote "
                                    "request); "
                                    "omitted "
                                    "for "
                                    "the "
                                    "core "
                                    "output "
                                    "of "
                                    "the "
                                    "swap. "
                                    "One "
                                    "INTEGRATOR "
                                    "output "
                                    "is "
                                    "returned "
                                    "per "
                                    "fee "
                                    "recipient, "
                                    "in "
                                    "the "
                                    "order "
                                    "the "
                                    "recipients "
                                    "were "
                                    "requested, "
                                    "and "
                                    "their "
                                    "amounts "
                                    "sum "
                                    "to "
                                    "the "
                                    "amount "
                                    "deducted "
                                    "from "
                                    "the "
                                    "core "
                                    "output.",
                                },
                            },
                        },
                    },
                },
                "required": ["encodedOrder", "orderInfo", "orderId"],
            },
            {
                "title": "UniswapX V3 Quote",
                "type": "object",
                "properties": {
                    "encodedOrder": {
                        "type": "string",
                        "description": "An encoded copy of the "
                        "order details which will "
                        "be submitted to the filler "
                        "network along with the "
                        "signed permit.",
                    },
                    "orderId": {
                        "type": "string",
                        "description": "A unique ID for the order. Used "
                        "to track the order's status.",
                    },
                    "orderInfo": {
                        "type": "object",
                        "properties": {
                            "chainId": {
                                "description": "The "
                                "unique "
                                "ID "
                                "of "
                                "the "
                                "blockchain. "
                                "For "
                                "a "
                                "list "
                                "of "
                                "supported "
                                "chains "
                                "see "
                                "the "
                                "[FAQ](https://api-docs.uniswap.org/guides/faqs).",
                                "type": "number",
                                "enum": [
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
                                ],
                                "default": 1,
                            },
                            "nonce": {
                                "type": "string",
                                "description": "A "
                                "unique "
                                "nonce "
                                "for "
                                "this "
                                "order.",
                            },
                            "reactor": {
                                "type": "string",
                                "description": "The "
                                "address "
                                "of "
                                "a "
                                "contract "
                                "which "
                                "will "
                                "be "
                                "used "
                                "to "
                                "facilitate "
                                "the "
                                "swap.",
                                "pattern": "^(0x)?[0-9a-fA-F]{40}$",
                            },
                            "swapper": {
                                "type": "string",
                                "description": "(optional) "
                                "The "
                                "wallet "
                                "address "
                                "which "
                                "will "
                                "receive "
                                "the "
                                "output "
                                "of "
                                "the "
                                "swap. "
                                "If "
                                "not "
                                "provided, "
                                "the "
                                "output "
                                "is "
                                "returned "
                                "to "
                                "the "
                                "`swapper`.",
                                "pattern": "^(0x)?[0-9a-fA-F]{40}$",
                            },
                            "deadline": {
                                "type": "number",
                                "description": "The "
                                "unix "
                                "timestamp "
                                "at "
                                "which "
                                "the "
                                "order "
                                "will "
                                "be "
                                "reverted "
                                "if "
                                "not "
                                "filled.",
                            },
                            "additionalValidationContract": {
                                "type": "string",
                                "default": "0x0000000000000000000000000000000000000000",
                                "description": "Unused " "and " "deprecated.",
                                "deprecated": True,
                            },
                            "additionalValidationData": {
                                "type": "string",
                                "default": "0x",
                                "description": "Unused " "and " "deprecated.",
                                "deprecated": True,
                            },
                            "input": {
                                "type": "object",
                                "properties": {
                                    "startAmount": {
                                        "type": "string",
                                        "description": "The "
                                        "intended "
                                        "execution "
                                        "quantity "
                                        "of "
                                        "tokens "
                                        "resulting "
                                        "from "
                                        "this "
                                        "swap.",
                                    },
                                    "maxAmount": {"type": "string"},
                                    "adjustmentPerGweiBaseFee": {"type": "string"},
                                    "curve": {
                                        "type": "object",
                                        "properties": {
                                            "relativeBlocks": {
                                                "type": "array",
                                                "items": {"type": "number"},
                                            },
                                            "relativeAmounts": {
                                                "type": "array",
                                                "items": {"type": "string"},
                                            },
                                        },
                                        "required": ["type"],
                                    },
                                    "token": {
                                        "type": "string",
                                        "description": "The "
                                        "token "
                                        "which "
                                        "will "
                                        "be "
                                        "sent, "
                                        "specified "
                                        "by "
                                        "its "
                                        "token "
                                        "address. "
                                        "For "
                                        "a "
                                        "list "
                                        "of "
                                        "supported "
                                        "tokens, "
                                        "see "
                                        "the "
                                        "[FAQ](https://api-docs.uniswap.org/guides/faqs).",
                                        "pattern": "^(0x)?[0-9a-fA-F]{40}$",
                                    },
                                },
                                "required": [
                                    "startAmount",
                                    "maxAmount",
                                    "adjustmentPerGweiBaseFee",
                                    "curve",
                                    "token",
                                ],
                            },
                            "outputs": {
                                "type": "array",
                                "items": {
                                    "type": "object",
                                    "properties": {
                                        "startAmount": {
                                            "type": "string",
                                            "description": "The "
                                            "intended "
                                            "execution "
                                            "quantity "
                                            "of "
                                            "tokens "
                                            "resulting "
                                            "from "
                                            "this "
                                            "swap.",
                                        },
                                        "minAmount": {
                                            "type": "string",
                                            "description": "The "
                                            "minimum "
                                            "portion "
                                            "of "
                                            "the "
                                            "swap, "
                                            "stated "
                                            "in "
                                            "the "
                                            "base "
                                            "unit "
                                            "of "
                                            "the "
                                            "token, "
                                            "which "
                                            "will "
                                            "be "
                                            "output "
                                            "to "
                                            "the "
                                            "recipient.",
                                        },
                                        "recipient": {
                                            "type": "string",
                                            "description": "(optional) "
                                            "The "
                                            "wallet "
                                            "address "
                                            "which "
                                            "will "
                                            "receive "
                                            "the "
                                            "output "
                                            "of "
                                            "the "
                                            "swap. "
                                            "If "
                                            "not "
                                            "provided, "
                                            "the "
                                            "output "
                                            "is "
                                            "returned "
                                            "to "
                                            "the "
                                            "`swapper`.",
                                            "pattern": "^(0x)?[0-9a-fA-F]{40}$",
                                        },
                                        "adjustmentPerGweiBaseFee": {"type": "string"},
                                        "curve": {
                                            "type": "object",
                                            "properties": {
                                                "relativeBlocks": {
                                                    "type": "array",
                                                    "items": {"type": "number"},
                                                },
                                                "relativeAmounts": {
                                                    "type": "array",
                                                    "items": {"type": "string"},
                                                },
                                            },
                                            "required": ["type"],
                                        },
                                        "token": {
                                            "type": "string",
                                            "description": "The "
                                            "token "
                                            "which "
                                            "will "
                                            "be "
                                            "received, "
                                            "specified "
                                            "by "
                                            "its "
                                            "token "
                                            "address. "
                                            "For "
                                            "a "
                                            "list "
                                            "of "
                                            "supported "
                                            "tokens, "
                                            "see "
                                            "the "
                                            "[FAQ](https://api-docs.uniswap.org/guides/faqs).",
                                            "pattern": "^(0x)?[0-9a-fA-F]{40}$",
                                        },
                                    },
                                    "required": [
                                        "startAmount",
                                        "maxAmount",
                                        "adjustmentPerGweiBaseFee",
                                        "curve",
                                        "token",
                                        "recipient",
                                    ],
                                },
                            },
                            "cosigner": {
                                "type": "string",
                                "description": "The "
                                "address "
                                "of "
                                "a "
                                "cosigner "
                                "who "
                                "will "
                                "run "
                                "the "
                                "auction "
                                "and "
                                "ensure "
                                "the "
                                "best "
                                "executable "
                                "price "
                                "within "
                                "the "
                                "given "
                                "parameters. "
                                "Currently "
                                "the "
                                "cosigner "
                                "is "
                                "always "
                                "Uniswap "
                                "Labs.",
                                "pattern": "^(0x)?[0-9a-fA-F]{40}$",
                            },
                            "startingBaseFee": {"type": "string"},
                        },
                        "required": [
                            "chainId",
                            "nonce",
                            "reactor",
                            "swapper",
                            "deadline",
                            "validationContract",
                            "validationData",
                            "startTime",
                            "endTime",
                            "exclusiveFiller",
                            "exclusivityOverrideBps",
                            "input",
                            "outputs",
                        ],
                    },
                    "input": {
                        "type": "object",
                        "properties": {
                            "amount": {
                                "type": "string",
                                "description": "The "
                                "quantity "
                                "of "
                                "tokens "
                                "denominated "
                                "in the "
                                "token's "
                                "base "
                                "units. "
                                "(For "
                                "example, "
                                "for an "
                                "ERC20 "
                                "token "
                                "one "
                                "token "
                                "is "
                                "1x10^18 "
                                "base "
                                "units. "
                                "For one "
                                "USDC "
                                "token "
                                "one "
                                "token "
                                "is "
                                "1x10^6 "
                                "base "
                                "units.) "
                                "This "
                                "value "
                                "must be "
                                "greater "
                                "than 0.",
                                "pattern": "^[0-9]+$",
                            },
                            "token": {
                                "type": "string",
                                "description": "The "
                                "token "
                                "which "
                                "will be "
                                "sent, "
                                "specified "
                                "by its "
                                "token "
                                "address. "
                                "For a "
                                "list of "
                                "supported "
                                "tokens, "
                                "see the "
                                "[FAQ](https://api-docs.uniswap.org/guides/faqs).",
                                "pattern": "^(0x)?[0-9a-fA-F]{40}$",
                            },
                            "maximumAmount": {
                                "type": "string",
                                "description": "The "
                                "quantity "
                                "of "
                                "tokens "
                                "denominated "
                                "in "
                                "the "
                                "token's "
                                "base "
                                "units. "
                                "(For "
                                "example, "
                                "for "
                                "an "
                                "ERC20 "
                                "token "
                                "one "
                                "token "
                                "is "
                                "1x10^18 "
                                "base "
                                "units. "
                                "For "
                                "one "
                                "USDC "
                                "token "
                                "one "
                                "token "
                                "is "
                                "1x10^6 "
                                "base "
                                "units.) "
                                "This "
                                "value "
                                "must "
                                "be "
                                "greater "
                                "than "
                                "0.",
                                "pattern": "^[0-9]+$",
                            },
                        },
                    },
                    "output": {
                        "type": "object",
                        "properties": {
                            "amount": {
                                "type": "string",
                                "description": "The "
                                "quantity "
                                "of "
                                "tokens "
                                "denominated "
                                "in the "
                                "token's "
                                "base "
                                "units. "
                                "(For "
                                "example, "
                                "for an "
                                "ERC20 "
                                "token "
                                "one "
                                "token "
                                "is "
                                "1x10^18 "
                                "base "
                                "units. "
                                "For "
                                "one "
                                "USDC "
                                "token "
                                "one "
                                "token "
                                "is "
                                "1x10^6 "
                                "base "
                                "units.) "
                                "This "
                                "value "
                                "must "
                                "be "
                                "greater "
                                "than "
                                "0.",
                                "pattern": "^[0-9]+$",
                            },
                            "token": {
                                "type": "string",
                                "description": "The "
                                "token "
                                "which "
                                "will be "
                                "received, "
                                "specified "
                                "by its "
                                "token "
                                "address. "
                                "For a "
                                "list of "
                                "supported "
                                "tokens, "
                                "see the "
                                "[FAQ](https://api-docs.uniswap.org/guides/faqs).",
                                "pattern": "^(0x)?[0-9a-fA-F]{40}$",
                            },
                            "recipient": {
                                "type": "string",
                                "description": "(optional) "
                                "The "
                                "wallet "
                                "address "
                                "which "
                                "will "
                                "receive "
                                "the "
                                "output "
                                "of "
                                "the "
                                "swap. "
                                "If "
                                "not "
                                "provided, "
                                "the "
                                "output "
                                "is "
                                "returned "
                                "to "
                                "the "
                                "`swapper`.",
                                "pattern": "^(0x)?[0-9a-fA-F]{40}$",
                            },
                            "minimumAmount": {
                                "type": "string",
                                "description": "The "
                                "quantity "
                                "of "
                                "tokens "
                                "denominated "
                                "in "
                                "the "
                                "token's "
                                "base "
                                "units. "
                                "(For "
                                "example, "
                                "for "
                                "an "
                                "ERC20 "
                                "token "
                                "one "
                                "token "
                                "is "
                                "1x10^18 "
                                "base "
                                "units. "
                                "For "
                                "one "
                                "USDC "
                                "token "
                                "one "
                                "token "
                                "is "
                                "1x10^6 "
                                "base "
                                "units.) "
                                "This "
                                "value "
                                "must "
                                "be "
                                "greater "
                                "than "
                                "0.",
                                "pattern": "^[0-9]+$",
                            },
                        },
                    },
                    "quoteId": {
                        "type": "string",
                        "description": "A unique ID for the quote.",
                    },
                    "slippageTolerance": {
                        "description": "The slippage "
                        "tolerance as a "
                        "percentage up to a "
                        "maximum of two "
                        "decimal places, "
                        "between 0 and 100 (a "
                        "value outside that "
                        "range is rejected). "
                        "This is the maximum "
                        "acceptable output "
                        "loss as a percentage: "
                        "for exact-input "
                        "trades, the minimum "
                        "received is "
                        "expectedOut × (1 - "
                        "slippageTolerance); "
                        "for exact-output "
                        "trades, the maximum "
                        "input is expectedIn × "
                        "(1 + "
                        "slippageTolerance).\n"
                        "\n"
                        "When submitting a "
                        "quote, note that "
                        "slippage tolerance "
                        "works differently in "
                        "UniswapX swaps where "
                        "it does not set a "
                        "limit on the Spread "
                        "in an order. See "
                        "[here](https://api-docs.uniswap.org/guides/faqs#why-do-uniswapx-quotes-have-more-slippage-than-the-tolerance-i-set) "
                        "for more "
                        "information.\n"
                        "\n"
                        "Note that if the "
                        "trade type is "
                        "`EXACT_INPUT`, then "
                        "the slippage is in "
                        "terms of the output "
                        "token. If the trade "
                        "type is "
                        "`EXACT_OUTPUT`, then "
                        "the slippage is in "
                        "terms of the input "
                        "token.\n"
                        "\n"
                        "When submitting a "
                        "request, "
                        "`slippageTolerance` "
                        "may not be set when "
                        "`autoSlippage` is "
                        "defined. One of "
                        "`slippageTolerance` "
                        "or `autoSlippage` "
                        "must be defined.",
                        "type": "number",
                        "minimum": 0,
                        "maximum": 100,
                        "pattern": "^[0-9]{0,3}\\.?[0-9]{0,2}$",
                    },
                    "deadlineBufferSecs": {"type": "number"},
                    "classicGasUseEstimateUSD": {
                        "description": "The gas fee "
                        "you would pay "
                        "if you opted "
                        "for a CLASSIC "
                        "swap over a "
                        "Uniswap X "
                        "order in terms "
                        "of USD.",
                        "type": "string",
                    },
                    "expectedAmountIn": {"type": "string"},
                    "expectedAmountOut": {"type": "string"},
                    "aggregatedOutputs": {
                        "type": "array",
                        "items": {
                            "description": "An array of "
                            "all outputs "
                            "of the "
                            "proposed "
                            "transaction. "
                            "This "
                            "includes "
                            "the swap as "
                            "well as any "
                            "fees "
                            "collected "
                            "by the API "
                            "integrator. "
                            "This does "
                            "not include "
                            "pool fees "
                            "when "
                            "routing is "
                            "through a "
                            "Uniswap "
                            "Protocol "
                            "pool.",
                            "type": "object",
                            "properties": {
                                "token": {
                                    "type": "string",
                                    "description": "The "
                                    "token "
                                    "which "
                                    "will "
                                    "be "
                                    "received, "
                                    "specified "
                                    "by "
                                    "its "
                                    "token "
                                    "address. "
                                    "For "
                                    "a "
                                    "list "
                                    "of "
                                    "supported "
                                    "tokens, "
                                    "see "
                                    "the "
                                    "[FAQ](https://api-docs.uniswap.org/guides/faqs).",
                                    "pattern": "^(0x)?[0-9a-fA-F]{40}$",
                                },
                                "amount": {
                                    "type": "string",
                                    "description": "The "
                                    "quantity "
                                    "of "
                                    "tokens "
                                    "denominated "
                                    "in "
                                    "the "
                                    "token's "
                                    "base "
                                    "units. "
                                    "(For "
                                    "example, "
                                    "for "
                                    "an "
                                    "ERC20 "
                                    "token "
                                    "one "
                                    "token "
                                    "is "
                                    "1x10^18 "
                                    "base "
                                    "units. "
                                    "For "
                                    "one "
                                    "USDC "
                                    "token "
                                    "one "
                                    "token "
                                    "is "
                                    "1x10^6 "
                                    "base "
                                    "units.) "
                                    "This "
                                    "value "
                                    "must "
                                    "be "
                                    "greater "
                                    "than "
                                    "0.",
                                    "pattern": "^[0-9]+$",
                                },
                                "recipient": {
                                    "type": "string",
                                    "description": "(optional) "
                                    "The "
                                    "wallet "
                                    "address "
                                    "which "
                                    "will "
                                    "receive "
                                    "the "
                                    "output "
                                    "of "
                                    "the "
                                    "swap. "
                                    "If "
                                    "not "
                                    "provided, "
                                    "the "
                                    "output "
                                    "is "
                                    "returned "
                                    "to "
                                    "the "
                                    "`swapper`.",
                                    "pattern": "^(0x)?[0-9a-fA-F]{40}$",
                                },
                                "bps": {
                                    "type": "number",
                                    "multipleOf": 0.01,
                                    "description": "The "
                                    "portion "
                                    "of "
                                    "the "
                                    "swap "
                                    "stated "
                                    "in "
                                    "basis "
                                    "points. "
                                    "Fractional "
                                    "basis "
                                    "points "
                                    "are "
                                    "supported "
                                    "with "
                                    "up "
                                    "to "
                                    "two "
                                    "decimal "
                                    "places "
                                    "(e.g. "
                                    "12.5).",
                                },
                                "minAmount": {
                                    "type": "string",
                                    "description": "The "
                                    "minimum "
                                    "portion "
                                    "of "
                                    "the "
                                    "swap, "
                                    "stated "
                                    "in "
                                    "the "
                                    "base "
                                    "unit "
                                    "of "
                                    "the "
                                    "token, "
                                    "which "
                                    "will "
                                    "be "
                                    "output "
                                    "to "
                                    "the "
                                    "recipient.",
                                },
                                "fee": {
                                    "type": "string",
                                    "enum": ["INTEGRATOR"],
                                    "description": "Set "
                                    "to "
                                    "INTEGRATOR "
                                    "when "
                                    "this "
                                    "output "
                                    "is "
                                    "an "
                                    "integrator "
                                    "fee "
                                    "(as "
                                    "specified "
                                    "by "
                                    "the "
                                    "`integratorFees` "
                                    "array "
                                    "in "
                                    "the "
                                    "/quote "
                                    "request); "
                                    "omitted "
                                    "for "
                                    "the "
                                    "core "
                                    "output "
                                    "of "
                                    "the "
                                    "swap. "
                                    "One "
                                    "INTEGRATOR "
                                    "output "
                                    "is "
                                    "returned "
                                    "per "
                                    "fee "
                                    "recipient, "
                                    "in "
                                    "the "
                                    "order "
                                    "the "
                                    "recipients "
                                    "were "
                                    "requested, "
                                    "and "
                                    "their "
                                    "amounts "
                                    "sum "
                                    "to "
                                    "the "
                                    "amount "
                                    "deducted "
                                    "from "
                                    "the "
                                    "core "
                                    "output.",
                                },
                            },
                        },
                    },
                },
                "required": ["encodedOrder", "orderInfo", "orderId"],
            },
            {
                "title": "UniswapX Priority Quote",
                "type": "object",
                "properties": {
                    "encodedOrder": {
                        "type": "string",
                        "description": "An encoded copy of the "
                        "order details which will "
                        "be submitted to the filler "
                        "network along with the "
                        "signed permit.",
                    },
                    "orderId": {
                        "type": "string",
                        "description": "A unique ID for the order. Used "
                        "to track the order's status.",
                    },
                    "orderInfo": {
                        "type": "object",
                        "properties": {
                            "chainId": {
                                "description": "The "
                                "unique "
                                "ID "
                                "of "
                                "the "
                                "blockchain. "
                                "For "
                                "a "
                                "list "
                                "of "
                                "supported "
                                "chains "
                                "see "
                                "the "
                                "[FAQ](https://api-docs.uniswap.org/guides/faqs).",
                                "type": "number",
                                "enum": [
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
                                ],
                                "default": 1,
                            },
                            "nonce": {
                                "type": "string",
                                "description": "A "
                                "unique "
                                "nonce "
                                "for "
                                "this "
                                "order.",
                            },
                            "reactor": {
                                "type": "string",
                                "description": "The "
                                "address "
                                "of "
                                "a "
                                "contract "
                                "which "
                                "will "
                                "be "
                                "used "
                                "to "
                                "facilitate "
                                "the "
                                "swap.",
                                "pattern": "^(0x)?[0-9a-fA-F]{40}$",
                            },
                            "swapper": {
                                "type": "string",
                                "description": "(optional) "
                                "The "
                                "wallet "
                                "address "
                                "which "
                                "will "
                                "receive "
                                "the "
                                "output "
                                "of "
                                "the "
                                "swap. "
                                "If "
                                "not "
                                "provided, "
                                "the "
                                "output "
                                "is "
                                "returned "
                                "to "
                                "the "
                                "`swapper`.",
                                "pattern": "^(0x)?[0-9a-fA-F]{40}$",
                            },
                            "deadline": {
                                "type": "number",
                                "description": "The "
                                "unix "
                                "timestamp "
                                "at "
                                "which "
                                "the "
                                "order "
                                "will "
                                "be "
                                "reverted "
                                "if "
                                "not "
                                "filled.",
                            },
                            "additionalValidationContract": {
                                "type": "string",
                                "default": "0x0000000000000000000000000000000000000000",
                                "description": "Unused " "and " "deprecated.",
                                "deprecated": True,
                            },
                            "additionalValidationData": {
                                "type": "string",
                                "default": "0x",
                                "description": "Unused " "and " "deprecated.",
                                "deprecated": True,
                            },
                            "auctionStartBlock": {"type": "string"},
                            "baselinePriorityFeeWei": {"type": "string"},
                            "input": {
                                "type": "object",
                                "properties": {
                                    "amount": {
                                        "type": "string",
                                        "description": "The "
                                        "quantity "
                                        "of "
                                        "tokens "
                                        "denominated "
                                        "in "
                                        "the "
                                        "token's "
                                        "base "
                                        "units. "
                                        "(For "
                                        "example, "
                                        "for "
                                        "an "
                                        "ERC20 "
                                        "token "
                                        "one "
                                        "token "
                                        "is "
                                        "1x10^18 "
                                        "base "
                                        "units. "
                                        "For "
                                        "one "
                                        "USDC "
                                        "token "
                                        "one "
                                        "token "
                                        "is "
                                        "1x10^6 "
                                        "base "
                                        "units.) "
                                        "This "
                                        "value "
                                        "must "
                                        "be "
                                        "greater "
                                        "than "
                                        "0.",
                                        "pattern": "^[0-9]+$",
                                    },
                                    "token": {
                                        "type": "string",
                                        "description": "The "
                                        "token "
                                        "which "
                                        "will "
                                        "be "
                                        "sent, "
                                        "specified "
                                        "by "
                                        "its "
                                        "token "
                                        "address. "
                                        "For "
                                        "a "
                                        "list "
                                        "of "
                                        "supported "
                                        "tokens, "
                                        "see "
                                        "the "
                                        "[FAQ](https://api-docs.uniswap.org/guides/faqs).",
                                        "pattern": "^(0x)?[0-9a-fA-F]{40}$",
                                    },
                                    "mpsPerPriorityFeeWei": {"type": "string"},
                                },
                                "required": ["amount", "token", "mpsPerPriorityFeeWei"],
                            },
                            "outputs": {
                                "type": "array",
                                "items": {
                                    "type": "object",
                                    "properties": {
                                        "amount": {
                                            "type": "string",
                                            "description": "The "
                                            "quantity "
                                            "of "
                                            "tokens "
                                            "denominated "
                                            "in "
                                            "the "
                                            "token's "
                                            "base "
                                            "units. "
                                            "(For "
                                            "example, "
                                            "for "
                                            "an "
                                            "ERC20 "
                                            "token "
                                            "one "
                                            "token "
                                            "is "
                                            "1x10^18 "
                                            "base "
                                            "units. "
                                            "For "
                                            "one "
                                            "USDC "
                                            "token "
                                            "one "
                                            "token "
                                            "is "
                                            "1x10^6 "
                                            "base "
                                            "units.) "
                                            "This "
                                            "value "
                                            "must "
                                            "be "
                                            "greater "
                                            "than "
                                            "0.",
                                            "pattern": "^[0-9]+$",
                                        },
                                        "token": {
                                            "type": "string",
                                            "description": "The "
                                            "token "
                                            "which "
                                            "will "
                                            "be "
                                            "received, "
                                            "specified "
                                            "by "
                                            "its "
                                            "token "
                                            "address. "
                                            "For "
                                            "a "
                                            "list "
                                            "of "
                                            "supported "
                                            "tokens, "
                                            "see "
                                            "the "
                                            "[FAQ](https://api-docs.uniswap.org/guides/faqs).",
                                            "pattern": "^(0x)?[0-9a-fA-F]{40}$",
                                        },
                                        "recipient": {
                                            "type": "string",
                                            "description": "(optional) "
                                            "The "
                                            "wallet "
                                            "address "
                                            "which "
                                            "will "
                                            "receive "
                                            "the "
                                            "output "
                                            "of "
                                            "the "
                                            "swap. "
                                            "If "
                                            "not "
                                            "provided, "
                                            "the "
                                            "output "
                                            "is "
                                            "returned "
                                            "to "
                                            "the "
                                            "`swapper`.",
                                            "pattern": "^(0x)?[0-9a-fA-F]{40}$",
                                        },
                                        "mpsPerPriorityFeeWei": {
                                            "type": "string",
                                            "description": "The "
                                            "scaling "
                                            "factor "
                                            "of "
                                            "the "
                                            "priority "
                                            "fee "
                                            "based "
                                            "on "
                                            "the "
                                            "output "
                                            "token "
                                            "amount.",
                                        },
                                    },
                                    "required": [
                                        "amount",
                                        "token",
                                        "recipient",
                                        "mpsPerPriorityFeeWei",
                                    ],
                                },
                            },
                            "cosigner": {
                                "type": "string",
                                "description": "The "
                                "address "
                                "of "
                                "a "
                                "cosigner "
                                "who "
                                "will "
                                "run "
                                "the "
                                "auction "
                                "and "
                                "ensure "
                                "the "
                                "best "
                                "executable "
                                "price "
                                "within "
                                "the "
                                "given "
                                "parameters. "
                                "Currently "
                                "the "
                                "cosigner "
                                "is "
                                "always "
                                "Uniswap "
                                "Labs.",
                                "pattern": "^(0x)?[0-9a-fA-F]{40}$",
                            },
                        },
                        "required": [
                            "chainId",
                            "nonce",
                            "reactor",
                            "swapper",
                            "deadline",
                            "validationContract",
                            "validationData",
                            "auctionStartBlock",
                            "baselinePriorityFeeWei",
                            "input",
                            "outputs",
                            "cosigner",
                        ],
                    },
                    "input": {
                        "type": "object",
                        "properties": {
                            "amount": {
                                "type": "string",
                                "description": "The "
                                "quantity "
                                "of "
                                "tokens "
                                "denominated "
                                "in the "
                                "token's "
                                "base "
                                "units. "
                                "(For "
                                "example, "
                                "for an "
                                "ERC20 "
                                "token "
                                "one "
                                "token "
                                "is "
                                "1x10^18 "
                                "base "
                                "units. "
                                "For one "
                                "USDC "
                                "token "
                                "one "
                                "token "
                                "is "
                                "1x10^6 "
                                "base "
                                "units.) "
                                "This "
                                "value "
                                "must be "
                                "greater "
                                "than 0.",
                                "pattern": "^[0-9]+$",
                            },
                            "token": {
                                "type": "string",
                                "description": "The "
                                "token "
                                "which "
                                "will be "
                                "sent, "
                                "specified "
                                "by its "
                                "token "
                                "address. "
                                "For a "
                                "list of "
                                "supported "
                                "tokens, "
                                "see the "
                                "[FAQ](https://api-docs.uniswap.org/guides/faqs).",
                                "pattern": "^(0x)?[0-9a-fA-F]{40}$",
                            },
                            "maximumAmount": {
                                "type": "string",
                                "description": "The "
                                "quantity "
                                "of "
                                "tokens "
                                "denominated "
                                "in "
                                "the "
                                "token's "
                                "base "
                                "units. "
                                "(For "
                                "example, "
                                "for "
                                "an "
                                "ERC20 "
                                "token "
                                "one "
                                "token "
                                "is "
                                "1x10^18 "
                                "base "
                                "units. "
                                "For "
                                "one "
                                "USDC "
                                "token "
                                "one "
                                "token "
                                "is "
                                "1x10^6 "
                                "base "
                                "units.) "
                                "This "
                                "value "
                                "must "
                                "be "
                                "greater "
                                "than "
                                "0.",
                                "pattern": "^[0-9]+$",
                            },
                        },
                    },
                    "output": {
                        "type": "object",
                        "properties": {
                            "amount": {
                                "type": "string",
                                "description": "The "
                                "quantity "
                                "of "
                                "tokens "
                                "denominated "
                                "in the "
                                "token's "
                                "base "
                                "units. "
                                "(For "
                                "example, "
                                "for an "
                                "ERC20 "
                                "token "
                                "one "
                                "token "
                                "is "
                                "1x10^18 "
                                "base "
                                "units. "
                                "For "
                                "one "
                                "USDC "
                                "token "
                                "one "
                                "token "
                                "is "
                                "1x10^6 "
                                "base "
                                "units.) "
                                "This "
                                "value "
                                "must "
                                "be "
                                "greater "
                                "than "
                                "0.",
                                "pattern": "^[0-9]+$",
                            },
                            "token": {
                                "type": "string",
                                "description": "The "
                                "token "
                                "which "
                                "will be "
                                "received, "
                                "specified "
                                "by its "
                                "token "
                                "address. "
                                "For a "
                                "list of "
                                "supported "
                                "tokens, "
                                "see the "
                                "[FAQ](https://api-docs.uniswap.org/guides/faqs).",
                                "pattern": "^(0x)?[0-9a-fA-F]{40}$",
                            },
                            "recipient": {
                                "type": "string",
                                "description": "(optional) "
                                "The "
                                "wallet "
                                "address "
                                "which "
                                "will "
                                "receive "
                                "the "
                                "output "
                                "of "
                                "the "
                                "swap. "
                                "If "
                                "not "
                                "provided, "
                                "the "
                                "output "
                                "is "
                                "returned "
                                "to "
                                "the "
                                "`swapper`.",
                                "pattern": "^(0x)?[0-9a-fA-F]{40}$",
                            },
                            "minimumAmount": {
                                "type": "string",
                                "description": "The "
                                "quantity "
                                "of "
                                "tokens "
                                "denominated "
                                "in "
                                "the "
                                "token's "
                                "base "
                                "units. "
                                "(For "
                                "example, "
                                "for "
                                "an "
                                "ERC20 "
                                "token "
                                "one "
                                "token "
                                "is "
                                "1x10^18 "
                                "base "
                                "units. "
                                "For "
                                "one "
                                "USDC "
                                "token "
                                "one "
                                "token "
                                "is "
                                "1x10^6 "
                                "base "
                                "units.) "
                                "This "
                                "value "
                                "must "
                                "be "
                                "greater "
                                "than "
                                "0.",
                                "pattern": "^[0-9]+$",
                            },
                        },
                    },
                    "quoteId": {
                        "type": "string",
                        "description": "A unique ID for the quote.",
                    },
                    "slippageTolerance": {
                        "description": "The slippage "
                        "tolerance as a "
                        "percentage up to a "
                        "maximum of two "
                        "decimal places, "
                        "between 0 and 100 (a "
                        "value outside that "
                        "range is rejected). "
                        "This is the maximum "
                        "acceptable output "
                        "loss as a percentage: "
                        "for exact-input "
                        "trades, the minimum "
                        "received is "
                        "expectedOut × (1 - "
                        "slippageTolerance); "
                        "for exact-output "
                        "trades, the maximum "
                        "input is expectedIn × "
                        "(1 + "
                        "slippageTolerance).\n"
                        "\n"
                        "When submitting a "
                        "quote, note that "
                        "slippage tolerance "
                        "works differently in "
                        "UniswapX swaps where "
                        "it does not set a "
                        "limit on the Spread "
                        "in an order. See "
                        "[here](https://api-docs.uniswap.org/guides/faqs#why-do-uniswapx-quotes-have-more-slippage-than-the-tolerance-i-set) "
                        "for more "
                        "information.\n"
                        "\n"
                        "Note that if the "
                        "trade type is "
                        "`EXACT_INPUT`, then "
                        "the slippage is in "
                        "terms of the output "
                        "token. If the trade "
                        "type is "
                        "`EXACT_OUTPUT`, then "
                        "the slippage is in "
                        "terms of the input "
                        "token.\n"
                        "\n"
                        "When submitting a "
                        "request, "
                        "`slippageTolerance` "
                        "may not be set when "
                        "`autoSlippage` is "
                        "defined. One of "
                        "`slippageTolerance` "
                        "or `autoSlippage` "
                        "must be defined.",
                        "type": "number",
                        "minimum": 0,
                        "maximum": 100,
                        "pattern": "^[0-9]{0,3}\\.?[0-9]{0,2}$",
                    },
                    "deadlineBufferSecs": {"type": "number"},
                    "classicGasUseEstimateUSD": {
                        "description": "The gas fee "
                        "you would pay "
                        "if you opted "
                        "for a CLASSIC "
                        "swap over a "
                        "Uniswap X "
                        "order in terms "
                        "of USD.",
                        "type": "string",
                    },
                    "expectedAmountIn": {
                        "type": "string",
                        "description": "The quantity of tokens "
                        "denominated in the "
                        "token's base units. "
                        "(For example, for an "
                        "ERC20 token one token "
                        "is 1x10^18 base units. "
                        "For one USDC token one "
                        "token is 1x10^6 base "
                        "units.) This value "
                        "must be greater than "
                        "0.",
                        "pattern": "^[0-9]+$",
                    },
                    "expectedAmountOut": {
                        "type": "string",
                        "description": "The quantity of "
                        "tokens denominated in "
                        "the token's base "
                        "units. (For example, "
                        "for an ERC20 token "
                        "one token is 1x10^18 "
                        "base units. For one "
                        "USDC token one token "
                        "is 1x10^6 base "
                        "units.) This value "
                        "must be greater than "
                        "0.",
                        "pattern": "^[0-9]+$",
                    },
                    "aggregatedOutputs": {
                        "type": "array",
                        "items": {
                            "description": "An array of "
                            "all outputs "
                            "of the "
                            "proposed "
                            "transaction. "
                            "This "
                            "includes "
                            "the swap as "
                            "well as any "
                            "fees "
                            "collected "
                            "by the API "
                            "integrator. "
                            "This does "
                            "not include "
                            "pool fees "
                            "when "
                            "routing is "
                            "through a "
                            "Uniswap "
                            "Protocol "
                            "pool.",
                            "type": "object",
                            "properties": {
                                "token": {
                                    "type": "string",
                                    "description": "The "
                                    "token "
                                    "which "
                                    "will "
                                    "be "
                                    "received, "
                                    "specified "
                                    "by "
                                    "its "
                                    "token "
                                    "address. "
                                    "For "
                                    "a "
                                    "list "
                                    "of "
                                    "supported "
                                    "tokens, "
                                    "see "
                                    "the "
                                    "[FAQ](https://api-docs.uniswap.org/guides/faqs).",
                                    "pattern": "^(0x)?[0-9a-fA-F]{40}$",
                                },
                                "amount": {
                                    "type": "string",
                                    "description": "The "
                                    "quantity "
                                    "of "
                                    "tokens "
                                    "denominated "
                                    "in "
                                    "the "
                                    "token's "
                                    "base "
                                    "units. "
                                    "(For "
                                    "example, "
                                    "for "
                                    "an "
                                    "ERC20 "
                                    "token "
                                    "one "
                                    "token "
                                    "is "
                                    "1x10^18 "
                                    "base "
                                    "units. "
                                    "For "
                                    "one "
                                    "USDC "
                                    "token "
                                    "one "
                                    "token "
                                    "is "
                                    "1x10^6 "
                                    "base "
                                    "units.) "
                                    "This "
                                    "value "
                                    "must "
                                    "be "
                                    "greater "
                                    "than "
                                    "0.",
                                    "pattern": "^[0-9]+$",
                                },
                                "recipient": {
                                    "type": "string",
                                    "description": "(optional) "
                                    "The "
                                    "wallet "
                                    "address "
                                    "which "
                                    "will "
                                    "receive "
                                    "the "
                                    "output "
                                    "of "
                                    "the "
                                    "swap. "
                                    "If "
                                    "not "
                                    "provided, "
                                    "the "
                                    "output "
                                    "is "
                                    "returned "
                                    "to "
                                    "the "
                                    "`swapper`.",
                                    "pattern": "^(0x)?[0-9a-fA-F]{40}$",
                                },
                                "bps": {
                                    "type": "number",
                                    "multipleOf": 0.01,
                                    "description": "The "
                                    "portion "
                                    "of "
                                    "the "
                                    "swap "
                                    "stated "
                                    "in "
                                    "basis "
                                    "points. "
                                    "Fractional "
                                    "basis "
                                    "points "
                                    "are "
                                    "supported "
                                    "with "
                                    "up "
                                    "to "
                                    "two "
                                    "decimal "
                                    "places "
                                    "(e.g. "
                                    "12.5).",
                                },
                                "minAmount": {
                                    "type": "string",
                                    "description": "The "
                                    "minimum "
                                    "portion "
                                    "of "
                                    "the "
                                    "swap, "
                                    "stated "
                                    "in "
                                    "the "
                                    "base "
                                    "unit "
                                    "of "
                                    "the "
                                    "token, "
                                    "which "
                                    "will "
                                    "be "
                                    "output "
                                    "to "
                                    "the "
                                    "recipient.",
                                },
                                "fee": {
                                    "type": "string",
                                    "enum": ["INTEGRATOR"],
                                    "description": "Set "
                                    "to "
                                    "INTEGRATOR "
                                    "when "
                                    "this "
                                    "output "
                                    "is "
                                    "an "
                                    "integrator "
                                    "fee "
                                    "(as "
                                    "specified "
                                    "by "
                                    "the "
                                    "`integratorFees` "
                                    "array "
                                    "in "
                                    "the "
                                    "/quote "
                                    "request); "
                                    "omitted "
                                    "for "
                                    "the "
                                    "core "
                                    "output "
                                    "of "
                                    "the "
                                    "swap. "
                                    "One "
                                    "INTEGRATOR "
                                    "output "
                                    "is "
                                    "returned "
                                    "per "
                                    "fee "
                                    "recipient, "
                                    "in "
                                    "the "
                                    "order "
                                    "the "
                                    "recipients "
                                    "were "
                                    "requested, "
                                    "and "
                                    "their "
                                    "amounts "
                                    "sum "
                                    "to "
                                    "the "
                                    "amount "
                                    "deducted "
                                    "from "
                                    "the "
                                    "core "
                                    "output.",
                                },
                            },
                        },
                    },
                },
                "required": ["encodedOrder", "orderInfo", "orderId"],
            },
        ]
    },
    "CreateSwap.quote": {
        "anyOf": [
            {
                "title": "Classic Quote",
                "type": "object",
                "properties": {
                    "input": {
                        "type": "object",
                        "properties": {
                            "amount": {
                                "type": "string",
                                "description": "The "
                                "quantity "
                                "of "
                                "tokens "
                                "denominated "
                                "in the "
                                "token's "
                                "base "
                                "units. "
                                "(For "
                                "example, "
                                "for an "
                                "ERC20 "
                                "token "
                                "one "
                                "token is "
                                "1x10^18 "
                                "base "
                                "units. "
                                "For one "
                                "USDC "
                                "token "
                                "one "
                                "token is "
                                "1x10^6 "
                                "base "
                                "units.) "
                                "This "
                                "value "
                                "must be "
                                "greater "
                                "than 0.",
                                "pattern": "^[0-9]+$",
                            },
                            "token": {
                                "type": "string",
                                "description": "The token "
                                "which "
                                "will be "
                                "sent, "
                                "specified "
                                "by its "
                                "token "
                                "address. "
                                "For a "
                                "list of "
                                "supported "
                                "tokens, "
                                "see the "
                                "[FAQ](https://api-docs.uniswap.org/guides/faqs).",
                                "pattern": "^(0x)?[0-9a-fA-F]{40}$",
                            },
                            "maximumAmount": {
                                "type": "string",
                                "description": "The "
                                "quantity "
                                "of "
                                "tokens "
                                "denominated "
                                "in "
                                "the "
                                "token's "
                                "base "
                                "units. "
                                "(For "
                                "example, "
                                "for "
                                "an "
                                "ERC20 "
                                "token "
                                "one "
                                "token "
                                "is "
                                "1x10^18 "
                                "base "
                                "units. "
                                "For "
                                "one "
                                "USDC "
                                "token "
                                "one "
                                "token "
                                "is "
                                "1x10^6 "
                                "base "
                                "units.) "
                                "This "
                                "value "
                                "must "
                                "be "
                                "greater "
                                "than "
                                "0.",
                                "pattern": "^[0-9]+$",
                            },
                        },
                    },
                    "output": {
                        "type": "object",
                        "properties": {
                            "amount": {
                                "type": "string",
                                "description": "The "
                                "quantity "
                                "of "
                                "tokens "
                                "denominated "
                                "in the "
                                "token's "
                                "base "
                                "units. "
                                "(For "
                                "example, "
                                "for an "
                                "ERC20 "
                                "token "
                                "one "
                                "token "
                                "is "
                                "1x10^18 "
                                "base "
                                "units. "
                                "For one "
                                "USDC "
                                "token "
                                "one "
                                "token "
                                "is "
                                "1x10^6 "
                                "base "
                                "units.) "
                                "This "
                                "value "
                                "must be "
                                "greater "
                                "than 0.",
                                "pattern": "^[0-9]+$",
                            },
                            "token": {
                                "type": "string",
                                "description": "The "
                                "token "
                                "which "
                                "will be "
                                "received, "
                                "specified "
                                "by its "
                                "token "
                                "address. "
                                "For a "
                                "list of "
                                "supported "
                                "tokens, "
                                "see the "
                                "[FAQ](https://api-docs.uniswap.org/guides/faqs).",
                                "pattern": "^(0x)?[0-9a-fA-F]{40}$",
                            },
                            "recipient": {
                                "type": "string",
                                "description": "(optional) "
                                "The "
                                "wallet "
                                "address "
                                "which "
                                "will "
                                "receive "
                                "the "
                                "output "
                                "of "
                                "the "
                                "swap. "
                                "If "
                                "not "
                                "provided, "
                                "the "
                                "output "
                                "is "
                                "returned "
                                "to "
                                "the "
                                "`swapper`.",
                                "pattern": "^(0x)?[0-9a-fA-F]{40}$",
                            },
                            "minimumAmount": {
                                "type": "string",
                                "description": "The "
                                "quantity "
                                "of "
                                "tokens "
                                "denominated "
                                "in "
                                "the "
                                "token's "
                                "base "
                                "units. "
                                "(For "
                                "example, "
                                "for "
                                "an "
                                "ERC20 "
                                "token "
                                "one "
                                "token "
                                "is "
                                "1x10^18 "
                                "base "
                                "units. "
                                "For "
                                "one "
                                "USDC "
                                "token "
                                "one "
                                "token "
                                "is "
                                "1x10^6 "
                                "base "
                                "units.) "
                                "This "
                                "value "
                                "must "
                                "be "
                                "greater "
                                "than "
                                "0.",
                                "pattern": "^[0-9]+$",
                            },
                        },
                    },
                    "swapper": {
                        "type": "string",
                        "description": "The wallet address which will be "
                        "used to send the token.",
                        "pattern": "^0x[0-9a-fA-F]{40}$",
                    },
                    "chainId": {
                        "description": "The unique ID of the blockchain. "
                        "For a list of supported chains "
                        "see the "
                        "[FAQ](https://api-docs.uniswap.org/guides/faqs).",
                        "type": "number",
                        "enum": [
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
                        ],
                        "default": 1,
                    },
                    "slippage": {
                        "description": "The slippage tolerance as a "
                        "percentage up to a maximum of "
                        "two decimal places, between 0 "
                        "and 100 (a value outside that "
                        "range is rejected). This is the "
                        "maximum acceptable output loss "
                        "as a percentage: for "
                        "exact-input trades, the minimum "
                        "received is expectedOut × (1 - "
                        "slippageTolerance); for "
                        "exact-output trades, the "
                        "maximum input is expectedIn × "
                        "(1 + slippageTolerance).\n"
                        "\n"
                        "When submitting a quote, note "
                        "that slippage tolerance works "
                        "differently in UniswapX swaps "
                        "where it does not set a limit "
                        "on the Spread in an order. See "
                        "[here](https://api-docs.uniswap.org/guides/faqs#why-do-uniswapx-quotes-have-more-slippage-than-the-tolerance-i-set) "
                        "for more information.\n"
                        "\n"
                        "Note that if the trade type is "
                        "`EXACT_INPUT`, then the "
                        "slippage is in terms of the "
                        "output token. If the trade type "
                        "is `EXACT_OUTPUT`, then the "
                        "slippage is in terms of the "
                        "input token.\n"
                        "\n"
                        "When submitting a request, "
                        "`slippageTolerance` may not be "
                        "set when `autoSlippage` is "
                        "defined. One of "
                        "`slippageTolerance` or "
                        "`autoSlippage` must be defined.",
                        "type": "number",
                        "minimum": 0,
                        "maximum": 100,
                        "pattern": "^[0-9]{0,3}\\.?[0-9]{0,2}$",
                    },
                    "tradeType": {
                        "type": "string",
                        "enum": ["EXACT_INPUT", "EXACT_OUTPUT"],
                        "description": "The handling of the `amount` "
                        "field. `EXACT_INPUT` means the "
                        "requester will send the "
                        "specified `amount` of input "
                        "tokens and get a quote with a "
                        "variable quantity of output "
                        "tokens. `EXACT_OUTPUT` means "
                        "the requester will receive the "
                        "specified `amount` of output "
                        "tokens and get a quote with a "
                        "variable quantity of input "
                        "tokens.",
                        "default": "EXACT_INPUT",
                    },
                    "gasFee": {
                        "type": "string",
                        "description": "The total estimated gas cost of "
                        "this transaction (eg. `gasLimit` "
                        "multiplied by `maxFeePerGas`) in "
                        "the base unit of the chain.",
                    },
                    "gasFeeUSD": {
                        "type": "string",
                        "description": "The total estimated gas cost "
                        "of this transaction (eg. "
                        "`gasLimit` multiplied by "
                        "`maxFeePerGas`) denominated in "
                        "USDC.",
                    },
                    "gasFeeQuote": {
                        "type": "string",
                        "description": "The total estimated gas cost "
                        "of this transaction (eg. "
                        "gasLimit multiplied by "
                        "maxFeePerGas) in the quoted "
                        "currency (e.g. output token) "
                        "in the base units of the "
                        "quoted currency.",
                    },
                    "route": {
                        "type": "array",
                        "items": {
                            "type": "array",
                            "items": {
                                "anyOf": [
                                    {
                                        "title": "V2 Route",
                                        "type": "object",
                                        "properties": {
                                            "type": {
                                                "type": "string",
                                                "default": "v2-pool",
                                            },
                                            "address": {
                                                "type": "string",
                                                "description": "The "
                                                "address "
                                                "of "
                                                "a "
                                                "contract "
                                                "which "
                                                "will "
                                                "be "
                                                "used "
                                                "to "
                                                "facilitate "
                                                "the "
                                                "swap.",
                                                "pattern": "^(0x)?[0-9a-fA-F]{40}$",
                                            },
                                            "tokenIn": {
                                                "type": "object",
                                                "properties": {
                                                    "address": {
                                                        "type": "string",
                                                        "description": "The "
                                                        "token "
                                                        "which "
                                                        "will "
                                                        "be "
                                                        "sent, "
                                                        "specified "
                                                        "by "
                                                        "its "
                                                        "token "
                                                        "address. "
                                                        "For "
                                                        "a "
                                                        "list "
                                                        "of "
                                                        "supported "
                                                        "tokens, "
                                                        "see "
                                                        "the "
                                                        "[FAQ](https://api-docs.uniswap.org/guides/faqs).",
                                                        "pattern": "^(0x)?[0-9a-fA-F]{40}$",
                                                    },
                                                    "chainId": {
                                                        "description": "The "
                                                        "unique "
                                                        "ID "
                                                        "of "
                                                        "the "
                                                        "blockchain. "
                                                        "For "
                                                        "a "
                                                        "list "
                                                        "of "
                                                        "supported "
                                                        "chains "
                                                        "see "
                                                        "the "
                                                        "[FAQ](https://api-docs.uniswap.org/guides/faqs).",
                                                        "type": "number",
                                                        "enum": [
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
                                                        ],
                                                        "default": 1,
                                                    },
                                                    "symbol": {
                                                        "type": "string",
                                                        "description": "The "
                                                        "symbol "
                                                        "of "
                                                        "the "
                                                        "token.",
                                                    },
                                                    "decimals": {
                                                        "type": "string",
                                                        "description": "The "
                                                        "number "
                                                        "of "
                                                        "decimals "
                                                        "supported "
                                                        "by "
                                                        "the "
                                                        "token. "
                                                        "This "
                                                        "number "
                                                        "is "
                                                        "used "
                                                        "to "
                                                        "convert "
                                                        "token "
                                                        "amounts "
                                                        "to "
                                                        "the "
                                                        "token's "
                                                        "common "
                                                        "representation.",
                                                    },
                                                    "buyFeeBps": {
                                                        "type": "string",
                                                        "description": "A "
                                                        "fee "
                                                        "charged "
                                                        "by "
                                                        "the "
                                                        "token "
                                                        "specified "
                                                        "in "
                                                        "basis "
                                                        "points. "
                                                        "Field "
                                                        "is "
                                                        "not "
                                                        "present "
                                                        "if "
                                                        "the "
                                                        "token "
                                                        "does "
                                                        "not "
                                                        "charge "
                                                        "a "
                                                        "fee.",
                                                    },
                                                    "sellFeeBps": {
                                                        "type": "string",
                                                        "description": "A "
                                                        "fee "
                                                        "charged "
                                                        "by "
                                                        "the "
                                                        "token "
                                                        "specified "
                                                        "in "
                                                        "basis "
                                                        "points. "
                                                        "Field "
                                                        "is "
                                                        "not "
                                                        "present "
                                                        "if "
                                                        "the "
                                                        "token "
                                                        "does "
                                                        "not "
                                                        "charge "
                                                        "a "
                                                        "fee.",
                                                    },
                                                },
                                            },
                                            "tokenOut": {
                                                "type": "object",
                                                "properties": {
                                                    "address": {
                                                        "type": "string",
                                                        "description": "The "
                                                        "token "
                                                        "which "
                                                        "will "
                                                        "be "
                                                        "sent, "
                                                        "specified "
                                                        "by "
                                                        "its "
                                                        "token "
                                                        "address. "
                                                        "For "
                                                        "a "
                                                        "list "
                                                        "of "
                                                        "supported "
                                                        "tokens, "
                                                        "see "
                                                        "the "
                                                        "[FAQ](https://api-docs.uniswap.org/guides/faqs).",
                                                        "pattern": "^(0x)?[0-9a-fA-F]{40}$",
                                                    },
                                                    "chainId": {
                                                        "description": "The "
                                                        "unique "
                                                        "ID "
                                                        "of "
                                                        "the "
                                                        "blockchain. "
                                                        "For "
                                                        "a "
                                                        "list "
                                                        "of "
                                                        "supported "
                                                        "chains "
                                                        "see "
                                                        "the "
                                                        "[FAQ](https://api-docs.uniswap.org/guides/faqs).",
                                                        "type": "number",
                                                        "enum": [
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
                                                        ],
                                                        "default": 1,
                                                    },
                                                    "symbol": {
                                                        "type": "string",
                                                        "description": "The "
                                                        "symbol "
                                                        "of "
                                                        "the "
                                                        "token.",
                                                    },
                                                    "decimals": {
                                                        "type": "string",
                                                        "description": "The "
                                                        "number "
                                                        "of "
                                                        "decimals "
                                                        "supported "
                                                        "by "
                                                        "the "
                                                        "token. "
                                                        "This "
                                                        "number "
                                                        "is "
                                                        "used "
                                                        "to "
                                                        "convert "
                                                        "token "
                                                        "amounts "
                                                        "to "
                                                        "the "
                                                        "token's "
                                                        "common "
                                                        "representation.",
                                                    },
                                                    "buyFeeBps": {
                                                        "type": "string",
                                                        "description": "A "
                                                        "fee "
                                                        "charged "
                                                        "by "
                                                        "the "
                                                        "token "
                                                        "specified "
                                                        "in "
                                                        "basis "
                                                        "points. "
                                                        "Field "
                                                        "is "
                                                        "not "
                                                        "present "
                                                        "if "
                                                        "the "
                                                        "token "
                                                        "does "
                                                        "not "
                                                        "charge "
                                                        "a "
                                                        "fee.",
                                                    },
                                                    "sellFeeBps": {
                                                        "type": "string",
                                                        "description": "A "
                                                        "fee "
                                                        "charged "
                                                        "by "
                                                        "the "
                                                        "token "
                                                        "specified "
                                                        "in "
                                                        "basis "
                                                        "points. "
                                                        "Field "
                                                        "is "
                                                        "not "
                                                        "present "
                                                        "if "
                                                        "the "
                                                        "token "
                                                        "does "
                                                        "not "
                                                        "charge "
                                                        "a "
                                                        "fee.",
                                                    },
                                                },
                                            },
                                            "reserve0": {
                                                "description": "The "
                                                "remaining "
                                                "reserve "
                                                "of "
                                                "this "
                                                "token "
                                                "in "
                                                "the "
                                                "pool.",
                                                "type": "object",
                                                "properties": {
                                                    "token": {
                                                        "type": "object",
                                                        "properties": {
                                                            "address": {
                                                                "type": "string",
                                                                "description": "The "
                                                                "token "
                                                                "which "
                                                                "will "
                                                                "be "
                                                                "sent, "
                                                                "specified "
                                                                "by "
                                                                "its "
                                                                "token "
                                                                "address. "
                                                                "For "
                                                                "a "
                                                                "list "
                                                                "of "
                                                                "supported "
                                                                "tokens, "
                                                                "see "
                                                                "the "
                                                                "[FAQ](https://api-docs.uniswap.org/guides/faqs).",
                                                                "pattern": "^(0x)?[0-9a-fA-F]{40}$",
                                                            },
                                                            "chainId": {
                                                                "description": "The "
                                                                "unique "
                                                                "ID "
                                                                "of "
                                                                "the "
                                                                "blockchain. "
                                                                "For "
                                                                "a "
                                                                "list "
                                                                "of "
                                                                "supported "
                                                                "chains "
                                                                "see "
                                                                "the "
                                                                "[FAQ](https://api-docs.uniswap.org/guides/faqs).",
                                                                "type": "number",
                                                                "enum": [
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
                                                                ],
                                                                "default": 1,
                                                            },
                                                            "symbol": {
                                                                "type": "string",
                                                                "description": "The "
                                                                "symbol "
                                                                "of "
                                                                "the "
                                                                "token.",
                                                            },
                                                            "decimals": {
                                                                "type": "string",
                                                                "description": "The "
                                                                "number "
                                                                "of "
                                                                "decimals "
                                                                "supported "
                                                                "by "
                                                                "the "
                                                                "token. "
                                                                "This "
                                                                "number "
                                                                "is "
                                                                "used "
                                                                "to "
                                                                "convert "
                                                                "token "
                                                                "amounts "
                                                                "to "
                                                                "the "
                                                                "token's "
                                                                "common "
                                                                "representation.",
                                                            },
                                                            "buyFeeBps": {
                                                                "type": "string",
                                                                "description": "A "
                                                                "fee "
                                                                "charged "
                                                                "by "
                                                                "the "
                                                                "token "
                                                                "specified "
                                                                "in "
                                                                "basis "
                                                                "points. "
                                                                "Field "
                                                                "is "
                                                                "not "
                                                                "present "
                                                                "if "
                                                                "the "
                                                                "token "
                                                                "does "
                                                                "not "
                                                                "charge "
                                                                "a "
                                                                "fee.",
                                                            },
                                                            "sellFeeBps": {
                                                                "type": "string",
                                                                "description": "A "
                                                                "fee "
                                                                "charged "
                                                                "by "
                                                                "the "
                                                                "token "
                                                                "specified "
                                                                "in "
                                                                "basis "
                                                                "points. "
                                                                "Field "
                                                                "is "
                                                                "not "
                                                                "present "
                                                                "if "
                                                                "the "
                                                                "token "
                                                                "does "
                                                                "not "
                                                                "charge "
                                                                "a "
                                                                "fee.",
                                                            },
                                                        },
                                                    },
                                                    "quotient": {
                                                        "description": "The "
                                                        "quantity "
                                                        "of "
                                                        "this "
                                                        "token "
                                                        "remaining "
                                                        "in "
                                                        "the "
                                                        "pool, "
                                                        "specified "
                                                        "in "
                                                        "the "
                                                        "base "
                                                        "units "
                                                        "of "
                                                        "the "
                                                        "token.",
                                                        "type": "string",
                                                    },
                                                },
                                            },
                                            "reserve1": {
                                                "description": "The "
                                                "remaining "
                                                "reserve "
                                                "of "
                                                "this "
                                                "token "
                                                "in "
                                                "the "
                                                "pool.",
                                                "type": "object",
                                                "properties": {
                                                    "token": {
                                                        "type": "object",
                                                        "properties": {
                                                            "address": {
                                                                "type": "string",
                                                                "description": "The "
                                                                "token "
                                                                "which "
                                                                "will "
                                                                "be "
                                                                "sent, "
                                                                "specified "
                                                                "by "
                                                                "its "
                                                                "token "
                                                                "address. "
                                                                "For "
                                                                "a "
                                                                "list "
                                                                "of "
                                                                "supported "
                                                                "tokens, "
                                                                "see "
                                                                "the "
                                                                "[FAQ](https://api-docs.uniswap.org/guides/faqs).",
                                                                "pattern": "^(0x)?[0-9a-fA-F]{40}$",
                                                            },
                                                            "chainId": {
                                                                "description": "The "
                                                                "unique "
                                                                "ID "
                                                                "of "
                                                                "the "
                                                                "blockchain. "
                                                                "For "
                                                                "a "
                                                                "list "
                                                                "of "
                                                                "supported "
                                                                "chains "
                                                                "see "
                                                                "the "
                                                                "[FAQ](https://api-docs.uniswap.org/guides/faqs).",
                                                                "type": "number",
                                                                "enum": [
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
                                                                ],
                                                                "default": 1,
                                                            },
                                                            "symbol": {
                                                                "type": "string",
                                                                "description": "The "
                                                                "symbol "
                                                                "of "
                                                                "the "
                                                                "token.",
                                                            },
                                                            "decimals": {
                                                                "type": "string",
                                                                "description": "The "
                                                                "number "
                                                                "of "
                                                                "decimals "
                                                                "supported "
                                                                "by "
                                                                "the "
                                                                "token. "
                                                                "This "
                                                                "number "
                                                                "is "
                                                                "used "
                                                                "to "
                                                                "convert "
                                                                "token "
                                                                "amounts "
                                                                "to "
                                                                "the "
                                                                "token's "
                                                                "common "
                                                                "representation.",
                                                            },
                                                            "buyFeeBps": {
                                                                "type": "string",
                                                                "description": "A "
                                                                "fee "
                                                                "charged "
                                                                "by "
                                                                "the "
                                                                "token "
                                                                "specified "
                                                                "in "
                                                                "basis "
                                                                "points. "
                                                                "Field "
                                                                "is "
                                                                "not "
                                                                "present "
                                                                "if "
                                                                "the "
                                                                "token "
                                                                "does "
                                                                "not "
                                                                "charge "
                                                                "a "
                                                                "fee.",
                                                            },
                                                            "sellFeeBps": {
                                                                "type": "string",
                                                                "description": "A "
                                                                "fee "
                                                                "charged "
                                                                "by "
                                                                "the "
                                                                "token "
                                                                "specified "
                                                                "in "
                                                                "basis "
                                                                "points. "
                                                                "Field "
                                                                "is "
                                                                "not "
                                                                "present "
                                                                "if "
                                                                "the "
                                                                "token "
                                                                "does "
                                                                "not "
                                                                "charge "
                                                                "a "
                                                                "fee.",
                                                            },
                                                        },
                                                    },
                                                    "quotient": {
                                                        "description": "The "
                                                        "quantity "
                                                        "of "
                                                        "this "
                                                        "token "
                                                        "remaining "
                                                        "in "
                                                        "the "
                                                        "pool, "
                                                        "specified "
                                                        "in "
                                                        "the "
                                                        "base "
                                                        "units "
                                                        "of "
                                                        "the "
                                                        "token.",
                                                        "type": "string",
                                                    },
                                                },
                                            },
                                            "amountIn": {
                                                "type": "string",
                                                "description": "The "
                                                "quantity "
                                                "of "
                                                "tokens "
                                                "denominated "
                                                "in "
                                                "the "
                                                "token's "
                                                "base "
                                                "units. "
                                                "(For "
                                                "example, "
                                                "for "
                                                "an "
                                                "ERC20 "
                                                "token "
                                                "one "
                                                "token "
                                                "is "
                                                "1x10^18 "
                                                "base "
                                                "units. "
                                                "For "
                                                "one "
                                                "USDC "
                                                "token "
                                                "one "
                                                "token "
                                                "is "
                                                "1x10^6 "
                                                "base "
                                                "units.) "
                                                "This "
                                                "value "
                                                "must "
                                                "be "
                                                "greater "
                                                "than "
                                                "0.",
                                                "pattern": "^[0-9]+$",
                                            },
                                            "amountOut": {
                                                "type": "string",
                                                "description": "The "
                                                "quantity "
                                                "of "
                                                "tokens "
                                                "denominated "
                                                "in "
                                                "the "
                                                "token's "
                                                "base "
                                                "units. "
                                                "(For "
                                                "example, "
                                                "for "
                                                "an "
                                                "ERC20 "
                                                "token "
                                                "one "
                                                "token "
                                                "is "
                                                "1x10^18 "
                                                "base "
                                                "units. "
                                                "For "
                                                "one "
                                                "USDC "
                                                "token "
                                                "one "
                                                "token "
                                                "is "
                                                "1x10^6 "
                                                "base "
                                                "units.) "
                                                "This "
                                                "value "
                                                "must "
                                                "be "
                                                "greater "
                                                "than "
                                                "0.",
                                                "pattern": "^[0-9]+$",
                                            },
                                        },
                                    },
                                    {
                                        "title": "V3 Route",
                                        "type": "object",
                                        "properties": {
                                            "type": {
                                                "type": "string",
                                                "default": "v3-pool",
                                            },
                                            "address": {
                                                "type": "string",
                                                "description": "The "
                                                "address "
                                                "of "
                                                "a "
                                                "contract "
                                                "which "
                                                "will "
                                                "be "
                                                "used "
                                                "to "
                                                "facilitate "
                                                "the "
                                                "swap.",
                                                "pattern": "^(0x)?[0-9a-fA-F]{40}$",
                                            },
                                            "tokenIn": {
                                                "type": "object",
                                                "properties": {
                                                    "address": {
                                                        "type": "string",
                                                        "description": "The "
                                                        "token "
                                                        "which "
                                                        "will "
                                                        "be "
                                                        "sent, "
                                                        "specified "
                                                        "by "
                                                        "its "
                                                        "token "
                                                        "address. "
                                                        "For "
                                                        "a "
                                                        "list "
                                                        "of "
                                                        "supported "
                                                        "tokens, "
                                                        "see "
                                                        "the "
                                                        "[FAQ](https://api-docs.uniswap.org/guides/faqs).",
                                                        "pattern": "^(0x)?[0-9a-fA-F]{40}$",
                                                    },
                                                    "chainId": {
                                                        "description": "The "
                                                        "unique "
                                                        "ID "
                                                        "of "
                                                        "the "
                                                        "blockchain. "
                                                        "For "
                                                        "a "
                                                        "list "
                                                        "of "
                                                        "supported "
                                                        "chains "
                                                        "see "
                                                        "the "
                                                        "[FAQ](https://api-docs.uniswap.org/guides/faqs).",
                                                        "type": "number",
                                                        "enum": [
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
                                                        ],
                                                        "default": 1,
                                                    },
                                                    "symbol": {
                                                        "type": "string",
                                                        "description": "The "
                                                        "symbol "
                                                        "of "
                                                        "the "
                                                        "token.",
                                                    },
                                                    "decimals": {
                                                        "type": "string",
                                                        "description": "The "
                                                        "number "
                                                        "of "
                                                        "decimals "
                                                        "supported "
                                                        "by "
                                                        "the "
                                                        "token. "
                                                        "This "
                                                        "number "
                                                        "is "
                                                        "used "
                                                        "to "
                                                        "convert "
                                                        "token "
                                                        "amounts "
                                                        "to "
                                                        "the "
                                                        "token's "
                                                        "common "
                                                        "representation.",
                                                    },
                                                    "buyFeeBps": {
                                                        "type": "string",
                                                        "description": "A "
                                                        "fee "
                                                        "charged "
                                                        "by "
                                                        "the "
                                                        "token "
                                                        "specified "
                                                        "in "
                                                        "basis "
                                                        "points. "
                                                        "Field "
                                                        "is "
                                                        "not "
                                                        "present "
                                                        "if "
                                                        "the "
                                                        "token "
                                                        "does "
                                                        "not "
                                                        "charge "
                                                        "a "
                                                        "fee.",
                                                    },
                                                    "sellFeeBps": {
                                                        "type": "string",
                                                        "description": "A "
                                                        "fee "
                                                        "charged "
                                                        "by "
                                                        "the "
                                                        "token "
                                                        "specified "
                                                        "in "
                                                        "basis "
                                                        "points. "
                                                        "Field "
                                                        "is "
                                                        "not "
                                                        "present "
                                                        "if "
                                                        "the "
                                                        "token "
                                                        "does "
                                                        "not "
                                                        "charge "
                                                        "a "
                                                        "fee.",
                                                    },
                                                },
                                            },
                                            "tokenOut": {
                                                "type": "object",
                                                "properties": {
                                                    "address": {
                                                        "type": "string",
                                                        "description": "The "
                                                        "token "
                                                        "which "
                                                        "will "
                                                        "be "
                                                        "sent, "
                                                        "specified "
                                                        "by "
                                                        "its "
                                                        "token "
                                                        "address. "
                                                        "For "
                                                        "a "
                                                        "list "
                                                        "of "
                                                        "supported "
                                                        "tokens, "
                                                        "see "
                                                        "the "
                                                        "[FAQ](https://api-docs.uniswap.org/guides/faqs).",
                                                        "pattern": "^(0x)?[0-9a-fA-F]{40}$",
                                                    },
                                                    "chainId": {
                                                        "description": "The "
                                                        "unique "
                                                        "ID "
                                                        "of "
                                                        "the "
                                                        "blockchain. "
                                                        "For "
                                                        "a "
                                                        "list "
                                                        "of "
                                                        "supported "
                                                        "chains "
                                                        "see "
                                                        "the "
                                                        "[FAQ](https://api-docs.uniswap.org/guides/faqs).",
                                                        "type": "number",
                                                        "enum": [
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
                                                        ],
                                                        "default": 1,
                                                    },
                                                    "symbol": {
                                                        "type": "string",
                                                        "description": "The "
                                                        "symbol "
                                                        "of "
                                                        "the "
                                                        "token.",
                                                    },
                                                    "decimals": {
                                                        "type": "string",
                                                        "description": "The "
                                                        "number "
                                                        "of "
                                                        "decimals "
                                                        "supported "
                                                        "by "
                                                        "the "
                                                        "token. "
                                                        "This "
                                                        "number "
                                                        "is "
                                                        "used "
                                                        "to "
                                                        "convert "
                                                        "token "
                                                        "amounts "
                                                        "to "
                                                        "the "
                                                        "token's "
                                                        "common "
                                                        "representation.",
                                                    },
                                                    "buyFeeBps": {
                                                        "type": "string",
                                                        "description": "A "
                                                        "fee "
                                                        "charged "
                                                        "by "
                                                        "the "
                                                        "token "
                                                        "specified "
                                                        "in "
                                                        "basis "
                                                        "points. "
                                                        "Field "
                                                        "is "
                                                        "not "
                                                        "present "
                                                        "if "
                                                        "the "
                                                        "token "
                                                        "does "
                                                        "not "
                                                        "charge "
                                                        "a "
                                                        "fee.",
                                                    },
                                                    "sellFeeBps": {
                                                        "type": "string",
                                                        "description": "A "
                                                        "fee "
                                                        "charged "
                                                        "by "
                                                        "the "
                                                        "token "
                                                        "specified "
                                                        "in "
                                                        "basis "
                                                        "points. "
                                                        "Field "
                                                        "is "
                                                        "not "
                                                        "present "
                                                        "if "
                                                        "the "
                                                        "token "
                                                        "does "
                                                        "not "
                                                        "charge "
                                                        "a "
                                                        "fee.",
                                                    },
                                                },
                                            },
                                            "sqrtRatioX96": {
                                                "type": "string",
                                                "description": "The "
                                                "square "
                                                "root "
                                                "of "
                                                "the "
                                                "ratio "
                                                "of "
                                                "the "
                                                "token0 "
                                                "and "
                                                "token1 "
                                                "in "
                                                "the "
                                                "pool, "
                                                "as "
                                                "a "
                                                "Q64.64 "
                                                "number. "
                                                "For "
                                                "more "
                                                "information "
                                                "see "
                                                "the "
                                                "[Uniswap "
                                                "V3 "
                                                "Whitepaper](https://app.uniswap.org/whitepaper-v3.pdf).",
                                            },
                                            "liquidity": {
                                                "type": "string",
                                                "description": "The "
                                                "amount "
                                                "of "
                                                "liquidity "
                                                "in "
                                                "the "
                                                "pool "
                                                "at "
                                                "a "
                                                "given "
                                                "tick. "
                                                "For "
                                                "more "
                                                "information "
                                                "see "
                                                "the "
                                                "[Uniswap "
                                                "V3 "
                                                "Whitepaper](https://app.uniswap.org/whitepaper-v3.pdf).",
                                            },
                                            "tickCurrent": {
                                                "type": "string",
                                                "description": "The "
                                                "current "
                                                "tick "
                                                "of "
                                                "the "
                                                "pool. "
                                                "For "
                                                "more "
                                                "information "
                                                "see "
                                                "the "
                                                "[Uniswap "
                                                "V3 "
                                                "Whitepaper](https://app.uniswap.org/whitepaper-v3.pdf).",
                                            },
                                            "fee": {
                                                "type": "string",
                                                "description": "The "
                                                "fee "
                                                "of "
                                                "the "
                                                "pool "
                                                "in "
                                                "basis "
                                                "points.",
                                            },
                                            "amountIn": {
                                                "type": "string",
                                                "description": "The "
                                                "quantity "
                                                "of "
                                                "tokens "
                                                "denominated "
                                                "in "
                                                "the "
                                                "token's "
                                                "base "
                                                "units. "
                                                "(For "
                                                "example, "
                                                "for "
                                                "an "
                                                "ERC20 "
                                                "token "
                                                "one "
                                                "token "
                                                "is "
                                                "1x10^18 "
                                                "base "
                                                "units. "
                                                "For "
                                                "one "
                                                "USDC "
                                                "token "
                                                "one "
                                                "token "
                                                "is "
                                                "1x10^6 "
                                                "base "
                                                "units.) "
                                                "This "
                                                "value "
                                                "must "
                                                "be "
                                                "greater "
                                                "than "
                                                "0.",
                                                "pattern": "^[0-9]+$",
                                            },
                                            "amountOut": {
                                                "type": "string",
                                                "description": "The "
                                                "quantity "
                                                "of "
                                                "tokens "
                                                "denominated "
                                                "in "
                                                "the "
                                                "token's "
                                                "base "
                                                "units. "
                                                "(For "
                                                "example, "
                                                "for "
                                                "an "
                                                "ERC20 "
                                                "token "
                                                "one "
                                                "token "
                                                "is "
                                                "1x10^18 "
                                                "base "
                                                "units. "
                                                "For "
                                                "one "
                                                "USDC "
                                                "token "
                                                "one "
                                                "token "
                                                "is "
                                                "1x10^6 "
                                                "base "
                                                "units.) "
                                                "This "
                                                "value "
                                                "must "
                                                "be "
                                                "greater "
                                                "than "
                                                "0.",
                                                "pattern": "^[0-9]+$",
                                            },
                                        },
                                    },
                                    {
                                        "title": "V4 Route",
                                        "type": "object",
                                        "properties": {
                                            "type": {
                                                "type": "string",
                                                "default": "v4-pool",
                                            },
                                            "address": {
                                                "type": "string",
                                                "description": "The "
                                                "address "
                                                "of "
                                                "a "
                                                "contract "
                                                "which "
                                                "will "
                                                "be "
                                                "used "
                                                "to "
                                                "facilitate "
                                                "the "
                                                "swap.",
                                                "pattern": "^(0x)?[0-9a-fA-F]{40}$",
                                            },
                                            "tokenIn": {
                                                "type": "object",
                                                "properties": {
                                                    "address": {
                                                        "type": "string",
                                                        "description": "The "
                                                        "token "
                                                        "which "
                                                        "will "
                                                        "be "
                                                        "sent, "
                                                        "specified "
                                                        "by "
                                                        "its "
                                                        "token "
                                                        "address. "
                                                        "For "
                                                        "a "
                                                        "list "
                                                        "of "
                                                        "supported "
                                                        "tokens, "
                                                        "see "
                                                        "the "
                                                        "[FAQ](https://api-docs.uniswap.org/guides/faqs).",
                                                        "pattern": "^(0x)?[0-9a-fA-F]{40}$",
                                                    },
                                                    "chainId": {
                                                        "description": "The "
                                                        "unique "
                                                        "ID "
                                                        "of "
                                                        "the "
                                                        "blockchain. "
                                                        "For "
                                                        "a "
                                                        "list "
                                                        "of "
                                                        "supported "
                                                        "chains "
                                                        "see "
                                                        "the "
                                                        "[FAQ](https://api-docs.uniswap.org/guides/faqs).",
                                                        "type": "number",
                                                        "enum": [
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
                                                        ],
                                                        "default": 1,
                                                    },
                                                    "symbol": {
                                                        "type": "string",
                                                        "description": "The "
                                                        "symbol "
                                                        "of "
                                                        "the "
                                                        "token.",
                                                    },
                                                    "decimals": {
                                                        "type": "string",
                                                        "description": "The "
                                                        "number "
                                                        "of "
                                                        "decimals "
                                                        "supported "
                                                        "by "
                                                        "the "
                                                        "token. "
                                                        "This "
                                                        "number "
                                                        "is "
                                                        "used "
                                                        "to "
                                                        "convert "
                                                        "token "
                                                        "amounts "
                                                        "to "
                                                        "the "
                                                        "token's "
                                                        "common "
                                                        "representation.",
                                                    },
                                                    "buyFeeBps": {
                                                        "type": "string",
                                                        "description": "A "
                                                        "fee "
                                                        "charged "
                                                        "by "
                                                        "the "
                                                        "token "
                                                        "specified "
                                                        "in "
                                                        "basis "
                                                        "points. "
                                                        "Field "
                                                        "is "
                                                        "not "
                                                        "present "
                                                        "if "
                                                        "the "
                                                        "token "
                                                        "does "
                                                        "not "
                                                        "charge "
                                                        "a "
                                                        "fee.",
                                                    },
                                                    "sellFeeBps": {
                                                        "type": "string",
                                                        "description": "A "
                                                        "fee "
                                                        "charged "
                                                        "by "
                                                        "the "
                                                        "token "
                                                        "specified "
                                                        "in "
                                                        "basis "
                                                        "points. "
                                                        "Field "
                                                        "is "
                                                        "not "
                                                        "present "
                                                        "if "
                                                        "the "
                                                        "token "
                                                        "does "
                                                        "not "
                                                        "charge "
                                                        "a "
                                                        "fee.",
                                                    },
                                                },
                                            },
                                            "tokenOut": {
                                                "type": "object",
                                                "properties": {
                                                    "address": {
                                                        "type": "string",
                                                        "description": "The "
                                                        "token "
                                                        "which "
                                                        "will "
                                                        "be "
                                                        "sent, "
                                                        "specified "
                                                        "by "
                                                        "its "
                                                        "token "
                                                        "address. "
                                                        "For "
                                                        "a "
                                                        "list "
                                                        "of "
                                                        "supported "
                                                        "tokens, "
                                                        "see "
                                                        "the "
                                                        "[FAQ](https://api-docs.uniswap.org/guides/faqs).",
                                                        "pattern": "^(0x)?[0-9a-fA-F]{40}$",
                                                    },
                                                    "chainId": {
                                                        "description": "The "
                                                        "unique "
                                                        "ID "
                                                        "of "
                                                        "the "
                                                        "blockchain. "
                                                        "For "
                                                        "a "
                                                        "list "
                                                        "of "
                                                        "supported "
                                                        "chains "
                                                        "see "
                                                        "the "
                                                        "[FAQ](https://api-docs.uniswap.org/guides/faqs).",
                                                        "type": "number",
                                                        "enum": [
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
                                                        ],
                                                        "default": 1,
                                                    },
                                                    "symbol": {
                                                        "type": "string",
                                                        "description": "The "
                                                        "symbol "
                                                        "of "
                                                        "the "
                                                        "token.",
                                                    },
                                                    "decimals": {
                                                        "type": "string",
                                                        "description": "The "
                                                        "number "
                                                        "of "
                                                        "decimals "
                                                        "supported "
                                                        "by "
                                                        "the "
                                                        "token. "
                                                        "This "
                                                        "number "
                                                        "is "
                                                        "used "
                                                        "to "
                                                        "convert "
                                                        "token "
                                                        "amounts "
                                                        "to "
                                                        "the "
                                                        "token's "
                                                        "common "
                                                        "representation.",
                                                    },
                                                    "buyFeeBps": {
                                                        "type": "string",
                                                        "description": "A "
                                                        "fee "
                                                        "charged "
                                                        "by "
                                                        "the "
                                                        "token "
                                                        "specified "
                                                        "in "
                                                        "basis "
                                                        "points. "
                                                        "Field "
                                                        "is "
                                                        "not "
                                                        "present "
                                                        "if "
                                                        "the "
                                                        "token "
                                                        "does "
                                                        "not "
                                                        "charge "
                                                        "a "
                                                        "fee.",
                                                    },
                                                    "sellFeeBps": {
                                                        "type": "string",
                                                        "description": "A "
                                                        "fee "
                                                        "charged "
                                                        "by "
                                                        "the "
                                                        "token "
                                                        "specified "
                                                        "in "
                                                        "basis "
                                                        "points. "
                                                        "Field "
                                                        "is "
                                                        "not "
                                                        "present "
                                                        "if "
                                                        "the "
                                                        "token "
                                                        "does "
                                                        "not "
                                                        "charge "
                                                        "a "
                                                        "fee.",
                                                    },
                                                },
                                            },
                                            "sqrtRatioX96": {
                                                "type": "string",
                                                "description": "The "
                                                "square "
                                                "root "
                                                "of "
                                                "the "
                                                "ratio "
                                                "of "
                                                "the "
                                                "token0 "
                                                "and "
                                                "token1 "
                                                "in "
                                                "the "
                                                "pool, "
                                                "as "
                                                "a "
                                                "Q64.64 "
                                                "number. "
                                                "For "
                                                "more "
                                                "information "
                                                "see "
                                                "the "
                                                "[Uniswap "
                                                "V3 "
                                                "Whitepaper](https://app.uniswap.org/whitepaper-v3.pdf).",
                                            },
                                            "liquidity": {
                                                "type": "string",
                                                "description": "The "
                                                "amount "
                                                "of "
                                                "liquidity "
                                                "in "
                                                "the "
                                                "pool "
                                                "at "
                                                "a "
                                                "given "
                                                "tick. "
                                                "For "
                                                "more "
                                                "information "
                                                "see "
                                                "the "
                                                "[Uniswap "
                                                "V3 "
                                                "Whitepaper](https://app.uniswap.org/whitepaper-v3.pdf).",
                                            },
                                            "tickCurrent": {
                                                "type": "string",
                                                "description": "The "
                                                "current "
                                                "tick "
                                                "of "
                                                "the "
                                                "pool. "
                                                "For "
                                                "more "
                                                "information "
                                                "see "
                                                "the "
                                                "[Uniswap "
                                                "V3 "
                                                "Whitepaper](https://app.uniswap.org/whitepaper-v3.pdf).",
                                            },
                                            "fee": {
                                                "type": "string",
                                                "description": "The "
                                                "fee "
                                                "of "
                                                "the "
                                                "pool "
                                                "in "
                                                "basis "
                                                "points.",
                                            },
                                            "tickSpacing": {
                                                "type": "number",
                                                "description": "The "
                                                "width "
                                                "of "
                                                "ticks "
                                                "in "
                                                "this "
                                                "pool "
                                                "(e.g. "
                                                "the "
                                                "price "
                                                "range "
                                                "between "
                                                "two "
                                                "ticks) "
                                                "specified "
                                                "in "
                                                "basis "
                                                "points. "
                                                "For "
                                                "more "
                                                "information "
                                                "see "
                                                "the "
                                                "[Uniswap "
                                                "V3 "
                                                "Whitepaper](https://app.uniswap.org/whitepaper-v3.pdf).",
                                            },
                                            "hooks": {
                                                "type": "string",
                                                "description": "The "
                                                "address "
                                                "of "
                                                "the "
                                                "hook "
                                                "for "
                                                "the "
                                                "pool, "
                                                "if "
                                                "any. "
                                                "If "
                                                "the "
                                                "pool "
                                                "has "
                                                "no "
                                                "hook, "
                                                "this "
                                                "field "
                                                "will "
                                                "be "
                                                "the "
                                                "null "
                                                "address "
                                                "(e.g. "
                                                "0x0000000000000000000000000000000000000000).",
                                            },
                                            "amountIn": {
                                                "type": "string",
                                                "description": "The "
                                                "quantity "
                                                "of "
                                                "tokens "
                                                "denominated "
                                                "in "
                                                "the "
                                                "token's "
                                                "base "
                                                "units. "
                                                "(For "
                                                "example, "
                                                "for "
                                                "an "
                                                "ERC20 "
                                                "token "
                                                "one "
                                                "token "
                                                "is "
                                                "1x10^18 "
                                                "base "
                                                "units. "
                                                "For "
                                                "one "
                                                "USDC "
                                                "token "
                                                "one "
                                                "token "
                                                "is "
                                                "1x10^6 "
                                                "base "
                                                "units.) "
                                                "This "
                                                "value "
                                                "must "
                                                "be "
                                                "greater "
                                                "than "
                                                "0.",
                                                "pattern": "^[0-9]+$",
                                            },
                                            "amountOut": {
                                                "type": "string",
                                                "description": "The "
                                                "quantity "
                                                "of "
                                                "tokens "
                                                "denominated "
                                                "in "
                                                "the "
                                                "token's "
                                                "base "
                                                "units. "
                                                "(For "
                                                "example, "
                                                "for "
                                                "an "
                                                "ERC20 "
                                                "token "
                                                "one "
                                                "token "
                                                "is "
                                                "1x10^18 "
                                                "base "
                                                "units. "
                                                "For "
                                                "one "
                                                "USDC "
                                                "token "
                                                "one "
                                                "token "
                                                "is "
                                                "1x10^6 "
                                                "base "
                                                "units.) "
                                                "This "
                                                "value "
                                                "must "
                                                "be "
                                                "greater "
                                                "than "
                                                "0.",
                                                "pattern": "^[0-9]+$",
                                            },
                                            "settleBeforeSwap": {
                                                "type": "boolean",
                                                "description": "Set "
                                                "to "
                                                "true "
                                                "when "
                                                "the "
                                                "pool's "
                                                "hook "
                                                "needs "
                                                "the "
                                                "swap "
                                                "input "
                                                "in "
                                                "the "
                                                "PoolManager "
                                                "before "
                                                "the "
                                                "swap "
                                                "runs. "
                                                "The "
                                                "swap "
                                                "transaction "
                                                "then "
                                                "settles "
                                                "the "
                                                "input "
                                                "before "
                                                "the "
                                                "swap. "
                                                "Send "
                                                "the "
                                                "field "
                                                "back "
                                                "to "
                                                "/swap "
                                                "unchanged.",
                                            },
                                        },
                                        "required": [
                                            "type",
                                            "address",
                                            "tokenIn",
                                            "tokenOut",
                                            "sqrtRatioX96",
                                            "liquidity",
                                            "tickCurrent",
                                            "fee",
                                            "tickSpacing",
                                            "hooks",
                                        ],
                                    },
                                ]
                            },
                        },
                    },
                    "routeString": {
                        "type": "string",
                        "description": "The route in string format.",
                    },
                    "quoteId": {
                        "type": "string",
                        "description": "A unique ID for the quote.",
                    },
                    "gasUseEstimate": {
                        "type": "string",
                        "description": "The estimated gas use. It "
                        "does NOT include the "
                        "additional gas for token "
                        "approvals.",
                    },
                    "blockNumber": {
                        "type": "string",
                        "description": "The current block number.",
                    },
                    "gasPrice": {
                        "type": "string",
                        "description": "The cost per unit of gas.",
                    },
                    "maxFeePerGas": {
                        "type": "string",
                        "description": "The sum of the base fee and "
                        "priority fee. Subtracting "
                        "`maxPriorityFeePerGas` from "
                        "this value will yield the "
                        "base fee to be paid for "
                        "this transaction.",
                    },
                    "maxPriorityFeePerGas": {
                        "type": "string",
                        "description": "The maximum tip to "
                        "the block builder. "
                        "Adjusted based upon "
                        "the urgency "
                        "specified in the "
                        "request.",
                    },
                    "txFailureReasons": {
                        "description": "The reason(s) why the "
                        "transaction failed "
                        "during simulation.",
                        "type": "array",
                        "items": {
                            "type": "string",
                            "enum": [
                                "SIMULATION_ERROR",
                                "UNSUPPORTED_SIMULATION",
                                "SIMULATION_UNAVAILABLE",
                                "SLIPPAGE_TOO_LOW",
                                "TRANSFER_FROM_FAILED",
                            ],
                        },
                    },
                    "priceImpact": {
                        "type": "number",
                        "description": "The impact the trade has on "
                        "the market price of the "
                        "pool, between 0-100 percent",
                    },
                    "aggregatedOutputs": {
                        "type": "array",
                        "items": {
                            "description": "An array of "
                            "all outputs "
                            "of the "
                            "proposed "
                            "transaction. "
                            "This "
                            "includes the "
                            "swap as well "
                            "as any fees "
                            "collected by "
                            "the API "
                            "integrator. "
                            "This does "
                            "not include "
                            "pool fees "
                            "when routing "
                            "is through a "
                            "Uniswap "
                            "Protocol "
                            "pool.",
                            "type": "object",
                            "properties": {
                                "token": {
                                    "type": "string",
                                    "description": "The "
                                    "token "
                                    "which "
                                    "will "
                                    "be "
                                    "received, "
                                    "specified "
                                    "by "
                                    "its "
                                    "token "
                                    "address. "
                                    "For "
                                    "a "
                                    "list "
                                    "of "
                                    "supported "
                                    "tokens, "
                                    "see "
                                    "the "
                                    "[FAQ](https://api-docs.uniswap.org/guides/faqs).",
                                    "pattern": "^(0x)?[0-9a-fA-F]{40}$",
                                },
                                "amount": {
                                    "type": "string",
                                    "description": "The "
                                    "quantity "
                                    "of "
                                    "tokens "
                                    "denominated "
                                    "in "
                                    "the "
                                    "token's "
                                    "base "
                                    "units. "
                                    "(For "
                                    "example, "
                                    "for "
                                    "an "
                                    "ERC20 "
                                    "token "
                                    "one "
                                    "token "
                                    "is "
                                    "1x10^18 "
                                    "base "
                                    "units. "
                                    "For "
                                    "one "
                                    "USDC "
                                    "token "
                                    "one "
                                    "token "
                                    "is "
                                    "1x10^6 "
                                    "base "
                                    "units.) "
                                    "This "
                                    "value "
                                    "must "
                                    "be "
                                    "greater "
                                    "than "
                                    "0.",
                                    "pattern": "^[0-9]+$",
                                },
                                "recipient": {
                                    "type": "string",
                                    "description": "(optional) "
                                    "The "
                                    "wallet "
                                    "address "
                                    "which "
                                    "will "
                                    "receive "
                                    "the "
                                    "output "
                                    "of "
                                    "the "
                                    "swap. "
                                    "If "
                                    "not "
                                    "provided, "
                                    "the "
                                    "output "
                                    "is "
                                    "returned "
                                    "to "
                                    "the "
                                    "`swapper`.",
                                    "pattern": "^(0x)?[0-9a-fA-F]{40}$",
                                },
                                "bps": {
                                    "type": "number",
                                    "multipleOf": 0.01,
                                    "description": "The "
                                    "portion "
                                    "of "
                                    "the "
                                    "swap "
                                    "stated "
                                    "in "
                                    "basis "
                                    "points. "
                                    "Fractional "
                                    "basis "
                                    "points "
                                    "are "
                                    "supported "
                                    "with "
                                    "up "
                                    "to "
                                    "two "
                                    "decimal "
                                    "places "
                                    "(e.g. "
                                    "12.5).",
                                },
                                "minAmount": {
                                    "type": "string",
                                    "description": "The "
                                    "minimum "
                                    "portion "
                                    "of "
                                    "the "
                                    "swap, "
                                    "stated "
                                    "in "
                                    "the "
                                    "base "
                                    "unit "
                                    "of "
                                    "the "
                                    "token, "
                                    "which "
                                    "will "
                                    "be "
                                    "output "
                                    "to "
                                    "the "
                                    "recipient.",
                                },
                                "fee": {
                                    "type": "string",
                                    "enum": ["INTEGRATOR"],
                                    "description": "Set "
                                    "to "
                                    "INTEGRATOR "
                                    "when "
                                    "this "
                                    "output "
                                    "is "
                                    "an "
                                    "integrator "
                                    "fee "
                                    "(as "
                                    "specified "
                                    "by "
                                    "the "
                                    "`integratorFees` "
                                    "array "
                                    "in "
                                    "the "
                                    "/quote "
                                    "request); "
                                    "omitted "
                                    "for "
                                    "the "
                                    "core "
                                    "output "
                                    "of "
                                    "the "
                                    "swap. "
                                    "One "
                                    "INTEGRATOR "
                                    "output "
                                    "is "
                                    "returned "
                                    "per "
                                    "fee "
                                    "recipient, "
                                    "in "
                                    "the "
                                    "order "
                                    "the "
                                    "recipients "
                                    "were "
                                    "requested, "
                                    "and "
                                    "their "
                                    "amounts "
                                    "sum "
                                    "to "
                                    "the "
                                    "amount "
                                    "deducted "
                                    "from "
                                    "the "
                                    "core "
                                    "output.",
                                },
                            },
                        },
                    },
                    "swapSteps": {
                        "type": "array",
                        "description": "Universal Router swap step "
                        "sequence. Additive, opt-in via "
                        "the "
                        "`x-universal-router-swapsteps` "
                        "header. When present, mirrors "
                        "the inputs to "
                        "`SwapRouter.encodeSwaps`. Only "
                        "emitted when GuideStar wins "
                        "the hybrid quoter race "
                        "(`EXACT_INPUT` today; broader "
                        "coverage once UniRoute's "
                        "transformer ships).",
                        "items": {
                            "description": "Universal Router "
                            "swap step. "
                            "Discriminated by the "
                            "`type` field.",
                            "anyOf": [
                                {
                                    "type": "object",
                                    "properties": {
                                        "type": {
                                            "type": "string",
                                            "enum": ["V2_SWAP_EXACT_IN"],
                                        },
                                        "recipient": {"type": "string"},
                                        "amountIn": {"type": "string"},
                                        "amountOutMin": {"type": "string"},
                                        "path": {
                                            "type": "array",
                                            "items": {"type": "string"},
                                        },
                                        "minHopPriceX36": {
                                            "type": "array",
                                            "items": {"type": "string"},
                                        },
                                        "payerIsUser": {"type": "boolean"},
                                    },
                                    "required": [
                                        "type",
                                        "recipient",
                                        "amountIn",
                                        "amountOutMin",
                                        "path",
                                    ],
                                },
                                {
                                    "type": "object",
                                    "properties": {
                                        "type": {
                                            "type": "string",
                                            "enum": ["V2_SWAP_EXACT_OUT"],
                                        },
                                        "recipient": {"type": "string"},
                                        "amountOut": {"type": "string"},
                                        "amountInMax": {"type": "string"},
                                        "path": {
                                            "type": "array",
                                            "items": {"type": "string"},
                                        },
                                        "minHopPriceX36": {
                                            "type": "array",
                                            "items": {"type": "string"},
                                        },
                                        "payerIsUser": {"type": "boolean"},
                                    },
                                    "required": [
                                        "type",
                                        "recipient",
                                        "amountOut",
                                        "amountInMax",
                                        "path",
                                    ],
                                },
                                {
                                    "type": "object",
                                    "properties": {
                                        "type": {
                                            "type": "string",
                                            "enum": ["V3_SWAP_EXACT_IN"],
                                        },
                                        "recipient": {"type": "string"},
                                        "amountIn": {"type": "string"},
                                        "amountOutMin": {"type": "string"},
                                        "path": {
                                            "type": "string",
                                            "description": "Hex-encoded "
                                            "packed "
                                            "V3 "
                                            "path "
                                            "(e.g. "
                                            "`0xa0b8...000bb8c02aaa...`).",
                                        },
                                        "minHopPriceX36": {
                                            "type": "array",
                                            "items": {"type": "string"},
                                        },
                                        "payerIsUser": {"type": "boolean"},
                                    },
                                    "required": [
                                        "type",
                                        "recipient",
                                        "amountIn",
                                        "amountOutMin",
                                        "path",
                                    ],
                                },
                                {
                                    "type": "object",
                                    "properties": {
                                        "type": {
                                            "type": "string",
                                            "enum": ["V3_SWAP_EXACT_OUT"],
                                        },
                                        "recipient": {"type": "string"},
                                        "amountOut": {"type": "string"},
                                        "amountInMax": {"type": "string"},
                                        "path": {
                                            "type": "string",
                                            "description": "Hex-encoded "
                                            "packed "
                                            "V3 "
                                            "path "
                                            "(e.g. "
                                            "`0xa0b8...000bb8c02aaa...`).",
                                        },
                                        "minHopPriceX36": {
                                            "type": "array",
                                            "items": {"type": "string"},
                                        },
                                        "payerIsUser": {"type": "boolean"},
                                    },
                                    "required": [
                                        "type",
                                        "recipient",
                                        "amountOut",
                                        "amountInMax",
                                        "path",
                                    ],
                                },
                                {
                                    "type": "object",
                                    "properties": {
                                        "type": {"type": "string", "enum": ["V4_SWAP"]},
                                        "v4Actions": {
                                            "type": "array",
                                            "items": {
                                                "description": "V4 "
                                                "action. "
                                                "Discriminated "
                                                "by "
                                                "the "
                                                "`action` "
                                                "field.",
                                                "anyOf": [
                                                    {
                                                        "type": "object",
                                                        "properties": {
                                                            "action": {
                                                                "type": "string",
                                                                "enum": [
                                                                    "SWAP_EXACT_IN"
                                                                ],
                                                            },
                                                            "currencyIn": {
                                                                "type": "string"
                                                            },
                                                            "path": {
                                                                "type": "array",
                                                                "items": {
                                                                    "type": "object",
                                                                    "properties": {
                                                                        "intermediateCurrency": {
                                                                            "type": "string"
                                                                        },
                                                                        "fee": {
                                                                            "type": "integer"
                                                                        },
                                                                        "tickSpacing": {
                                                                            "type": "integer"
                                                                        },
                                                                        "hooks": {
                                                                            "type": "string"
                                                                        },
                                                                        "hookData": {
                                                                            "type": "string"
                                                                        },
                                                                    },
                                                                    "required": [
                                                                        "intermediateCurrency",
                                                                        "fee",
                                                                        "tickSpacing",
                                                                        "hooks",
                                                                        "hookData",
                                                                    ],
                                                                },
                                                            },
                                                            "amountIn": {
                                                                "type": "string"
                                                            },
                                                            "amountOutMinimum": {
                                                                "type": "string"
                                                            },
                                                            "minHopPriceX36": {
                                                                "type": "array",
                                                                "items": {
                                                                    "type": "string"
                                                                },
                                                            },
                                                        },
                                                        "required": [
                                                            "action",
                                                            "currencyIn",
                                                            "path",
                                                            "amountIn",
                                                            "amountOutMinimum",
                                                        ],
                                                    },
                                                    {
                                                        "type": "object",
                                                        "properties": {
                                                            "action": {
                                                                "type": "string",
                                                                "enum": [
                                                                    "SWAP_EXACT_IN_SINGLE"
                                                                ],
                                                            },
                                                            "poolKey": {
                                                                "type": "object",
                                                                "properties": {
                                                                    "currency0": {
                                                                        "type": "string"
                                                                    },
                                                                    "currency1": {
                                                                        "type": "string"
                                                                    },
                                                                    "fee": {
                                                                        "type": "integer"
                                                                    },
                                                                    "tickSpacing": {
                                                                        "type": "integer"
                                                                    },
                                                                    "hooks": {
                                                                        "type": "string"
                                                                    },
                                                                },
                                                                "required": [
                                                                    "currency0",
                                                                    "currency1",
                                                                    "fee",
                                                                    "tickSpacing",
                                                                    "hooks",
                                                                ],
                                                            },
                                                            "zeroForOne": {
                                                                "type": "boolean"
                                                            },
                                                            "amountIn": {
                                                                "type": "string"
                                                            },
                                                            "amountOutMinimum": {
                                                                "type": "string"
                                                            },
                                                            "hookData": {
                                                                "type": "string"
                                                            },
                                                            "minHopPriceX36": {
                                                                "type": "string"
                                                            },
                                                        },
                                                        "required": [
                                                            "action",
                                                            "poolKey",
                                                            "zeroForOne",
                                                            "amountIn",
                                                            "amountOutMinimum",
                                                            "hookData",
                                                        ],
                                                    },
                                                    {
                                                        "type": "object",
                                                        "properties": {
                                                            "action": {
                                                                "type": "string",
                                                                "enum": [
                                                                    "SWAP_EXACT_OUT"
                                                                ],
                                                            },
                                                            "currencyOut": {
                                                                "type": "string"
                                                            },
                                                            "path": {
                                                                "type": "array",
                                                                "items": {
                                                                    "type": "object",
                                                                    "properties": {
                                                                        "intermediateCurrency": {
                                                                            "type": "string"
                                                                        },
                                                                        "fee": {
                                                                            "type": "integer"
                                                                        },
                                                                        "tickSpacing": {
                                                                            "type": "integer"
                                                                        },
                                                                        "hooks": {
                                                                            "type": "string"
                                                                        },
                                                                        "hookData": {
                                                                            "type": "string"
                                                                        },
                                                                    },
                                                                    "required": [
                                                                        "intermediateCurrency",
                                                                        "fee",
                                                                        "tickSpacing",
                                                                        "hooks",
                                                                        "hookData",
                                                                    ],
                                                                },
                                                            },
                                                            "amountOut": {
                                                                "type": "string"
                                                            },
                                                            "amountInMaximum": {
                                                                "type": "string"
                                                            },
                                                            "minHopPriceX36": {
                                                                "type": "array",
                                                                "items": {
                                                                    "type": "string"
                                                                },
                                                            },
                                                        },
                                                        "required": [
                                                            "action",
                                                            "currencyOut",
                                                            "path",
                                                            "amountOut",
                                                            "amountInMaximum",
                                                        ],
                                                    },
                                                    {
                                                        "type": "object",
                                                        "properties": {
                                                            "action": {
                                                                "type": "string",
                                                                "enum": [
                                                                    "SWAP_EXACT_OUT_SINGLE"
                                                                ],
                                                            },
                                                            "poolKey": {
                                                                "type": "object",
                                                                "properties": {
                                                                    "currency0": {
                                                                        "type": "string"
                                                                    },
                                                                    "currency1": {
                                                                        "type": "string"
                                                                    },
                                                                    "fee": {
                                                                        "type": "integer"
                                                                    },
                                                                    "tickSpacing": {
                                                                        "type": "integer"
                                                                    },
                                                                    "hooks": {
                                                                        "type": "string"
                                                                    },
                                                                },
                                                                "required": [
                                                                    "currency0",
                                                                    "currency1",
                                                                    "fee",
                                                                    "tickSpacing",
                                                                    "hooks",
                                                                ],
                                                            },
                                                            "zeroForOne": {
                                                                "type": "boolean"
                                                            },
                                                            "amountOut": {
                                                                "type": "string"
                                                            },
                                                            "amountInMaximum": {
                                                                "type": "string"
                                                            },
                                                            "hookData": {
                                                                "type": "string"
                                                            },
                                                            "minHopPriceX36": {
                                                                "type": "string"
                                                            },
                                                        },
                                                        "required": [
                                                            "action",
                                                            "poolKey",
                                                            "zeroForOne",
                                                            "amountOut",
                                                            "amountInMaximum",
                                                            "hookData",
                                                        ],
                                                    },
                                                    {
                                                        "type": "object",
                                                        "properties": {
                                                            "action": {
                                                                "type": "string",
                                                                "enum": ["SETTLE"],
                                                            },
                                                            "currency": {
                                                                "type": "string"
                                                            },
                                                            "amount": {
                                                                "type": "string"
                                                            },
                                                            "payerIsUser": {
                                                                "type": "boolean"
                                                            },
                                                        },
                                                        "required": [
                                                            "action",
                                                            "currency",
                                                            "amount",
                                                        ],
                                                    },
                                                    {
                                                        "type": "object",
                                                        "properties": {
                                                            "action": {
                                                                "type": "string",
                                                                "enum": ["SETTLE_ALL"],
                                                            },
                                                            "currency": {
                                                                "type": "string"
                                                            },
                                                            "maxAmount": {
                                                                "type": "string"
                                                            },
                                                        },
                                                        "required": [
                                                            "action",
                                                            "currency",
                                                            "maxAmount",
                                                        ],
                                                    },
                                                    {
                                                        "type": "object",
                                                        "properties": {
                                                            "action": {
                                                                "type": "string",
                                                                "enum": ["TAKE"],
                                                            },
                                                            "currency": {
                                                                "type": "string"
                                                            },
                                                            "recipient": {
                                                                "type": "string"
                                                            },
                                                            "amount": {
                                                                "type": "string"
                                                            },
                                                        },
                                                        "required": [
                                                            "action",
                                                            "currency",
                                                            "recipient",
                                                            "amount",
                                                        ],
                                                    },
                                                    {
                                                        "type": "object",
                                                        "properties": {
                                                            "action": {
                                                                "type": "string",
                                                                "enum": ["TAKE_ALL"],
                                                            },
                                                            "currency": {
                                                                "type": "string"
                                                            },
                                                            "minAmount": {
                                                                "type": "string"
                                                            },
                                                        },
                                                        "required": [
                                                            "action",
                                                            "currency",
                                                            "minAmount",
                                                        ],
                                                    },
                                                    {
                                                        "type": "object",
                                                        "properties": {
                                                            "action": {
                                                                "type": "string",
                                                                "enum": [
                                                                    "TAKE_PORTION"
                                                                ],
                                                            },
                                                            "currency": {
                                                                "type": "string"
                                                            },
                                                            "recipient": {
                                                                "type": "string"
                                                            },
                                                            "bips": {"type": "string"},
                                                        },
                                                        "required": [
                                                            "action",
                                                            "currency",
                                                            "recipient",
                                                            "bips",
                                                        ],
                                                    },
                                                ],
                                            },
                                        },
                                    },
                                    "required": ["type", "v4Actions"],
                                },
                                {
                                    "type": "object",
                                    "properties": {
                                        "type": {
                                            "type": "string",
                                            "enum": ["WRAP_ETH"],
                                        },
                                        "recipient": {"type": "string"},
                                        "amount": {"type": "string"},
                                    },
                                    "required": ["type", "recipient", "amount"],
                                },
                                {
                                    "type": "object",
                                    "properties": {
                                        "type": {
                                            "type": "string",
                                            "enum": ["UNWRAP_WETH"],
                                        },
                                        "recipient": {"type": "string"},
                                        "amountMin": {"type": "string"},
                                    },
                                    "required": ["type", "recipient", "amountMin"],
                                },
                            ],
                        },
                    },
                    "routeCandidates": {
                        "type": "array",
                        "description": "Top route candidates the "
                        "router considered but "
                        "did NOT serve (the "
                        "served route and "
                        "candidates proven "
                        "unviable — simulation or "
                        "trade-build failures — "
                        "are excluded), "
                        "best-first. Additive, "
                        "opt-in via the "
                        "`includeRouteCandidates` "
                        "request flag; only "
                        "populated for "
                        "uniroute-backed quotes. "
                        "May be short or empty "
                        "when the route cache "
                        "limits the candidate "
                        "pool.",
                        "items": {
                            "type": "object",
                            "description": "A quoted route "
                            "candidate with "
                            "its "
                            "whole-route "
                            "(not per-hop) "
                            "amounts.",
                            "properties": {
                                "routeString": {
                                    "type": "string",
                                    "description": "The "
                                    "candidate "
                                    "route "
                                    "in "
                                    "string "
                                    "format.",
                                },
                                "quoteAmount": {
                                    "type": "string",
                                    "description": "The "
                                    "whole-route "
                                    "quoted "
                                    "amount: "
                                    "output "
                                    "amount "
                                    "for "
                                    "EXACT_INPUT, "
                                    "required "
                                    "input "
                                    "amount "
                                    "for "
                                    "EXACT_OUTPUT. "
                                    "A "
                                    "quoter "
                                    "estimate "
                                    "— "
                                    "does "
                                    "not "
                                    "carry "
                                    "the "
                                    "simulation/portion "
                                    "corrections "
                                    "applied "
                                    "to "
                                    "the "
                                    "served "
                                    "quote.",
                                },
                                "quoteGasAdjusted": {
                                    "type": "string",
                                    "description": "The "
                                    "gas-adjusted "
                                    "whole-route "
                                    "amount. "
                                    "Omitted "
                                    "when "
                                    "gas "
                                    "details "
                                    "are "
                                    "unavailable.",
                                },
                            },
                            "required": ["routeString", "quoteAmount"],
                        },
                    },
                    "gasLimit": {
                        "type": "string",
                        "pattern": "^[1-9][0-9]*$",
                        "description": "The minimum gas limit for the "
                        "swap transaction, in gas units, "
                        "as a positive decimal integer "
                        "string. Only present when the "
                        "route goes through a pool whose "
                        "swap needs more gas available "
                        "than it uses (for example, a "
                        "hook that checks `gasleft()`). "
                        "When the response includes "
                        "`permitData`, it already "
                        "includes the gas for that "
                        "Permit2 permit; it does NOT "
                        "include the gas for an ERC-20 "
                        "approval transaction. Pass the "
                        "quote back to `/swap` "
                        "unchanged: the swap "
                        "transaction's gas limit is at "
                        "least this value. A quote whose "
                        "`gasLimit` is not a positive "
                        "decimal integer string is "
                        "rejected with a 400 "
                        "`RequestValidationError`.",
                    },
                },
            },
            {
                "title": "Wrap/Unwrap Quote",
                "type": "object",
                "properties": {
                    "swapper": {
                        "type": "string",
                        "description": "(optional) The wallet address "
                        "which will receive the output of "
                        "the swap. If not provided, the "
                        "output is returned to the "
                        "`swapper`.",
                        "pattern": "^(0x)?[0-9a-fA-F]{40}$",
                    },
                    "input": {
                        "type": "object",
                        "properties": {
                            "amount": {
                                "type": "string",
                                "description": "The "
                                "quantity "
                                "of "
                                "tokens "
                                "denominated "
                                "in the "
                                "token's "
                                "base "
                                "units. "
                                "(For "
                                "example, "
                                "for an "
                                "ERC20 "
                                "token "
                                "one "
                                "token is "
                                "1x10^18 "
                                "base "
                                "units. "
                                "For one "
                                "USDC "
                                "token "
                                "one "
                                "token is "
                                "1x10^6 "
                                "base "
                                "units.) "
                                "This "
                                "value "
                                "must be "
                                "greater "
                                "than 0.",
                                "pattern": "^[0-9]+$",
                            },
                            "token": {
                                "type": "string",
                                "description": "The token "
                                "which "
                                "will be "
                                "sent, "
                                "specified "
                                "by its "
                                "token "
                                "address. "
                                "For a "
                                "list of "
                                "supported "
                                "tokens, "
                                "see the "
                                "[FAQ](https://api-docs.uniswap.org/guides/faqs).",
                                "pattern": "^(0x)?[0-9a-fA-F]{40}$",
                            },
                            "maximumAmount": {
                                "type": "string",
                                "description": "The "
                                "quantity "
                                "of "
                                "tokens "
                                "denominated "
                                "in "
                                "the "
                                "token's "
                                "base "
                                "units. "
                                "(For "
                                "example, "
                                "for "
                                "an "
                                "ERC20 "
                                "token "
                                "one "
                                "token "
                                "is "
                                "1x10^18 "
                                "base "
                                "units. "
                                "For "
                                "one "
                                "USDC "
                                "token "
                                "one "
                                "token "
                                "is "
                                "1x10^6 "
                                "base "
                                "units.) "
                                "This "
                                "value "
                                "must "
                                "be "
                                "greater "
                                "than "
                                "0.",
                                "pattern": "^[0-9]+$",
                            },
                        },
                    },
                    "output": {
                        "type": "object",
                        "properties": {
                            "amount": {
                                "type": "string",
                                "description": "The "
                                "quantity "
                                "of "
                                "tokens "
                                "denominated "
                                "in the "
                                "token's "
                                "base "
                                "units. "
                                "(For "
                                "example, "
                                "for an "
                                "ERC20 "
                                "token "
                                "one "
                                "token "
                                "is "
                                "1x10^18 "
                                "base "
                                "units. "
                                "For one "
                                "USDC "
                                "token "
                                "one "
                                "token "
                                "is "
                                "1x10^6 "
                                "base "
                                "units.) "
                                "This "
                                "value "
                                "must be "
                                "greater "
                                "than 0.",
                                "pattern": "^[0-9]+$",
                            },
                            "token": {
                                "type": "string",
                                "description": "The "
                                "token "
                                "which "
                                "will be "
                                "received, "
                                "specified "
                                "by its "
                                "token "
                                "address. "
                                "For a "
                                "list of "
                                "supported "
                                "tokens, "
                                "see the "
                                "[FAQ](https://api-docs.uniswap.org/guides/faqs).",
                                "pattern": "^(0x)?[0-9a-fA-F]{40}$",
                            },
                            "recipient": {
                                "type": "string",
                                "description": "(optional) "
                                "The "
                                "wallet "
                                "address "
                                "which "
                                "will "
                                "receive "
                                "the "
                                "output "
                                "of "
                                "the "
                                "swap. "
                                "If "
                                "not "
                                "provided, "
                                "the "
                                "output "
                                "is "
                                "returned "
                                "to "
                                "the "
                                "`swapper`.",
                                "pattern": "^(0x)?[0-9a-fA-F]{40}$",
                            },
                            "minimumAmount": {
                                "type": "string",
                                "description": "The "
                                "quantity "
                                "of "
                                "tokens "
                                "denominated "
                                "in "
                                "the "
                                "token's "
                                "base "
                                "units. "
                                "(For "
                                "example, "
                                "for "
                                "an "
                                "ERC20 "
                                "token "
                                "one "
                                "token "
                                "is "
                                "1x10^18 "
                                "base "
                                "units. "
                                "For "
                                "one "
                                "USDC "
                                "token "
                                "one "
                                "token "
                                "is "
                                "1x10^6 "
                                "base "
                                "units.) "
                                "This "
                                "value "
                                "must "
                                "be "
                                "greater "
                                "than "
                                "0.",
                                "pattern": "^[0-9]+$",
                            },
                        },
                    },
                    "chainId": {
                        "description": "The unique ID of the blockchain. "
                        "For a list of supported chains "
                        "see the "
                        "[FAQ](https://api-docs.uniswap.org/guides/faqs).",
                        "type": "number",
                        "enum": [
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
                        ],
                        "default": 1,
                    },
                    "tradeType": {
                        "type": "string",
                        "enum": ["EXACT_INPUT", "EXACT_OUTPUT"],
                        "description": "The handling of the `amount` "
                        "field. `EXACT_INPUT` means the "
                        "requester will send the "
                        "specified `amount` of input "
                        "tokens and get a quote with a "
                        "variable quantity of output "
                        "tokens. `EXACT_OUTPUT` means "
                        "the requester will receive the "
                        "specified `amount` of output "
                        "tokens and get a quote with a "
                        "variable quantity of input "
                        "tokens.",
                        "default": "EXACT_INPUT",
                    },
                    "gasFee": {
                        "type": "string",
                        "description": "The total estimated gas cost of "
                        "this transaction (eg. `gasLimit` "
                        "multiplied by `maxFeePerGas`) in "
                        "the base unit of the chain.",
                    },
                    "gasFeeUSD": {
                        "type": "string",
                        "description": "The total estimated gas cost "
                        "of this transaction (eg. "
                        "`gasLimit` multiplied by "
                        "`maxFeePerGas`) denominated in "
                        "USDC.",
                    },
                    "gasFeeQuote": {
                        "type": "string",
                        "description": "The total estimated gas cost "
                        "of this transaction (eg. "
                        "gasLimit multiplied by "
                        "maxFeePerGas) in the quoted "
                        "currency (e.g. output token) "
                        "in the base units of the "
                        "quoted currency.",
                    },
                    "gasUseEstimate": {
                        "type": "string",
                        "description": "The maximum units of gas "
                        "that will be consumed by "
                        "this transaction.",
                    },
                    "gasPrice": {
                        "type": "string",
                        "description": "The cost per unit of gas.",
                    },
                    "maxFeePerGas": {
                        "type": "string",
                        "description": "The sum of the base fee and "
                        "priority fee. Subtracting "
                        "`maxPriorityFeePerGas` from "
                        "this value will yield the "
                        "base fee to be paid for "
                        "this transaction.",
                    },
                    "maxPriorityFeePerGas": {
                        "type": "string",
                        "description": "The maximum tip to "
                        "the block builder. "
                        "Adjusted based upon "
                        "the urgency "
                        "specified in the "
                        "request.",
                    },
                },
            },
            {
                "title": "Bridge Quote",
                "type": "object",
                "properties": {
                    "quoteId": {
                        "type": "string",
                        "description": "A unique ID for the quote.",
                    },
                    "chainId": {
                        "description": "The unique ID of the blockchain. "
                        "For a list of supported chains "
                        "see the "
                        "[FAQ](https://api-docs.uniswap.org/guides/faqs).",
                        "type": "number",
                        "enum": [
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
                        ],
                        "default": 1,
                    },
                    "destinationChainId": {
                        "description": "The unique ID of the "
                        "blockchain. For a "
                        "list of supported "
                        "chains see the "
                        "[FAQ](https://api-docs.uniswap.org/guides/faqs).",
                        "type": "number",
                        "enum": [
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
                        ],
                        "default": 1,
                    },
                    "swapper": {
                        "type": "string",
                        "description": "(optional) The wallet address "
                        "which will receive the output of "
                        "the swap. If not provided, the "
                        "output is returned to the "
                        "`swapper`.",
                        "pattern": "^(0x)?[0-9a-fA-F]{40}$",
                    },
                    "input": {
                        "type": "object",
                        "properties": {
                            "amount": {
                                "type": "string",
                                "description": "The "
                                "quantity "
                                "of "
                                "tokens "
                                "denominated "
                                "in the "
                                "token's "
                                "base "
                                "units. "
                                "(For "
                                "example, "
                                "for an "
                                "ERC20 "
                                "token "
                                "one "
                                "token is "
                                "1x10^18 "
                                "base "
                                "units. "
                                "For one "
                                "USDC "
                                "token "
                                "one "
                                "token is "
                                "1x10^6 "
                                "base "
                                "units.) "
                                "This "
                                "value "
                                "must be "
                                "greater "
                                "than 0.",
                                "pattern": "^[0-9]+$",
                            },
                            "token": {
                                "type": "string",
                                "description": "The token "
                                "which "
                                "will be "
                                "sent, "
                                "specified "
                                "by its "
                                "token "
                                "address. "
                                "For a "
                                "list of "
                                "supported "
                                "tokens, "
                                "see the "
                                "[FAQ](https://api-docs.uniswap.org/guides/faqs).",
                                "pattern": "^(0x)?[0-9a-fA-F]{40}$",
                            },
                            "maximumAmount": {
                                "type": "string",
                                "description": "The "
                                "quantity "
                                "of "
                                "tokens "
                                "denominated "
                                "in "
                                "the "
                                "token's "
                                "base "
                                "units. "
                                "(For "
                                "example, "
                                "for "
                                "an "
                                "ERC20 "
                                "token "
                                "one "
                                "token "
                                "is "
                                "1x10^18 "
                                "base "
                                "units. "
                                "For "
                                "one "
                                "USDC "
                                "token "
                                "one "
                                "token "
                                "is "
                                "1x10^6 "
                                "base "
                                "units.) "
                                "This "
                                "value "
                                "must "
                                "be "
                                "greater "
                                "than "
                                "0.",
                                "pattern": "^[0-9]+$",
                            },
                        },
                    },
                    "output": {
                        "type": "object",
                        "properties": {
                            "amount": {
                                "type": "string",
                                "description": "The "
                                "quantity "
                                "of "
                                "tokens "
                                "denominated "
                                "in the "
                                "token's "
                                "base "
                                "units. "
                                "(For "
                                "example, "
                                "for an "
                                "ERC20 "
                                "token "
                                "one "
                                "token "
                                "is "
                                "1x10^18 "
                                "base "
                                "units. "
                                "For one "
                                "USDC "
                                "token "
                                "one "
                                "token "
                                "is "
                                "1x10^6 "
                                "base "
                                "units.) "
                                "This "
                                "value "
                                "must be "
                                "greater "
                                "than 0.",
                                "pattern": "^[0-9]+$",
                            },
                            "token": {
                                "type": "string",
                                "description": "The "
                                "token "
                                "which "
                                "will be "
                                "received, "
                                "specified "
                                "by its "
                                "token "
                                "address. "
                                "For a "
                                "list of "
                                "supported "
                                "tokens, "
                                "see the "
                                "[FAQ](https://api-docs.uniswap.org/guides/faqs).",
                                "pattern": "^(0x)?[0-9a-fA-F]{40}$",
                            },
                            "recipient": {
                                "type": "string",
                                "description": "(optional) "
                                "The "
                                "wallet "
                                "address "
                                "which "
                                "will "
                                "receive "
                                "the "
                                "output "
                                "of "
                                "the "
                                "swap. "
                                "If "
                                "not "
                                "provided, "
                                "the "
                                "output "
                                "is "
                                "returned "
                                "to "
                                "the "
                                "`swapper`.",
                                "pattern": "^(0x)?[0-9a-fA-F]{40}$",
                            },
                            "minimumAmount": {
                                "type": "string",
                                "description": "The "
                                "quantity "
                                "of "
                                "tokens "
                                "denominated "
                                "in "
                                "the "
                                "token's "
                                "base "
                                "units. "
                                "(For "
                                "example, "
                                "for "
                                "an "
                                "ERC20 "
                                "token "
                                "one "
                                "token "
                                "is "
                                "1x10^18 "
                                "base "
                                "units. "
                                "For "
                                "one "
                                "USDC "
                                "token "
                                "one "
                                "token "
                                "is "
                                "1x10^6 "
                                "base "
                                "units.) "
                                "This "
                                "value "
                                "must "
                                "be "
                                "greater "
                                "than "
                                "0.",
                                "pattern": "^[0-9]+$",
                            },
                        },
                    },
                    "tradeType": {
                        "type": "string",
                        "enum": ["EXACT_INPUT", "EXACT_OUTPUT"],
                        "description": "The handling of the `amount` "
                        "field. `EXACT_INPUT` means the "
                        "requester will send the "
                        "specified `amount` of input "
                        "tokens and get a quote with a "
                        "variable quantity of output "
                        "tokens. `EXACT_OUTPUT` means "
                        "the requester will receive the "
                        "specified `amount` of output "
                        "tokens and get a quote with a "
                        "variable quantity of input "
                        "tokens.",
                        "default": "EXACT_INPUT",
                    },
                    "quoteTimestamp": {"type": "number"},
                    "gasPrice": {
                        "type": "string",
                        "description": "The cost per unit of gas.",
                    },
                    "maxFeePerGas": {
                        "type": "string",
                        "description": "The sum of the base fee and "
                        "priority fee. Subtracting "
                        "`maxPriorityFeePerGas` from "
                        "this value will yield the "
                        "base fee to be paid for "
                        "this transaction.",
                    },
                    "maxPriorityFeePerGas": {
                        "type": "string",
                        "description": "The maximum tip to "
                        "the block builder. "
                        "Adjusted based upon "
                        "the urgency "
                        "specified in the "
                        "request.",
                    },
                    "gasFee": {
                        "type": "string",
                        "description": "The total estimated gas cost of "
                        "this transaction (eg. `gasLimit` "
                        "multiplied by `maxFeePerGas`) in "
                        "the base unit of the chain.",
                    },
                    "gasUseEstimate": {
                        "type": "string",
                        "description": "The maximum units of gas "
                        "that will be consumed by "
                        "this transaction.",
                    },
                    "gasFeeUSD": {
                        "type": "string",
                        "description": "The total estimated gas cost "
                        "of this transaction (eg. "
                        "`gasLimit` multiplied by "
                        "`maxFeePerGas`) denominated in "
                        "USDC.",
                    },
                    "estimatedFillTimeMs": {
                        "type": "number",
                        "description": "The estimated time "
                        "it will take to fill "
                        "the order in "
                        "milliseconds.",
                    },
                    "exclusiveRelayer": {
                        "type": "string",
                        "description": "The address of the "
                        "exclusive filler (the "
                        "relayer).",
                        "pattern": "^(0x)?[0-9a-fA-F]{40}$",
                    },
                    "exclusivityDeadline": {
                        "type": "number",
                        "description": "The deadline (unix "
                        "timestamp) by which "
                        "the exclusive "
                        "relayer must fill "
                        "the order before "
                        "other relayers can "
                        "fill it.",
                    },
                    "fillDeadline": {
                        "type": "number",
                        "description": "The deadline by which, if "
                        "the order is not filled, "
                        "the order will be "
                        "reverted.",
                    },
                },
            },
        ]
    },
    "CreateSwap.permitData": {
        "allOf": [
            {
                "description": "the permit2 message object for the customer to sign to "
                "permit spending by the permit2 contract.",
                "type": "object",
                "properties": {
                    "domain": {"type": "object"},
                    "values": {"type": "object"},
                    "types": {"type": "object"},
                },
            }
        ]
    },
    "CreateSwap.urgency": {
        "anyOf": [
            {"type": "string", "enum": ["normal", "fast", "urgent"]},
            {
                "type": "object",
                "description": "High-level fee tier selection with optional "
                "caller-supplied caps. Use this form when you need to "
                "override one or more gas fields; otherwise send the bare "
                "`Urgency` string.",
                "properties": {
                    "level": {"type": "string", "enum": ["normal", "fast", "urgent"]},
                    "overrides": {
                        "type": "object",
                        "description": "Caller-supplied caps applied "
                        "on top of the gas service's "
                        "computed quote. All fields "
                        "are absolute wei (decimal "
                        "string). "
                        "`maxPriorityFeePerGas` and "
                        "`maxFeePerGas` are treated "
                        "as caps - they lower the "
                        "quote, never raise it. "
                        "`gasLimit`, if set, replaces "
                        "the limit calculation "
                        "entirely.",
                        "properties": {
                            "maxPriorityFeePerGas": {
                                "type": "string",
                                "description": "Maximum "
                                "priority "
                                "fee "
                                "in "
                                "wei "
                                "(decimal "
                                "string).",
                            },
                            "maxFeePerGas": {
                                "type": "string",
                                "description": "Maximum "
                                "total "
                                "fee "
                                "per "
                                "gas "
                                "in "
                                "wei "
                                "(decimal "
                                "string).",
                            },
                            "gasLimit": {
                                "type": "string",
                                "description": "Gas "
                                "limit "
                                "cap "
                                "(in "
                                "gas "
                                "units, "
                                "decimal "
                                "string).",
                            },
                        },
                    },
                },
                "required": ["level"],
            },
        ],
        "description": "The urgency impacts the estimated gas price of the transaction. The "
        "higher the urgency, the higher the gas price, and the faster the "
        "transaction is likely to be selected from the mempool. Send the bare "
        'string form (e.g. `"normal"`) for the common case, or the object '
        "form `{ level, overrides }` to supply caller caps for "
        "`maxPriorityFeePerGas`, `maxFeePerGas`, and `gasLimit`.",
    },
    "GetSwaps.txHashes": {
        "type": "array",
        "items": {
            "type": "string",
            "description": "The unique hash of the transaction.",
            "pattern": "^(0x)?[0-9a-fA-F]{64}$",
        },
    },
    "GetSwaps.userOpHashes": {
        "type": "array",
        "items": {
            "type": "string",
            "description": "The unique hash of the transaction.",
            "pattern": "^(0x)?[0-9a-fA-F]{64}$",
        },
    },
}
