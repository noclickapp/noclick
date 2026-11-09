"""CarsXE vehicle data lookups and asynchronous batch submissions.

Each operation uses one published API endpoint and a manually supplied API key.
The catalogue probe establishes key reachability; CarsXE exposes no account identity read.
"""
from __future__ import annotations

from typing import Annotated, Literal, Union
import httpx
from pydantic import BaseModel, ConfigDict, Field, StrictBool, field_validator, model_validator
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret

BASE_URL = "https://api.carsxe.com"


class CarsxeApiKeyCredential(BaseModel):
    model_config = ConfigDict(title="CarsXE API Key", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://carsxe.com/dashboard/developer",
            "x-credential-instructions": "Copy your API key from the CarsXE dashboard. NoClick sends it as the key query parameter to api.carsxe.com. Your plan must enable the products you use; lookups and batch submissions may consume paid credits. The connection check reads the vehicle catalogue and confirms reachability, not account identity.",
        })
    credential_type: Literal["carsxe_api_key"] = Field("carsxe_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., title="API key", min_length=1, max_length=4096,
                         json_schema_extra={"ui:widget": "password"})

    @field_validator("api_key", mode="before")
    @classmethod
    def key(cls, value):
        value = clean_secret(value, field_name="API key", key=True)
        if any(c.isspace() for c in value):
            raise ValueError("Paste the API key without whitespace")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


Vin = Annotated[str, Field(min_length=17, max_length=17, pattern=r"^[A-HJ-NPR-Z0-9]{17}$")]


class CollateralVehicle(_Input):
    vin: Vin
    mileage: int = Field(..., ge=0, le=1000000)
    zip: str = Field(..., pattern=r"^[0-9]{5}$", title="ZIP code")
    loan_term_months: int | None = Field(None, ge=1, le=96)


class GetSpecsConfig(_Input):
    """Vehicle Specifications (VIN decoder)."""
    operation: Literal["get_specs"] = Field("get_specs", json_schema_extra={"ui:hidden": True})
    vin: Vin = Field(..., description='The 17 character long vehicle identification number.')
    format: Literal["json"] | None = Field(None, description='The format of the response. One of `json` or `xml`.')
    deepdata: Literal['1'] | None = Field(None, description='Request extra data. Set to `1` to use. Significantly slower than the regular request but retrieves additional data.')
    disableIntVINDecoding: Literal['1'] | None = Field(None, description='Set to `1` to disable the International VIN decoding fallback and return an error instead of a potential partial response.')


class DecodeInternationalVinConfig(_Input):
    """International VIN Decoder."""
    operation: Literal["decode_international_vin"] = Field("decode_international_vin", json_schema_extra={"ui:hidden": True})
    vin: Vin = Field(..., description='The 17 character long vehicle identification number.')


class GetRecallsConfig(_Input):
    """Vehicle Recalls."""
    operation: Literal["get_recalls"] = Field("get_recalls", json_schema_extra={"ui:hidden": True})
    vin: Vin = Field(..., description='The 17 character long vehicle identification number.')


class GetRecallsByYmmConfig(_Input):
    """Recalls by Year, Make & Model."""
    operation: Literal["get_recalls_by_ymm"] = Field("get_recalls_by_ymm", json_schema_extra={"ui:hidden": True})
    year: str = Field(..., min_length=1, pattern=r"^[0-9]{4}$", description='The 4-digit model year (e.g. `2019`).')
    make: str = Field(..., min_length=1, description='The vehicle manufacturer name (e.g. `Toyota`). Case-insensitive.')
    model: str = Field(..., min_length=1, description='The vehicle model name (e.g. `Camry`). Case-insensitive.')


class GetRecallCampaignConfig(_Input):
    """Recall Campaign."""
    operation: Literal["get_recall_campaign"] = Field("get_recall_campaign", json_schema_extra={"ui:hidden": True})
    make: str = Field(..., max_length=120, min_length=1, description='The vehicle manufacturer name (e.g. `volkswagen`). Case and extra whitespace are ignored.')
    code: str = Field(..., max_length=64, min_length=1, description="The manufacturer's campaign code (e.g. `37M2`). Case-insensitive, the letter O is read as zero, and Volkswagen warranty codes match in any spelling (`VWP1403`, `VWP 14 03`, `VWP-14-03`).")


