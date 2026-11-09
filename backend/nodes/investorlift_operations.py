"""Typed request shapes for InvestorLift Data Services API 1.0.0.

Source: https://docs.investorliftdata.com/openapi.json
One operation is one API request. Metered pages are never fetched implicitly.
"""
from __future__ import annotations
from datetime import date
from typing import Annotated, Literal, Union
from pydantic import BaseModel, ConfigDict, Field, model_validator


class Input(BaseModel):
    model_config = ConfigDict(
        extra="forbid", hide_input_in_errors=True, populate_by_name=True
    )


class PredictConfigOverrides(Input):
    square_feet: float | None = Field(
        None,
        gt=0,
        strict=True,
        allow_inf_nan=False,
        description="Finished living area, in **square feet**. Must be above zero.",
    )
    bedrooms: float | None = Field(
        None,
        ge=0,
        strict=True,
        allow_inf_nan=False,
        description="Bedroom count. Zero or above; `0` is accepted, because a studio genuinely has none.",
    )
    bathrooms: float | None = Field(
        None,
        ge=0,
        strict=True,
        allow_inf_nan=False,
        description="Bathroom count, as the property data service counts them. Zero or above, and **may be fractional** — `2.5` is ordinary. It does not include `partial_bathrooms`, which stays at the county's figure and is not overridable; this service does not add the two together.",
    )
    year_built: float | None = Field(
        None,
        gt=0,
        strict=True,
        allow_inf_nan=False,
        description="Year the structure was built. Must be above zero.",
    )
    lot_size_square_feet: float | None = Field(
        None,
        gt=0,
        strict=True,
        allow_inf_nan=False,
        description="Lot size, in **square feet** — never acres. Must be above zero. This is one of the facts the valuation requires, so supplying it can make a property scorable that the county record alone could not score.",
    )
    property_type: str | None = Field(
        None,
        max_length=4096,
        description="Property type, as free text. Must not be blank or only spaces; surrounding spaces are trimmed, exactly as the county record's own value is, so the trimmed value is what appears in `subject_property.facts`. This is one of the facts the valuation requires, so supplying it can make a property scorable that the county record alone could not score.",
    )

    @model_validator(mode="after")
    def usable_overrides(self):
        if not self.model_fields_set or any(
            getattr(self, k) is None for k in self.model_fields_set
        ):
            raise ValueError("Supply at least one non-null property fact")
        if self.property_type is not None and not self.property_type.strip():
            raise ValueError("Property type must not be blank")
        return self


class PredictConfig(Input):
    "Score a property address"

    operation: Literal["predict"] = Field(
        "predict", json_schema_extra={"ui:hidden": True}
    )
    address: str | None = Field(
        None,
        max_length=4096,
        description="The full street address of the property to score.",
    )
    condition: Literal[
        "turn_key", "light_rehab", "major_rehab", "full_gut", "tear_down"
    ] | None = Field(
        None,
        max_length=4096,
        description="The property's condition, which sets the repair budget the derived numbers are built on. Optional: omit it and the property is priced as though it needs no repairs, which is exactly what `turn_key` does. It is a request option rather than a second property, so sending it never changes what the call costs.",
    )
    rehab_budget: int | None = Field(
        None,
        ge=0,
        le=10000000,
        strict=True,
        description="Your own repair budget for this property, in **whole dollars**. Optional, and additive: an integration that does not send it is unaffected.",
    )
    target_margin: float | None = Field(
        None,
        ge=0.01,
        le=0.9,
        gt=0,
        lt=1,
        strict=True,
        allow_inf_nan=False,
        description="The profit margin your buyer needs, as a **fraction** of the repaired value — `0.2` means twenty percent. Optional, and additive: an integration that does not send it is unaffected, and is priced at the default of `0.2`.",
    )
    overrides: PredictConfigOverrides | None = Field(
        None,
        description="Price the property **as you describe it**, not as the county record has it. Optional, and additive: an integration that does not send it is unaffected and its answers do not move.",
    )
    property_id: str | None = Field(
        None,
        pattern="^[0-9a-f]{32}$",
        max_length=4096,
        description="A property identifier taken from a Scored Call answer — the subject's own, or any comparable property's. 32 lowercase hexadecimal characters. On this arm **no address matching is performed**: the record is looked up directly, and `subject_property` reads back exactly which record answered. Identifiers are looked up in the same identifier space the Scored Call publishes them in.",
    )
    partial_answer: bool | None = Field(
        None,
        strict=True,
        description="Opt in to a charged description when the model cannot price the identified property. Absent or false retains the existing refund behavior.",
    )
    confirmation: str | None = Field(
        None,
        min_length=1,
        max_length=256,
        description="Optional. The confirmation value an assistant received when a question would cost more than the ask-first limit; send it back unchanged with the same request to run it. Ignored on calls made with an API key.",
    )
    idempotency_key: str | None = Field(None, max_length=4096)

    @model_validator(mode="after")
    def one_property(self):
        if (self.address is not None) == (self.property_id is not None):
            raise ValueError("Supply exactly one address or property ID")
        if self.address is not None and not self.address.strip():
            raise ValueError("Supply a nonempty street address")
        return self


