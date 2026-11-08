"""NetLicensing v2 licensing operations using a manually supplied API key.

Each operation makes one fixed REST call. Responses retain the provider envelope
and expose property pairs as records so account evidence can name products.
"""
from __future__ import annotations

from typing import Annotated, Literal, Union
from urllib.parse import quote

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

BASE = "https://go.netlicensing.io/core/v2/rest"
CREDENTIAL_TYPE = "netlicensing_api_key"


class NetlicensingAPIKeyCredential(BaseModel):
    model_config = ConfigDict(title="Netlicensing API Key", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://netlicensing.io/wiki/security",
            "x-credential-instructions": "Create an API key in the NetLicensing Management Console and paste it here. Analytics permits reads; Operation permits licensee and license writes; Maintenance permits product, module and template writes. NoClick sends it as the Basic password with the fixed username apiKey.",
        })
    credential_type: Literal["netlicensing_api_key"] = Field("netlicensing_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., title="API Key", min_length=1, max_length=4096, repr=False,
        json_schema_extra={"ui:widget": "password"})

    @field_validator("api_key", mode="before")
    @classmethod
    def key(cls, value):
        value = clean_secret(value, field_name="API Key")
        if any(c.isspace() for c in value):
            raise ValueError("Paste the API key without a header or whitespace")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True, allow_inf_nan=False)

    @field_validator("*", mode="after")
    @classmethod
    def bounded_text(cls, value, info):
        if isinstance(value, str) and info.field_name != "operation":
            if not value.strip() or len(value) > 1000 or any(ord(c) < 32 or ord(c) == 127 for c in value):
                raise ValueError("Use nonempty text of at most 1000 characters without controls")
            if info.field_name.endswith("Number") or info.field_name == "number":
                if any(c in value for c in "/\\?#") or value in {".", ".."}:
                    raise ValueError("Use one NetLicensing resource number")
        return value

    @model_validator(mode="after")
    def nonempty_update(self):
        if self.operation.startswith("update_"):
            values = self.model_dump(exclude_none=True, exclude={"operation"})
            if not any(not key.endswith("Number") for key in values):
                raise ValueError("Supply at least one property to update")
        return self


class ListProductsConfig(_Input):
    """Return a list of all configured Products for the current Vendor. Lists return the provider default page only."""
    operation: Literal["list_products"] = Field("list_products", title='List Products', json_schema_extra={"ui:hidden": True})


class GetProductConfig(_Input):
    """Return a Product by 'productNumber'."""
    operation: Literal["get_product"] = Field("get_product", title='Get Product', json_schema_extra={"ui:hidden": True})
    productNumber: str = Field(..., title='Product Number', min_length=1, max_length=1000)


class CreateProductConfig(_Input):
    """Creates a new Product."""
    operation: Literal["create_product"] = Field("create_product", title='Create Product', json_schema_extra={"ui:hidden": True})
    active: bool = Field(..., description="If set to 'false', the Product is disabled. No new Licensees can be registered for the Product, existing Licensees can not obtain new Licenses.")
    description: str | None = Field(None, description='Product description.', max_length=1000)
    licenseeAutoCreate: bool | None = Field(None, description="If set to 'true', non-existing Licensees will be created at first validation attempt.")
    licensingInfo: str | None = Field(None, description='Licensing information.', max_length=1000)
    name: str = Field(..., description='Product name. Together with the version identifies the Product for the end customer.', max_length=1000)
    number: str | None = Field(None, description='Unique number that identifies the Product. Vendor can assign this number when creating a Product or let NetLicensing generate one.', max_length=1000)
    vatMode: Literal['GROSS', 'NET'] | None = Field(None, description='Vat mode for Product. Supported types: GROSS, NET', max_length=1000)
    version: str = Field(..., description='Product version. Convenience parameter, additional to the Product name.', max_length=1000)