class SubmitRecallsBatchConfig(_Input):
    """Submit a bulk recalls batch."""
    operation: Literal["submit_recalls_batch"] = Field("submit_recalls_batch", json_schema_extra={"ui:hidden": True})
    vins: list[Vin] = Field(..., min_length=1, max_length=10000, description='Array of 17-character VINs (max 10,000 per batch).')
    webhookUrl: str | None = Field(None, min_length=1, description='HTTPS URL for a customer webhook. CarsXE POSTs a JSON payload when the batch finishes. Must be a valid HTTPS URL allowed by CarsXE validation rules.')


class GetRecallsBatchStatusConfig(_Input):
    """Get bulk recalls batch status."""
    operation: Literal["get_recalls_batch_status"] = Field("get_recalls_batch_status", json_schema_extra={"ui:hidden": True})
    batchId: str = Field(..., min_length=1, description='The batch ID returned from the submit endpoint.')


class GetRecallsBatchResultsConfig(_Input):
    """Get bulk recalls batch results."""
    operation: Literal["get_recalls_batch_results"] = Field("get_recalls_batch_results", json_schema_extra={"ui:hidden": True})
    batchId: str = Field(..., min_length=1, description='The batch ID returned from the submit endpoint.')


class DecodePlateConfig(_Input):
    """License Plate Decoder (v2)."""
    operation: Literal["decode_plate"] = Field("decode_plate", json_schema_extra={"ui:hidden": True})
    plate: str = Field(..., min_length=1, description='The vehicle registration number or license plate number.')
    country: str | None = Field(None, min_length=1, description='ISO 3166-1 alpha-2 country code such as `AU` for Australia or `ZA` for South Africa. Optional for `US`.')
    state: str | None = Field(None, min_length=1, description='The two letter state code (US) such as `CA` or `NY`, an Australian state (e.g. `NSW`, `VIC`), or a Canadian province (e.g. `ON`). Required for `AU` and `CA`. Optional for `US`: omit it, with `country=US`, to fan out across every covered US jurisdiction. x402 payments still require `state`.')
    district: str | None = Field(None, min_length=1, description='The district of the vehicle registration number. Required for Pakistan (`PK`) plates registered in the Khyber-Pakhtunkhwa province.')
    require_vin: StrictBool | None = Field(None, description='Only supported when `country=ES`. Set to `true` to always include a VIN. The request is billed 2x and usage counts 2x.')

    @model_validator(mode="after")
    def regional_state(self):
        if self.country in {"AU", "CA"} and not self.state:
            raise ValueError("State is required for Australian and Canadian plates")
        return self


class DecodeUsPlateConfig(_Input):
    """US Vehicle Plate Decoder."""
    operation: Literal["decode_us_plate"] = Field("decode_us_plate", json_schema_extra={"ui:hidden": True})
    plate: str = Field(..., min_length=1, description='The vehicle registration number or license plate number.')
    state: str = Field(..., min_length=1, description='Two-letter abbreviation for one of the 50 US states, the District of Columbia (`DC`), or Puerto Rico (`PR`).')
    decodeVIN: Literal['true', '1'] | None = Field(None, description='Set to `true` or `1` to decode the resolved VIN and include a `vehicle_specs` object in the response (identical in shape to the Specifications endpoint response).')


class GetLienTheftConfig(_Input):
    """Lien & Theft records."""
    operation: Literal["get_lien_theft"] = Field("get_lien_theft", json_schema_extra={"ui:hidden": True})
    vin: Vin = Field(..., description='The 17 character long vehicle identification number.')