class PredictBatchConfigPropertiesItemOverrides(Input):
    square_feet: float | None = Field(
        None,
        gt=0,
        strict=True,
        allow_inf_nan=False,
        description="Finished living area, in **square feet**. Must be above zero.",
    )
    bedrooms: float | None = Field(
        None,
        ge=0,
        strict=True,
        allow_inf_nan=False,
        description="Bedroom count. Zero or above; `0` is accepted, because a studio genuinely has none.",
    )
    bathrooms: float | None = Field(
        None,
        ge=0,
        strict=True,
        allow_inf_nan=False,
        description="Bathroom count, as the property data service counts them. Zero or above, and **may be fractional** — `2.5` is ordinary. It does not include `partial_bathrooms`, which stays at the county's figure and is not overridable; this service does not add the two together.",
    )
    year_built: float | None = Field(
        None,
        gt=0,
        strict=True,
        allow_inf_nan=False,
        description="Year the structure was built. Must be above zero.",
    )
    lot_size_square_feet: float | None = Field(
        None,
        gt=0,
        strict=True,
        allow_inf_nan=False,
        description="Lot size, in **square feet** — never acres. Must be above zero. This is one of the facts the valuation requires, so supplying it can make a property scorable that the county record alone could not score.",
    )
    property_type: str | None = Field(
        None,
        max_length=4096,
        description="Property type, as free text. Must not be blank or only spaces; surrounding spaces are trimmed, exactly as the county record's own value is, so the trimmed value is what appears in `subject_property.facts`. This is one of the facts the valuation requires, so supplying it can make a property scorable that the county record alone could not score.",
    )

    @model_validator(mode="after")
    def usable_overrides(self):
        if not self.model_fields_set or any(
            getattr(self, k) is None for k in self.model_fields_set
        ):
            raise ValueError("Supply at least one non-null property fact")
        if self.property_type is not None and not self.property_type.strip():
            raise ValueError("Property type must not be blank")
        return self


class PredictBatchConfigPropertiesItem(Input):
    address: str = Field(
        ...,
        max_length=4096,
        description="The full street address of the property to score.",
    )
    condition: Literal[
        "turn_key", "light_rehab", "major_rehab", "full_gut", "tear_down"
    ] | None = Field(
        None,
        max_length=4096,
        description="The property's condition, which sets the repair budget the derived numbers are built on. Optional: omit it and the property is priced as though it needs no repairs, which is exactly what `turn_key` does. It is a request option rather than a second property, so sending it never changes what the call costs.",
    )
    rehab_budget: int | None = Field(
        None,
        ge=0,
        le=10000000,
        strict=True,
        description="Your own repair budget for this property, in **whole dollars**. Optional, and additive: an integration that does not send it is unaffected.",
    )
    target_margin: float | None = Field(
        None,
        ge=0.01,
        le=0.9,
        gt=0,
        lt=1,
        strict=True,
        allow_inf_nan=False,
        description="The profit margin your buyer needs, as a **fraction** of the repaired value — `0.2` means twenty percent. Optional, and additive: an integration that does not send it is unaffected, and is priced at the default of `0.2`.",
    )
    overrides: PredictBatchConfigPropertiesItemOverrides | None = Field(
        None,
        description="Price the property **as you describe it**, not as the county record has it. Optional, and additive: an integration that does not send it is unaffected and its answers do not move.",
    )


