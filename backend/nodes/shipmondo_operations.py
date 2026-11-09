"""Shipmondo API v3 operation forms, pinned to the provider's OpenAPI contract.

https://app.shipmondo.com/api/public/v3/openapi.json
Only the declared method/path is dispatched; JSON payloads cannot alter routing.
"""
from datetime import datetime
from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, create_model, field_validator
import json

OPERATIONS = {
    "get_account": {
        "method": "GET",
        "path": "/account/",
        "label": "Retrieve account information",
        "operation_id": "account",
        "query": [],
        "body": [],
        "fields": {},
        "json_body": False,
    },
    "get_balance": {
        "method": "GET",
        "path": "/account/balance",
        "label": "Retrieve balance",
        "operation_id": "account_balance_get",
        "query": [],
        "body": [],
        "fields": {},
        "json_body": False,
    },
    "list_carriers": {
        "method": "GET",
        "path": "/carriers",
        "label": "List available carriers",
        "operation_id": "carriers_get",
        "query": ["sender_country_code", "receiver_country_code"],
        "body": [],
        "fields": {
            "sender_country_code": {
                "schema": {"type": "string", "example": "DK"},
                "required": False,
                "description": "Sender country code to be included in the filter.",
            },
            "receiver_country_code": {
                "schema": {"type": "string", "example": "DK"},
                "required": True,
                "description": "Receiver country code to be included in the filter.",
            },
        },
        "json_body": False,
    },
    "list_products": {
        "method": "GET",
        "path": "/products",
        "label": "List all products",
        "operation_id": "products_get",
        "query": [
            "id",
            "product_code",
            "sender_country_code",
            "receiver_country_code",
            "carrier_code",
            "per_page",
            "page",
        ],
        "body": [],
        "fields": {
            "id": {
                "schema": {"type": "integer"},
                "required": False,
                "description": "ID for the product to be included in the filter.",
            },
            "product_code": {
                "schema": {"type": "string", "example": "GLSDK_SD"},
                "required": False,
                "description": "Code for the product to be included in the filter.",
            },
            "sender_country_code": {
                "schema": {"type": "string", "example": "DK"},
                "required": False,
                "description": "Country code (ISO Alpha-2) of the sender country to be included in the filter.",
            },
            "receiver_country_code": {
                "schema": {"type": "string", "example": "DK"},
                "required": False,
                "description": "Country code (ISO Alpha-2) of the receiver country to be included in the filter.",
            },
            "carrier_code": {
                "schema": {"type": "string", "example": "gls"},
                "required": False,
                "description": "Carrier code to be included in the filter.",
            },
            "per_page": {
                "schema": {"type": "integer", "default": 20, "maximum": 50},
                "required": False,
                "description": "For pagination. Defines how many entries are returned per page.",
            },
            "page": {
                "schema": {"type": "integer", "default": 1},
                "required": False,
                "description": "For pagination. Defines which page the results are fetched from.",
            },
        },
        "json_body": False,
    },
    "list_shipment_templates": {
        "method": "GET",
        "path": "/shipment_templates",
        "label": "List all shipment templates",
        "operation_id": "shipment_templates_get",
        "query": ["id", "sender_country", "receiver_country", "per_page", "page"],
        "body": [],
        "fields": {
            "id": {
                "schema": {"type": "integer"},
                "required": False,
                "description": "ID for the shipment template to be included in the filter",
            },
            "sender_country": {
                "schema": {"type": "string", "example": "DK"},
                "required": False,
                "description": "Country code (ISO Alpha-2) to be included in the filter.",
            },
            "receiver_country": {
                "schema": {"type": "string", "example": "DK"},
                "required": False,
                "description": "Country code (ISO Alpha-2) to be included in the filter.",
            },
            "per_page": {
                "schema": {"type": "integer", "default": 20, "maximum": 50},
                "required": False,
                "description": "For pagination. Defines how many entries are returned per page.",
            },
            "page": {
                "schema": {"type": "integer", "default": 1},
                "required": False,
                "description": "For pagination. Defines which page the results are fetched from.",
            },
        },
        "json_body": False,
    },
    "list_shipments": {
        "method": "GET",
        "path": "/shipments",
        "label": "List all shipments",
        "operation_id": "shipments_get",
        "query": [
            "id",
            "order_id",
            "package_number",
            "carrier_code",
            "sender_country",
            "receiver_country",
            "waybill_reference",
            "created_at_min",
            "created_at_max",
            "per_page",
            "page",
            "reference",
            "additional_reference",
        ],
        "body": [],
        "fields": {
            "id": {
                "schema": {"type": "integer"},
                "required": False,
                "description": "ID for the shipment to be included in the filter",
            },
            "order_id": {
                "schema": {"type": "string"},
                "required": False,
                "description": "Order ID for the shipments to be included in the filter",
            },
            "package_number": {
                "schema": {"type": "string"},
                "required": False,
                "description": "Shipment or package number for the shipments to be included in the filter",
            },
            "carrier_code": {
                "schema": {
                    "type": "string",
                    "enum": [
                        "airmee",
                        "alpi",
                        "asendia",
                        "best",
                        "bft",
                        "bhs_logistics",
                        "bws",
                        "bpost",
                        "bring",
                        "brink",
                        "budbee",
                        "burd",
                        "city_mail",
                        "cm_transport",
                        "collicare",
                        "dachser",
                        "dansk_distribution_brabrand",
                        "dansk_distribution",
                        "dansk_distribution_taulov",
                        "dfm",
                        "dao",
                        "deutsche_post",
                        "dhl_express",
                        "dhl_freight_se",
                        "dhl_parcel",
                        "dpd",
                        "dsv_parcel",
                        "dsv",
                        "db_schenker",
                        "dsv_xpress",
                        "early_bird",
                        "esbjerg_gods",
                        "esbjerg_gods_sjaelland",
                        "fed_ex",
                        "freja",
                        "geodis",
                        "gls",
                        "gls_de",
                        "gordon",
                        "helthjem",
                        "instabox",
                        "interfjord",
                        "jetpak",
                        "jetpak_se",
                        "jjd",
                        "joervi_transport",
                        "kht",
                        "leman",
                        "lgt_logistics",
                        "link_logistics",
                        "b2c_europe",
                        "mover",
                        "nonbo_fragt",
                        "packeta",
                        "posti",
                        "post_nl",
                        "pdk",
                        "post_nord",
                        "sand_distribution",
                        "sdl",
                        "simptra",
                        "tjw",
                        "tnt",
                        "ups",
                        "webrinq",
                        "xpressen",
                        "unspecified",
                    ],
                },
                "required": False,
                "description": "Carrier code to be included in the filter.",
            },
            "sender_country": {
                "schema": {"type": "string", "example": "DK"},
                "required": False,
                "description": "Country code (ISO Alpha-2) to be included in the filter.",
            },
            "receiver_country": {
                "schema": {"type": "string", "example": "DK"},
                "required": False,
                "description": "Country code (ISO Alpha-2) to be included in the filter.",
            },
            "waybill_reference": {
                "schema": {"type": "string", "example": "CS000000000NO"},
                "required": False,
                "description": "Reference of the bulk waybill that the shipment is included in, to be included in the filter.",
            },
            "created_at_min": {
                "schema": {"type": "string", "format": "date-time"},
                "required": False,
                "description": '"From" timestamp for the shipments to be included in the filter. Examples:\n* 2017-06-19T11:00:03.305+02:00\n* 2017-06-19 will be transformed into 2017-06-19T00:00:00.000+02:00\n',
            },
            "created_at_max": {
                "schema": {"type": "string", "format": "date-time"},
                "required": False,
                "description": '"To" timestamp for the shipments to be included in the filter. Examples:\n* 2017-06-29T11:00:03.305+02:00\n* 2017-06-29 will be transformed into 2017-06-29T00:00:00.000+02:00\n',
            },
            "per_page": {
                "schema": {"type": "integer", "default": 20, "maximum": 50},
                "required": False,
                "description": "For pagination. Defines how many entries are returned per page.",
            },
            "page": {
                "schema": {"type": "integer", "default": 1},
                "required": False,
                "description": "For pagination. Defines which page the results are fetched from.",
            },
            "reference": {
                "schema": {"type": "string"},
                "required": False,
                "description": "Filter based on the reference field.",
            },
            "additional_reference": {
                "schema": {"type": "string"},
                "required": False,
                "description": "Filter based on the additional_reference field.",
            },
        },
        "json_body": False,
    },
    "get_shipment": {
        "method": "GET",
        "path": "/shipments/{id}",
        "label": "Retrieve a shipment",
        "operation_id": "shipment_get",
        "query": [],
        "body": [],
        "fields": {
            "id": {
                "schema": {"type": "integer"},
                "required": True,
                "description": "ID for the shipment to be included in the filter",
            }
        },
        "json_body": False,
    },
    "create_shipment": {
        "method": "POST",
        "path": "/shipments",
        "label": "Create a shipment",
        "operation_id": "shipments_post",
        "query": [],
        "body": [],
        "fields": {},
        "json_body": True,
    },
    "cancel_shipment": {
        "method": "PUT",
        "path": "/shipments/{id}/cancel",
        "label": "Cancel a shipment",
        "operation_id": "shipment_cancel",
        "query": [],
        "body": [],
        "fields": {
            "id": {
                "schema": {"type": "integer"},
                "required": True,
                "description": "ID for the shipment to be included in the filter",
            }
        },
        "json_body": False,
    },
    "get_shipment_labels": {
        "method": "GET",
        "path": "/shipments/{id}/labels",
        "label": "Retrieve labels of a shipment",
        "operation_id": "shipment_labels",
        "query": ["label_format", "scale_by", "scale_size", "label_dpi"],
        "body": [],
        "fields": {
            "id": {
                "schema": {"type": "integer"},
                "required": True,
                "description": "ID for the shipment to be included in the filter",
            },
            "label_format": {
                "schema": {
                    "type": "string",
                    "enum": [
                        "a4_pdf",
                        "10x19_pdf",
                        "10x19_png",
                        "10x19_zpl",
                        "compact_png",
                        "compact_pdf",
                        "compact_zpl",
                    ],
                },
                "required": False,
                "description": "Which format the labels should be.\n\n*10x19* is 10 cm x 19 cm\n\n*compact* format returns the smallest label possible.",
            },
            "scale_by": {
                "schema": {"type": "string", "enum": ["height", "width"]},
                "required": False,
                "description": "Scale down the labels by either width or height. Only applicable when label_format: a4_pdf, 10x19_pdf, 10x19_zpl, compact_pdf, compact_zpl",
            },
            "scale_size": {
                "schema": {"type": "number", "example": 15.6},
                "required": False,
                "description": 'Desired scaled length in cm of dimension in "scale_by".If the length is higher or wider than the original labels, the labels will not be scaled.\n\n Only applicable when label_format: a4_pdf, 10x19_pdf, 10x19_zpl, compact_pdf, compact_zpl.',
            },
            "label_dpi": {
                "schema": {"type": "integer", "enum": [200, 300]},
                "required": False,
                "description": "Resolution (dots per inch) to return the ZPL label at. If it differs from the resolution the label was originally created at, the ZPL is converted to this resolution. Only applicable when label_format: zpl, 10x19_zpl, compact_zpl.",
            },
        },
        "json_body": False,
    },
    "list_sales_orders": {
        "method": "GET",
        "path": "/sales_orders",
        "label": "List all sales orders",
        "operation_id": "sales_orders_get",
        "query": [
            "id",
            "order_id",
            "reference",
            "bill_to_email",
            "bill_to_mobile",
            "ship_to_email",
            "ship_to_mobile",
            "archived",
            "created_at_min",
            "created_at_max",
            "updated_at_min",
            "updated_at_max",
            "per_page",
            "page",
        ],
        "body": [],
        "fields": {
            "id": {
                "schema": {"type": "integer"},
                "required": False,
                "description": "ID for the sales order to be included in the filter.",
            },
            "order_id": {
                "schema": {"type": "string"},
                "required": False,
                "description": "Order ID for the sales order to be included in the filter.",
            },
            "reference": {
                "schema": {"type": "string"},
                "required": False,
                "description": "reference for the order to be included in the filter.",
            },
            "bill_to_email": {
                "schema": {"type": "string"},
                "required": False,
                "description": "Billing email for the order to be included in the filter.",
            },
            "bill_to_mobile": {
                "schema": {"type": "string"},
                "required": False,
                "description": "Billing mobile for the order to be included in the filter.",
            },
            "ship_to_email": {
                "schema": {"type": "string"},
                "required": False,
                "description": "Shipping email for the order to be included in the filter.",
            },
            "ship_to_mobile": {
                "schema": {"type": "string"},
                "required": False,
                "description": "Shipping mobile for the order to be included in the filter.",
            },
            "archived": {
                "schema": {"type": "boolean"},
                "required": False,
                "description": "Filter for archived or not.",
            },
            "created_at_min": {
                "schema": {"type": "string", "format": "date-time"},
                "required": False,
                "description": '"From" value of "created" timestamp for the sales orders to be included in the filter. Examples:\n* 2018-06-19T11:00:03.305+02:00\n* 2018-06-19 will be transformed into 2017-06-19T00:00:00.000+02:00',
            },
            "created_at_max": {
                "schema": {"type": "string", "format": "date-time"},
                "required": False,
                "description": '"To" value of "created" timestamp for the sales orders to be included in the filter. Examples:\n* 2018-06-29T11:00:03.305+02:00\n* 2018-06-29 will be transformed into 2017-06-29T00:00:00.000+02:00',
            },
            "updated_at_min": {
                "schema": {"type": "string", "format": "date-time"},
                "required": False,
                "description": '"From" value of "updated" timestamp for the sales orders to be included in the filter. Examples:\n* 2018-06-19T11:00:03.305+02:00\n* 2018-06-19 will be transformed into 2017-06-19T00:00:00.000+02:00',
            },
            "updated_at_max": {
                "schema": {"type": "string", "format": "date-time"},
                "required": False,
                "description": '"To" value of "updated" timestamp for the sales orders to be included in the filter. Examples:\n* 2018-06-29T11:00:03.305+02:00\n* 2018-06-29 will be transformed into 2017-06-29T00:00:00.000+02:00',
            },
            "per_page": {
                "schema": {
                    "type": "integer",
                    "default": 10,
                    "minimum": 1,
                    "maximum": 25,
                },
                "required": False,
                "description": "For pagination. Defines how many entries are returned per page.",
            },
            "page": {
                "schema": {"type": "integer", "default": 1},
                "required": False,
                "description": "For pagination. Defines which page the results are fetched from.",
            },
        },
        "json_body": False,
    },
    "get_sales_order": {
        "method": "GET",
        "path": "/sales_orders/{id}",
        "label": "Retrieve a sales order",
        "operation_id": "sales_order_get",
        "query": [],
        "body": [],
        "fields": {
            "id": {
                "schema": {"type": "integer"},
                "required": True,
                "description": "ID for the sales order to be included in the filter",
            }
        },
        "json_body": False,
    },
    "create_sales_order": {
        "method": "POST",
        "path": "/sales_orders",
        "label": "Create a sales order",
        "operation_id": "sales_orders_post",
        "query": [],
        "body": [],
        "fields": {},
        "json_body": True,
    },
    "update_sales_order": {
        "method": "PUT",
        "path": "/sales_orders/{id}",
        "label": "Update a sales order",
        "operation_id": "sales_order_put",
        "query": [],
        "body": [],
        "fields": {
            "id": {
                "schema": {"type": "integer"},
                "required": True,
                "description": "ID for the sales order that needs to be updated",
            }
        },
        "json_body": True,
    },
    "update_sales_order_note": {
        "method": "PUT",
        "path": "/sales_orders/{id}/order_note",
        "label": "Update a sales order note",
        "operation_id": "sales_order_update_note",
        "query": [],
        "body": ["order_note"],
        "fields": {
            "id": {
                "schema": {"type": "integer"},
                "required": True,
                "description": "ID for the sales order that note should be updated for",
            },
            "order_note": {
                "schema": {
                    "type": "string",
                    "example": "Note",
                    "description": "A note for the sales order.",
                },
                "required": False,
                "description": "A note for the sales order.",
            },
        },
        "json_body": False,
    },
    "hold_sales_order": {
        "method": "PUT",
        "path": "/sales_orders/{id}/hold",
        "label": "Hold a sales order",
        "operation_id": "sales_order_hold",
        "query": [],
        "body": [],
        "fields": {
            "id": {
                "schema": {"type": "integer"},
                "required": True,
                "description": "ID for the sales order that should be put on hold.",
            }
        },
        "json_body": False,
    },
    "resume_sales_order": {
        "method": "PUT",
        "path": "/sales_orders/{id}/unhold",
        "label": "Resume a sales order",
        "operation_id": "sales_order_unhold",
        "query": [],
        "body": [],
        "fields": {
            "id": {
                "schema": {"type": "integer"},
                "required": True,
                "description": "ID for the sales order that should be resumed.",
            }
        },
        "json_body": False,
    },
    "create_sales_order_shipment": {
        "method": "POST",
        "path": "/sales_orders/{id}/create_shipment",
        "label": "Create a shipment",
        "operation_id": "sales_order_create_shipment",
        "query": [],
        "body": [],
        "fields": {
            "id": {
                "schema": {"type": "integer"},
                "required": True,
                "description": "ID of the sales order to create a shipment for",
            }
        },
        "json_body": False,
    },
    "list_items": {
        "method": "GET",
        "path": "/items",
        "label": "List all items",
        "operation_id": "items_get",
        "query": [
            "id",
            "sku",
            "name",
            "barcode",
            "created_at_min",
            "created_at_max",
            "updated_at_min",
            "updated_at_max",
            "per_page",
            "page",
        ],
        "body": [],
        "fields": {
            "id": {
                "schema": {"type": "integer"},
                "required": False,
                "description": "ID of the item that needs to be considered for filter",
            },
            "sku": {
                "schema": {"type": "string"},
                "required": False,
                "description": "SKU of the item that needs to be considered for filter",
            },
            "name": {
                "schema": {"type": "string"},
                "required": False,
                "description": "Name of the item that needs to be considered for filter",
            },
            "barcode": {
                "schema": {"type": "string"},
                "required": False,
                "description": "The barcode value of the item that needs to be considered for filter",
            },
            "created_at_min": {
                "schema": {"type": "string", "format": "date-time"},
                "required": False,
                "description": '"From" timestamp for the items to be included in the filter. Examples:\n* 2017-06-19T11:00:03.305+02:00\n* 2017-06-19 will be transformed into 2017-06-19T00:00:00.000+02:00\n',
            },
            "created_at_max": {
                "schema": {"type": "string", "format": "date-time"},
                "required": False,
                "description": '"To" timestamp for the items to be included in the filter. Examples:\n* 2017-06-29T11:00:03.305+02:00\n* 2017-06-29 will be transformed into 2017-06-29T00:00:00.000+02:00\n',
            },
            "updated_at_min": {
                "schema": {"type": "string", "format": "date-time"},
                "required": False,
                "description": '"From" value of "updated" timestamp for the items to be included in the filter. Examples:\n* 2018-06-19T11:00:03.305+02:00\n* 2018-06-19 will be transformed into 2017-06-19T00:00:00.000+02:00\n',
            },
            "updated_at_max": {
                "schema": {"type": "string", "format": "date-time"},
                "required": False,
                "description": '"To" value of "updated" timestamp for the items to be included in the filter. Examples:\n* 2018-06-29T11:00:03.305+02:00\n* 2018-06-29 will be transformed into 2017-06-29T00:00:00.000+02:00\n',
            },
            "per_page": {
                "schema": {
                    "type": "integer",
                    "default": 10,
                    "minimum": 1,
                    "maximum": 50,
                },
                "required": False,
                "description": "For pagination. Defines how many entries are returned per page.",
            },
            "page": {
                "schema": {"type": "integer", "default": 1},
                "required": False,
                "description": "For pagination. Defines which page the results are fetched from.",
            },
        },
        "json_body": False,
    },
    "get_item": {
        "method": "GET",
        "path": "/items/{id}",
        "label": "Retrieve an item",
        "operation_id": "item_get",
        "query": [],
        "body": [],
        "fields": {
            "id": {
                "schema": {"type": "integer"},
                "required": True,
                "description": "ID for the item to be included in the filter",
            }
        },
        "json_body": False,
    },
    "create_item": {
        "method": "POST",
        "path": "/items",
        "label": "Create an item",
        "operation_id": "item_create",
        "query": [],
        "body": [
            "sku",
            "name",
            "variant_code",
            "barcode",
            "bin",
            "weight",
            "image_url",
            "country_code_of_origin",
            "currency_code",
            "customs_commodity_code",
            "customs_description",
            "shop",
            "virtual",
        ],
        "fields": {
            "sku": {
                "schema": {
                    "type": "string",
                    "example": "EX-123",
                    "description": "SKU (stock keeping unit). Must be unique for every item, including variants.",
                },
                "required": True,
                "description": "SKU (stock keeping unit). Must be unique for every item, including variants.",
            },
            "name": {
                "schema": {
                    "type": "string",
                    "example": "T-Shirt",
                    "description": "Name of the item.",
                },
                "required": True,
                "description": "Name of the item.",
            },
            "variant_code": {
                "schema": {
                    "type": "string",
                    "example": "Large",
                    "description": "Variant code of the item.",
                },
                "required": False,
                "description": "Variant code of the item.",
            },
            "barcode": {
                "schema": {
                    "type": "string",
                    "example": "1234567891011",
                    "description": "Barcode of the item, which is used when scanning item for pick. Will be displayed as a code 128 barcode",
                },
                "required": False,
                "description": "Barcode of the item, which is used when scanning item for pick. Will be displayed as a code 128 barcode",
            },
            "bin": {
                "schema": {
                    "type": "string",
                    "example": "123-a",
                    "description": "The bin/location where the item is located in the warehouse.",
                },
                "required": False,
                "description": "The bin/location where the item is located in the warehouse.",
            },
            "weight": {
                "schema": {
                    "type": "integer",
                    "example": 1000,
                    "description": "Weight of the item in grams.",
                },
                "required": False,
                "description": "Weight of the item in grams.",
            },
            "image_url": {
                "schema": {
                    "type": "string",
                    "example": "https://example.com/image.jpg",
                    "description": "Image URL of the item that appears on the order or when picking. Will only be displayed if the URL is HTTPS.",
                },
                "required": False,
                "description": "Image URL of the item that appears on the order or when picking. Will only be displayed if the URL is HTTPS.",
            },
            "country_code_of_origin": {
                "schema": {
                    "type": "string",
                    "example": "DK",
                    "description": "ISO 3166-1 alpha-2 country code of origin.",
                },
                "required": False,
                "description": "ISO 3166-1 alpha-2 country code of origin.",
            },
            "currency_code": {
                "schema": {
                    "type": "string",
                    "example": "DKK",
                    "description": "ISO 4217 currency code.",
                },
                "required": False,
                "description": "ISO 4217 currency code.",
            },
            "customs_commodity_code": {
                "schema": {
                    "type": "string",
                    "example": "123456",
                    "description": "Global tariff code for the item. Used when creating shipments that require customs declaration.",
                },
                "required": False,
                "description": "Global tariff code for the item. Used when creating shipments that require customs declaration.",
            },
            "customs_description": {
                "schema": {
                    "type": "string",
                    "example": "Example contents",
                    "description": "Customs description for the item. Used when creating shipments that require customs declaration.",
                },
                "required": False,
                "description": "Customs description for the item. Used when creating shipments that require customs declaration.",
            },
            "shop": {
                "schema": {
                    "type": "string",
                    "example": "API",
                    "description": "Origin shop of the item.",
                },
                "required": False,
                "description": "Origin shop of the item.",
            },
            "virtual": {
                "schema": {
                    "type": "boolean",
                    "default": False,
                    "description": "Describes if the item is a virtual item.",
                },
                "required": False,
                "description": "Describes if the item is a virtual item.",
            },
        },
        "json_body": False,
    },
    "update_item": {
        "method": "PUT",
        "path": "/items/{id}",
        "label": "Update an item",
        "operation_id": "item_update",
        "query": [],
        "body": [
            "name",
            "variant_code",
            "barcode",
            "bin",
            "weight",
            "image_url",
            "country_code_of_origin",
            "currency_code",
            "customs_commodity_code",
            "customs_description",
            "virtual",
        ],
        "fields": {
            "id": {
                "schema": {"type": "integer"},
                "required": True,
                "description": "ID for the item that is to be updated",
            },
            "name": {
                "schema": {
                    "type": "string",
                    "example": "T-Shirt",
                    "description": "Name of the item.",
                },
                "required": False,
                "description": "Name of the item.",
            },
            "variant_code": {
                "schema": {
                    "type": "string",
                    "example": "Large",
                    "description": "Variant code of the item.",
                },
                "required": False,
                "description": "Variant code of the item.",
            },
            "barcode": {
                "schema": {
                    "type": "string",
                    "example": "1234567891011",
                    "description": "Barcode of the item. Used when scanning item for pick.",
                },
                "required": False,
                "description": "Barcode of the item. Used when scanning item for pick.",
            },
            "bin": {
                "schema": {
                    "type": "string",
                    "example": "123-a",
                    "description": "The bin/location where the item is located in the warehouse.",
                },
                "required": False,
                "description": "The bin/location where the item is located in the warehouse.",
            },
            "weight": {
                "schema": {
                    "type": "integer",
                    "example": 1000,
                    "description": "Weight of the item in grams.",
                },
                "required": False,
                "description": "Weight of the item in grams.",
            },
            "image_url": {
                "schema": {
                    "type": "string",
                    "example": "https://example.com/image.jpg",
                    "description": "Image URL of the item that appears on the order or when picking. Will only be displayed if the URL is HTTPS.",
                },
                "required": False,
                "description": "Image URL of the item that appears on the order or when picking. Will only be displayed if the URL is HTTPS.",
            },
            "country_code_of_origin": {
                "schema": {
                    "type": "string",
                    "example": "DK",
                    "description": "ISO 3166-1 alpha-2 country code of origin.",
                },
                "required": False,
                "description": "ISO 3166-1 alpha-2 country code of origin.",
            },
            "currency_code": {
                "schema": {
                    "type": "string",
                    "example": "DKK",
                    "description": "ISO 4217 currency code.",
                },
                "required": False,
                "description": "ISO 4217 currency code.",
            },
            "customs_commodity_code": {
                "schema": {
                    "type": "string",
                    "example": "123456",
                    "description": "Global tariff code for the item. Used when creating shipments that require customs declaration.",
                },
                "required": False,
                "description": "Global tariff code for the item. Used when creating shipments that require customs declaration.",
            },
            "customs_description": {
                "schema": {
                    "type": "string",
                    "example": "Example contents",
                    "description": "Customs description for the item. Used when creating shipments that require customs declaration.",
                },
                "required": False,
                "description": "Customs description for the item. Used when creating shipments that require customs declaration.",
            },
            "virtual": {
                "schema": {
                    "type": "boolean",
                    "default": False,
                    "description": "Describes if the item is a virtual item.",
                },
                "required": False,
                "description": "Describes if the item is a virtual item.",
            },
        },
        "json_body": False,
    },
}


