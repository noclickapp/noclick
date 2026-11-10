"""Nookipedia v1.7.0 read-only Animal Crossing catalogs.

Contract: https://api.nookipedia.com/static/doc.yaml (published OpenAPI).
No writes, webhook registration or created/updated-time polling are published.
Responses retain Nookipedia article links and attribution for downstream use.
"""
from __future__ import annotations

from typing import Annotated, Literal, Optional, Union
from urllib.parse import quote
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

BASE_URL = "https://api.nookipedia.com"
API_VERSION = "1.7.0"


class DodoAPIKeyCredential(BaseModel):
    model_config = ConfigDict(
        title="Nookipedia API Key",
        hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://api.nookipedia.com/",
            "x-credential-instructions": "Paste the UUID API key supplied by the Nookipedia team. Request access at api.nookipedia.com if you do not have one. Catalog reads verify that the key is accepted; they do not identify an account.",
        },
    )
    credential_type: Literal["dodo_api_key"] = Field(
        "dodo_api_key", json_schema_extra={"ui:hidden": True}
    )
    api_key: str = Field(
        ..., title="API Key", repr=False, json_schema_extra={"ui:widget": "password"}
    )

    @field_validator("api_key", mode="before")
    @classmethod
    def validate_key(cls, value):
        value = clean_secret(value, field_name="API key")
        try:
            return str(UUID(value))
        except (ValueError, TypeError, AttributeError):
            raise ValueError("Paste the UUID API key supplied by Nookipedia") from None


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid")


class DodoListVillagersConfig(_Input):
    """Villagers."""

    operation: Literal["list_villagers"] = Field(
        "list_villagers", json_schema_extra={"ui:hidden": True}
    )
    name: Optional[str] = Field(
        None,
        description="Villager name. For most names you will get back an array with one object, but note that names are not a unique identifier across the series, as there are 3 names that are shared by multiple villagers (Lulu, Petunia, Carmen). For those 3 names you will get back an array with 2 objects. How you disambiguate between these villagers is up to you.",
        max_length=500,
    )
    species: Optional[
        Literal[
            "alligator",
            "anteater",
            "bear",
            "bear cub",
            "bird",
            "bull",
            "cat",
            "cub",
            "chicken",
            "cow",
            "deer",
            "dog",
            "duck",
            "eagle",
            "elephant",
            "frog",
            "goat",
            "gorilla",
            "hamster",
            "hippo",
            "horse",
            "koala",
            "kangaroo",
            "lion",
            "monkey",
            "mouse",
            "octopus",
            "ostrich",
            "penguin",
            "pig",
            "rabbit",
            "rhino",
            "rhinoceros",
            "sheep",
            "squirrel",
            "tiger",
            "wolf",
        ]
    ] = Field(None, description="Retrieve villagers of a certain species.")
    personality: Optional[
        Literal[
            "big sister",
            "cranky",
            "jock",
            "lazy",
            "normal",
            "peppy",
            "sisterly",
            "smug",
            "snooty",
        ]
    ] = Field(
        None,
        description="Retrieve villagers with a certain personality. For 'sisterly', note that the community often also calls it 'uchi' or 'big sister'.",
    )
    game: Optional[
        list[
            Literal[
                "DNM", "AC", "E_PLUS", "WW", "CF", "NL", "WA", "NH", "FILM", "HHD", "PC"
            ]
        ]
    ] = Field(
        None,
        description="Retrieve villagers that appear in all listed games. For example, if you want only villagers that appear in both *New Horizons* and *Pocket Camp*, you would send in `?game=nh&game=pc`.",
    )
    birthmonth: Optional[str] = Field(
        None,
        description="Retrieve villagers born in a specific month. Value may be the month's name (`jan`, `january`) or the integer representing the month (`01`, `1`).",
        max_length=500,
    )
    birthday: Optional[str] = Field(
        None,
        description="Use with `birthmonth` to get villager(s) born on a specific day. Value should be an int, 1 through 31.",
        max_length=500,
    )
    nhdetails: Optional[Literal["true", "false"]] = Field(
        None,
        description="When set to `true`, an `nh_details` object will be included that contains *New Horizons* details about the villager. If the villager does not appear in *New Horizons*, the returned `nh_details` field will be set to null.",
    )
    excludedetails: Optional[Literal["true", "false"]] = Field(
        None,
        description="When set to `true`, only villager names are returned. Instead of an array of objects with all details, the return will be an array of strings.",
    )
    thumbsize: Optional[int] = Field(
        None,
        description="Specify the desired width of returned image URLs. When unspecified, the linked image(s) returned by the API will be full-resolution. Note that images can only be reduced in size; specifying a width greater than than the maximum size will return the default full-size image URL. Note that requesting specific image sizes for long lists may result in a very long response time.",
        strict=True,
        ge=1,
        le=4096,
    )