class PredictBatchConfig(Input):
    "Score a batch of property addresses"

    operation: Literal["predict_batch"] = Field(
        "predict_batch", json_schema_extra={"ui:hidden": True}
    )
    properties: list[PredictBatchConfigPropertiesItem] = Field(
        ...,
        min_length=1,
        max_length=10,
        description="The properties to score, each the same shape `POST /v1/predict` accepts. Order is preserved: the response's `results` array answers these properties in this order. Duplicate addresses are allowed and each is charged — two identical entries are two work items.",
    )
    confirmation: str | None = Field(
        None,
        min_length=1,
        max_length=256,
        description="Optional. The confirmation value an assistant received when a question would cost more than the ask-first limit; send it back unchanged with the same request to run it. Ignored on calls made with an API key.",
    )
    idempotency_key: str | None = Field(None, max_length=4096)


class GetHistoryConfig(Input):
    "Read a property’s recorded transaction history"

    operation: Literal["get_history"] = Field(
        "get_history", json_schema_extra={"ui:hidden": True}
    )
    address: str | None = Field(
        None,
        min_length=1,
        max_length=4096,
        description="The full street address of the property whose history you want.",
    )
    property_id: str | None = Field(
        None,
        pattern="^[0-9a-f]{32}$",
        max_length=4096,
        description="A property identifier taken from a Scored Call answer — the subject's own, or any comparable property's. 32 lowercase hexadecimal characters. On this arm **no address matching is performed**: the record is looked up directly, and `subject_property` reads back exactly which record answered. Identifiers are looked up in the same identifier space the Scored Call publishes them in.",
    )
    confirmation: str | None = Field(
        None,
        min_length=1,
        max_length=256,
        description="Optional. The confirmation value an assistant received when a question would cost more than the ask-first limit; send it back unchanged with the same request to run it. Ignored on calls made with an API key.",
    )
    idempotency_key: str | None = Field(None, max_length=4096)

    @model_validator(mode="after")
    def one_property(self):
        if (self.address is not None) == (self.property_id is not None):
            raise ValueError("Supply exactly one address or property ID")
        if self.address is not None and not self.address.strip():
            raise ValueError("Supply a nonempty street address")
        return self


class ValidateRequestConfigOverrides(Input):
    square_feet: float | None = Field(
        None,
        gt=0,
        strict=True,
        allow_inf_nan=False,
        description="Finished living area, in **square feet**. Must be above zero.",
    )
    bedrooms: float | None = Field(
        None,
        ge=0,
        strict=True,
        allow_inf_nan=False,
        description="Bedroom count. Zero or above; `0` is accepted, because a studio genuinely has none.",
    )
    bathrooms: float | None = Field(
        None,
        ge=0,
        strict=True,
        allow_inf_nan=False,
        description="Bathroom count, as the property data service counts them. Zero or above, and **may be fractional** — `2.5` is ordinary. It does not include `partial_bathrooms`, which stays at the county's figure and is not overridable; this service does not add the two together.",
    )
    year_built: float | None = Field(
        None,
        gt=0,
        strict=True,
        allow_inf_nan=False,
        description="Year the structure was built. Must be above zero.",
    )
    lot_size_square_feet: float | None = Field(
        None,
        gt=0,
        strict=True,
        allow_inf_nan=False,
        description="Lot size, in **square feet** — never acres. Must be above zero. This is one of the facts the valuation requires, so supplying it can make a property scorable that the county record alone could not score.",
    )
    property_type: str | None = Field(
        None,
        max_length=4096,
        description="Property type, as free text. Must not be blank or only spaces; surrounding spaces are trimmed, exactly as the county record's own value is, so the trimmed value is what appears in `subject_property.facts`. This is one of the facts the valuation requires, so supplying it can make a property scorable that the county record alone could not score.",
    )

    @model_validator(mode="after")
    def usable_overrides(self):
        if not self.model_fields_set or any(
            getattr(self, k) is None for k in self.model_fields_set
        ):
            raise ValueError("Supply at least one non-null property fact")
        if self.property_type is not None and not self.property_type.strip():
            raise ValueError("Property type must not be blank")
        return self