class GetImagesConfig(_Input):
    """Vehicle Images."""
    operation: Literal["get_images"] = Field("get_images", json_schema_extra={"ui:hidden": True})
    make: str = Field(..., min_length=1, description='The vehicle make.')
    model: str = Field(..., min_length=1, description='The vehicle model.')
    year: str | None = Field(None, min_length=1, pattern=r"^[0-9]{4}$", description='The vehicle year.')
    trim: str | None = Field(None, min_length=1, description='The vehicle trim.')
    color: str | None = Field(None, min_length=1, description='The vehicle color.')
    transparent: StrictBool | None = Field(None, description='Prioritize images with transparent background. Defaults to `true`.')
    angle: Literal['front', 'side', 'back'] | None = Field(None, description='The angle to show the car in.')
    photoType: Literal['interior', 'exterior', 'engine'] | None = Field(None, description='Request images of the interior, exterior or engine. Can only be used in conjunction with year, make, model and trim query params.')
    size: Literal['Small', 'Medium', 'Large', 'Wallpaper', 'All'] | None = Field(None, description='Request images of a given size. Defaults to all sizes.')
    license: str | None = Field(None, min_length=1, description="Filter images by usage-rights labels supplied by the hosting site. This does not grant a license; confirm each image's contextLink before reuse. Presets: Public (public domain only); Share (free to use or share, including NonCommercial and NoDerivatives); ShareCommercially (free to share commercially; excludes NonCommercial, includes NoDerivatives); Modify (free to modify; excludes NoDerivatives, includes NonCommercial); ModifyCommercially (free to modify commercially; public domain, attribution, and ShareAlike only). Or pass specific tokens as a comma-separated list: cc_publicdomain (public domain), cc_attribute (attribution; commercial use and modification, with credit when shared), cc_sharealike (ShareAlike; shared adaptations use the same license), cc_noncommercial (NonCommercial), cc_nonderived (NoDerivatives). Prefix a token with - to exclude it. At least one included token is required. Leave blank to return all images.")
    format: Literal["json"] | None = Field(None, description='The format of the response. One of `json` or `xml`.')

    @model_validator(mode="after")
    def photo_filters(self):
        if self.photoType and not (self.year and self.trim):
            raise ValueError("Photo type requires year and trim")
        return self


class GetMarketValueConfig(_Input):
    """Vehicle Market Value (v2)."""
    operation: Literal["get_market_value"] = Field("get_market_value", json_schema_extra={"ui:hidden": True})
    vin: Vin = Field(..., description='The 17 character long vehicle identification number.')
    state: str | None = Field(None, min_length=1, description='The US state of the vehicle to get the market value for.')
    mileage: float | None = Field(None, ge=0, description='The current odometer reading (miles in the US, kilometers in Canada). When passed with condition, the API selects the matching mileage_list band and writes it into mileage_*, then recalculates adjusted_*. Omit mileage to apply bands yourself.')
    condition: Literal['excellent', 'clean', 'average', 'rough'] | None = Field(None, description='Overall condition: excellent, clean, average, or rough. excellent maps to the xclean response tier. Used with mileage to apply the matching band.')


class GetHistoryConfig(_Input):
    """Vehicle History."""
    operation: Literal["get_history"] = Field("get_history", json_schema_extra={"ui:hidden": True})
    vin: Vin = Field(..., description='The 17 character long vehicle identification number.')
    format: Literal["json"] | None = Field(None, description='The format of the response. One of `json` or `xml`.')
    lienTheft: Literal['true', '1'] | None = Field(None, description='Set to `true` or `1` to include a Lien & Theft check for the same VIN under `lienTheft`. Billed as one extra Lien & Theft call, only when lien & theft data is returned.')


class RecognizePlateConfig(_Input):
    """Plate Image Recognition."""
    operation: Literal["recognize_plate"] = Field("recognize_plate", json_schema_extra={"ui:hidden": True})
    image_url: str = Field(..., min_length=1, description="URL to an image of a vehicle's license plate.")


class RecognizeVinConfig(_Input):
    """VIN OCR."""
    operation: Literal["recognize_vin"] = Field("recognize_vin", json_schema_extra={"ui:hidden": True})
    image_url: str = Field(..., min_length=1, description='URL to an image, or the base64 string of the image.')


