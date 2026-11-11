"""Royal Mail Public API v1 request models from the pinned provider contract.

Source: https://api.parcel.royalmail.com/doc/v1/click-and-drop-api-v1.yaml
Version: 1.0.0. Fields retain the provider's names; no shared registration edits.
"""
from __future__ import annotations
from datetime import datetime
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator

class RMBody(BaseModel):
    model_config = ConfigDict(extra="forbid")


class RMCreateOrderRequest(RMBody):
    orderReference: str | None = Field(None, max_length=40)
    isRecipientABusiness: bool | None = Field(None, description='Indicates if the recipient is a business or not. Mandatory for Business senders on orders shipping from Great Britain to Northern Ireland, which require additional information for B2B shipments. (Business senders are OBA accounts and OLP accounts declaring themselves as a Business sender).')
    recipient: RMRecipientDetailsRequest = Field(...)
    sender: RMSenderDetailsRequest | None = Field(None)
    billing: RMBillingDetailsRequest | None = Field(None)
    packages: list[RMShipmentPackageRequest] | None = Field(None, min_length=0)
    orderDate: datetime = Field(...)
    plannedDespatchDate: datetime | None = Field(None)
    specialInstructions: str | None = Field(None, max_length=500)
    subtotal: float = Field(..., ge=0, le=999999, description='The total value of all the goods in the order, excluding tax. This should not include retail shipping costs')
    shippingCostCharged: float = Field(..., ge=0, le=999999, description='The shipping costs you charged to your customer')
    otherCosts: float | None = Field(None, ge=0, le=999999)
    customsDutyCosts: float | None = Field(None, ge=0, le=99999.99, description='Customs Duty Costs is only supported in DDP (Delivery Duty Paid) services')
    total: float = Field(..., ge=0, le=999999, description='The sum of order subtotal, tax and retail shipping costs')
    currencyCode: str | None = Field(None, max_length=3)
    deliveryTerm: str | None = Field(None, max_length=20, description='Specifies how customs duties, taxes, and handling fees are paid for international shipments. Accepted values are  DDP, IOSS_DDP, DDU_DAP, IOSS_DDU, DTP, IOSS_DTP .   N.B. If no value is provided, the delivery term saved on your account is used, or DDU_DAP if none is saved.')
    customsDeclarationCategory: Literal['gift', 'commercialSample', 'documents', 'other', 'returnedGoods', 'commercialSaleOfGoods', 'eCommerceSaleOfGoods'] | None = Field(None, description='Customs Declaration Category for the whole order. When provided it is used instead of the product level categories.')
    postageDetails: RMPostageDetailsRequest | None = Field(None)
    tags: list[RMTagRequest] | None = Field(None)
    label: RMLabelGenerationRequest | None = Field(None)
    orderTax: float | None = Field(None, ge=0, le=999999, description='The total tax charged for the order')
    containsDangerousGoods: bool | None = Field(None, description='Indicates that the package contents contain a dangerous goods item')
    dangerousGoodsUnCode: str | None = Field(None, max_length=4, description='UN Code of the dangerous goods')
    dangerousGoodsDescription: float | None = Field(None, description='Description of the dangerous goods')
    dangerousGoodsQuantity: float | None = Field(None, description='Quantity or volume of the dangerous goods')
    importer: RMImporter | None = Field(None)

class RMRecipientDetailsRequest(RMBody):
    address: RMAddressRequest | None = Field(None)
    phoneNumber: str | None = Field(None, max_length=25)
    emailAddress: str | None = Field(None, max_length=254)
    addressBookReference: str | None = Field(None, max_length=100, description='The presence or not of  addressBookReference  and a valid  recipient address object  in the request body will determine which of the following behaviours occur:-  1) addressBookReference  provided  and a valid recipient address object  provided  - In addition to the provided recipient address fields being used for the order creation, an existing account Address Book Reference with matching addressBookReference will be overwritten with all provided recipient address fields, including phone and email. If no existing account Address Book Reference with matching addressBookReference can be found then a new one will be created with the provided addressBookReference and address fields, including phone and email. 2) addressBookReference  provided  and a valid recipient address object  not provided  - An account Address Book Reference with the provided addressBookReference will be used for the order if it exists. 3) addressBookReference  not provided  and a valid recipient address object  provided  - All provided recipient address fields, including phone and email, will be used for the order creation. 4) All other scenarios will result in a validation error.')

class RMAddressRequest(RMBody):
    fullName: str | None = Field(None, max_length=210)
    companyName: str | None = Field(None, max_length=100)
    addressLine1: str = Field(..., max_length=100)
    addressLine2: str | None = Field(None, max_length=100)
    addressLine3: str | None = Field(None, max_length=100)
    city: str = Field(..., max_length=100)
    county: str | None = Field(None, max_length=100)
    postcode: str | None = Field(None, max_length=20)
    countryCode: str = Field(..., max_length=3)

class RMSenderDetailsRequest(RMBody):
    tradingName: str | None = Field(None, max_length=250)
    phoneNumber: str | None = Field(None, max_length=25, description='Either phoneNumber or emailAddress is required for USA shipments.')
    emailAddress: str | None = Field(None, max_length=254, description='Either phoneNumber or emailAddress is required for USA shipments.')