class UpdateProductConfig(_Input):
    """Sets the provided properties to a Product. Return an updated Product."""
    operation: Literal["update_product"] = Field("update_product", title='Update Product', json_schema_extra={"ui:hidden": True})
    productNumber: str = Field(..., title='Product Number', min_length=1, max_length=1000)
    active: bool | None = Field(None, description="If set to 'false', the Product is disabled. No new Licensees can be registered for the Product, existing Licensees can not obtain new Licenses.")
    description: str | None = Field(None, description='Product description.', max_length=1000)
    licenseeAutoCreate: bool | None = Field(None, description="If set to 'true', non-existing Licensees will be created at first validation attempt.")
    licensingInfo: str | None = Field(None, description='Licensing information.', max_length=1000)
    name: str | None = Field(None, description='Product name. Together with the version identifies the Product for the end customer.', max_length=1000)
    number: str | None = Field(None, description='New Product number (update)', max_length=1000)
    vatMode: Literal['GROSS', 'NET'] | None = Field(None, description='Vat mode for Product. Supported types: GROSS, NET', max_length=1000)
    version: str | None = Field(None, description='Product version. Convenience parameter, additional to the Product name.', max_length=1000)


class ListProductModulesConfig(_Input):
    """Return a list of all Product Modules for the current Vendor. Lists return the provider default page only."""
    operation: Literal["list_product_modules"] = Field("list_product_modules", title='List Product Modules', json_schema_extra={"ui:hidden": True})


class GetProductModuleConfig(_Input):
    """Return a Product Module by 'productModuleNumber'."""
    operation: Literal["get_product_module"] = Field("get_product_module", title='Get Product Module', json_schema_extra={"ui:hidden": True})
    productModuleNumber: str = Field(..., title='Product Module Number', min_length=1, max_length=1000)


class CreateProductModuleConfig(_Input):
    """Creates a new Product Module."""
    operation: Literal["create_product_module"] = Field("create_product_module", title='Create Product Module', json_schema_extra={"ui:hidden": True})
    active: bool = Field(..., description="If set to 'false', the Product Module is disabled. Licensees can not obtain any new Licenses for this Product Module.")
    licensingModel: str = Field(..., description='Licensing model applied to this Product Module. Defines what License Templates can be configured for the Product Module and how Licenses for this Product Module are processed during validation.', max_length=1000)
    maxCheckoutValidity: int | None = Field(None, description="Maximum checkout validity (days). Mandatory for 'Floating' licensing model.", ge=0)
    name: str = Field(..., description='Product Module name that is visible to the end customers in NetLicensing Shop.', max_length=1000)
    number: str | None = Field(None, description='Unique number (across all Products of a Vendor) that identifies the Product Module. Vendor can assign this number when creating a Product Module or let NetLicensing generate one. Read-only after creation of the first Licensee for the Product.', max_length=1000)
    productNumber: str = Field(..., description='Unique number (across all Products of a Vendor) that identifies the Product Module. Vendor can assign this number when creating a Product Module or let NetLicensing generate one. Read-only after creation of the first Licensee for the Product.', max_length=1000)
    redThreshold: int | None = Field(None, description="Remaining time volume for red level. Mandatory for 'Rental' licensing model.", ge=0)
    yellowThreshold: int | None = Field(None, description="Remaining time volume for yellow level. Mandatory for 'Rental' licensing model.", ge=0)


class UpdateProductModuleConfig(_Input):
    """Sets the provided properties to a Product Module. Return an updated Product Module."""
    operation: Literal["update_product_module"] = Field("update_product_module", title='Update Product Module', json_schema_extra={"ui:hidden": True})
    productModuleNumber: str = Field(..., title='Product Module Number', min_length=1, max_length=1000)
    active: bool | None = Field(None, description="If set to 'false', the Product Module is disabled. Licensees can not obtain any new Licenses for this Product Module.")
    licensingModel: str | None = Field(None, description='Licensing model applied to this Product Module. Defines what License Templates can be configured for the Product Module and how Licenses for this Product Module are processed during validation.', max_length=1000)
    maxCheckoutValidity: int | None = Field(None, description="Maximum checkout validity (days). Mandatory for 'Floating' licensing model.", ge=0)
    name: str | None = Field(None, description='Product Module name that is visible to the end customers in NetLicensing Shop.', max_length=1000)
    number: str | None = Field(None, description='New Product Module number (update).', max_length=1000)
    redThreshold: int | None = Field(None, description="Remaining time volume for red level. Mandatory for 'Rental' licensing model.", ge=0)
    yellowThreshold: int | None = Field(None, description="Remaining time volume for yellow level. Mandatory for 'Rental' licensing model.", ge=0)


class ListLicenseTemplatesConfig(_Input):
    """Return a list of all License Templates for the current Vendor. Lists return the provider default page only."""
    operation: Literal["list_license_templates"] = Field("list_license_templates", title='List License Templates', json_schema_extra={"ui:hidden": True})