class DodoListEventsConfig(_Input):
    """All New Horizons events."""

    operation: Literal["list_events"] = Field(
        "list_events", json_schema_extra={"ui:hidden": True}
    )
    date: Optional[str] = Field(
        None,
        description="Specify a specific date (in the current or next year) to retrieve events for. Accepts many date formats, such as `YYYY-MM-DD` or `Month Day, Year`, as well as `today` to retrieve the current day's events (UTC time).",
        max_length=500,
    )
    year: Optional[str] = Field(
        None,
        description="Specify the year to retrieve events for. Must be the current or next year.",
        max_length=500,
    )
    month: Optional[str] = Field(
        None,
        description="Specify the month to retrieve events for (accepts multiple formats, such as `Oct`, `October`, or `10`). Most likely want to use alongside `year`, otherwise events in both the current and next year are returned.",
        max_length=500,
    )
    day: Optional[int] = Field(
        None,
        description="Specify the day of the month to retrieve events for.",
        strict=True,
        ge=1,
        le=31,
    )


class DodoListFishConfig(_Input):
    """All New Horizons fish."""

    operation: Literal["list_fish"] = Field(
        "list_fish", json_schema_extra={"ui:hidden": True}
    )
    month: Optional[str] = Field(
        None,
        description="Retrieve only the fish that are available in a specific month. Value may be the month's name (`jan`, `january`), the integer representing the month (`01`, `1`), or `current` for the current month. When `current` is specified, the return body will be an object with two arrays inside, one called `north` and the other `south` containing the fish available in each respective hemisphere. Note that the current month is calculated based off the API server's time, so it may be slightly off for you at the beginning or end of the month.",
        max_length=500,
    )
    excludedetails: Optional[Literal["true", "false"]] = Field(
        None,
        description="When set to `true`, only fish names are returned. Instead of an array of objects with all details, the return will be an array of strings. This is particularly useful when used with the `month` filter, for users who want just a list of fish in a given month but not all their respective details.",
    )
    thumbsize: Optional[int] = Field(
        None,
        description="Specify the desired width of returned image URLs. When unspecified, the linked image(s) returned by the API will be full-resolution. Note that images can only be reduced in size; specifying a width greater than than the maximum size will return the default full-size image URL. Note that requesting specific image sizes for long lists may result in a very long response time.",
        strict=True,
        ge=1,
        le=4096,
    )


class DodoGetFishConfig(_Input):
    """Single New Horizons fish."""

    operation: Literal["get_fish"] = Field(
        "get_fish", json_schema_extra={"ui:hidden": True}
    )
    fish: str = Field(
        ...,
        description="The name of the fish you wish to retrieve information about.",
        min_length=1,
        max_length=300,
    )
    thumbsize: Optional[int] = Field(
        None,
        description="Specify the desired width of returned image URLs. When unspecified, the linked image(s) returned by the API will be full-resolution. Note that images can only be reduced in size; specifying a width greater than than the maximum size will return the default full-size image URL.",
        strict=True,
        ge=1,
        le=4096,
    )


class DodoListBugsConfig(_Input):
    """All New Horizons bugs."""

    operation: Literal["list_bugs"] = Field(
        "list_bugs", json_schema_extra={"ui:hidden": True}
    )
    month: Optional[str] = Field(
        None,
        description="Retrieve only the bug that are available in a specific month. Value may be the month's name (`jan`, `january`), the integer representing the month (`01`, `1`), or `current` for the current month. When `current` is specified, the return body will be an object with two arrays inside, one called `north` and the other `south` containing the bug available in each respective hemisphere. Note that the current month is calculated based off the API server's time, so it may be slightly off for you at the beginning or end of the month.",
        max_length=500,
    )
    excludedetails: Optional[Literal["true", "false"]] = Field(
        None,
        description="When set to `true`, only bug names are returned. Instead of an array of objects with all details, the return will be an array of strings. This is particularly useful when used with the `month` filter, for users who want just a list of bugs in a given month but not all their respective details.",
    )
    thumbsize: Optional[int] = Field(
        None,
        description="Specify the desired width of returned image URLs. When unspecified, the linked image(s) returned by the API will be full-resolution. Note that images can only be reduced in size; specifying a width greater than than the maximum size will return the default full-size image URL. Note that requesting specific image sizes for long lists may result in a very long response time.",
        strict=True,
        ge=1,
        le=4096,
    )