class RMBillingDetailsRequest(RMBody):
    address: RMAddressRequest | None = Field(None)
    phoneNumber: str | None = Field(None, max_length=25)
    emailAddress: str | None = Field(None, max_length=254)

class RMShipmentPackageRequest(RMBody):
    weightInGrams: int = Field(..., ge=1, le=30000)
    packageFormatIdentifier: str = Field(..., description="If you have a ChannelShipper account, you can also pass the name of any of your custom package formats instead of the values below.   Enum: 'undefined', 'letter', 'largeLetter', 'smallParcel', 'mediumParcel', 'largeParcel', 'parcel', 'documents'")
    customPackageFormatIdentifier: str | None = Field(None, description="This field will be deprecated in the future. Please use 'packageFormatIdentifier' for custom package formats from ChannelShipper.")
    dimensions: RMDimensionsRequest | None = Field(None)
    contents: list[RMProductItemRequest] | None = Field(None, min_length=0)
    commercialInvoice: str | None = Field(None, description='Commercial invoice encoded as a base64 PDF string, under 2MB.')
    supportingDocuments: list[str] | None = Field(None, description='Optional supporting documents, each encoded as a base64 PDF string, under 2MB.')
    commercialInvoiceNumber: str | None = Field(None, max_length=35, description='Commercial invoice number for this package.')
    commercialInvoiceDate: datetime | None = Field(None, description="Date of the commercial invoice for this package. If a commercial invoice is provided without a date, the current date is used. The current date is also used if the minimum value '0001-01-01' is supplied.")

class RMDimensionsRequest(RMBody):
    heightInMms: int = Field(...)
    widthInMms: int = Field(...)
    depthInMms: int = Field(...)

class RMProductItemRequest(RMBody):
    name: str | None = Field(None, max_length=800)
    SKU: str | None = Field(None, max_length=100, description='The presence or not of field  SKU  and other fields in the request body will determine which of the following behaviours occur:-  1) A minimum of  SKU ,  unitValue ,  unitWeightInGrams  and  quantity  provided - In addition to the provided product fields being used for the order creation, an existing account Product with matching SKU will be overwritten with all provided product parameters. If no existing account Product with matching SKU can be found then a new product will be created with the provided SKU and product parameters. 2)  SKU ,  quantity  provided and  no other fields  provided - An account Product with the provided SKU will be used for the order if it exists. 3)  SKU not provided  and a minimum of  unitValue ,  unitWeightInGrams  and  quantity  provided - All provided product fields will be used for the order creation. 4) All other scenarios will result in a validation error. Required for EU shipments on items declared as eCommerceSaleOfGoods or commercialSaleOfGoods')
    ReferenceId: str | None = Field(None, max_length=50, description="The non-standardised manufacturer's product reference code for the item. This field will be deprecated in the future. Please use 'NonStandardisedManufacturerId' instead.")
    ContentsPieceURL: str | None = Field(None, max_length=250, description='A URL linking directly to the specific product page for the item being shipped. Must point to an individual product listing, not a general shop homepage or category page.')
    NonStandardisedManufacturerId: str | None = Field(None, max_length=50, description="The non-standardised manufacturer's product reference code for the item.  Required for EU shipments on items declared as eCommerceSaleOfGoods or commercialSaleOfGoods")
    StandardisedManufacturerId: str | None = Field(None, max_length=50, description="The standardised manufacturer's product reference code for the item (e.g. GTIN, EAN, UPC).  If NonStandardisedManufacturerId isn't provided, this value is also used as the NonStandardisedManufacturerId.")
    PgaReferenceNumber: str | None = Field(None, max_length=50, description='The PGA (Partner Government Agency) reference number for the item. Can only contain A-Z, 0-9, spaces, full stops, hyphens and forward slashes.  USA Shipments only')
    quantity: int = Field(..., ge=1, le=999999, description='The number of units in a given line')
    unitValue: float | None = Field(None, ge=0, le=999999, description='The price of a single unit excluding tax')
    unitWeightInGrams: int | None = Field(None, ge=0, le=999999)
    customsDescription: str | None = Field(None, max_length=255, description='A description of the goods in the item, used for customs.')
    extendedCustomsDescription: str | None = Field(None, max_length=300)
    customsCode: str | None = Field(None, max_length=10)
    originCountryCode: str | None = Field(None, max_length=3)
    customsDeclarationCategory: Literal['none', 'gift', 'commercialSample', 'documents', 'other', 'returnedGoods', 'commercialSaleOfGoods', 'eCommerceSaleOfGoods'] | None = Field(None)
    requiresExportLicence: bool | None = Field(None)
    stockLocation: str | None = Field(None, max_length=50)
    useOriginPreference: bool | None = Field(None)
    supplementaryUnits: str | None = Field(None, max_length=17)
    licenseNumber: str | None = Field(None, max_length=41)
    certificateNumber: str | None = Field(None, max_length=41)

