"""Native Bókun catalog, availability, booking-status and metadata operations.
Three existing credential families stay distinct; this node never creates a booking.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import re
from decimal import Decimal

import httpx
from datetime import date, datetime, timezone
from typing import Annotated, Literal, Union

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret


class CredentialBase(BaseModel):
    model_config = ConfigDict(extra="ignore", hide_input_in_errors=True)
    environment: Literal["sandbox", "production"] = Field("sandbox", title="Environment", description="Use the environment belonging to this existing credential; the node never changes it automatically.")

    @field_validator("access_key", "secret_key", "access_token", mode="before", check_fields=False)
    @classmethod
    def header_secret(cls, value):
        if not isinstance(value, str):
            raise ValueError("Supply the existing Bókun credential.")
        value = clean_secret(value, field_name="Bókun credential")
        if not value or not value.isascii() or any(ord(c) < 33 or ord(c) > 126 for c in value):
            raise ValueError("The Bókun credential must be a printable header value.")
        return value


class BokunRESTKeysCredential(CredentialBase):
    model_config = ConfigDict(extra="ignore", hide_input_in_errors=True, json_schema_extra={"title": "Bókun REST Key Pair", "x-credential-url": "https://bokun.dev/", "x-credential-instructions": "Existing REST API access-key and secret-key pair documented by Bókun's current publisher schema. These keys are distinct from App Store GraphQL access tokens. Match sandbox/production; actual vendor permissions and API entitlement must be verified. No key creation or secret retrieval is performed."})
    credential_type: Literal["bokun_rest_keys"] = Field("bokun_rest_keys", json_schema_extra={"ui:hidden": True})
    access_key: str = Field(..., min_length=1, max_length=4096, title="REST Access Key", json_schema_extra={"ui:widget": "password"})
    secret_key: str = Field(..., min_length=1, max_length=4096, title="REST Secret Key", json_schema_extra={"ui:widget": "password"})


class BokunRESTHMACCredential(BokunRESTKeysCredential):
    model_config = ConfigDict(extra="ignore", hide_input_in_errors=True, json_schema_extra={"title": "Bókun REST HMAC Key Pair", "x-credential-url": "https://bokun.dev/", "x-credential-instructions": "Existing direct REST key pair for Bókun's documented X-Bokun-Date/AccessKey/Signature HmacSHA1 scheme. The signature covers UTC date, access key, verb and encoded path including query. The current schema also documents direct key headers; choose the family actually enabled for your key. No automatic authentication fallback."})
    credential_type: Literal["bokun_rest_hmac"] = Field("bokun_rest_hmac", json_schema_extra={"ui:hidden": True})


class BokunAppTokenCredential(CredentialBase):
    model_config = ConfigDict(extra="ignore", hide_input_in_errors=True, json_schema_extra={"title": "Bókun Existing App Token", "x-credential-url": "https://bokun.dev/", "x-credential-instructions": "Supply an already issued App Store access token and its vendor tenant label. GraphQL uses X-Bokun-App-Access-Token on that tenant's host. Catalog reads require the actual PRODUCTS_READ grant; booking reads require BOOKINGS_READ. Installation/consent, callback verification, REST-secret retrieval and token issuance are not performed by this supplied-token method. Keep the token private; no token is sent in provider URLs or output."})
    credential_type: Literal["bokun_app_token"] = Field("bokun_app_token", json_schema_extra={"ui:hidden": True})
    tenant: str = Field(..., min_length=1, max_length=63, title="Vendor Tenant", description="The existing vendor's single subdomain label, without a URL or suffix.")
    access_token: str = Field(..., min_length=1, max_length=4096, title="App Access Token", json_schema_extra={"ui:widget": "password"})

    @field_validator("tenant")
    @classmethod
    def tenant_label(cls, value):
        if not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", value) or value in {"api", "www", "api-docs"}:
            raise ValueError("Use the existing vendor's lowercase tenant label.")
        return value


BokunCredential = Union[BokunRESTHMACCredential, BokunRESTKeysCredential, BokunAppTokenCredential]
FAMILIES = {"bokun_rest_hmac": BokunRESTHMACCredential, "bokun_rest_keys": BokunRESTKeysCredential, "bokun_app_token": BokunAppTokenCredential}


def credential_shape(value):
    try:
        if not isinstance(value, dict) or value.get("credential_type") not in FAMILIES:
            raise ValueError()
        return FAMILIES[value["credential_type"]].model_validate(value).model_dump()
    except Exception:
        raise ValueError("A valid Bókun credential of the selected family is required.") from None


def operation(value):
    return Field(value, json_schema_extra={"const": value, "ui:hidden": True})


def options(name):
    return {"x-dynamic-options": {"field_name": name, "searchable": True, "allow_custom": True, "placeholder": "Choose an accessible record or enter its exact ID"}}


class BaseOperation(BaseModel):
    model_config = ConfigDict(extra="ignore", hide_input_in_errors=True)


class RESTOperation(BaseOperation):
    model_config = ConfigDict(extra="ignore", hide_input_in_errors=True, json_schema_extra={"x-requires-tier": True, "x-tier-label": "REST Key Pair"})

    @field_validator("experience_id", "pricing_category_id", "product_list_id", "activity_id", "booking_id", "page_no", "page_size", mode="before", check_fields=False)
    @classmethod
    def canonical_integer(cls, value):
        if type(value) is int or isinstance(value, str) and re.fullmatch(r"0|[1-9][0-9]{0,18}", value):
            return value
        raise ValueError("Use a canonical integer ID or page value.")


class GraphQLOperation(BaseOperation):
    model_config = ConfigDict(extra="ignore", hide_input_in_errors=True, json_schema_extra={"x-requires-tier": True, "x-tier-label": "Existing App Token"})


class CheckConnection(BaseOperation):
    operation: Literal["check_connection"] = operation("check_connection")


class ListOwnedExperiences(RESTOperation):
    operation: Literal["list_owned_experience_ids"] = operation("list_owned_experience_ids")
    activated: bool | None = Field(None, title="Activated Filter", description="Omitted reads both activated and deactivated owned IDs.")


class ExperienceSelection(RESTOperation):
    experience_id: int = Field(..., ge=1, le=2**63-1, title="Owned Experience", json_schema_extra=options("experience_id"))


class GetExperienceMetadata(ExperienceSelection):
    operation: Literal["get_experience_metadata"] = operation("get_experience_metadata")


class UpdateExperienceMetadata(ExperienceSelection):
    operation: Literal["update_experience_metadata"] = operation("update_experience_metadata")
    title: str | None = Field(None, min_length=1, max_length=140, title="New Title", description="Omitted leaves it unchanged. This changes existing product metadata and may affect published product presentation.")
    short_description: str | None = Field(None, max_length=8192, title="New Short Description", description="Omitted or blank leaves it unchanged. Use Clear Short Description to remove the existing text.", json_schema_extra={"ui:widget": "textarea"})
    clear_short_description: bool = Field(False, title="Clear Short Description", description="Explicitly replace the existing short description with an empty string. Leave New Short Description blank when clearing.")
    keywords: list[str] | None = Field(None, max_length=50, title="New Keywords", description="Omitted leaves keywords unchanged; an empty list explicitly clears them.")

    @model_validator(mode="after")
    def meaningful(self):
        if self.clear_short_description and self.short_description not in (None, ""):
            raise ValueError("Choose either a new short description or Clear Short Description.")
        if not self.clear_short_description and all(v is None for v in (self.title, self.short_description, self.keywords)):
            raise ValueError("Supply at least one metadata change.")
        if self.keywords is not None and (any(not v.strip() or len(v)>1000 for v in self.keywords) or sum(len(v)+1 for v in self.keywords)>1000):
            raise ValueError("The keyword list must fit Bókun's 1000-character bound.")
        return self


class ListPricingCategories(RESTOperation):
    operation: Literal["list_pricing_categories"] = operation("list_pricing_categories")
    page_no: int = Field(0, ge=0, le=100000, title="Page Number", description="Bókun's documented zero-based page.")
    page_size: int = Field(25, ge=1, le=100, title="Page Size")


class PricingSelection(RESTOperation):
    pricing_category_id: int = Field(..., ge=1, le=2**63-1, title="Pricing Category", json_schema_extra=options("pricing_category_id"))


class GetPricingCategory(PricingSelection):
    operation: Literal["get_pricing_category"] = operation("get_pricing_category")


class UpdatePricingCategoryTitle(PricingSelection):
    operation: Literal["update_pricing_category_title"] = operation("update_pricing_category_title")
    title: str = Field(..., min_length=1, max_length=255, title="New Title", description="Read-modify-write of the existing category. Seat/age/dependency constraints are preserved; no amount or product linkage is changed.")


class DeleteUnusedPricingCategory(PricingSelection):
    operation: Literal["delete_unused_pricing_category"] = operation("delete_unused_pricing_category")
    acknowledge_deletion: Literal[True] = Field(..., title="Confirm Deletion", description="Deletes the selected category. Bókun refuses categories still linked to any product. Use only an owned disposable unused category.")


class LocalizedREST(RESTOperation):
    language: str = Field("EN", pattern=r"^[A-Z]{2}(?:_[A-Z]{2})?$", title="Language")


class ListProductLists(LocalizedREST):
    operation: Literal["list_product_lists"] = operation("list_product_lists")


class GetProductList(LocalizedREST):
    operation: Literal["get_product_list"] = operation("get_product_list")
    product_list_id: int = Field(..., ge=1, le=2**63-1, title="Product List", json_schema_extra=options("product_list_id"))


class ListCategories(LocalizedREST):
    operation: Literal["list_categories"] = operation("list_categories")
    product_type: str = Field(..., min_length=1, max_length=64, pattern=r"^[A-Z_]+$", title="Product Type", description="Exact product-type value for your Bókun catalog; the reference does not enumerate this path parameter.")


class ActivitySelection(LocalizedREST):
    activity_id: int = Field(..., ge=1, le=2**63-1, title="Activity ID")
    currency: str = Field(..., pattern=r"^[A-Z]{3}$", title="Currency", description="Explicit currency; no implicit ISK default.")


class GetActivity(ActivitySelection):
    operation: Literal["get_activity"] = operation("get_activity")


class GetActivityAvailability(ActivitySelection):
    operation: Literal["get_activity_availability"] = operation("get_activity_availability")
    start: date = Field(..., title="Start Date")
    end: date = Field(..., title="End Date")
    include_sold_out: bool = Field(False, title="Include Sold Out")

    @model_validator(mode="after")
    def interval(self):
        if not 0 <= (self.end-self.start).days <= 31:
            raise ValueError("Choose an ordered interval of at most 31 days.")
        return self


class GetBookingStatus(LocalizedREST):
    operation: Literal["get_booking_status"] = operation("get_booking_status")
    booking_id: int = Field(..., ge=1, le=2**63-1, title="Existing Booking ID", description="Reads status only; customer, invoices, payment records and confirmation codes are omitted.")
    currency: str = Field(..., pattern=r"^[A-Z]{3}$", title="Currency")


class GraphQLPage(GraphQLOperation):
    first: int = Field(25, ge=1, le=100, title="Page Size")
    page_token: str | None = Field(None, max_length=4096, title="Next Page Token", description="Use this node's signed continuation from the same credential and operation.")


class ListGraphQLProductLists(GraphQLPage):
    operation: Literal["list_graphql_product_lists"] = operation("list_graphql_product_lists")


class ListGraphQLExperiences(GraphQLPage):
    operation: Literal["list_graphql_experiences"] = operation("list_graphql_experiences")


class GraphQLSelection(GraphQLOperation):
    resource_id: str = Field(..., min_length=1, max_length=512, title="GraphQL Resource ID", description="Exact opaque GraphQL ID; REST integer IDs are a different wire type.")


class GetGraphQLExperience(GraphQLSelection):
    operation: Literal["get_graphql_experience"] = operation("get_graphql_experience")


class GetGraphQLBooking(GraphQLSelection):
    operation: Literal["get_graphql_booking"] = operation("get_graphql_booking")


class GetGraphQLVendor(GraphQLOperation):
    operation: Literal["get_graphql_vendor"] = operation("get_graphql_vendor")


BokunOperation = Annotated[Union[CheckConnection, ListOwnedExperiences, GetExperienceMetadata, UpdateExperienceMetadata,
    ListPricingCategories, GetPricingCategory, UpdatePricingCategoryTitle, DeleteUnusedPricingCategory, ListProductLists,
    GetProductList, ListCategories, GetActivity, GetActivityAvailability, GetBookingStatus, ListGraphQLProductLists,
    ListGraphQLExperiences, GetGraphQLExperience, GetGraphQLBooking, GetGraphQLVendor], Field(discriminator="operation")]


class BokunFullConfig(NodeConfig[BokunOperation, BokunCredential]):
    credentials: BokunCredential | None = Field(None, description="Select an existing Bókun credential. No environment fallback or token issuance is performed.")


class BokunNode(WorkflowNode):
    integration_type = "automation-bokun"
    credential_provider_labels = {"bokun": "Bókun Account"}
    connection_evidence = ConnectionEvidence(noun="Bókun API", identity_operation="check_connection", proves="reachability", identity_keys=())

    @classmethod
    def get_config_model(cls):
        return BokunFullConfig

    @staticmethod
    async def _ids(data, activated=None):
        value = await request(data, route="/restapi/v2.0/experiences/ids", params={"activated": str(activated).lower()} if activated is not None else None)
        if not isinstance(value, list) or len(value)>200:
            raise BokunAPIError("The owned experience-ID list exceeds this bounded read; no pagination is documented.")
        ids = [integer(v,1) for v in value]
        if len(set(ids))!=len(ids):
            raise BokunAPIError("Bókun returned duplicate experience IDs.")
        return ids

    @staticmethod
    async def _components(data, cid):
        value = await request(data, route=f"/restapi/v2.0/experience/{cid}/components", params=[("componentType",v) for v in COMPONENTS])
        return components(value,cid)

    @staticmethod
    async def _pricing_page(data, page, size):
        value = object_data(await request(data, route="/restapi/v2.0/pricing/categories", params={"pageNo":page,"pageSize":size}))
        if integer(value.get("pageNo"))!=page or integer(value.get("pageSize"),1)!=size:
            raise BokunAPIError("Bókun returned a different pricing-category page.")
        pages,total=integer(value.get("totalPageCount")),integer(value.get("totalCount"))
        items=[pricing_category(v) for v in rows(value.get("items"),size)]
        if len({v['id'] for v in items})!=len(items) or len(items)>total or pages!=(total+size-1)//size:
            raise BokunAPIError("Bókun returned inconsistent category pagination.")
        return {"items":items,"pageNo":page,"pageSize":size,"totalPageCount":pages,"totalCount":total,"next_page_no":page+1 if page+1<pages and page<100000 else None}

    @staticmethod
    def _graph_resource(value, expected=None):
        value=object_data(value);rid=text(value.get("id"))
        if expected is not None and rid!=expected:
            raise BokunAPIError("Bókun returned a different GraphQL resource.")
        out={"id":rid}
        for key in ("name","currency","timeZone","bookingType","capacityType","status","paymentStatus"):
            if value.get(key) is not None:
                out[key]=text(value[key])
        if value.get('briefDescription') is not None:
            if not isinstance(value['briefDescription'],str) or len(value['briefDescription'])>8192:
                raise BokunAPIError("Bókun returned an invalid brief description.")
            out['briefDescription']=value['briefDescription']
        if "activated" in value:
            out['activated']=boolean(value['activated'])
        for key in ("createdDate","lastModifiedDate"):
            if value.get(key) is not None:
                timestamp=text(value[key],32)
                if not re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d",timestamp):
                    raise BokunAPIError("Bókun returned an unexpected UTC date format.")
                datetime.fromisoformat(timestamp);out[key]=timestamp
        if value.get('keywords') is not None:
            if not isinstance(value['keywords'],list) or len(value['keywords'])>50:
                raise BokunAPIError("Bókun returned invalid keywords.")
            out['keywords']=[text(v,1000) for v in value['keywords']]
        return out

    @classmethod
    async def _graphql_page(cls,data,kind,first,token=None):
        state={"kind":kind,"first":first}
        cursor=page_cursor(data,token,state) if token else None
        value=object_data(await request(data,gql=kind,variables={"first":first,"after":cursor}))
        items=[]
        for edge in rows(value.get('edges'),first):
            text(edge.get('cursor'),1024);items.append(cls._graph_resource(edge.get('node')))
        info=object_data(value.get('pageInfo'));more=boolean(info.get('hasNextPage'))
        end=text(info.get('endCursor'),1024) if more else None
        if more and (not items or end==cursor) or len({v['id'] for v in items})!=len(items):
            raise BokunAPIError("Bókun returned a repeated or inconsistent GraphQL page.")
        return {"items":items,"totalCount":integer(value.get('totalCount')),"more_records":more,"next_page_token":scoped_page(data,state,end) if more else None}

    @classmethod
    async def load_field_options(cls, field_name, credential_data, context=None, page_token=None, search=None):
        data=dict(credential_data or {});data.update(credential_shape(data))
        if search is not None and (not isinstance(search,str) or len(search)>512):
            raise ValueError("Bókun picker search is invalid.")
        if field_name=='experience_id':
            if page_token:raise ValueError("Owned-ID continuation is not documented.")
            items=[{'value':str(v),'label':str(v)} for v in await cls._ids(data)];next_token=None
        elif field_name=='pricing_category_id':
            state={'kind':'pricing-picker','size':100};cursor=page_cursor(data,page_token,state) if page_token else '0'
            if not re.fullmatch(r"[0-9]{1,6}",cursor) or int(cursor)>100000:raise ValueError("Invalid picker page.")
            value=await cls._pricing_page(data,int(cursor),100);items=[{'value':str(v['id']),'label':v['title']} for v in value['items']]
            next_token=scoped_page(data,state,str(value['next_page_no'])) if value['next_page_no'] is not None else None
        elif field_name=='product_list_id':
            if page_token:raise ValueError("REST product-list continuation is not documented.")
            native=rows(await request(data,route='/product-list.json/list',params={'lang':'EN'}))
            items=[{'value':str(integer(v.get('id'),1)),'label':text(v.get('title'))} for v in native];next_token=None
        else:return {'options':[],'next_page_token':None}
        if search:items=[v for v in items if search.casefold() in v['label'].casefold() or search.casefold() in v['value'].casefold()]
        return {'options':items,'next_page_token':next_token,'search_scope':'current page only'}

    async def execute(self, inputs):
        mutation=False
        data={}
        try:
            if not isinstance(self.config,BokunFullConfig) or self.config.credentials is None:
                raise ValueError("Choose a Bókun credential and operation.")
            cfg=self.config.config;mutation=isinstance(cfg,(UpdateExperienceMetadata,UpdatePricingCategoryTitle,DeleteUnusedPricingCategory))
            data = credential_shape(self.config.credentials.model_dump())
            if isinstance(cfg,CheckConnection):
                if data['credential_type']=='bokun_app_token':self._graph_resource(await request(data,gql='vendor'))
                else:await self._ids(data)
                result={'reachable':True,'account_label':None,'proves':'reachability'}
            elif isinstance(cfg,ListOwnedExperiences):result={'ids':await self._ids(data,cfg.activated)}
            elif isinstance(cfg,(GetExperienceMetadata,UpdateExperienceMetadata)):
                current=await self._components(data,cfg.experience_id)
                if isinstance(cfg,UpdateExperienceMetadata):
                    body={k:v for k,v in {'title':cfg.title,'shortDescription':cfg.short_description,'keywords':cfg.keywords}.items() if v is not None}
                    if cfg.clear_short_description:
                        body['shortDescription']=''
                    response=object_data(await request(data,method='PUT',route=f'/restapi/v2.0/experience/{cfg.experience_id}/components',body=body))
                    if response.get('id') is not None and integer(response['id'],1)!=cfg.experience_id:
                        raise BokunAPIError("Bókun acknowledged a different experience.",uncertain=True)
                    if any(k in response and response[k]!=v for k,v in body.items()):
                        raise BokunAPIError("Bókun acknowledged different component values.",uncertain=True)
                    result=await self._components(data,cfg.experience_id)
                    if any(result.get(k)!=v for k,v in body.items()):raise BokunAPIError("The experience change was not confirmed by readback.",uncertain=True)
                else:result=current
            elif isinstance(cfg,ListPricingCategories):result=await self._pricing_page(data,cfg.page_no,cfg.page_size)
            elif isinstance(cfg,(GetPricingCategory,UpdatePricingCategoryTitle,DeleteUnusedPricingCategory)):
                route=f'/restapi/v2.0/pricing/category/{cfg.pricing_category_id}'
                current=pricing_category(await request(data,route=route),cfg.pricing_category_id)
                if isinstance(cfg,UpdatePricingCategoryTitle):
                    body={**current,'title':cfg.title};response=await request(data,method='PUT',route=route,body=body,unchanged=True)
                    if response is not None:pricing_category(response,cfg.pricing_category_id)
                    result=pricing_category(await request(data,route=route),cfg.pricing_category_id)
                    if result!=body:raise BokunAPIError("The category update was not confirmed by readback.",uncertain=True)
                elif isinstance(cfg,DeleteUnusedPricingCategory):
                    await request(data,method='DELETE',route=route,empty=True);result={'deleted_id':cfg.pricing_category_id,'provider_success_status':200}
                else:result=current
            elif isinstance(cfg,ListProductLists):
                result={'items':[{'id':integer(v.get('id'),1),'title':text(v.get('title'))} for v in rows(await request(data,route='/product-list.json/list',params={'lang':cfg.language}))]}
            elif isinstance(cfg,GetProductList):
                value=object_data(await request(data,route=f'/product-list.json/{cfg.product_list_id}',params={'lang':cfg.language}))
                if integer(value.get('id'),1)!=cfg.product_list_id:raise BokunAPIError("Bókun returned another product list.")
                result={'id':cfg.product_list_id,'title':text(value.get('title')),'size':integer(value.get('size'))}
            elif isinstance(cfg,ListCategories):
                result={'categories':self._categories(await request(data,route=f'/category.json/{cfg.product_type}',params={'lang':cfg.language}))}
            elif isinstance(cfg,(GetActivity,GetActivityAvailability)):
                params={'lang':cfg.language,'currency':cfg.currency};route=f'/activity.json/{cfg.activity_id}'
                if isinstance(cfg,GetActivityAvailability):
                    params.update(start=cfg.start.isoformat(),end=cfg.end.isoformat(),includeSoldOut=str(cfg.include_sold_out).lower())
                    result={'availabilities':[self._availability(v,cfg.activity_id) for v in rows(await request(data,route=route+'/availabilities',params=params),200)]}
                else:
                    value=object_data(await request(data,route=route,params=params))
                    if integer(value.get('id'),1)!=cfg.activity_id:raise BokunAPIError("Bókun returned another activity.")
                    result={'id':cfg.activity_id,'title':text(value.get('title')),'bookingType':text(value.get('bookingType'))}
            elif isinstance(cfg,GetBookingStatus):
                value=object_data(await request(data,route=f'/booking.json/booking/{cfg.booking_id}',params={'lang':cfg.language,'currency':cfg.currency}))
                if integer(value.get('bookingId'),1)!=cfg.booking_id:raise BokunAPIError("Bókun returned another booking.")
                if value.get('status') not in {'CART','REQUESTED','RESERVED','CONFIRMED','TIMEOUT','ABORTED','CANCELLED','ERROR','ARRIVED','NO_SHOW','REJECTED'}:raise BokunAPIError("Bókun returned an unknown booking status.")
                result={'bookingId':cfg.booking_id,'status':value['status'],'currency':text(value.get('currency'),3)}
            elif isinstance(cfg,GraphQLPage):result=await self._graphql_page(data,'productLists' if isinstance(cfg,ListGraphQLProductLists) else 'experiences',cfg.first,cfg.page_token)
            elif isinstance(cfg,GraphQLSelection):result=self._graph_resource(await request(data,gql='experience' if isinstance(cfg,GetGraphQLExperience) else 'booking',variables={'id':cfg.resource_id}),cfg.resource_id)
            elif isinstance(cfg,GetGraphQLVendor):result=self._graph_resource(await request(data,gql='vendor'))
            else:raise ValueError("Unsupported Bókun operation.")
            return {'status':'success','data':result}
        except BokunAPIError as exc:
            return {'status':'error','error':str(exc),'code':exc.code,'http_status':exc.http_status,'outcome_uncertain':exc.uncertain or data.get('_bokun_write_success_status_seen',False),'automatic_replay':False}
        except Exception:
            return {'status':'error','error':'The Bókun result is unverified. Check configuration and current access; read back any attempted metadata change before retrying.','code':'unverified_configuration','outcome_uncertain':data.get('_bokun_mutation_attempted',False),'automatic_replay':False}

    @classmethod
    def _categories(cls,value,depth=0):
        if depth>6:raise BokunAPIError("The category tree exceeds the native depth bound.")
        return [{'id':integer(v.get('id'),1),'title':text(v.get('title')),'categories':cls._categories(v.get('categories') or [],depth+1)} for v in rows(value)]

    @staticmethod
    def _availability(v,activity_id):
        v=object_data(v)
        if integer(v.get('activityId'),1)!=activity_id:raise BokunAPIError("Bókun returned another activity's availability.")
        result={'id':text(v.get('id')),'activityId':activity_id,'date':integer(v.get('date')),'startTime':text(v.get('startTime'),5),'availabilityCount':integer(v.get('availabilityCount'))}
        for k in ('soldOut','unavailable','unlimitedAvailability'):
            if v.get(k) is not None:result[k]=boolean(v[k])
        # V1's documented epoch number is preserved, not reinterpreted as v2 UTC ms.
        # Monetary v1 floats, passenger identity, tickets and customer data are omitted.
        return result


# Provider transport and response parsers remain owned by this integration.

MAX_BYTES = 2 * 1024 * 1024
REST_ORIGINS = {"production": "https://api.bokun.io", "sandbox": "https://api.bokuntest.com"}
GRAPHQL_SUFFIXES = {"production": "bokun.io", "sandbox": "bokuntest.com"}
COMPONENTS = ("ID", "TITLE", "SHORT_DESCRIPTION", "KEYWORDS", "TIME_ZONE", "CREATED", "LAST_MODIFIED")
GQL = {
    "vendor": "query NativeVendor { vendor { id name currency } }",
    "productLists": "query NativeLists($first:Int,$after:String) { productLists(first:$first,after:$after) { edges { cursor node { id name activated } } pageInfo { hasNextPage endCursor } totalCount } }",
    "experiences": "query NativeExperiences($first:Int,$after:String) { experiences(first:$first,after:$after) { edges { cursor node { id name activated timeZone } } pageInfo { hasNextPage endCursor } totalCount } }",
    "experience": "query NativeExperience($id:ID!) { experience(id:$id) { id name activated timeZone bookingType capacityType briefDescription keywords createdDate lastModifiedDate } }",
    "booking": "query NativeBooking($id:ID!) { booking(id:$id) { id status paymentStatus currency createdDate lastModifiedDate } }",
}


class BokunAPIError(RuntimeError):
    def __init__(self, message, *, code="unverified_response", http_status=None, uncertain=False):
        super().__init__(message)
        self.code, self.http_status, self.uncertain = code, http_status, uncertain


def object_data(value):
    if not isinstance(value, dict):
        raise BokunAPIError("Bókun returned an unexpected object.")
    return value


def rows(value, maximum=100):
    if not isinstance(value, list) or len(value) > maximum or any(not isinstance(v, dict) for v in value):
        raise BokunAPIError("Bókun returned an unexpected or oversized collection.")
    return value


def integer(value, minimum=0):
    if type(value) is not int or not minimum <= value <= 2**63 - 1:
        raise BokunAPIError("Bókun returned an invalid integer identifier or count.")
    return value


def text(value, maximum=512):
    if not isinstance(value, str) or not value.strip() or len(value) > maximum or any(ord(c) < 32 for c in value):
        raise BokunAPIError("Bókun returned invalid text metadata.")
    return value


def boolean(value):
    if type(value) is not bool:
        raise BokunAPIError("Bókun returned an invalid boolean.")
    return value


def parse_json(raw, secrets=()):
    def pairs(items):
        out = {}
        for k, v in items:
            if k in out:
                raise ValueError()
            out[k] = v
        return out
    def bound(v, depth=0):
        if depth > 16:
            raise ValueError()
        if isinstance(v, (dict, list)):
            if len(v) > 1000:
                raise ValueError()
            for member in (list(v.keys()) + list(v.values()) if isinstance(v, dict) else v):
                bound(member, depth + 1)
        elif isinstance(v, str) and (len(v) > 32768 or any(s and s in v for s in secrets)):
            raise ValueError()
        elif isinstance(v, Decimal) and not v.is_finite():
            raise ValueError()
    try:
        if len(raw) > MAX_BYTES:
            raise ValueError()
        value = json.loads(raw, object_pairs_hook=pairs, parse_float=Decimal,
                           parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
        bound(value)
        return value
    except Exception:
        raise BokunAPIError("Bókun returned malformed, private or oversized JSON.") from None


def signed_headers(data, method, encoded_path, *, date=None):
    """HmacSHA1 signs UTC date + access key + uppercase verb + exact wire path/query.
    The request body and origin are deliberately absent from the published input.
    """
    date = date or datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    message = date + data["access_key"] + method.upper() + encoded_path
    signature = base64.b64encode(hmac.new(data["secret_key"].encode(), message.encode(), hashlib.sha1).digest()).decode()
    return {"X-Bokun-Date": date, "X-Bokun-AccessKey": data["access_key"], "X-Bokun-Signature": signature}


def _client():
    return httpx.AsyncClient(timeout=20.0, follow_redirects=False, trust_env=False)


def _route(method, route):
    if method == "GET":
        return route in {"/restapi/v2.0/experiences/ids", "/restapi/v2.0/pricing/categories", "/product-list.json/list"} or bool(re.fullmatch(
            r"/restapi/v2\.0/(?:experience/[1-9][0-9]*/components|pricing/category/[1-9][0-9]*)|/product-list\.json/[1-9][0-9]*|/category\.json/[A-Z_]+|/activity\.json/[1-9][0-9]*(?:/availabilities)?|/booking\.json/booking/[1-9][0-9]*", route))
    return method in {"PUT", "DELETE"} and bool(re.fullmatch(r"/restapi/v2\.0/pricing/category/[1-9][0-9]*", route)) or method == "PUT" and bool(re.fullmatch(r"/restapi/v2\.0/experience/[1-9][0-9]*/components", route))


async def request(data, *, method="GET", route=None, params=None, body=None, gql=None, variables=None, empty=False, unchanged=False):
    family = data["credential_type"]
    if gql is not None:
        if family != "bokun_app_token" or gql not in GQL or route is not None:
            raise ValueError("This operation requires a Bókun App Token.")
        url = httpx.URL(f"https://{data['tenant']}.{GRAPHQL_SUFFIXES[data['environment']]}/api/graphql")
        headers = {"X-Bokun-App-Access-Token": data["access_token"]}
        method, body = "POST", {"query": GQL[gql], "variables": variables or {}}
    else:
        if family not in {"bokun_rest_hmac", "bokun_rest_keys"} or not _route(method, route or ""):
            raise ValueError("This operation requires the selected Bókun REST key pair.")
        if params and set(dict(params)) - {"componentType", "pageNo", "pageSize", "activated", "lang", "currency", "start", "end", "includeSoldOut"}:
            raise ValueError("Unsupported Bókun query fields.")
        if body is not None:
            fields = {"title", "shortDescription", "keywords"} if route.endswith("/components") else {"id", "title", "ticketCategory", "occupancy", "groupSize", "ageQualified", "minAge", "maxAge", "dependent", "masterCategoryId", "maxPerMaster", "sumDependentCategories", "maxDependentSum", "internalUseOnly"}
            if not isinstance(body, dict) or set(body) - fields or method != "PUT":
                raise ValueError("Unsupported Bókun management fields.")
        url = httpx.URL(REST_ORIGINS[data["environment"]] + route, params=params)
        headers = signed_headers(data, method, url.raw_path.decode("ascii")) if family == "bokun_rest_hmac" else {"access-key": data["access_key"], "secret-key": data["secret_key"]}
    mutation = method in {"PUT", "DELETE"}
    try:
        async with _client() as client:
            if mutation:
                data["_bokun_mutation_attempted"] = True
            async with client.stream(method, url, json=body, headers={**headers, "Accept": "application/json"}) as response:
                allowed = {200, 204} if unchanged else {200}
                if response.status_code not in allowed:
                    raise BokunAPIError(f"Bókun returned HTTP {response.status_code}; verify access and the requested action.",
                        code="provider_http_error", http_status=response.status_code, uncertain=mutation and response.status_code >= 500 or mutation and response.status_code in {202, 429})
                if mutation:
                    data["_bokun_write_success_status_seen"] = True
                raw = bytearray()
                async for chunk in response.aiter_bytes():
                    raw.extend(chunk)
                    if len(raw) > MAX_BYTES:
                        raise BokunAPIError("Bókun returned an oversized response.", uncertain=mutation)
                if empty or response.status_code == 204:
                    if raw:
                        raise BokunAPIError("Bókun returned an unexpected body for its empty success contract.", uncertain=mutation)
                    result = None
                else:
                    if response.headers.get("content-type", "").split(";")[0].strip().lower() != "application/json":
                        raise BokunAPIError("Bókun returned a non-JSON response.", uncertain=mutation)
                    result = parse_json(bytes(raw), tuple(data.get(k) for k in ("access_key", "secret_key", "access_token")))
    except BokunAPIError as exc:
        if mutation and exc.code == "unverified_response":
            exc.uncertain = True
        raise
    except Exception:
        raise BokunAPIError("The Bókun result is unverified. Read back the record before any deliberate retry.", code="unverified_transport", uncertain=mutation) from None
    if gql is not None:
        envelope = object_data(result)
        if "errors" in envelope and (not isinstance(envelope["errors"], list) or len(envelope["errors"]) > 100):
            raise BokunAPIError("Bókun returned an invalid GraphQL error envelope.")
        if envelope.get("errors"):
            # No arbitrary provider messages, private extensions or partial data escape.
            raise BokunAPIError("Bókun GraphQL rejected the selection; check app permissions and token access.", code="graphql_rejection")
        result = object_data(envelope.get("data")).get(gql)
        if result is None:
            raise BokunAPIError("Bókun did not return the selected GraphQL resource.")
    return result


def components(value, expected):
    value = object_data(value)
    if integer(value.get("id"), 1) != expected:
        raise BokunAPIError("Bókun returned a different experience.")
    out = {"id": expected}
    for key in ("title", "timeZone"):
        if value.get(key) is not None:
            out[key] = text(value[key])
    if value.get("shortDescription") is not None:
        if not isinstance(value["shortDescription"], str) or len(value["shortDescription"]) > 8192:
            raise BokunAPIError("Bókun returned an invalid short description.")
        out["shortDescription"] = value["shortDescription"]
    for key in ("created", "lastModified"):
        if value.get(key) is not None:
            out[key] = integer(value[key])  # explicitly UTC epoch milliseconds in v2
    if value.get("keywords") is not None:
        if not isinstance(value["keywords"], list) or len(value["keywords"]) > 50:
            raise BokunAPIError("Bókun returned invalid experience keywords.")
        out["keywords"] = [text(v, 1000) for v in value["keywords"]]
    return out


def pricing_category(value, expected=None):
    value = object_data(value)
    cid = integer(value.get("id"), 1)
    if expected is not None and cid != expected:
        raise BokunAPIError("Bókun returned a different pricing category.")
    if value.get("ticketCategory") not in {"ADULT", "CHILD", "TEENAGER", "INFANT", "SENIOR", "STUDENT", "MILITARY", "GROUP", "OTHER"}:
        raise BokunAPIError("Bókun returned an invalid ticket category.")
    out = {"id": cid, "title": text(value.get("title"), 255), "ticketCategory": value["ticketCategory"], "occupancy": integer(value.get("occupancy"))}
    for name in ("ageQualified", "dependent", "sumDependentCategories", "internalUseOnly"):
        out[name] = boolean(value.get(name))
    required = {"groupSize": value["ticketCategory"] == "GROUP", "minAge": out["ageQualified"], "maxAge": out["ageQualified"], "masterCategoryId": out["dependent"], "maxPerMaster": out["dependent"], "maxDependentSum": out["sumDependentCategories"]}
    for key, needed in required.items():
        if needed:
            out[key] = integer(value.get(key), 1 if key in {"masterCategoryId", "groupSize"} else 0)
        elif value.get(key) is not None:
            raise BokunAPIError("Bókun returned inconsistent pricing-category constraints.")
    return out


def scoped_page(data, state, cursor):
    secret = data.get("access_token") or data["secret_key"]
    grant = hashlib.sha256(json.dumps({k: data.get(k) for k in ("credential_type", "environment", "tenant", "access_key", "secret_key", "access_token")}, sort_keys=True).encode()).hexdigest()
    payload = json.dumps({"state": state, "cursor": cursor, "grant": grant}, sort_keys=True, separators=(",", ":")).encode()
    return base64.urlsafe_b64encode(payload + hmac.new(secret.encode(), b"bokun-native-page\0" + payload, hashlib.sha256).digest()).decode().rstrip("=")


def page_cursor(data, token, state):
    try:
        if not isinstance(token, str) or len(token) > 4096 or not re.fullmatch(r"[A-Za-z0-9_-]+", token):
            raise ValueError()
        raw = base64.urlsafe_b64decode(token + "=" * (-len(token) % 4))
        payload, signature = raw[:-32], raw[-32:]
        value = parse_json(payload)
        if not hmac.compare_digest(scoped_page(data, state, value["cursor"]), token) or not isinstance(value["cursor"], str) or len(value["cursor"]) > 1024:
            raise ValueError()
        return value["cursor"]
    except Exception:
        raise ValueError("The Bókun continuation does not match the current credential and selection.") from None
