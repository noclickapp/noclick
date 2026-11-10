"""BigOven partner v2: one documented request per operation.

Contract: https://api2.bigoven.com/swagger/docs/partner
User operations use an API key and the person's Basic credentials over HTTPS.
Lists return one provider page. No webhook/time-filtered polling API is published.
"""
from __future__ import annotations

import base64
from typing import Annotated, Literal, Union
from urllib.parse import quote
import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from utils.ssrf import guarded_async_client

BASE_URL = "https://api2.bigoven.com"


class BigOvenCredential(BaseModel):
    model_config = ConfigDict(title="BigOven API Key and Account", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://api2.bigoven.com/",
            "x-credential-instructions": "Paste your BigOven Build API key and your BigOven username and password. BigOven requires the API key on every request and Basic authentication to act on your recipes, notes, reviews and grocery list. NoClick checks your account with a read of /me.",
        })
    credential_type: Literal["bigoven_api_key"] = Field("bigoven_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., min_length=1, title="API key", json_schema_extra={"ui:widget": "password"})
    username: str = Field(..., min_length=1, title="BigOven username")
    password: str = Field(..., min_length=1, title="BigOven password", json_schema_extra={"ui:widget": "password"})

    @field_validator("api_key", "username", "password")
    @classmethod
    def no_controls(cls, value):
        if any(ord(c) < 32 or ord(c) == 127 for c in value):
            raise ValueError("Credentials cannot contain control characters")
        return value

    @field_validator("username")
    @classmethod
    def basic_username(cls, value):
        if ":" in value:
            raise ValueError("A Basic authentication username cannot contain a colon")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Ingredient(_Input):
    Name: str = Field(..., min_length=1, title="Ingredient name")
    Quantity: float | None = None
    Unit: str | None = None
    PreparationNotes: str | None = None
    IsHeading: bool | None = None
    DisplayIndex: int | None = None


class _Recipe(_Input):
    Title: str = Field(..., min_length=1, title="Recipe title")
    Instructions: str = Field(..., min_length=1, json_schema_extra={"ui:widget": "textarea"})
    Ingredients: list[Ingredient] = Field(..., min_length=1)
    Description: str | None = None
    Cuisine: str | None = None
    Category: str | None = None
    YieldNumber: float | None = None
    YieldUnit: str | None = None
    TotalMinutes: int | None = Field(None, ge=0)
    ActiveMinutes: int | None = Field(None, ge=0)
    IsPrivate: bool | None = None


class _Page(_Input):
    pg: int = Field(1, ge=1, title="Page", description="One provider page, numbered from 1.")
    rpp: int = Field(25, ge=1, title="Results per page")


class _RecipeId(_Input):
    recipe_id: int = Field(..., ge=1, title="Recipe ID")


class _Note(_RecipeId):
    note_id: int = Field(..., ge=1, title="Note ID")


class _NoteBody(_Input):
    Notes: str = Field(..., min_length=1, title="Notes", json_schema_extra={"ui:widget": "textarea"})
    Date: str | None = Field(None, description="ISO 8601 date/time of the meal.")
    People: str | None = None
    Variations: str | None = None


class _GroceryItem(_Input):
    name: str = Field(..., min_length=1, title="Item name")
    quantity: str | None = None
    unit: str | None = None
    notes: str | None = None
    department: str | None = None


class _GroceryGuid(_Input):
    guid: str = Field(..., min_length=1, title="Grocery item GUID")


class BigOvenGetMeConfig(_Input):
    """Read your BigOven account profile."""
    operation: Literal["get_me"] = Field("get_me", json_schema_extra={"ui:hidden": True})


class BigOvenSearchRecipesConfig(_Page):
    """Search recipes by title, ingredients, cuisine, user or saved recipe filter."""
    operation: Literal["search_recipes"] = Field("search_recipes", json_schema_extra={"ui:hidden": True})
    title_kw: str | None = None
    any_kw: str | None = None
    include_ing: str | None = Field(None, description="Up to three comma-separated ingredients")
    exclude_ing: str | None = None
    include_cat: str | None = None
    cuisine: str | None = None
    username: str | None = None
    filter: Literal["added", "try", "favorites", "myrecipes"] | None = None


class BigOvenGetRecipeConfig(_RecipeId):
    """Read the ingredients, instructions and details of a recipe."""
    operation: Literal["get_recipe"] = Field("get_recipe", json_schema_extra={"ui:hidden": True})


class BigOvenCreateRecipeConfig(_Recipe):
    """Create a recipe with ingredients and cooking instructions."""
    operation: Literal["create_recipe"] = Field("create_recipe", json_schema_extra={"ui:hidden": True})


class BigOvenUpdateRecipeConfig(_Recipe):
    """Update a recipe you own with the supplied ingredients and instructions."""
    operation: Literal["update_recipe"] = Field("update_recipe", json_schema_extra={"ui:hidden": True})
    RecipeID: int = Field(..., ge=1, title="Recipe ID")


class BigOvenDeleteRecipeConfig(_RecipeId):
    """Delete a recipe you own."""
    operation: Literal["delete_recipe"] = Field("delete_recipe", json_schema_extra={"ui:hidden": True})


class BigOvenListCategoriesConfig(_Input):
    """List the recipe categories available for search."""
    operation: Literal["list_categories"] = Field("list_categories", json_schema_extra={"ui:hidden": True})


class BigOvenListCollectionsConfig(_Input):
    """List current seasonal recipe collections."""
    operation: Literal["list_collections"] = Field("list_collections", json_schema_extra={"ui:hidden": True})


class BigOvenGetCollectionConfig(_Page):
    """Read one page of recipes in a curated collection."""
    operation: Literal["get_collection"] = Field("get_collection", json_schema_extra={"ui:hidden": True})
    collection_id: int = Field(..., ge=1, title="Collection ID")


class BigOvenGetGroceryListConfig(_Input):
    """Read your grocery list, including checked and pending items."""
    operation: Literal["get_grocery_list"] = Field("get_grocery_list", json_schema_extra={"ui:hidden": True})


class BigOvenClearGroceryListConfig(_Input):
    """Delete every item from your grocery list."""
    operation: Literal["clear_grocery_list"] = Field("clear_grocery_list", json_schema_extra={"ui:hidden": True})


class BigOvenAddRecipeToGroceryListConfig(_RecipeId):
    """Add a recipe to your grocery list, scaled to the amount you need."""
    operation: Literal["add_recipe_to_grocery_list"] = Field("add_recipe_to_grocery_list", json_schema_extra={"ui:hidden": True})
    scale: float = Field(1.0, gt=0)
    mark_as_pending: bool = False


class BigOvenAddGroceryItemConfig(_GroceryItem):
    """Add a single item to your grocery list."""
    operation: Literal["add_grocery_item"] = Field("add_grocery_item", json_schema_extra={"ui:hidden": True})


class BigOvenUpdateGroceryItemConfig(_GroceryItem, _GroceryGuid):
    """Update a grocery item or mark it checked or unchecked."""
    operation: Literal["update_grocery_item"] = Field("update_grocery_item", json_schema_extra={"ui:hidden": True})
    ischecked: bool | None = None


class BigOvenDeleteGroceryItemConfig(_GroceryGuid):
    """Delete one item from your grocery list."""
    operation: Literal["delete_grocery_item"] = Field("delete_grocery_item", json_schema_extra={"ui:hidden": True})


class BigOvenClearCheckedItemsConfig(_Input):
    """Remove all checked items from your grocery list."""
    operation: Literal["clear_checked_items"] = Field("clear_checked_items", json_schema_extra={"ui:hidden": True})


class BigOvenListNotesConfig(_RecipeId, _Page):
    """Read one page of your notes for a recipe."""
    operation: Literal["list_notes"] = Field("list_notes", json_schema_extra={"ui:hidden": True})


class BigOvenGetNoteConfig(_Note):
    """Read one of your recipe notes."""
    operation: Literal["get_note"] = Field("get_note", json_schema_extra={"ui:hidden": True})


class BigOvenCreateNoteConfig(_RecipeId, _NoteBody):
    """Add a recipe note with people, variations and meal date."""
    operation: Literal["create_note"] = Field("create_note", json_schema_extra={"ui:hidden": True})


class BigOvenUpdateNoteConfig(_Note, _NoteBody):
    """Update one of your recipe notes."""
    operation: Literal["update_note"] = Field("update_note", json_schema_extra={"ui:hidden": True})


class BigOvenDeleteNoteConfig(_Note):
    """Delete one of your recipe notes."""
    operation: Literal["delete_note"] = Field("delete_note", json_schema_extra={"ui:hidden": True})


class BigOvenListReviewsConfig(_RecipeId, _Page):
    """Read one page of reviews for a recipe."""
    operation: Literal["list_reviews"] = Field("list_reviews", json_schema_extra={"ui:hidden": True})


class BigOvenCreateReviewConfig(_RecipeId):
    """Post your recipe review; BigOven updates your existing review if you already have one."""
    operation: Literal["create_review"] = Field("create_review", json_schema_extra={"ui:hidden": True})
    StarRating: int = Field(..., ge=1, le=5)
    MakeAgain: Literal["yes", "no"] | None = None
    Comment: str = Field(..., min_length=1)
    ActiveMinutes: int | None = Field(None, ge=0)
    TotalMinutes: int | None = Field(None, ge=0)


class BigOvenListPhotosConfig(_RecipeId, _Page):
    """Read one page of photos for a recipe."""
    operation: Literal["list_photos"] = Field("list_photos", json_schema_extra={"ui:hidden": True})


BigOvenConfig = Annotated[Union[
    BigOvenGetMeConfig,
    BigOvenSearchRecipesConfig,
    BigOvenGetRecipeConfig,
    BigOvenCreateRecipeConfig,
    BigOvenUpdateRecipeConfig,
    BigOvenDeleteRecipeConfig,
    BigOvenListCategoriesConfig,
    BigOvenListCollectionsConfig,
    BigOvenGetCollectionConfig,
    BigOvenGetGroceryListConfig,
    BigOvenClearGroceryListConfig,
    BigOvenAddRecipeToGroceryListConfig,
    BigOvenAddGroceryItemConfig,
    BigOvenUpdateGroceryItemConfig,
    BigOvenDeleteGroceryItemConfig,
    BigOvenClearCheckedItemsConfig,
    BigOvenListNotesConfig,
    BigOvenGetNoteConfig,
    BigOvenCreateNoteConfig,
    BigOvenUpdateNoteConfig,
    BigOvenDeleteNoteConfig,
    BigOvenListReviewsConfig,
    BigOvenCreateReviewConfig,
    BigOvenListPhotosConfig,
], Field(discriminator="operation")]


class BigOvenFullConfig(NodeConfig[BigOvenConfig, BigOvenCredential]):
    pass


ROUTES = {
    'get_me': ('GET', '/me'),
    'search_recipes': ('GET', '/recipes'),
    'get_recipe': ('GET', '/recipe/{recipe_id}'),
    'create_recipe': ('POST', '/recipe'),
    'update_recipe': ('PUT', '/recipe'),
    'delete_recipe': ('DELETE', '/recipe/{recipe_id}'),
    'list_categories': ('GET', '/recipe/categories'),
    'list_collections': ('GET', '/collections'),
    'get_collection': ('GET', '/collection/{collection_id}'),
    'get_grocery_list': ('GET', '/grocerylist'),
    'clear_grocery_list': ('DELETE', '/grocerylist'),
    'add_recipe_to_grocery_list': ('POST', '/grocerylist/recipe'),
    'add_grocery_item': ('POST', '/grocerylist/item'),
    'update_grocery_item': ('PUT', '/grocerylist/item/{guid}'),
    'delete_grocery_item': ('DELETE', '/grocerylist/item/{guid}'),
    'clear_checked_items': ('POST', '/grocerylist/clearcheckedlines'),
    'list_notes': ('GET', '/recipe/{recipe_id}/notes'),
    'get_note': ('GET', '/recipe/{recipe_id}/note/{note_id}'),
    'create_note': ('POST', '/recipe/{recipe_id}/note'),
    'update_note': ('PUT', '/recipe/{recipe_id}/note/{note_id}'),
    'delete_note': ('DELETE', '/recipe/{recipe_id}/note/{note_id}'),
    'list_reviews': ('GET', '/recipe/{recipe_id}/reviews'),
    'create_review': ('POST', '/recipe/{recipe_id}/review'),
    'list_photos': ('GET', '/recipe/{recipe_id}/photos'),
}
BODY_OPERATIONS = {
    'create_recipe': 'recipe',
    'update_recipe': 'recipe',
    'add_recipe_to_grocery_list': 'mapped',
    'add_grocery_item': 'item',
    'update_grocery_item': 'item',
    'create_note': 'note',
    'update_note': 'note',
    'create_review': 'review',
}


class BigOvenNode(WorkflowNode):
    integration_type = "automation-bigoven"
    connection_evidence = ConnectionEvidence(noun="BigOven account", identity_operation="get_me")

    @classmethod
    def get_config_model(cls):
        return BigOvenFullConfig

    @staticmethod
    def _check_credential_family(data):
        credential = data.get("credentials")
        if isinstance(credential, dict) and credential.get("credential_type", "bigoven_api_key") != "bigoven_api_key":
            raise ValueError("Attach a BigOven API key and account credential")

    @classmethod
    def parse_config(cls, config_data):
        cls._check_credential_family(config_data)
        return super().parse_config(config_data)

    @classmethod
    def validate_config(cls, config_data):
        try:
            cls._check_credential_family(config_data)
        except ValueError as exc:
            return {"valid": False, "errors": [str(exc)], "satisfied_set": None}
        return super().validate_config(config_data)

    async def execute(self, inputs):
        if not self.config or not self.config.credentials:
            return {"status": "error", "error": "Connect a BigOven API key and account"}
        config = self.config.config
        credential = self.config.credentials
        values = config.model_dump(exclude_none=True, exclude={"operation"})
        method, path = ROUTES[config.operation]
        path_fields = {key for key in values if "{" + key + "}" in path}
        path = path.format(**{key: quote(str(values[key]), safe="") for key in path_fields})
        body_kind = BODY_OPERATIONS.get(config.operation)
        params = {}
        body = None
        if body_kind == "mapped":
            body = {"recipeId": config.recipe_id, "scale": config.scale, "markAsPending": config.mark_as_pending}
        elif body_kind:
            body = {key: value for key, value in values.items() if key not in path_fields}
            if body_kind == "note":
                body["RecipeID"] = config.recipe_id
                if hasattr(config, "note_id"):
                    body["ID"] = config.note_id
            if config.operation == "update_grocery_item":
                body["guid"] = config.guid
        else:
            params = {key: value for key, value in values.items() if key not in path_fields}
        try:
            async with guarded_async_client(timeout=30, trust_env=False, follow_redirects=False) as client:
                response = await client.request(method, BASE_URL + path,
                    headers={"X-BigOven-API-Key": credential.api_key, "Accept": "application/json"},
                    auth=httpx.BasicAuth(credential.username, credential.password),
                    params=params, **({"json": body} if body is not None else {}))
            if not 200 <= response.status_code < 300:
                # Keep the provider's rejection text so credential connect can explain it.
                return {"status": "error", "status_code": response.status_code,
                    "error": self._redact(response.text[:2000]) or f"BigOven HTTP {response.status_code}"}
            data = response.json() if response.content else None
            if isinstance(data, dict) and (data.get("error") or data.get("Error") or data.get("errors")):
                return {"status": "error", "error": self._redact(str(data))}
            data = self._redact(data)
            result = {"status": "success", "data": data}
            if config.operation == "get_me" and isinstance(data, dict):
                profile = data.get("Profile")
                if isinstance(profile, dict):
                    result["name"] = profile.get("FullName") or profile.get("UserName")
                    result["id"] = profile.get("UserID")
            return result
        except (httpx.HTTPError, ValueError) as exc:
            return {"status": "error", "error": "BigOven request failed: " + self._redact(str(exc))}

    def _redact(self, value):
        if isinstance(value, dict):
            return {key: self._redact(item) for key, item in value.items()
                if key not in {"BOAuthToken", "api_key", "password", "Authorization"}}
        if isinstance(value, list):
            return [self._redact(item) for item in value]
        if isinstance(value, str):
            credential = self.config.credentials
            basic = base64.b64encode(
                f"{credential.username}:{credential.password}".encode("utf-8")
            ).decode("ascii")
            for secret in (basic, credential.api_key, credential.password):
                value = value.replace(secret, "[redacted]")
        return value