class DodoGetBugConfig(_Input):
    """Single New Horizons bug."""

    operation: Literal["get_bug"] = Field(
        "get_bug", json_schema_extra={"ui:hidden": True}
    )
    bug: str = Field(
        ...,
        description="The name of the bug you wish to retrieve information about.",
        min_length=1,
        max_length=300,
    )
    thumbsize: Optional[int] = Field(
        None,
        description="Specify the desired width of returned image URLs. When unspecified, the linked image(s) returned by the API will be full-resolution. Note that images can only be reduced in size; specifying a width greater than than the maximum size will return the default full-size image URL.",
        strict=True,
        ge=1,
        le=4096,
    )


class DodoListSeaConfig(_Input):
    """All New Horizons sea creatures."""

    operation: Literal["list_sea"] = Field(
        "list_sea", json_schema_extra={"ui:hidden": True}
    )
    month: Optional[str] = Field(
        None,
        description="Retrieve only the sea creature that are available in a specific month. Value may be the month's name (`jan`, `january`), the integer representing the month (`01`, `1`), or `current` for the current month. When `current` is specified, the return body will be an object with two arrays inside, one called `north` and the other `south` containing the sea creature available in each respective hemisphere. Note that the current month is calculated based off the API server's time, so it may be slightly off for you at the beginning or end of the month.",
        max_length=500,
    )
    excludedetails: Optional[Literal["true", "false"]] = Field(
        None,
        description="When set to `true`, only sea creature names are returned. Instead of an array of objects with all details, the return will be an array of strings. This is particularly useful when used with the `month` filter, for users who want just a list of sea creatures in a given month but not all their respective details.",
    )
    thumbsize: Optional[int] = Field(
        None,
        description="Specify the desired width of returned image URLs. When unspecified, the linked image(s) returned by the API will be full-resolution. Note that images can only be reduced in size; specifying a width greater than than the maximum size will return the default full-size image URL. Note that requesting specific image sizes for long lists may result in a very long response time.",
        strict=True,
        ge=1,
        le=4096,
    )


class DodoGetSeaCreatureConfig(_Input):
    """Single New Horizons sea creature."""

    operation: Literal["get_sea_creature"] = Field(
        "get_sea_creature", json_schema_extra={"ui:hidden": True}
    )
    sea_creature: str = Field(
        ...,
        description="The name of the sea creature you wish to retrieve information about.",
        min_length=1,
        max_length=300,
    )
    thumbsize: Optional[int] = Field(
        None,
        description="Specify the desired width of returned image URLs. When unspecified, the linked image(s) returned by the API will be full-resolution. Note that images can only be reduced in size; specifying a width greater than than the maximum size will return the default full-size image URL.",
        strict=True,
        ge=1,
        le=4096,
    )


class DodoListArtConfig(_Input):
    """All New Horizons artwork."""

    operation: Literal["list_art"] = Field(
        "list_art", json_schema_extra={"ui:hidden": True}
    )
    hasfake: Optional[Literal["true", "false"]] = Field(
        None,
        description="When set to `true`, only artwork that has a fake will be returned. When set to `false`, only artwork without fakes will be returned.",
    )
    excludedetails: Optional[Literal["true", "false"]] = Field(
        None,
        description="When set to `true`, only artwork names are returned. Instead of an array of objects with all details, the return will be an array of strings.",
    )
    thumbsize: Optional[int] = Field(
        None,
        description="Specify the desired width of returned image URLs. When unspecified, the linked image(s) returned by the API will be full-resolution. Note that images can only be reduced in size; specifying a width greater than than the maximum size will return the default full-size image URL. Note that requesting specific image sizes for long lists may result in a very long response time.",
        strict=True,
        ge=1,
        le=4096,
    )