class GetLicenseTemplateConfig(_Input):
    """Return a License Template by 'licenseTemplateNumber'."""
    operation: Literal["get_license_template"] = Field("get_license_template", title='Get License Template', json_schema_extra={"ui:hidden": True})
    licenseTemplateNumber: str = Field(..., title='License Template Number', min_length=1, max_length=1000)


class CreateLicenseTemplateConfig(_Input):
    """Creates a new License Template."""
    operation: Literal["create_license_template"] = Field("create_license_template", title='Create License Template', json_schema_extra={"ui:hidden": True})
    active: bool = Field(..., description="If set to 'false', the License Template is disabled. Licensee can not obtain any new Licenses off this License Template.")
    automatic: bool | None = Field(None, description="If set to 'true', every new Licensee automatically gets one License out of this License Template on creation. Automatic Licenses must have their price set to 0.")
    currency: str | None = Field(None, description='Specifies currency for the License price. Check data types to discover which currencies are supported.', max_length=1000)
    hidden: bool | None = Field(None, description="If set to 'true', this License Template is not shown in NetLicensing Shop as offered for purchase.")
    hideLicenses: bool | None = Field(None, description="If set to 'true', Licenses from this License Template are not visible to the end customer, but participate in validation.")
    licenseType: str = Field(..., description='Type of Licenses created from this License Template. Supported types: FEATURE, TIMEVOLUME, FLOATING, QUANTITY', max_length=1000)
    maxSessions: str | None = Field(None, description="Mandatory for 'FLOATING' License Type.", max_length=1000)
    name: str = Field(..., description='License Template name to create License Template object', max_length=1000)
    number: str | None = Field(None, description='Unique number (across all Products of a Vendor) that identifies the License Template. Vendor can assign this number when creating a License Template or let NetLicensing generate one. Read-only after creation of the first License from this License Template.', max_length=1000)
    price: float | None = Field(None, description='Price for the License. If >0, it must always be accompanied by the currency specification.', ge=0)
    productModuleNumber: str = Field(..., description='Number of Product Module to create License Template object', max_length=1000)
    quantity: str | None = Field(None, description="Mandatory for 'Pay-per-Use' and 'Node-Locked' License Model.", max_length=1000)
    quota: str | None = Field(None, description="Mandatory for 'Quota' License Model.", max_length=1000)
    timeVolume: str | None = Field(None, description="Mandatory for 'TIMEVOLUME' License Type.", max_length=1000)
    timeVolumePeriod: str | None = Field(None, description="For 'TIMEVOLUME' License Type.", max_length=1000)


class UpdateLicenseTemplateConfig(_Input):
    """Sets the provided properties to a License Template. Return an updated License Template."""
    operation: Literal["update_license_template"] = Field("update_license_template", title='Update License Template', json_schema_extra={"ui:hidden": True})
    licenseTemplateNumber: str = Field(..., title='License Template Number', min_length=1, max_length=1000)
    active: bool | None = Field(None, description="If set to 'false', the License Template is disabled. Licensee can not obtain any new Licenses off this License Template.")
    automatic: bool | None = Field(None, description="If set to 'true', every new Licensee automatically gets one License out of this License Template on creation. Automatic Licenses must have their price set to 0.")
    currency: str | None = Field(None, description='Specifies currency for the License price. Check data types to discover which currencies are supported.', max_length=1000)
    hidden: bool | None = Field(None, description="If set to 'true', this License Template is not shown in NetLicensing Shop as offered for purchase.")
    hideLicenses: bool | None = Field(None, description="If set to 'true', Licenses from this License Template are not visible to the end customer, but participate in validation.")
    licenseType: str | None = Field(None, description='Type of Licenses created from this License Template. Supported types: FEATURE, TIMEVOLUME, FLOATING, QUANTITY', max_length=1000)
    maxSessions: str | None = Field(None, description="Mandatory for 'FLOATING' License Type.", max_length=1000)
    name: str | None = Field(None, description='Name for the Licensed item', max_length=1000)
    number: str | None = Field(None, description='New License Template number (update).', max_length=1000)
    price: float | None = Field(None, description='Price for the License. If >0, it must always be accompanied by the currency specification.', ge=0)
    quantity: str | None = Field(None, description="Mandatory for 'Pay-per-Use' and 'Node-Locked' License Model.", max_length=1000)
    quota: str | None = Field(None, description="Mandatory for 'Quota' License Model.", max_length=1000)
    timeVolume: str | None = Field(None, description="Mandatory for 'TIMEVOLUME' License Type.", max_length=1000)
    timeVolumePeriod: str | None = Field(None, description="For 'TIMEVOLUME' License Type.", max_length=1000)