class ValidateRequestConfig(Input):
    "Check a request without spending"

    operation: Literal["validate_request"] = Field(
        "validate_request", json_schema_extra={"ui:hidden": True}
    )
    address: str | None = Field(
        None,
        max_length=4096,
        description="The full street address of the property to score.",
    )
    condition: Literal[
        "turn_key", "light_rehab", "major_rehab", "full_gut", "tear_down"
    ] | None = Field(
        None,
        max_length=4096,
        description="The property's condition, which sets the repair budget the derived numbers are built on. Optional: omit it and the property is priced as though it needs no repairs, which is exactly what `turn_key` does. It is a request option rather than a second property, so sending it never changes what the call costs.",
    )
    rehab_budget: int | None = Field(
        None,
        ge=0,
        le=10000000,
        strict=True,
        description="Your own repair budget for this property, in **whole dollars**. Optional, and additive: an integration that does not send it is unaffected.",
    )
    target_margin: float | None = Field(
        None,
        ge=0.01,
        le=0.9,
        gt=0,
        lt=1,
        strict=True,
        allow_inf_nan=False,
        description="The profit margin your buyer needs, as a **fraction** of the repaired value — `0.2` means twenty percent. Optional, and additive: an integration that does not send it is unaffected, and is priced at the default of `0.2`.",
    )
    overrides: ValidateRequestConfigOverrides | None = Field(
        None,
        description="Price the property **as you describe it**, not as the county record has it. Optional, and additive: an integration that does not send it is unaffected and its answers do not move.",
    )
    property_id: str | None = Field(
        None,
        pattern="^[0-9a-f]{32}$",
        max_length=4096,
        description="A property identifier taken from a Scored Call answer — the subject's own, or any comparable property's. 32 lowercase hexadecimal characters. On this arm **no address matching is performed**: the record is looked up directly, and `subject_property` reads back exactly which record answered. Identifiers are looked up in the same identifier space the Scored Call publishes them in.",
    )
    partial_answer: bool | None = Field(
        None,
        strict=True,
        description="Opt in to a charged description when the model cannot price the identified property. Absent or false retains the existing refund behavior.",
    )
    confirmation: str | None = Field(
        None,
        min_length=1,
        max_length=256,
        description="Optional. The confirmation value an assistant received when a question would cost more than the ask-first limit; send it back unchanged with the same request to run it. Ignored on calls made with an API key.",
    )

    @model_validator(mode="after")
    def one_property(self):
        if (self.address is not None) == (self.property_id is not None):
            raise ValueError("Supply exactly one address or property ID")
        if self.address is not None and not self.address.strip():
            raise ValueError("Supply a nonempty street address")
        return self


class ResolvePropertyConfig(Input):
    "Find a property by address"

    operation: Literal["resolve_property"] = Field(
        "resolve_property", json_schema_extra={"ui:hidden": True}
    )
    address: str = Field(..., max_length=4096)
    zip: str = Field(..., pattern="^[0-9]{5}$", max_length=4096)
    idempotency_key: str | None = Field(None, max_length=4096)
    customer_reference: str | None = Field(
        None, pattern="^[A-Za-z0-9._:-]{1,64}$", max_length=4096
    )


class GetPropertyConfig(Input):
    "Read a property’s record"

    operation: Literal["get_property"] = Field(
        "get_property", json_schema_extra={"ui:hidden": True}
    )
    property_id: str = Field(..., pattern="^[0-9a-f]{32}$", max_length=4096)
    idempotency_key: str | None = Field(None, max_length=4096)
    customer_reference: str | None = Field(
        None, pattern="^[A-Za-z0-9._:-]{1,64}$", max_length=4096
    )


class GetPropertyHistoryConfig(Input):
    "Read a property’s ownership history"

    operation: Literal["get_property_history"] = Field(
        "get_property_history", json_schema_extra={"ui:hidden": True}
    )
    property_id: str = Field(..., pattern="^[0-9a-f]{32}$", max_length=4096)
    idempotency_key: str | None = Field(None, max_length=4096)
    customer_reference: str | None = Field(
        None, pattern="^[A-Za-z0-9._:-]{1,64}$", max_length=4096
    )