class GetYearMakeModelConfig(_Input):
    """Year Make Model."""
    operation: Literal["get_year_make_model"] = Field("get_year_make_model", json_schema_extra={"ui:hidden": True})
    year: str = Field(..., min_length=1, pattern=r"^[0-9]{4}$", description='The manufacturing year of the vehicle (numeric, between 1900 and the current model year plus one).')
    make: str = Field(..., min_length=1, description='The manufacturer of the vehicle (e.g., Toyota, Ford, BMW).')
    model: str = Field(..., min_length=1, description='The specific model of the vehicle (e.g., Camry, F-150, X5).')
    trim: str | None = Field(None, min_length=1, description='The vehicle trim (e.g., XLE, XSE).')
    exact_match: StrictBool | None = Field(None, description='Accepts true/1 or false/0, case-insensitively; defaults to false. Other values, arrays and objects return HTTP 400. Strict mode requires exact make/model and supplied trim, ignoring case and extra whitespace but preserving punctuation. Trim must equal the complete short trim or complete style string. Without trim, selects the most popular eligible style, otherwise the first in stable name/ID order. No eligible match returns the existing HTTP 404. Fuzzy mode retains substring-filtered selection without an unrestricted most-popular fallback.')
    allTrimOptions: Literal['1'] | None = Field(None, description='Return all trim options available for the year, make and model. Set to `1` to use. In strict mode, returns only eligible styles.')


class GetYmmOptionsConfig(_Input):
    """Year Make Model Options."""
    operation: Literal["get_ymm_options"] = Field("get_ymm_options", json_schema_extra={"ui:hidden": True})
    dimension: Literal['years', 'makes', 'models', 'trims', 'variants'] | None = Field(None, description='Return exactly this array when required filters are present. If omitted, the response is inferred automatically from `make`/`model`/`year`.')
    year: str | None = Field(None, min_length=1, pattern=r"^[0-9]{4}$", description='Filter to a specific manufacturing year. Required when filtering by `model` without `make`.')
    make: str | None = Field(None, min_length=1, description='Filter to a specific manufacturer (e.g., Toyota, Ford, Lexus). Required for `dimension=models`.')
    model: str | None = Field(None, min_length=1, description='Filter to a specific model (e.g., Camry, F-150, LX). Required for `dimension=trims` and for `dimension=variants` unless both `year` and `make` are set.')
    trim: str | None = Field(None, min_length=1, description='Optional substring filter on trim names. Only applied when querying `dimension=trims` or `dimension=variants`.')

    @model_validator(mode="after")
    def option_filters(self):
        if self.dimension == "models" and not self.make:
            raise ValueError("Models requires make")
        if self.dimension == "trims" and not self.model:
            raise ValueError("Trims requires model")
        if self.dimension == "variants" and not (self.model or (self.year and self.make)):
            raise ValueError("Variants requires model or year and make")
        if self.model and not (self.make or self.year):
            raise ValueError("Model requires make or year")
        return self


class DecodeObdCodeConfig(_Input):
    """OBD Codes Decoder."""
    operation: Literal["decode_obd_code"] = Field("decode_obd_code", json_schema_extra={"ui:hidden": True})
    code: str = Field(..., min_length=1, description='The OBD code.')


class GetCollateralScoreConfig(_Input):
    """Collateral Score."""
    operation: Literal["get_collateral_score"] = Field("get_collateral_score", json_schema_extra={"ui:hidden": True})
    vin: Vin = Field(...)
    mileage: int = Field(..., ge=0, le=1000000, description='Current odometer reading in miles.')
    zip: str = Field(..., pattern='^[0-9]{5}$', min_length=1, description='US ZIP; its state sets the regional value adjustment.')
    loan_term_months: int | None = Field(None, ge=1, le=96, description='Adds `depreciation_forecast.at_loan_maturity`.')


class SubmitCollateralBatchConfig(_Input):
    """Collateral Score Batch (submit)."""
    operation: Literal["submit_collateral_batch"] = Field("submit_collateral_batch", json_schema_extra={"ui:hidden": True})
    vehicles: list[CollateralVehicle] = Field(..., min_length=1, max_length=500)
    webhook_url: str | None = Field(None, min_length=1, description='Public HTTPS URL. Redirects are not followed.')


class GetCollateralBatchConfig(_Input):
    """Collateral Score Batch (status and results)."""
    operation: Literal["get_collateral_batch"] = Field("get_collateral_batch", json_schema_extra={"ui:hidden": True})
    batch_id: str = Field(..., min_length=1)