class ListLicenseesConfig(_Input):
    """Return a list of all Licensees for the current Vendor. Lists return the provider default page only."""
    operation: Literal["list_licensees"] = Field("list_licensees", title='List Licensees', json_schema_extra={"ui:hidden": True})


class GetLicenseeConfig(_Input):
    """Return a Licensee by 'licenseeNumber'."""
    operation: Literal["get_licensee"] = Field("get_licensee", title='Get Licensee', json_schema_extra={"ui:hidden": True})
    licenseeNumber: str = Field(..., title='Licensee Number', min_length=1, max_length=1000)


class CreateLicenseeConfig(_Input):
    """Creates a new Licensee."""
    operation: Literal["create_licensee"] = Field("create_licensee", title='Create Licensee', json_schema_extra={"ui:hidden": True})
    active: bool = Field(..., description="If set to 'false', the Licensee is disabled. Licensee can not obtain new Licenses, and validation is disabled")
    markedForTransfer: bool | None = Field(None, description='Mark Licensee for transfer.')
    name: str | None = Field(None, description='', max_length=1000)
    number: str | None = Field(None, description='Unique number (across all Products of a Vendor) that identifies the Licensee. Vendor can assign this number when creating a Licensee or let NetLicensing generate one. Read-only after creation of the first License for the Licensee', max_length=1000)
    productNumber: str = Field(..., description="'productNumber' to assign new Licensee object", max_length=1000)


class UpdateLicenseeConfig(_Input):
    """Sets the provided properties to a Licensee. Return an updated Licensee."""
    operation: Literal["update_licensee"] = Field("update_licensee", title='Update Licensee', json_schema_extra={"ui:hidden": True})
    licenseeNumber: str = Field(..., title='Licensee Number', min_length=1, max_length=1000)
    active: bool | None = Field(None, description="If set to 'false', the Licensee is disabled. Licensee can not obtain new Licenses, and validation is disabled")
    markedForTransfer: bool | None = Field(None, description='Mark Licensee for transfer.')
    name: str | None = Field(None, description='', max_length=1000)
    number: str | None = Field(None, description='New Licensee number (update).', max_length=1000)


class DeleteLicenseeConfig(_Input):
    """Delete a Licensee by 'number'."""
    operation: Literal["delete_licensee"] = Field("delete_licensee", title='Delete Licensee', json_schema_extra={"ui:hidden": True})
    licenseeNumber: str = Field(..., title='Licensee Number', min_length=1, max_length=1000)


class ListLicensesConfig(_Input):
    """Return a list of all Licenses for the current Vendor. Lists return the provider default page only."""
    operation: Literal["list_licenses"] = Field("list_licenses", title='List Licenses', json_schema_extra={"ui:hidden": True})


class GetLicenseConfig(_Input):
    """Get License by a 'licenseNumber'."""
    operation: Literal["get_license"] = Field("get_license", title='Get License', json_schema_extra={"ui:hidden": True})
    licenseNumber: str = Field(..., title='License Number', min_length=1, max_length=1000)