class DodoGetArtworkConfig(_Input):
    """Single New Horizons artwork."""

    operation: Literal["get_artwork"] = Field(
        "get_artwork", json_schema_extra={"ui:hidden": True}
    )
    artwork: str = Field(
        ...,
        description="The name of the artwork you wish to retrieve information about.",
        min_length=1,
        max_length=300,
    )
    thumbsize: Optional[int] = Field(
        None,
        description="Specify the desired width of returned image URLs. When unspecified, the linked image(s) returned by the API will be full-resolution. Note that images can only be reduced in size; specifying a width greater than than the maximum size will return the default full-size image URL.",
        strict=True,
        ge=1,
        le=4096,
    )


class DodoListFurnitureConfig(_Input):
    """All New Horizons furniture."""

    operation: Literal["list_furniture"] = Field(
        "list_furniture", json_schema_extra={"ui:hidden": True}
    )
    category: Optional[
        Literal["Housewares", "Miscellaneous", "Wall-mounted", "Ceiling decor"]
    ] = Field(
        None,
        description="Specify the category of furniture to return (housewares, miscellaneous, wall-mounted, or ceiling decor).",
    )
    color: Optional[
        list[
            Literal[
                "Aqua",
                "Beige",
                "Black",
                "Blue",
                "Brown",
                "Colorful",
                "Gray",
                "Green",
                "Orange",
                "Pink",
                "Purple",
                "Red",
                "White",
                "Yellow",
            ]
        ]
    ] = Field(
        None,
        description="Return furniture that matches the provided colors (may specify one or two colors).",
    )
    excludedetails: Optional[Literal["true", "false"]] = Field(
        None,
        description="When set to `true`, only furniture names are returned. Instead of an array of objects with all details, the return will be an array of strings.",
    )


class DodoGetFurnitureConfig(_Input):
    """Single New Horizons furniture."""

    operation: Literal["get_furniture"] = Field(
        "get_furniture", json_schema_extra={"ui:hidden": True}
    )
    furniture: str = Field(
        ...,
        description="The name of the furniture you wish to retrieve information about.",
        min_length=1,
        max_length=300,
    )
    thumbsize: Optional[int] = Field(
        None,
        description="Specify the desired width of returned image URLs. When unspecified, the linked image(s) returned by the API will be full-resolution. Note that images can only be reduced in size; specifying a width greater than than the maximum size will return the default full-size image URL.",
        strict=True,
        ge=1,
        le=4096,
    )


class DodoListClothingConfig(_Input):
    """All New Horizons clothing."""

    operation: Literal["list_clothing"] = Field(
        "list_clothing", json_schema_extra={"ui:hidden": True}
    )
    category: Optional[
        Literal[
            "Tops",
            "Bottoms",
            "Dress-up",
            "Headwear",
            "Accessories",
            "Socks",
            "Shoes",
            "Bags",
            "Umbrellas",
        ]
    ] = Field(None, description="Specify the category of clothing to return.")
    color: Optional[
        list[
            Literal[
                "Aqua",
                "Beige",
                "Black",
                "Blue",
                "Brown",
                "Colorful",
                "Gray",
                "Green",
                "Orange",
                "Pink",
                "Purple",
                "Red",
                "White",
                "Yellow",
            ]
        ]
    ] = Field(
        None,
        description="Return clothing that matches the provided colors (may specify one or two colors). Colors are used for gifting villagers.",
    )
    style: Optional[
        list[Literal["Active", "Cool", "Cute", "Elegant", "Gorgeous", "Simple"]]
    ] = Field(
        None,
        description="Return clothing that matches the provided styles (may specify one or two styles). Styles are used for gifting villagers.",
    )
    labeltheme: Optional[
        Literal[
            "Comfy",
            "Everyday",
            "Fairy tale",
            "Formal",
            "Goth",
            "Outdoorsy",
            "Party",
            "Sporty",
            "Theatrical",
            "Vacation",
            "Work",
        ]
    ] = Field(
        None,
        description="Return clothing that have the specified Label theme. This is used for completing the requested outfit theme for [Label](https://nookipedia.com/wiki/Label) when she visits the player's island.",
    )
    excludedetails: Optional[Literal["true", "false"]] = Field(
        None,
        description="When set to `true`, only clothing names are returned. Instead of an array of objects with all details, the return will be an array of strings.",
    )