class GetListingHistoryConfig(Input):
    "Read a property’s listing history"

    operation: Literal["get_listing_history"] = Field(
        "get_listing_history", json_schema_extra={"ui:hidden": True}
    )
    property_id: str = Field(..., pattern="^[0-9a-f]{32}$", max_length=4096)
    idempotency_key: str | None = Field(None, max_length=4096)
    customer_reference: str | None = Field(
        None, pattern="^[A-Za-z0-9._:-]{1,64}$", max_length=4096
    )


class ListListingsConfig(Input):
    "List properties for sale near a place"

    operation: Literal["list_listings"] = Field(
        "list_listings", json_schema_extra={"ui:hidden": True}
    )
    lat: float | None = Field(None, ge=-90, le=90, strict=True, allow_inf_nan=False)
    lng: float | None = Field(None, ge=-180, le=180, strict=True, allow_inf_nan=False)
    radius_miles: float | None = Field(None, le=20, strict=True, allow_inf_nan=False)
    address: str | None = Field(None, max_length=4096)
    zip: list[
        Annotated[str, Field(pattern="^[0-9]{5}$", max_length=4096)]
    ] | None = Field(None, max_length=60)
    bbox: str | None = Field(None, max_length=4096)
    on_market: bool | None = Field(None, strict=True)
    is_rental: bool | None = Field(None, strict=True)
    sort: str | None = Field(None, max_length=4096)
    limit: int | None = Field(None, ge=1, le=500, strict=True)
    cursor: str | None = Field(None, max_length=4096)
    idempotency_key: str | None = Field(None, max_length=4096)
    customer_reference: str | None = Field(
        None, pattern="^[A-Za-z0-9._:-]{1,64}$", max_length=4096
    )

    @model_validator(mode="after")
    def one_place(self):
        point = self.lat is not None or self.lng is not None
        if point and (self.lat is None or self.lng is None):
            raise ValueError("Send both latitude and longitude")
        if self.radius_miles is not None and not point:
            raise ValueError("Radius requires latitude and longitude")
        if (
            sum(
                [
                    point,
                    self.address is not None,
                    self.zip is not None and self.address is None,
                    self.bbox is not None,
                ]
            )
            != 1
        ):
            raise ValueError(
                "Send exactly one place: point, address with ZIP, ZIP list, or box"
            )
        if self.address is not None and (not self.zip or len(self.zip) != 1):
            raise ValueError("An address requires one ZIP code")
        return self


class GetListingConfig(Input):
    "Read one listing in full"

    operation: Literal["get_listing"] = Field(
        "get_listing", json_schema_extra={"ui:hidden": True}
    )
    listing_id: str = Field(..., pattern="^[0-9a-f]{32}$", max_length=4096)
    idempotency_key: str | None = Field(None, max_length=4096)
    customer_reference: str | None = Field(
        None, pattern="^[A-Za-z0-9._:-]{1,64}$", max_length=4096
    )


class ListRentalListingsConfig(Input):
    "List rentals near a place"

    operation: Literal["list_rental_listings"] = Field(
        "list_rental_listings", json_schema_extra={"ui:hidden": True}
    )
    lat: float | None = Field(None, ge=-90, le=90, strict=True, allow_inf_nan=False)
    lng: float | None = Field(None, ge=-180, le=180, strict=True, allow_inf_nan=False)
    radius_miles: float | None = Field(None, le=20, strict=True, allow_inf_nan=False)
    address: str | None = Field(None, max_length=4096)
    zip: list[
        Annotated[str, Field(pattern="^[0-9]{5}$", max_length=4096)]
    ] | None = Field(None, max_length=60)
    bbox: str | None = Field(None, max_length=4096)
    sort: str | None = Field(None, max_length=4096)
    limit: int | None = Field(None, ge=1, le=500, strict=True)
    cursor: str | None = Field(None, max_length=4096)
    idempotency_key: str | None = Field(None, max_length=4096)
    customer_reference: str | None = Field(
        None, pattern="^[A-Za-z0-9._:-]{1,64}$", max_length=4096
    )

    @model_validator(mode="after")
    def one_place(self):
        point = self.lat is not None or self.lng is not None
        if point and (self.lat is None or self.lng is None):
            raise ValueError("Send both latitude and longitude")
        if self.radius_miles is not None and not point:
            raise ValueError("Radius requires latitude and longitude")
        if (
            sum(
                [
                    point,
                    self.address is not None,
                    self.zip is not None and self.address is None,
                    self.bbox is not None,
                ]
            )
            != 1
        ):
            raise ValueError(
                "Send exactly one place: point, address with ZIP, ZIP list, or box"
            )
        if self.address is not None and (not self.zip or len(self.zip) != 1):
            raise ValueError("An address requires one ZIP code")
        return self