class CreateLicenseConfig(_Input):
    """Creates a new License."""
    operation: Literal["create_license"] = Field("create_license", title='Create License', json_schema_extra={"ui:hidden": True})
    active: bool = Field(..., description='')
    currency: str | None = Field(None, description='Specifies currency for the License price. Check data types to discover which currencies are supported. Read-only, set from License Template on creation', max_length=1000)
    hidden: bool | None = Field(None, description="If set to 'true', this License is not shown in NetLicensing Shop as purchased License. Set from License Template on creation, if not specified explicitly")
    licenseTemplateNumber: str = Field(..., description='', max_length=1000)
    licenseeNumber: str = Field(..., description='', max_length=1000)
    name: str | None = Field(None, description='Name for the Licensed item. Set from License Template on creation, if not specified explicitly.', max_length=1000)
    number: str | None = Field(None, description='', max_length=1000)
    parentfeature: str | None = Field(None, description="Mandatory for 'TIMEVOLUME' License Type and 'RENTAL' licensing model", max_length=1000)
    price: float | None = Field(None, description='Price for the License. If >0, it must always be accompanied by the currency specification. Read-only, set from License Template on creation', ge=0)
    quantity: str | None = Field(None, description="Mandatory for 'Pay-per-Use' License Model.", max_length=1000)
    startDate: str | None = Field(None, description="Mandatory for 'TIMEVOLUME' License Type.", max_length=1000)
    timeVolume: str | None = Field(None, description="Mandatory for 'TIMEVOLUME' License Type.", max_length=1000)
    timeVolumePeriod: str | None = Field(None, description="For 'TIMEVOLUME' License Type.", max_length=1000)
    usedQuantity: str | None = Field(None, description="Mandatory for 'Pay-per-Use' License Model.", max_length=1000)


class UpdateLicenseConfig(_Input):
    """Update License by a 'licenseNumber'."""
    operation: Literal["update_license"] = Field("update_license", title='Update License', json_schema_extra={"ui:hidden": True})
    licenseNumber: str = Field(..., title='License Number', min_length=1, max_length=1000)
    active: bool | None = Field(None, description='')
    currency: str | None = Field(None, description='Specifies currency for the License price. Check data types to discover which currencies are supported. Read-only, set from License Template on creation', max_length=1000)
    hidden: bool | None = Field(None, description="If set to 'true', this License is not shown in NetLicensing Shop as purchased License. Set from License Template on creation, if not specified explicitly")
    name: str | None = Field(None, description='Name for the Licensed item. Set from License Template on creation, if not specified explicitly.', max_length=1000)
    number: str | None = Field(None, description='Unique number (across all Products/Licensees of a Vendor) that identifies the License. Vendor can assign this number when creating a License or let NetLicensing generate one. Read-only after corresponding creation Transaction status is set to closed.', max_length=1000)
    parentfeature: str | None = Field(None, description='', max_length=1000)
    price: float | None = Field(None, description='Price for the License. If > 0, it must always be accompanied by the currency specification. Read-only, set from License Template on creation', ge=0)
    quantity: str | None = Field(None, description="Mandatory for 'Pay-per-Use' License Model.", max_length=1000)
    startDate: str | None = Field(None, description="For 'TIMEVOLUME' License type", max_length=1000)
    timeVolume: str | None = Field(None, description="Mandatory for 'TIMEVOLUME' License Type.", max_length=1000)
    timeVolumePeriod: str | None = Field(None, description="For 'TIMEVOLUME' License Type.", max_length=1000)
    usedQuantity: str | None = Field(None, description="Mandatory for 'Pay-per-Use' License Model.", max_length=1000)


class DeleteLicenseConfig(_Input):
    """Delete License by a 'licenseNumber'."""
    operation: Literal["delete_license"] = Field("delete_license", title='Delete License', json_schema_extra={"ui:hidden": True})
    licenseNumber: str = Field(..., title='License Number', min_length=1, max_length=1000)


class ValidateLicenseeConfig(_Input):
    """Validates active Licenses of the Licensee."""
    operation: Literal["validate_licensee"] = Field("validate_licensee", title='Validate Licensee', json_schema_extra={"ui:hidden": True})
    licenseeNumber: str = Field(..., title='Licensee Number', min_length=1, max_length=1000)
    action: Literal['checkOut', 'checkIn'] | None = Field(None, description="'Floating' licensing model: check-out or check-in session action, to allocate or return it from/to the pool of available sessions", max_length=1000)
    licenseeName: str | None = Field(None, description='Human-readable name for the auto-created Licensee (will be set as custom Licensee property)', max_length=1000)
    nodeSecret: str | None = Field(None, description="'Node-Locked' licensing model: specifies unique secret", max_length=1000)
    productModuleNumber: str | None = Field(None, description="'Node-Locked' licensing model: product module number", max_length=1000)
    productNumber: str | None = Field(None, description="Product number, must be provided when 'Licensee auto-create' is enabled (see also Product JavaDoc). Identifies the Product to which new Licensee should be added", max_length=1000)
    sessionId: str | None = Field(None, description="'Floating' licensing model: specifies unique session identifier", max_length=1000)