class DodoGetClothingConfig(_Input):
    """Single New Horizons clothing."""

    operation: Literal["get_clothing"] = Field(
        "get_clothing", json_schema_extra={"ui:hidden": True}
    )
    clothing: str = Field(
        ...,
        description="The name of the clothing you wish to retrieve information about.",
        min_length=1,
        max_length=300,
    )
    thumbsize: Optional[int] = Field(
        None,
        description="Specify the desired width of returned image URLs. When unspecified, the linked image(s) returned by the API will be full-resolution. Note that images can only be reduced in size; specifying a width greater than than the maximum size will return the default full-size image URL.",
        strict=True,
        ge=1,
        le=4096,
    )


class DodoListInteriorConfig(_Input):
    """All New Horizons interior items."""

    operation: Literal["list_interior"] = Field(
        "list_interior", json_schema_extra={"ui:hidden": True}
    )
    category: Optional[Literal["Rugs", "Wallpaper", "Floors"]] = Field(
        None,
        description="Specify the category of interior items to return (rugs, wallpaper, or floors).",
    )
    color: Optional[
        list[
            Literal[
                "Aqua",
                "Beige",
                "Black",
                "Blue",
                "Brown",
                "Colorful",
                "Gray",
                "Green",
                "Orange",
                "Pink",
                "Purple",
                "Red",
                "White",
                "Yellow",
            ]
        ]
    ] = Field(
        None,
        description="Return furniture that matches the provided colors (may specify one or two colors).",
    )
    excludedetails: Optional[Literal["true", "false"]] = Field(
        None,
        description="When set to `true`, only interior item names are returned. Instead of an array of objects with all details, the return will be an array of strings.",
    )


class DodoGetInteriorItemConfig(_Input):
    """Single New Horizons interior item."""

    operation: Literal["get_interior_item"] = Field(
        "get_interior_item", json_schema_extra={"ui:hidden": True}
    )
    item: str = Field(
        ...,
        description="The name of the interior item you wish to retrieve information about.",
        min_length=1,
        max_length=300,
    )
    color: Optional[
        list[
            Literal[
                "Aqua",
                "Beige",
                "Black",
                "Blue",
                "Brown",
                "Colorful",
                "Gray",
                "Green",
                "Orange",
                "Pink",
                "Purple",
                "Red",
                "White",
                "Yellow",
            ]
        ]
    ] = Field(
        None,
        description="Return furniture that matches the provided colors (may specify one or two colors).",
    )
    thumbsize: Optional[int] = Field(
        None,
        description="Specify the desired width of returned image URLs. When unspecified, the linked image(s) returned by the API will be full-resolution. Note that images can only be reduced in size; specifying a width greater than than the maximum size will return the default full-size image URL.",
        strict=True,
        ge=1,
        le=4096,
    )


class DodoListToolsConfig(_Input):
    """All New Horizons tools."""

    operation: Literal["list_tools"] = Field(
        "list_tools", json_schema_extra={"ui:hidden": True}
    )
    excludedetails: Optional[Literal["true", "false"]] = Field(
        None,
        description="When set to `true`, only tool names are returned. Instead of an array of objects with all details, the return will be an array of strings.",
    )


class DodoGetToolConfig(_Input):
    """Single New Horizons tool."""

    operation: Literal["get_tool"] = Field(
        "get_tool", json_schema_extra={"ui:hidden": True}
    )
    tool: str = Field(
        ...,
        description="The name of the interior item you wish to retrieve information about.",
        min_length=1,
        max_length=300,
    )
    thumbsize: Optional[int] = Field(
        None,
        description="Specify the desired width of returned image URLs. When unspecified, the linked image(s) returned by the API will be full-resolution. Note that images can only be reduced in size; specifying a width greater than than the maximum size will return the default full-size image URL.",
        strict=True,
        ge=1,
        le=4096,
    )


class DodoListItemsConfig(_Input):
    """Miscellaneous New Horizons items."""

    operation: Literal["list_items"] = Field(
        "list_items", json_schema_extra={"ui:hidden": True}
    )
    excludedetails: Optional[Literal["true", "false"]] = Field(
        None,
        description="When set to `true`, only item names are returned. Instead of an array of objects with all details, the return will be an array of strings.",
    )


class DodoGetItemConfig(_Input):
    """Single New Horizons miscellaneous item."""

    operation: Literal["get_item"] = Field(
        "get_item", json_schema_extra={"ui:hidden": True}
    )
    item: str = Field(
        ...,
        description="The name of the interior item you wish to retrieve information about.",
        min_length=1,
        max_length=300,
    )
    thumbsize: Optional[int] = Field(
        None,
        description="Specify the desired width of returned image URLs. When unspecified, the linked image(s) returned by the API will be full-resolution. Note that images can only be reduced in size; specifying a width greater than than the maximum size will return the default full-size image URL.",
        strict=True,
        ge=1,
        le=4096,
    )