class ListSoldListingsConfig(Input):
    "List recent sales near a place"

    operation: Literal["list_sold_listings"] = Field(
        "list_sold_listings", json_schema_extra={"ui:hidden": True}
    )
    lat: float | None = Field(None, ge=-90, le=90, strict=True, allow_inf_nan=False)
    lng: float | None = Field(None, ge=-180, le=180, strict=True, allow_inf_nan=False)
    radius_miles: float | None = Field(None, le=20, strict=True, allow_inf_nan=False)
    address: str | None = Field(None, max_length=4096)
    zip: list[
        Annotated[str, Field(pattern="^[0-9]{5}$", max_length=4096)]
    ] | None = Field(None, max_length=60)
    bbox: str | None = Field(None, max_length=4096)
    from_date: date | None = Field(None, alias="from")
    to: date | None = Field(None)
    sort: str | None = Field(None, max_length=4096)
    limit: int | None = Field(None, ge=1, le=500, strict=True)
    cursor: str | None = Field(None, max_length=4096)
    idempotency_key: str | None = Field(None, max_length=4096)
    customer_reference: str | None = Field(
        None, pattern="^[A-Za-z0-9._:-]{1,64}$", max_length=4096
    )

    @model_validator(mode="after")
    def one_place(self):
        point = self.lat is not None or self.lng is not None
        if point and (self.lat is None or self.lng is None):
            raise ValueError("Send both latitude and longitude")
        if self.radius_miles is not None and not point:
            raise ValueError("Radius requires latitude and longitude")
        if (
            sum(
                [
                    point,
                    self.address is not None,
                    self.zip is not None and self.address is None,
                    self.bbox is not None,
                ]
            )
            != 1
        ):
            raise ValueError(
                "Send exactly one place: point, address with ZIP, ZIP list, or box"
            )
        if self.address is not None and (not self.zip or len(self.zip) != 1):
            raise ValueError("An address requires one ZIP code")
        return self


class ListInvestorPurchasesConfig(Input):
    "List investor purchases near a place"

    operation: Literal["list_investor_purchases"] = Field(
        "list_investor_purchases", json_schema_extra={"ui:hidden": True}
    )
    lat: float | None = Field(None, ge=-90, le=90, strict=True, allow_inf_nan=False)
    lng: float | None = Field(None, ge=-180, le=180, strict=True, allow_inf_nan=False)
    radius_miles: float | None = Field(None, strict=True, allow_inf_nan=False)
    bbox: str | None = Field(None, max_length=4096)
    zip: list[
        Annotated[str, Field(pattern="^[0-9]{5}$", max_length=4096)]
    ] | None = Field(None)
    idempotency_key: str | None = Field(None, max_length=4096)
    customer_reference: str | None = Field(
        None, pattern="^[A-Za-z0-9._:-]{1,64}$", max_length=4096
    )


class GetInvestorPurchaseConfig(Input):
    "Read one investor purchase"

    operation: Literal["get_investor_purchase"] = Field(
        "get_investor_purchase", json_schema_extra={"ui:hidden": True}
    )
    purchase_id: str = Field(..., pattern="^[0-9a-f]{32}$", max_length=4096)
    idempotency_key: str | None = Field(None, max_length=4096)
    customer_reference: str | None = Field(
        None, pattern="^[A-Za-z0-9._:-]{1,64}$", max_length=4096
    )


class ListActiveInvestorsConfig(Input):
    "List the investors buying in ZIP codes"

    operation: Literal["list_active_investors"] = Field(
        "list_active_investors", json_schema_extra={"ui:hidden": True}
    )
    zip: list[Annotated[str, Field(pattern="^[0-9]{5}$", max_length=4096)]] = Field(...)
    idempotency_key: str | None = Field(None, max_length=4096)
    customer_reference: str | None = Field(
        None, pattern="^[A-Za-z0-9._:-]{1,64}$", max_length=4096
    )


