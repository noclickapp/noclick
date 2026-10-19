"""Responses of the phone-number purchase events. A separate module so the
engine's handler can import them in every edition; ``wss.sender.responses``
re-exports them for type generation."""

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class PhoneNumberCoverageResponse(BaseModel):
    """Response for phone_number:coverage"""
    countries: List[Dict[str, Any]] = Field(
        default_factory=list,
        description=("Countries numbers are for sale in: country (ISO alpha-2), number_types (in stock), "
                     "texting_types, documents_types (the kinds bought with documents, which the carrier reviews) "
                     "and steps_types (the kinds that ask a step that can't be taken here, so aren't sold here yet)"),
    )
    contact_phone: Optional[str] = Field(
        None, description="The account's own verified phone (E.164), offered as a holder's contact phone",
    )


class PhoneNumberPlacesResponse(BaseModel):
    """Response for phone_number:places"""
    places: List[Dict[str, Any]] = Field(
        default_factory=list,
        description="Where numbers are for sale: kind (locality | area_code), value, region",
    )


class PhoneNumberSearchResponse(BaseModel):
    """Response for phone_number:search"""
    numbers: List[Dict[str, Any]] = Field(
        default_factory=list,
        description=(
            "Available numbers: phone_number, country, number_type, locality, region, capabilities, "
            "monthly_credits and upfront_credits (its price for the account), requirements "
            "({needs: none | address | documents | steps, items: [{id, kind, name, description, example, values}]}) "
            "and texting (registration | unavailable | none)"
        ),
    )
    monthly_credits: Optional[float] = Field(
        None, description="What every number listed costs a month, in credits, where they all cost the same",
    )


class PhoneNumberBuyResponse(BaseModel):
    """Response for phone_number:buy: the number, or its order while the carrier reviews what was filed"""
    credential_id: Optional[str] = Field(None, description="The phone_number credential that now holds the number")
    phone_number: str = Field(..., description="The number, E.164")
    order_id: Optional[str] = Field(None, description="Its order, while the carrier reviews it (nothing charged yet)")
    status: Optional[str] = Field(None, description="in_review while the carrier reviews the order")


ORDER = ("A number order the carrier reviews: id, phone_number, country, number_type, status (in_review | rejected "
         "| completed | failed), reason (the carrier's words when it sent the order back or ended it), deadline, "
         "monthly_credits, upfront_credits, credential_id once completed, created_at, updated_at, and while it's "
         "open the requirements a resubmission answers")


class PhoneNumberDocumentsResponse(BaseModel):
    """Response for phone_number:documents"""
    documents: List[Dict[str, Any]] = Field(
        default_factory=list,
        description="The account's documents: id, requirement_id, requirement_name, filename, uploaded_at",
    )


class PhoneNumberDocumentUploadResponse(BaseModel):
    """Response for phone_number:document_upload"""
    upload_url_path: str = Field(..., description=(
        "Where to POST the file's bytes, on the backend's origin, with &filename=<its name>; good for 15 minutes"))


class PhoneNumberDocumentRemoveResponse(BaseModel):
    """Response for phone_number:document_remove"""
    id: str
    removed: bool
    kept_by_carrier: bool = Field(..., description="The carrier keeps it on file for a number it was filed for")


class PhoneNumberOrdersResponse(BaseModel):
    """Response for phone_number:orders"""
    orders: List[Dict[str, Any]] = Field(default_factory=list, description=ORDER)


class PhoneNumberResubmitResponse(BaseModel):
    """Response for phone_number:resubmit"""
    order: Dict[str, Any] = Field(..., description=ORDER)