class DodoListRecipesConfig(_Input):
    """All New Horizons recipes."""

    operation: Literal["list_recipes"] = Field(
        "list_recipes", json_schema_extra={"ui:hidden": True}
    )
    material: Optional[str] = Field(
        None,
        description="Specify a material to only get recipes that use that material. You can specify `material` up to six times (no recipe uses more than six materials).",
        max_length=500,
    )
    excludedetails: Optional[Literal["true", "false"]] = Field(
        None,
        description="When set to `true`, only recipe names are returned. Instead of an array of objects with all details, the return will be an array of strings.",
    )
    thumbsize: Optional[int] = Field(
        None,
        description="Specify the desired width of returned image URLs. When unspecified, the linked image(s) returned by the API will be full-resolution. Note that images can only be reduced in size; specifying a width greater than than the maximum size will return the default full-size image URL. Note that requesting specific image sizes for long lists may result in a very long response time.",
        strict=True,
        ge=1,
        le=4096,
    )


class DodoGetRecipeConfig(_Input):
    """Single New Horizons recipe."""

    operation: Literal["get_recipe"] = Field(
        "get_recipe", json_schema_extra={"ui:hidden": True}
    )
    item: str = Field(
        ...,
        description="The name of the item you wish to retrieve recipe information about.",
        min_length=1,
        max_length=300,
    )
    thumbsize: Optional[int] = Field(
        None,
        description="Specify the desired width of returned image URLs. When unspecified, the linked image(s) returned by the API will be full-resolution. Note that images can only be reduced in size; specifying a width greater than than the maximum size will return the default full-size image URL.",
        strict=True,
        ge=1,
        le=4096,
    )


class DodoListGyroidsConfig(_Input):
    """All New Horizons gyroids."""

    operation: Literal["list_gyroids"] = Field(
        "list_gyroids", json_schema_extra={"ui:hidden": True}
    )
    sound: Optional[
        Literal["crash", "drum set", "hi-hat", "kick", "melody", "snare"]
    ] = Field(None, description="Specify the sound of the gyroid.")
    excludedetails: Optional[Literal["true", "false"]] = Field(
        None,
        description="When set to `true`, only gyroid names are returned. Instead of an array of objects with all details, the return will be an array of strings.",
    )


class DodoGetGyroidConfig(_Input):
    """Single New Horizons gyroid."""

    operation: Literal["get_gyroid"] = Field(
        "get_gyroid", json_schema_extra={"ui:hidden": True}
    )
    gyroid: str = Field(
        ...,
        description="The name of the gyroid you wish to retrieve information about.",
        min_length=1,
        max_length=300,
    )
    thumbsize: Optional[int] = Field(
        None,
        description="Specify the desired width of returned image URLs. When unspecified, the linked image(s) returned by the API will be full-resolution. Note that images can only be reduced in size; specifying a width greater than than the maximum size will return the default full-size image URL.",
        strict=True,
        ge=1,
        le=4096,
    )


class DodoListFossilsConfig(_Input):
    """All New Horizons fossils."""

    operation: Literal["list_fossils"] = Field(
        "list_fossils", json_schema_extra={"ui:hidden": True}
    )
    thumbsize: Optional[int] = Field(
        None,
        description="Specify the desired width of returned image URLs. When unspecified, the linked image(s) returned by the API will be full-resolution. Note that images can only be reduced in size; specifying a width greater than than the maximum size will return the default full-size image URL.",
        strict=True,
        ge=1,
        le=4096,
    )


DodoConfig = Annotated[
    Union[
        DodoListVillagersConfig,
        DodoListEventsConfig,
        DodoListFishConfig,
        DodoGetFishConfig,
        DodoListBugsConfig,
        DodoGetBugConfig,
        DodoListSeaConfig,
        DodoGetSeaCreatureConfig,
        DodoListArtConfig,
        DodoGetArtworkConfig,
        DodoListFurnitureConfig,
        DodoGetFurnitureConfig,
        DodoListClothingConfig,
        DodoGetClothingConfig,
        DodoListInteriorConfig,
        DodoGetInteriorItemConfig,
        DodoListToolsConfig,
        DodoGetToolConfig,
        DodoListItemsConfig,
        DodoGetItemConfig,
        DodoListRecipesConfig,
        DodoGetRecipeConfig,
        DodoListGyroidsConfig,
        DodoGetGyroidConfig,
        DodoListFossilsConfig,
    ],
    Field(discriminator="operation"),
]