CarsxeConfig = Annotated[Union[
    GetSpecsConfig,
    DecodeInternationalVinConfig,
    GetRecallsConfig,
    GetRecallsByYmmConfig,
    GetRecallCampaignConfig,
    SubmitRecallsBatchConfig,
    GetRecallsBatchStatusConfig,
    GetRecallsBatchResultsConfig,
    DecodePlateConfig,
    DecodeUsPlateConfig,
    GetLienTheftConfig,
    GetImagesConfig,
    GetMarketValueConfig,
    GetHistoryConfig,
    RecognizePlateConfig,
    RecognizeVinConfig,
    GetYearMakeModelConfig,
    GetYmmOptionsConfig,
    DecodeObdCodeConfig,
    GetCollateralScoreConfig,
    SubmitCollateralBatchConfig,
    GetCollateralBatchConfig
], Field(discriminator="operation")]


class CarsxeFullConfig(NodeConfig[CarsxeConfig, CarsxeApiKeyCredential]):
    pass


ROUTES = {'get_specs': ('GET', '/specs'),
 'decode_international_vin': ('GET', '/v1/international-vin-decoder'),
 'get_recalls': ('GET', '/v1/recalls'),
 'get_recalls_by_ymm': ('GET', '/v1/recalls-ymm'),
 'get_recall_campaign': ('GET', '/v1/recalls-campaigns'),
 'submit_recalls_batch': ('POST', '/v1/recalls-batch/submit'),
 'get_recalls_batch_status': ('GET', '/v1/recalls-batch/status'),
 'get_recalls_batch_results': ('GET', '/v1/recalls-batch/results'),
 'decode_plate': ('GET', '/v2/platedecoder'),
 'decode_us_plate': ('GET', '/v1/us-platedecoder'),
 'get_lien_theft': ('GET', '/v1/lien-theft'),
 'get_images': ('GET', '/images'),
 'get_market_value': ('GET', '/v2/marketvalue'),
 'get_history': ('GET', '/history'),
 'recognize_plate': ('POST', '/platerecognition'),
 'recognize_vin': ('POST', '/v1/vinocr'),
 'get_year_make_model': ('GET', '/v1/ymm'),
 'get_ymm_options': ('GET', '/v1/ymm-options'),
 'decode_obd_code': ('GET', '/obdcodesdecoder'),
 'get_collateral_score': ('POST', '/v1/vehicle/collateral-score'),
 'submit_collateral_batch': ('POST', '/v1/vehicle/collateral-score/batch'),
 'get_collateral_batch': ('GET', '/v1/vehicle/collateral-score/batch')}


def _redact(value, key):
    if isinstance(value, str):
        return value.replace(key, "[redacted]")
    if isinstance(value, dict):
        return {_redact(k, key): _redact(v, key) for k, v in value.items()}
    if isinstance(value, list):
        return [_redact(v, key) for v in value]
    return value


class CarsxeNode(WorkflowNode):
    integration_type = "automation-carsxe"
    connection_evidence = ConnectionEvidence(operation="get_ymm_options",
        noun="vehicle catalogue", proves="reachability")
    default_operation = "get_specs"
    edit_examples = ["Decode a VIN", "Get market value for a vehicle", "Submit VINs for a recalls batch"]

    @classmethod
    def get_config_model(cls):
        return CarsxeFullConfig

    async def execute(self, inputs):
        if self.config is None or self.config.credentials is None:
            raise ValueError("Connect a CarsXE API key")
        key = self.config.credentials.api_key
        op = self.config.config
        method, path = ROUTES[op.operation]
        payload = op.model_dump(exclude={"operation"}, exclude_none=True)
        params = {"key": key}
        if method == "GET":
            params.update(payload)
        try:
            async with httpx.AsyncClient(timeout=90, follow_redirects=False, trust_env=False) as client:
                response = await client.request(method, BASE_URL + path, params=params,
                    headers={"Accept": "application/json"},
                    **({"json": payload} if method == "POST" else {}))
        except httpx.RequestError:
            raise ValueError("CarsXE request failed; completion could not be confirmed") from None
        try:
            body = response.json()
        except ValueError:
            raise ValueError("CarsXE returned a non-JSON response") from None
        if not 200 <= response.status_code < 300 or (isinstance(body, dict) and body.get("success") is False):
            message = body.get("message") if isinstance(body, dict) else None
            message = message if isinstance(message, str) else "CarsXE request rejected"
            raise ValueError(_redact(message, key))
        if not isinstance(body, (dict, list)):
            raise ValueError("CarsXE returned an unexpected JSON response")
        result = {"success": True, "data": _redact(body, key), "http_status": response.status_code}
        await self.emit(result)
        return result