class MatchInvestorsConfig(Input):
    "Rank the investors who buy homes like this one"

    operation: Literal["match_investors"] = Field(
        "match_investors", json_schema_extra={"ui:hidden": True}
    )
    property_id: str = Field(..., pattern="^[0-9a-f]{32}$", max_length=4096)
    idempotency_key: str | None = Field(None, max_length=4096)
    customer_reference: str | None = Field(
        None, pattern="^[A-Za-z0-9._:-]{1,64}$", max_length=4096
    )


class SearchInvestorsConfig(Input):
    "Find an investor company by name"

    operation: Literal["search_investors"] = Field(
        "search_investors", json_schema_extra={"ui:hidden": True}
    )
    q: str = Field(..., max_length=4096)


class GetInvestorCompanyConfig(Input):
    "Read an investor company’s profile"

    operation: Literal["get_investor_company"] = Field(
        "get_investor_company", json_schema_extra={"ui:hidden": True}
    )
    company_id: str = Field(..., max_length=4096)
    idempotency_key: str | None = Field(None, max_length=4096)
    customer_reference: str | None = Field(
        None, pattern="^[A-Za-z0-9._:-]{1,64}$", max_length=4096
    )


class ListCompanyPurchasesConfig(Input):
    "List an investor company’s purchases"

    operation: Literal["list_company_purchases"] = Field(
        "list_company_purchases", json_schema_extra={"ui:hidden": True}
    )
    company_id: str = Field(..., max_length=4096)
    idempotency_key: str | None = Field(None, max_length=4096)
    customer_reference: str | None = Field(
        None, pattern="^[A-Za-z0-9._:-]{1,64}$", max_length=4096
    )


class ListCompanySalesConfig(Input):
    "List an investor company’s sales"

    operation: Literal["list_company_sales"] = Field(
        "list_company_sales", json_schema_extra={"ui:hidden": True}
    )
    company_id: str = Field(..., max_length=4096)
    idempotency_key: str | None = Field(None, max_length=4096)
    customer_reference: str | None = Field(
        None, pattern="^[A-Za-z0-9._:-]{1,64}$", max_length=4096
    )


class ListLendersConfig(Input):
    "List the lenders active in a place"

    operation: Literal["list_lenders"] = Field(
        "list_lenders", json_schema_extra={"ui:hidden": True}
    )
    state: str = Field(..., max_length=4096)
    county: str | None = Field(None, max_length=4096)
    zip: list[
        Annotated[str, Field(pattern="^[0-9]{5}$", max_length=4096)]
    ] | None = Field(None)
    idempotency_key: str | None = Field(None, max_length=4096)
    customer_reference: str | None = Field(
        None, pattern="^[A-Za-z0-9._:-]{1,64}$", max_length=4096
    )


class GetLenderConfig(Input):
    "Read a lender’s profile"

    operation: Literal["get_lender"] = Field(
        "get_lender", json_schema_extra={"ui:hidden": True}
    )
    lender_id: str = Field(..., max_length=4096)
    idempotency_key: str | None = Field(None, max_length=4096)
    customer_reference: str | None = Field(
        None, pattern="^[A-Za-z0-9._:-]{1,64}$", max_length=4096
    )


class ListLenderLoansConfig(Input):
    "List a lender’s loans"

    operation: Literal["list_lender_loans"] = Field(
        "list_lender_loans", json_schema_extra={"ui:hidden": True}
    )
    lender_id: str = Field(..., max_length=4096)
    idempotency_key: str | None = Field(None, max_length=4096)
    customer_reference: str | None = Field(
        None, pattern="^[A-Za-z0-9._:-]{1,64}$", max_length=4096
    )


class ListLenderBorrowersConfig(Input):
    "List who a lender lends to"

    operation: Literal["list_lender_borrowers"] = Field(
        "list_lender_borrowers", json_schema_extra={"ui:hidden": True}
    )
    lender_id: str = Field(..., max_length=4096)
    idempotency_key: str | None = Field(None, max_length=4096)
    customer_reference: str | None = Field(
        None, pattern="^[A-Za-z0-9._:-]{1,64}$", max_length=4096
    )