class ListTransactionsConfig(_Input):
    """Return a list of all Transactions for the current Vendor. Lists return the provider default page only."""
    operation: Literal["list_transactions"] = Field("list_transactions", title='List Transactions', json_schema_extra={"ui:hidden": True})


class GetTransactionConfig(_Input):
    """Return a Transaction by 'transactionNumber'."""
    operation: Literal["get_transaction"] = Field("get_transaction", title='Get Transaction ', json_schema_extra={"ui:hidden": True})
    transactionNumber: str = Field(..., title='Transaction Number', min_length=1, max_length=1000)


NetlicensingConfig = Annotated[Union[
    ListProductsConfig,
    GetProductConfig,
    CreateProductConfig,
    UpdateProductConfig,
    ListProductModulesConfig,
    GetProductModuleConfig,
    CreateProductModuleConfig,
    UpdateProductModuleConfig,
    ListLicenseTemplatesConfig,
    GetLicenseTemplateConfig,
    CreateLicenseTemplateConfig,
    UpdateLicenseTemplateConfig,
    ListLicenseesConfig,
    GetLicenseeConfig,
    CreateLicenseeConfig,
    UpdateLicenseeConfig,
    DeleteLicenseeConfig,
    ListLicensesConfig,
    GetLicenseConfig,
    CreateLicenseConfig,
    UpdateLicenseConfig,
    DeleteLicenseConfig,
    ValidateLicenseeConfig,
    ListTransactionsConfig,
    GetTransactionConfig
], Field(discriminator="operation")]


class NetlicensingFullConfig(NodeConfig[NetlicensingConfig, NetlicensingAPIKeyCredential]):
    pass


ROUTES = {'list_products': ('GET', '/product', 'Product', None),
 'get_product': ('GET', '/product/{productNumber}', 'Product', 'productNumber'),
 'create_product': ('POST', '/product', 'Product', None),
 'update_product': ('POST', '/product/{productNumber}', 'Product', 'productNumber'),
 'list_product_modules': ('GET', '/productmodule', 'ProductModule', None),
 'get_product_module': ('GET',
                        '/productmodule/{productModuleNumber}',
                        'ProductModule',
                        'productModuleNumber'),
 'create_product_module': ('POST', '/productmodule', 'ProductModule', None),
 'update_product_module': ('POST',
                           '/productmodule/{productModuleNumber}',
                           'ProductModule',
                           'productModuleNumber'),
 'list_license_templates': ('GET', '/licensetemplate', 'LicenseTemplate', None),
 'get_license_template': ('GET',
                          '/licensetemplate/{licenseTemplateNumber}',
                          'LicenseTemplate',
                          'licenseTemplateNumber'),
 'create_license_template': ('POST', '/licensetemplate', 'LicenseTemplate', None),
 'update_license_template': ('POST',
                             '/licensetemplate/{licenseTemplateNumber}',
                             'LicenseTemplate',
                             'licenseTemplateNumber'),
 'list_licensees': ('GET', '/licensee', 'Licensee', None),
 'get_licensee': ('GET', '/licensee/{licenseeNumber}', 'Licensee', 'licenseeNumber'),
 'create_licensee': ('POST', '/licensee', 'Licensee', None),
 'update_licensee': ('POST', '/licensee/{licenseeNumber}', 'Licensee', 'licenseeNumber'),
 'delete_licensee': ('DELETE', '/licensee/{licenseeNumber}', 'Licensee', 'licenseeNumber'),
 'list_licenses': ('GET', '/license', 'License', None),
 'get_license': ('GET', '/license/{licenseNumber}', 'License', 'licenseNumber'),
 'create_license': ('POST', '/license', 'License', None),
 'update_license': ('POST', '/license/{licenseNumber}', 'License', 'licenseNumber'),
 'delete_license': ('DELETE', '/license/{licenseNumber}', 'License', 'licenseNumber'),
 'validate_licensee': ('POST',
                       '/licensee/{licenseeNumber}/validate',
                       'ProductModuleValidation',
                       'licenseeNumber'),
 'list_transactions': ('GET', '/transaction', 'Transaction', None),
 'get_transaction': ('GET', '/transaction/{transactionNumber}', 'Transaction', 'transactionNumber')}