class ShipmondoOperation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    @field_validator("*", mode="after")
    @classmethod
    def check_json(cls, value, info):
        if info.field_name == "payload":
            try:
                parsed = json.loads(value)
            except (ValueError, TypeError):
                raise ValueError("Enter a JSON object") from None
            if not isinstance(parsed, dict) or not parsed:
                raise ValueError("Enter a nonempty JSON object")
        return value


def _field(spec):
    schema = spec["schema"]
    kind = schema.get("type", "string")
    annotation = {"string": str, "integer": int, "number": float, "boolean": bool}.get(
        kind, Any
    )
    if schema.get("enum"):
        annotation = Literal[tuple(schema["enum"])]
    if schema.get("format") == "date-time":
        annotation = datetime
    required = spec["required"]
    # Server defaults are not user intent: omit optional write fields unless set.
    default = ... if required else None
    if not required and default is None:
        annotation = Optional[annotation]
    kwargs = {"description": spec["description"]}
    if kind in {"number", "integer"}:
        if "minimum" in schema:
            kwargs["ge"] = schema["minimum"]
        if "maximum" in schema:
            kwargs["le"] = schema["maximum"]
    if schema.get("example") is not None:
        kwargs["examples"] = [schema["example"]]
    return annotation, Field(default, **kwargs)