class GetCoverageConfig(Input):
    "See where the data service has data"

    operation: Literal["get_coverage"] = Field(
        "get_coverage", json_schema_extra={"ui:hidden": True}
    )


InvestorLiftConfig = Annotated[
    Union[
        PredictConfig,
        PredictBatchConfig,
        GetHistoryConfig,
        ValidateRequestConfig,
        ResolvePropertyConfig,
        GetPropertyConfig,
        GetPropertyHistoryConfig,
        GetListingHistoryConfig,
        ListListingsConfig,
        GetListingConfig,
        ListRentalListingsConfig,
        ListSoldListingsConfig,
        ListInvestorPurchasesConfig,
        GetInvestorPurchaseConfig,
        ListActiveInvestorsConfig,
        MatchInvestorsConfig,
        SearchInvestorsConfig,
        GetInvestorCompanyConfig,
        ListCompanyPurchasesConfig,
        ListCompanySalesConfig,
        ListLendersConfig,
        GetLenderConfig,
        ListLenderLoansConfig,
        ListLenderBorrowersConfig,
        GetCoverageConfig,
    ],
    Field(discriminator="operation"),
]

ROUTES = {
    "predict": ("POST", "/v1/predict", []),
    "predict_batch": ("POST", "/v1/predict/batch", []),
    "get_history": ("POST", "/v1/history", []),
    "validate_request": ("POST", "/v1/validate", []),
    "resolve_property": ("GET", "/v1/data/properties/resolve", ["address", "zip"]),
    "get_property": ("GET", "/v1/data/properties/{property_id}", ["property_id"]),
    "get_property_history": (
        "GET",
        "/v1/data/properties/{property_id}/history",
        ["property_id"],
    ),
    "get_listing_history": (
        "GET",
        "/v1/data/properties/{property_id}/listing-history",
        ["property_id"],
    ),
    "list_listings": (
        "GET",
        "/v1/data/listings",
        [
            "lat",
            "lng",
            "radius_miles",
            "address",
            "zip",
            "bbox",
            "on_market",
            "is_rental",
            "sort",
            "limit",
            "cursor",
        ],
    ),
    "get_listing": ("GET", "/v1/data/listings/{listing_id}", ["listing_id"]),
    "list_rental_listings": (
        "GET",
        "/v1/data/rental-listings",
        [
            "lat",
            "lng",
            "radius_miles",
            "address",
            "zip",
            "bbox",
            "sort",
            "limit",
            "cursor",
        ],
    ),
    "list_sold_listings": (
        "GET",
        "/v1/data/sold-listing-history",
        [
            "lat",
            "lng",
            "radius_miles",
            "address",
            "zip",
            "bbox",
            "from",
            "to",
            "sort",
            "limit",
            "cursor",
        ],
    ),
    "list_investor_purchases": (
        "GET",
        "/v1/data/investor-purchases",
        ["lat", "lng", "radius_miles", "bbox", "zip"],
    ),
    "get_investor_purchase": (
        "GET",
        "/v1/data/investor-purchases/{purchase_id}",
        ["purchase_id"],
    ),
    "list_active_investors": ("GET", "/v1/data/investors/active", ["zip"]),
    "match_investors": ("GET", "/v1/data/investors/match", ["property_id"]),
    "search_investors": ("GET", "/v1/data/investors/search", ["q"]),
    "get_investor_company": (
        "GET",
        "/v1/data/investor-companies/{company_id}",
        ["company_id"],
    ),
    "list_company_purchases": (
        "GET",
        "/v1/data/investor-companies/{company_id}/purchases",
        ["company_id"],
    ),
    "list_company_sales": (
        "GET",
        "/v1/data/investor-companies/{company_id}/sales",
        ["company_id"],
    ),
    "list_lenders": ("GET", "/v1/data/lenders", ["state", "county", "zip"]),
    "get_lender": ("GET", "/v1/data/lenders/{lender_id}", ["lender_id"]),
    "list_lender_loans": ("GET", "/v1/data/lenders/{lender_id}/loans", ["lender_id"]),
    "list_lender_borrowers": (
        "GET",
        "/v1/data/lenders/{lender_id}/borrowers",
        ["lender_id"],
    ),
    "get_coverage": ("GET", "/v1/data/coverage", []),
}