class RMPostageDetailsRequest(RMBody):
    sendNotificationsTo: Literal['sender', 'recipient', 'billing'] | None = Field(None)
    serviceCode: str | None = Field(None, max_length=10)
    shippingAccountName: str | None = Field(None, max_length=50, description='The name of the shipping account to use for this order. Required if the account has more than one shipping account. Must match a shippingAccountName returned by GET /carriers.')
    serviceRegisterCode: str | None = Field(None, max_length=2)
    consequentialLoss: int | None = Field(None, ge=0, le=10000)
    receiveEmailNotification: bool | None = Field(None)
    receiveSmsNotification: bool | None = Field(None)
    guaranteedSaturdayDelivery: bool | None = Field(None, description='This field has been deprecated')
    requestSignatureUponDelivery: bool | None = Field(None)
    isLocalCollect: bool | None = Field(None)
    safePlace: str | None = Field(None, max_length=90)
    department: str | None = Field(None, max_length=150)
    AIRNumber: str | None = Field(None, max_length=50, description='For B2B orders shipping from Great Britain to Northern Ireland, this field can be used to provide the Recipient UKIMs number.')
    IOSSNumber: str | None = Field(None, max_length=50)
    requiresExportLicense: bool | None = Field(None)
    commercialInvoiceNumber: str | None = Field(None, max_length=35, description='This field has been deprecated. Use commercialInvoiceNumber at the package level instead.')
    commercialInvoiceDate: datetime | None = Field(None, description='This field has been deprecated. Use commercialInvoiceDate at the package level instead.')
    recipientEoriNumber: str | None = Field(None)

class RMTagRequest(RMBody):
    key: str | None = Field(None, max_length=100)
    value: str | None = Field(None, max_length=100)

class RMLabelGenerationRequest(RMBody):
    includeLabelInResponse: bool = Field(...)
    includeCN: bool | None = Field(None)
    includeReturnsLabel: bool | None = Field(None)

class RMImporter(RMBody):
    companyName: str | None = Field(None, max_length=100)
    addressLine1: str | None = Field(None, max_length=100)
    addressLine2: str | None = Field(None, max_length=100)
    addressLine3: str | None = Field(None, max_length=100)
    city: str | None = Field(None, max_length=100)
    postcode: str | None = Field(None, max_length=20)
    country: str | None = Field(None, max_length=100)
    businessName: str | None = Field(None, max_length=100)
    contactName: str | None = Field(None, max_length=100)
    phoneNumber: str | None = Field(None, max_length=25)
    emailAddress: str | None = Field(None, max_length=254)
    vatNumber: str | None = Field(None, max_length=15)
    eoriNumber: str | None = Field(None, max_length=18)
    isABusiness: bool | None = Field(None)

class RMUpdateOrderStatusRequest(RMBody):
    orderIdentifier: int | None = Field(None)
    orderReference: str | None = Field(None)
    status: Literal['new', 'despatchedByOtherCourier', 'despatched'] | None = Field(None, description='" despatchedByOtherCourier  ":  Reserved for ChannelShipper customers only - please visit\n ChannelShipper.com  for more information \n\n" new  ": This will remove the order from its batch. Order information will not be lost during this process.\n\nPlease be aware labels generated on orders which are then set to "new" (reset) are no longer valid\nand must be destroyed. If the order is required to be despatched after setting to "new" status, a new\nlabel must be generated to attach to the item.\n\nCancelled label information is automatically shared with Royal Mail Revenue Protection, and should a\ncancelled label be identified on an item in the Royal Mail Network, you will be charged on your account\nand an additional handling fee applied.')
    trackingNumber: str | None = Field(None)
    despatchDate: datetime | None = Field(None)
    shippingCarrier: str | None = Field(None)
    shippingService: str | None = Field(None)

class RMCreateReturnRequest(RMBody):
    service: RMServiceCode = Field(...)
    shipment: RMShipment = Field(...)

class RMServiceCode(RMBody):
    serviceCode: str = Field(..., description='Return service code. Obtain available values from GET /returns/services.')
    serviceRegisterCode: str | None = Field(None)

class RMShipment(RMBody):
    shippingAddress: RMAddress = Field(...)
    returnAddress: RMAddress = Field(...)
    customerReference: RMCustomerReference | None = Field(None)

class RMAddress(RMBody):
    title: str | None = Field(None, max_length=25)
    firstName: str = Field(..., max_length=150)
    lastName: str = Field(..., max_length=150)
    companyName: str | None = Field(None, max_length=250)
    addressLine1: str = Field(..., max_length=250)
    addressLine2: str | None = Field(None, max_length=250)
    addressLine3: str | None = Field(None, max_length=250)
    city: str = Field(..., max_length=100)
    county: str | None = Field(None, max_length=250)
    postcode: str = Field(..., max_length=25)
    country: str = Field(..., max_length=50)
    countryIsoCode: str = Field(..., max_length=3, description='ISO 3166-1 alpha-3 country code (e.g. GBR, USA)')

class RMCustomerReference(RMBody):
    reference: str = Field(..., max_length=50)

# Resolve references after all provider request types have been declared.
for _model in tuple(globals().values()):
    if isinstance(_model, type) and issubclass(_model, RMBody):
        _model.model_rebuild()