def _records(body, expected_type):
    if not isinstance(body, dict) or "items" not in body:
        raise ValueError("NetLicensing must return its object envelope")
    infos = body.get("infos", {})
    if not isinstance(infos, dict):
        raise ValueError("Invalid NetLicensing information envelope")
    messages = infos.get("info", [])
    if not isinstance(messages, list):
        raise ValueError("Invalid NetLicensing messages")
    if any(isinstance(info, dict) and info.get("type") == "ERROR" for info in messages):
        raise ValueError("NetLicensing reported an API error")
    container = body.get("items", {})
    if not isinstance(container, dict):
        raise ValueError("Invalid NetLicensing items envelope")
    items = container.get("item", [])
    if not isinstance(items, list):
        raise ValueError("Invalid NetLicensing item list")
    records = []
    for item in items:
        if not isinstance(item, dict) or item.get("type") != expected_type:
            raise ValueError("NetLicensing returned an unexpected entity type")
        properties = item.get("property", [])
        if not isinstance(properties, list):
            raise ValueError("Invalid NetLicensing properties")
        record = {}
        for prop in properties:
            if not isinstance(prop, dict) or not isinstance(prop.get("name"), str) or prop["name"] in record:
                raise ValueError("Invalid or duplicate NetLicensing property")
            record[prop["name"]] = prop.get("value")
        records.append(record)
    return records


class NetlicensingNode(WorkflowNode):
    integration_type = "automation-netlicensing"
    connection_evidence = ConnectionEvidence(
        noun="products", operation="list_products", label_keys=("name", "number"))

    @classmethod
    def get_config_model(cls):
        return NetlicensingFullConfig

    async def execute(self, inputs):
        if not self.config.credentials:
            raise ValueError("Connect a NetLicensing API key")
        config = self.config.config
        method, route, entity_type, path_field = ROUTES[config.operation]
        if path_field:
            route = route.replace("{" + path_field + "}", quote(getattr(config, path_field), safe=""))
        values = config.model_dump(exclude_none=True, exclude={"operation", *([path_field] if path_field else [])})
        form = {key: str(value).lower() if isinstance(value, bool) else str(value) for key, value in values.items()}
        key = self.config.credentials.api_key
        try:
            async with guarded_async_client(timeout=30, trust_env=False, follow_redirects=False) as client:
                response = await client.request(method, BASE + route,
                    auth=httpx.BasicAuth("apiKey", key), headers={"Accept": "application/json", **({"Content-Type": "application/x-www-form-urlencoded"} if method == "POST" else {})},
                    **({"data": form} if method == "POST" else {}))
        except httpx.HTTPError:
            raise ValueError("NetLicensing request did not complete; inspect writes before retrying") from None
        if response.status_code not in {200, 204}:
            message = "NetLicensing request failed (HTTP " + str(response.status_code) + ")"
            try:
                info = response.json().get("infos", {}).get("info", [])
                details = [str(i.get("value") or i.get("id")) for i in info if isinstance(i, dict) and i.get("type") == "ERROR"]
                if details:
                    message += ": " + "; ".join(details)[:1000]
            except (ValueError, AttributeError, TypeError):
                pass
            return {"status": "error", "http_status": response.status_code, "error": message.replace(key, "[redacted]")}
        if method == "DELETE" and response.status_code == 204:
            return {"status": "success", "deleted_number": getattr(config, path_field), "http_status": 204}
        if response.status_code != 200:
            raise ValueError("NetLicensing omitted the expected result")
        if len(response.content) > 5_000_000 or "json" not in response.headers.get("content-type", "").lower():
            raise ValueError("NetLicensing returned an unsupported response")
        try:
            body = response.json()
            records = _records(body, entity_type)
        except (ValueError, TypeError):
            raise ValueError("NetLicensing returned an invalid result envelope") from None
        if config.operation.startswith(("get_", "create_", "update_")):
            if len(records) != 1 or not records[0].get("number"):
                raise ValueError("NetLicensing did not return the expected entity")
            expected = getattr(config, "number", None) or (getattr(config, path_field) if path_field else None)
            if expected is not None and records[0]["number"] != expected:
                raise ValueError("NetLicensing returned a different resource number")
        # Preserve nested validation lists and provider pagination metadata. A
        # validation HTTP success does not itself mean a license is valid.
        return {"status": "success", "http_status": 200, "items": records, "response": body,
            **({"page_scope": "provider default page"} if config.operation.startswith("list_") else {})}