class DodoFullConfig(NodeConfig[DodoConfig, DodoAPIKeyCredential]):
    pass


ROUTES = {
    "list_villagers": ("/villagers", []),
    "list_events": ("/nh/events", []),
    "list_fish": ("/nh/fish", []),
    "get_fish": ("/nh/fish/{fish}", ["fish"]),
    "list_bugs": ("/nh/bugs", []),
    "get_bug": ("/nh/bugs/{bug}", ["bug"]),
    "list_sea": ("/nh/sea", []),
    "get_sea_creature": ("/nh/sea/{sea_creature}", ["sea_creature"]),
    "list_art": ("/nh/art", []),
    "get_artwork": ("/nh/art/{artwork}", ["artwork"]),
    "list_furniture": ("/nh/furniture", []),
    "get_furniture": ("/nh/furniture/{furniture}", ["furniture"]),
    "list_clothing": ("/nh/clothing", []),
    "get_clothing": ("/nh/clothing/{clothing}", ["clothing"]),
    "list_interior": ("/nh/interior", []),
    "get_interior_item": ("/nh/interior/{item}", ["item"]),
    "list_tools": ("/nh/tools", []),
    "get_tool": ("/nh/tools/{tool}", ["tool"]),
    "list_items": ("/nh/items", []),
    "get_item": ("/nh/items/{item}", ["item"]),
    "list_recipes": ("/nh/recipes", []),
    "get_recipe": ("/nh/recipes/{item}", ["item"]),
    "list_gyroids": ("/nh/gyroids", []),
    "get_gyroid": ("/nh/gyroids/{gyroid}", ["gyroid"]),
    "list_fossils": ("/nh/fossils/individuals", []),
}


class DodoNode(WorkflowNode):
    integration_type = "automation-dodo"
    connection_evidence = ConnectionEvidence(
        noun="Nookipedia villagers",
        operation="list_villagers",
        proves="reachability",
    )

    @classmethod
    def get_config_model(cls):
        return DodoFullConfig

    async def execute(self, inputs):
        if not self.config.credentials:
            raise ValueError("Connect a Nookipedia API key")
        config = self.config.config
        path, path_fields = ROUTES[config.operation]
        for field in path_fields:
            value = getattr(config, field)
            # Keep user-supplied names in a single URL path segment.
            if value in {".", ".."} or any(ord(c) < 32 or ord(c) == 127 for c in value):
                raise ValueError(
                    "Use a Nookipedia item name without control characters"
                )
            path = path.replace("{" + field + "}", quote(value, safe=""))
        params = []
        for field, value in config.model_dump(exclude_none=True).items():
            if field == "operation" or field in path_fields:
                continue
            # OpenAPI form/explode arrays (e.g. game=NH&game=PC).
            params.extend(
                (field, item)
                for item in (value if isinstance(value, list) else [value])
            )
        async with guarded_async_client(
            timeout=60, follow_redirects=False, trust_env=False
        ) as client:
            response = await client.get(
                BASE_URL + path,
                params=params,
                headers={
                    "X-API-KEY": self.config.credentials.api_key,
                    "Accept-Version": API_VERSION,
                    "Accept": "application/json",
                },
            )
        response.raise_for_status()
        body = response.json()
        # The month=current query is documented to return hemisphere arrays,
        # although the published response schema only describes the default list.
        hemispheres = (
            config.operation in {"list_fish", "list_bugs", "list_sea"}
            and config.month == "current"
        )
        if hemispheres:
            valid = isinstance(body, dict) and all(
                isinstance(body.get(key), list) for key in ("north", "south")
            )
        else:
            valid = isinstance(body, dict if path_fields else list)
        if not valid or (
            isinstance(body, dict) and ("error" in body or "errors" in body)
        ):
            raise ValueError("Nookipedia returned an unexpected response shape")
        return {
            "status": "success",
            "data": body,
            "attribution": "Data from Nookipedia (CC BY-SA 3.0)",
            "source_url": "https://nookipedia.com/",
        }