def _make_model(name, spec):
    fields = {key: _field(value) for key, value in spec["fields"].items()}
    # IDs and pages are positive even where the published schema omits minimum.
    for key in ("id", "page"):
        if key in fields:
            required = spec["fields"][key]["required"]
            fields[key] = (
                int if required else Optional[int],
                Field(
                    ... if required else spec["fields"][key]["schema"].get("default"),
                    ge=1,
                ),
            )
    if "per_page" in fields:
        limit = spec["fields"]["per_page"]["schema"].get("maximum", 50)
        fields["per_page"] = (int, Field(20 if limit == 50 else 10, ge=1, le=limit))
    if spec["json_body"]:
        fields["payload"] = (
            str,
            Field(
                ...,
                title="Request JSON",
                description=(
                    "Shipmondo request object for "
                    + spec["method"]
                    + " "
                    + spec["path"]
                    + ". See https://shipmondo.dev/api-reference for required fields and carrier-specific options."
                ),
                json_schema_extra={"ui:widget": "code_editor", "ui:language": "json"},
            ),
        )
    fields["operation"] = (
        Literal[name],
        Field(
            name,
            title=spec["label"],
            json_schema_extra={
                "ui:hidden": True,
                "const": name,
                "x-display-name": spec["label"],
                "x-category": "Shipments"
                if "shipment" in name
                else "Sales orders"
                if "sales_order" in name
                else "Items"
                if "item" in name
                else "Account and catalog",
                "x-is-trigger": False,
            },
        ),
    )
    return create_model(
        "Shipmondo" + "".join(x.title() for x in name.split("_")) + "Config",
        __base__=ShipmondoOperation,
        __module__=__name__,
        **fields
    )


CONFIG_MODELS = {name: _make_model(name, spec) for name, spec in OPERATIONS.items()}
globals().update({model.__name__: model for model in CONFIG_MODELS.values()})
