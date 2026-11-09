"""Solcast solar forecasts, weather, sites, measurements and schedules.

The fixed operations follow Solcast OpenAPI 1.0.0. API keys are pasted by
people and sent only as Bearer headers to the official HTTPS API.
"""
from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal, Union

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

BASE_URL = "https://api.solcast.com.au"


class SolcastAPIKeyCredential(BaseModel):
    model_config = ConfigDict(title="Solcast API Key", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://toolkit.solcast.com.au/",
            "x-credential-instructions": "Copy your API key from your Solcast Toolkit account. Access depends on your plan. NoClick checks your account's PV power sites when connecting.",
        })
    credential_type: Literal["solcast_api_key"] = Field("solcast_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., title="API key", min_length=1, max_length=4096,
        json_schema_extra={"ui:widget": "password"})

    @field_validator("api_key", mode="before")
    @classmethod
    def key(cls, value):
        value = clean_secret(value, field_name="API key")
        if any(c.isspace() for c in value):
            raise ValueError("Paste the API key without a Bearer prefix")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="ignore", hide_input_in_errors=True, allow_inf_nan=False)

    @field_validator("*", mode="after")
    @classmethod
    def valid_datetime(cls, value, info):
        if value is not None and info.field_name in {"start", "end", "period_start", "period_end", "install_date", "issue_time"}:
            try:
                datetime.fromisoformat(value.replace("Z", "+00:00"))
            except (ValueError, TypeError):
                raise ValueError("Use an ISO 8601 date or datetime") from None
        return value


class GetForecastAdvancedPvPowerConfig(_Input):
    """Get Forecast Advanced PV."""
    operation: Literal['get_forecast_advanced_pv_power'] = Field('get_forecast_advanced_pv_power', json_schema_extra={"ui:hidden": True})
    hours: int | None = Field(None, description='The number of hours to return in the response.', ge=1, le=336)
    output_parameters: list[Literal['pv_power_advanced', 'pv_power_advanced10', 'pv_power_advanced90']] | None = Field(None, description='The output parameters to include in the response.')
    resource_id: str = Field(..., description='The resource id of the resource.', min_length=1, max_length=4096)
    period: Literal['PT5M', 'PT10M', 'PT15M', 'PT20M', 'PT30M', 'PT60M'] | None = Field(None, description='Length of the averaging period in ISO 8601 duration format. Default is PT30M.', min_length=1, max_length=4096)
    apply_availability: float | None = Field(None, description='Percentage of the site’s total AC (inverter) capacity that is currently generating or expected to be generating during the forecast request period. E.g. if you specify a 50% availability, your returned power will be half of what it otherwise would be.')
    apply_constraint: float | None = Field(None, description='Constraint on site’s total AC production, applied as a cap in the same way as the metadata parameter Site Export Limit. This will constrain all Solcast power values to be no higher than the apply_constraint value you specify. If you need an unconstrained forecast, you should not use this parameter.')
    apply_dust_soiling: float | None = Field(None, description="A user-override for dust_soiling_average. If you specify this parameter in your API call, we will replace the site's annual or monthly average dust soiling values with the value you specify in your API call.E.g. if you specify a 0.7 dust soiling, your returned power will be reduced by 70%.")
    apply_snow_soiling: float | None = Field(None, description='A user-override for Solcast’s dynamic snow soiling, which is based on global snow cover and weather forecast data, and changes from hour to hour. If you specify this parameter in your API call (e.g. if snow clearing has just been performed), we will replace the Solcast dynamic hour to hour value with the single value you specify. E.g. if you specify a 0.7 snow soiling, your returned power will be reduced by 70%.')
    apply_tracker_inactive: bool | None = Field(None, description='Indicating if trackers are inactive. If True, panels are assumed all facing up (i.e. zero rotation). Only has effect if your site has a tracking_type that is not “fixed”.')
    terrain_shading: bool | None = Field(None, description='If true, irradiance parameters are modified based on the surrounding terrain from a 90m-horizontal-resolution digital elevation model. The direct component of irradiance is set to zero when the beam from the sun is blocked by the terrain. The diffuse component of irradiance is reduced throughout the day if the sky view at the location is significantly reduced by the surrounding terrain. Global irradiance incorporates both effects.')


class GetLiveAdvancedPvPowerConfig(_Input):
    """Get Live Advanced PV."""
    operation: Literal['get_live_advanced_pv_power'] = Field('get_live_advanced_pv_power', json_schema_extra={"ui:hidden": True})
    hours: int | None = Field(None, description='The number of hours to return in the response.', ge=1, le=336)
    output_parameters: list[Literal['pv_power_advanced']] | None = Field(None, description='The output parameters to include in the response.')
    resource_id: str = Field(..., description='The resource id of the resource.', min_length=1, max_length=4096)
    period: Literal['PT5M', 'PT10M', 'PT15M', 'PT20M', 'PT30M', 'PT60M'] | None = Field(None, description='Length of the averaging period in ISO 8601 duration format. Default is PT30M.', min_length=1, max_length=4096)
    apply_availability: float | None = Field(None, description='Percentage of the site’s total AC (inverter) capacity that is currently generating or expected to be generating during the forecast request period. E.g. if you specify a 50% availability, your returned power will be half of what it otherwise would be.')
    apply_constraint: float | None = Field(None, description='Constraint on site’s total AC production, applied as a cap in the same way as the metadata parameter Site Export Limit. This will constrain all Solcast power values to be no higher than the apply_constraint value you specify. If you need an unconstrained forecast, you should not use this parameter.')
    apply_dust_soiling: float | None = Field(None, description="A user-override for dust_soiling_average. If you specify this parameter in your API call, we will replace the site's annual or monthly average dust soiling values with the value you specify in your API call.E.g. if you specify a 0.7 dust soiling, your returned power will be reduced by 70%.")
    apply_snow_soiling: float | None = Field(None, description='A user-override for Solcast’s dynamic snow soiling, which is based on global snow cover and weather forecast data, and changes from hour to hour. If you specify this parameter in your API call (e.g. if snow clearing has just been performed), we will replace the Solcast dynamic hour to hour value with the single value you specify. E.g. if you specify a 0.7 snow soiling, your returned power will be reduced by 70%.')
    apply_tracker_inactive: bool | None = Field(None, description='Indicating if trackers are inactive. If True, panels are assumed all facing up (i.e. zero rotation). Only has effect if your site has a tracking_type that is not “fixed”.')
    terrain_shading: bool | None = Field(None, description='If true, irradiance parameters are modified based on the surrounding terrain from a 90m-horizontal-resolution digital elevation model. The direct component of irradiance is set to zero when the beam from the sun is blocked by the terrain. The diffuse component of irradiance is reduced throughout the day if the sky view at the location is significantly reduced by the surrounding terrain. Global irradiance incorporates both effects.')


class GetHistoricRadiationAndWeatherConfig(_Input):
    """Get Historic Irradiance."""
    operation: Literal['get_historic_radiation_and_weather'] = Field('get_historic_radiation_and_weather', json_schema_extra={"ui:hidden": True})
    start: str = Field(..., description='ISO_8601 compliant starting datetime for the historical data. If the supplied value does not specify a timezone, the timezone will be inferred from the time_zone parameter, if supplied. Otherwise UTC is assumed.', min_length=1, max_length=4096)
    end: str | None = Field(None, description='Must include one of end_date and duration. ISO_8601 compliant ending datetime for the historical data. Must be within 31 days of the start_date. If the supplied value does not specify a timezone, the timezone will be inferred from the time_zone parameter, if supplied. Otherwise UTC is assumed.', min_length=1, max_length=4096)
    duration: str | None = Field(None, description='Must include one of end_date and duration. ISO_8601 compliant duration for the historical data. Must be within 31 days of the start_date.', min_length=1, max_length=4096)
    time_zone: str | None = Field(None, description='Timezone to return in data set. Accepted values are utc, longitudinal, or a range from -13 to 13 in 0.25 hour increments for utc offset.', min_length=1, max_length=4096)
    period: Literal['PT5M', 'PT10M', 'PT15M', 'PT20M', 'PT30M', 'PT60M'] | None = Field(None, description='Length of the averaging period in ISO 8601 duration format. Default is PT30M.', min_length=1, max_length=4096)
    tilt: float | None = Field(None, description="The angle (degrees) that the PV system is tilted off the horizontal. A tilt of 0 means the system faces directly upwards, and 90 means the system is vertical and facing the horizon. If you don't specify tilt, we use a default tilt angle based on the latitude you specify in your request. Must be between 0 and 90.", ge=0, le=90)
    azimuth: float | None = Field(None, description="The azimuth is defined as the angle (degrees) from true north that the PV system is facing. An azimuth of 0 means the system is facing true north. Positive values are anticlockwise, so azimuth is -90 for an east-facing system and 135 for a southwest-facing system. If you don't specify an azimuth, we use a default value of 0 (north facing) in the southern hemisphere and 180 (south-facing) in the northern hemisphere.")
    array_type: Literal['fixed', 'horizontal_single_axis'] | None = Field(None, description="The type of sun-tracking or geometry configuration of your site's modules.", min_length=1, max_length=4096)
    output_parameters: list[Literal['air_temp', 'albedo', 'azimuth', 'clearsky_dhi', 'clearsky_dni', 'clearsky_ghi', 'clearsky_gti', 'cloud_opacity', 'dewpoint_temp', 'dhi', 'dni', 'ghi', 'gti', 'precipitable_water', 'precipitation_rate', 'relative_humidity', 'surface_pressure', 'snow_soiling_rooftop', 'snow_soiling_ground', 'wind_direction_100m', 'wind_direction_10m', 'wind_speed_100m', 'wind_speed_10m', 'zenith', 'snow_depth', 'snow_water_equivalent', 'snowfall_rate', 'wind_gust', 'cape', 'weather_type', 'min_air_temp', 'max_air_temp', 'pm10', 'pm2.5']] | None = Field(None, description='The output parameters to include in the response.')
    terrain_shading: bool | None = Field(None, description='If true, irradiance parameters are modified based on the surrounding terrain from a 90m-horizontal-resolution digital elevation model. The direct component of irradiance is set to zero when the beam from the sun is blocked by the terrain. The diffuse component of irradiance is reduced throughout the day if the sky view at the location is significantly reduced by the surrounding terrain. Global irradiance incorporates both effects.')
    latitude: float = Field(..., description='The latitude of the location you request data for. Must be a decimal number between -90 and 90.', ge=-90, le=90)
    longitude: float = Field(..., description='The longitude of the location you request data for. Must be a decimal number between -180 and 180.', ge=-180, le=180)


class GetHistoricRooftopPvPowerConfig(_Input):
    """Get Historic Rooftop PV."""
    operation: Literal['get_historic_rooftop_pv_power'] = Field('get_historic_rooftop_pv_power', json_schema_extra={"ui:hidden": True})
    start: str = Field(..., description='ISO_8601 compliant starting datetime for the historical data. If the supplied value does not specify a timezone, the timezone will be inferred from the time_zone parameter, if supplied. Otherwise UTC is assumed.', min_length=1, max_length=4096)
    end: str | None = Field(None, description='Must include one of end_date and duration. ISO_8601 compliant ending datetime for the historical data. Must be within 31 days of the start_date. If the supplied value does not specify a timezone, the timezone will be inferred from the time_zone parameter, if supplied. Otherwise UTC is assumed.', min_length=1, max_length=4096)
    duration: str | None = Field(None, description='Must include one of end_date and duration. ISO_8601 compliant duration for the historical data. Must be within 31 days of the start_date.', min_length=1, max_length=4096)
    time_zone: str | None = Field(None, description='Timezone to return in data set. Accepted values are utc, longitudinal, or a range from -13 to 13 in 0.25 hour increments for utc offset.', min_length=1, max_length=4096)
    period: Literal['PT5M', 'PT10M', 'PT15M', 'PT20M', 'PT30M', 'PT60M'] | None = Field(None, description='Length of the averaging period in ISO 8601 duration format. Default is PT30M.', min_length=1, max_length=4096)
    latitude: float = Field(..., description='The latitude of the location you request data for. Must be a decimal number between -90 and 90.', ge=-90, le=90)
    longitude: float = Field(..., description='The longitude of the location you request data for. Must be a decimal number between -180 and 180.', ge=-180, le=180)
    capacity: float = Field(..., description='The capacity of the inverter (AC) or the modules (DC), whichever is greater, in kilowatts (kW).', ge=0)
    tilt: float | None = Field(None, description="The angle (degrees) that the PV system is tilted off the horizontal. A tilt of 0 means the system faces directly upwards, and 90 means the system is vertical and facing the horizon. If you don't specify tilt, we use a default tilt angle based on the latitude you specify in your request. Must be between 0 and 90.", ge=0, le=90)
    azimuth: float | None = Field(None, description="The azimuth is defined as the angle (degrees) from true north that the PV system is facing. An azimuth of 0 means the system is facing true north. Positive values are anticlockwise, so azimuth is -90 for an east-facing system and 135 for a southwest-facing system. If you don't specify an azimuth, we use a default value of 0 (north facing) in the southern hemisphere and 180 (south-facing) in the northern hemisphere.")
    install_date: str | None = Field(None, description='The date (yyyy-MM-dd) of installation of the PV system. We use this to estimate your loss_factor based on the ageing of your system. If you provide us with a loss_factor directly, we will ignore this date.', min_length=1, max_length=4096)
    loss_factor: float | None = Field(None, description='Default is 0.90 A factor to reduce your output forecast from the full capacity based on characteristics of the PV array or inverter. This is effectively the non-temperature loss effects on the nameplate rating of the PV system, including inefficiency and soiling. For a 1kW PV system anything that reduces 1000W/m2 solar radiation from producing 1000W of power output (assuming temperature is 25C). Valid values are between 0 and 1 (i.e. 0.6 equals 60%). If you specify 0.6 your returned power will be a maximum of 60% of AC capacity.')
    output_parameters: list[Literal['pv_power_rooftop']] | None = Field(None, description='The output parameters to include in the response.')
    terrain_shading: bool | None = Field(None, description='If true, irradiance parameters are modified based on the surrounding terrain from a 90m-horizontal-resolution digital elevation model. The direct component of irradiance is set to zero when the beam from the sun is blocked by the terrain. The diffuse component of irradiance is reduced throughout the day if the sky view at the location is significantly reduced by the surrounding terrain. Global irradiance incorporates both effects.')
    apply_snow_soiling: float | None = Field(None, description='A user-override for Solcast’s dynamic snow soiling, which is based on global snow cover and weather forecast data, and changes from hour to hour. If you specify this parameter in your API call (e.g. if snow clearing has just been performed), we will replace the Solcast dynamic hour to hour value with the single value you specify. E.g. if you specify a 0.7 snow soiling, your returned power will be reduced by 70%.')


class GetForecastPremiumPvPowerConfig(_Input):
    """Get Forecast Premium PV."""
    operation: Literal['get_forecast_premium_pv_power'] = Field('get_forecast_premium_pv_power', json_schema_extra={"ui:hidden": True})
    output_parameters: list[Literal['power', 'curtailed_power', 'availability', 'curtailment']] | None = Field(None, description='The output parameters to include in the response.')
    issue_time: str | None = Field(None, description='Return the forecast issued at this time (ISO 8601). Must be in the past. When omitted, the latest forecast is returned.', min_length=1, max_length=4096, json_schema_extra={'format': 'date-time'})
    request_id: str | None = Field(None, description='Optional request identifier for tracing and log correlation.', min_length=1, max_length=4096)
    hours: int | None = Field(None, description='The number of hours to return in the response.', ge=1, le=336)
    resource_id: str = Field(..., description='The resource id of the resource.', min_length=1, max_length=4096)
    period: Literal['PT5M', 'PT10M', 'PT15M', 'PT20M', 'PT30M', 'PT60M'] | None = Field(None, description='Length of the averaging period in ISO 8601 duration format. Default is PT30M.', min_length=1, max_length=4096)
    apply_availability: float | None = Field(None, description='Percentage of the site’s total AC (inverter) capacity that is currently generating or expected to be generating during the forecast request period. E.g. if you specify a 50% availability, your returned power will be half of what it otherwise would be.')
    apply_constraint: float | None = Field(None, description='Constraint on site’s total AC production, applied as a cap in the same way as the metadata parameter Site Export Limit. This will constrain all Solcast power values to be no higher than the apply_constraint value you specify. If you need an unconstrained forecast, you should not use this parameter.')
    apply_dust_soiling: float | None = Field(None, description="A user-override for dust_soiling_average. If you specify this parameter in your API call, we will replace the site's annual or monthly average dust soiling values with the value you specify in your API call.E.g. if you specify a 0.7 dust soiling, your returned power will be reduced by 70%.")
    apply_snow_soiling: float | None = Field(None, description='A user-override for Solcast’s dynamic snow soiling, which is based on global snow cover and weather forecast data, and changes from hour to hour. If you specify this parameter in your API call (e.g. if snow clearing has just been performed), we will replace the Solcast dynamic hour to hour value with the single value you specify. E.g. if you specify a 0.7 snow soiling, your returned power will be reduced by 70%.')
    apply_tracker_inactive: bool | None = Field(None, description='Indicating if trackers are inactive. If True, panels are assumed all facing up (i.e. zero rotation). Only has effect if your site has a tracking_type that is not “fixed”.')
    terrain_shading: bool | None = Field(None, description='If true, irradiance parameters are modified based on the surrounding terrain from a 90m-horizontal-resolution digital elevation model. The direct component of irradiance is set to zero when the beam from the sun is blocked by the terrain. The diffuse component of irradiance is reduced throughout the day if the sky view at the location is significantly reduced by the surrounding terrain. Global irradiance incorporates both effects.')


class GetLiveRooftopPvPowerConfig(_Input):
    """Get Live Rooftop PV."""
    operation: Literal['get_live_rooftop_pv_power'] = Field('get_live_rooftop_pv_power', json_schema_extra={"ui:hidden": True})
    hours: int | None = Field(None, description='The number of hours to return in the response.', ge=1, le=336)
    period: Literal['PT5M', 'PT10M', 'PT15M', 'PT20M', 'PT30M', 'PT60M'] | None = Field(None, description='Length of the averaging period in ISO 8601 duration format. Default is PT30M.', min_length=1, max_length=4096)
    latitude: float = Field(..., description='The latitude of the location you request data for. Must be a decimal number between -90 and 90.', ge=-90, le=90)
    longitude: float = Field(..., description='The longitude of the location you request data for. Must be a decimal number between -180 and 180.', ge=-180, le=180)
    capacity: float = Field(..., description='The capacity of the inverter (AC) or the modules (DC), whichever is greater, in kilowatts (kW).', ge=0)
    tilt: float | None = Field(None, description="The angle (degrees) that the PV system is tilted off the horizontal. A tilt of 0 means the system faces directly upwards, and 90 means the system is vertical and facing the horizon. If you don't specify tilt, we use a default tilt angle based on the latitude you specify in your request. Must be between 0 and 90.", ge=0, le=90)
    azimuth: float | None = Field(None, description="The azimuth is defined as the angle (degrees) from true north that the PV system is facing. An azimuth of 0 means the system is facing true north. Positive values are anticlockwise, so azimuth is -90 for an east-facing system and 135 for a southwest-facing system. If you don't specify an azimuth, we use a default value of 0 (north facing) in the southern hemisphere and 180 (south-facing) in the northern hemisphere.")
    install_date: str | None = Field(None, description='The date (yyyy-MM-dd) of installation of the PV system. We use this to estimate your loss_factor based on the ageing of your system. If you provide us with a loss_factor directly, we will ignore this date.', min_length=1, max_length=4096)
    loss_factor: float | None = Field(None, description='Default is 0.90 A factor to reduce your output forecast from the full capacity based on characteristics of the PV array or inverter. This is effectively the non-temperature loss effects on the nameplate rating of the PV system, including inefficiency and soiling. For a 1kW PV system anything that reduces 1000W/m2 solar radiation from producing 1000W of power output (assuming temperature is 25C). Valid values are between 0 and 1 (i.e. 0.6 equals 60%). If you specify 0.6 your returned power will be a maximum of 60% of AC capacity.')
    output_parameters: list[Literal['pv_power_rooftop']] | None = Field(None, description='The output parameters to include in the response.')
    terrain_shading: bool | None = Field(None, description='If true, irradiance parameters are modified based on the surrounding terrain from a 90m-horizontal-resolution digital elevation model. The direct component of irradiance is set to zero when the beam from the sun is blocked by the terrain. The diffuse component of irradiance is reduced throughout the day if the sky view at the location is significantly reduced by the surrounding terrain. Global irradiance incorporates both effects.')
    apply_snow_soiling: float | None = Field(None, description='A user-override for Solcast’s dynamic snow soiling, which is based on global snow cover and weather forecast data, and changes from hour to hour. If you specify this parameter in your API call (e.g. if snow clearing has just been performed), we will replace the Solcast dynamic hour to hour value with the single value you specify. E.g. if you specify a 0.7 snow soiling, your returned power will be reduced by 70%.')


class GetForecastRooftopPvPowerConfig(_Input):
    """Get Forecast Rooftop PV."""
    operation: Literal['get_forecast_rooftop_pv_power'] = Field('get_forecast_rooftop_pv_power', json_schema_extra={"ui:hidden": True})
    hours: int | None = Field(None, description='The number of hours to return in the response.', ge=1, le=336)
    output_parameters: list[Literal['pv_power_rooftop', 'pv_power_rooftop10', 'pv_power_rooftop90']] | None = Field(None, description='The output parameters to include in the response.')
    period: Literal['PT5M', 'PT10M', 'PT15M', 'PT20M', 'PT30M', 'PT60M'] | None = Field(None, description='Length of the averaging period in ISO 8601 duration format. Default is PT30M.', min_length=1, max_length=4096)
    latitude: float = Field(..., description='The latitude of the location you request data for. Must be a decimal number between -90 and 90.', ge=-90, le=90)
    longitude: float = Field(..., description='The longitude of the location you request data for. Must be a decimal number between -180 and 180.', ge=-180, le=180)
    capacity: float = Field(..., description='The capacity of the inverter (AC) or the modules (DC), whichever is greater, in kilowatts (kW).', ge=0)
    tilt: float | None = Field(None, description="The angle (degrees) that the PV system is tilted off the horizontal. A tilt of 0 means the system faces directly upwards, and 90 means the system is vertical and facing the horizon. If you don't specify tilt, we use a default tilt angle based on the latitude you specify in your request. Must be between 0 and 90.", ge=0, le=90)
    azimuth: float | None = Field(None, description="The azimuth is defined as the angle (degrees) from true north that the PV system is facing. An azimuth of 0 means the system is facing true north. Positive values are anticlockwise, so azimuth is -90 for an east-facing system and 135 for a southwest-facing system. If you don't specify an azimuth, we use a default value of 0 (north facing) in the southern hemisphere and 180 (south-facing) in the northern hemisphere.")
    install_date: str | None = Field(None, description='The date (yyyy-MM-dd) of installation of the PV system. We use this to estimate your loss_factor based on the ageing of your system. If you provide us with a loss_factor directly, we will ignore this date.', min_length=1, max_length=4096)
    loss_factor: float | None = Field(None, description='Default is 0.90 A factor to reduce your output forecast from the full capacity based on characteristics of the PV array or inverter. This is effectively the non-temperature loss effects on the nameplate rating of the PV system, including inefficiency and soiling. For a 1kW PV system anything that reduces 1000W/m2 solar radiation from producing 1000W of power output (assuming temperature is 25C). Valid values are between 0 and 1 (i.e. 0.6 equals 60%). If you specify 0.6 your returned power will be a maximum of 60% of AC capacity.')
    terrain_shading: bool | None = Field(None, description='If true, irradiance parameters are modified based on the surrounding terrain from a 90m-horizontal-resolution digital elevation model. The direct component of irradiance is set to zero when the beam from the sun is blocked by the terrain. The diffuse component of irradiance is reduced throughout the day if the sky view at the location is significantly reduced by the surrounding terrain. Global irradiance incorporates both effects.')
    apply_snow_soiling: float | None = Field(None, description='A user-override for Solcast’s dynamic snow soiling, which is based on global snow cover and weather forecast data, and changes from hour to hour. If you specify this parameter in your API call (e.g. if snow clearing has just been performed), we will replace the Solcast dynamic hour to hour value with the single value you specify. E.g. if you specify a 0.7 snow soiling, your returned power will be reduced by 70%.')


class ListPvPowerResourcesConfig(_Input):
    """List Resources."""
    operation: Literal['list_pv_power_resources'] = Field('list_pv_power_resources', json_schema_extra={"ui:hidden": True})
    entitlement: Literal['advanced', 'premium'] | None = Field(None, description='Optional filter for site entitlement.', min_length=1, max_length=4096)
    show_all: bool | None = Field(None, description='When true, returns all sites in the system. Requires admin privileges.')
    start: str | None = Field(None, description='Filter to sites created on or after this date (ISO 8601 format).', min_length=1, max_length=4096, json_schema_extra={'format': 'date-time'})
    end: str | None = Field(None, description='Filter to sites created before this date (ISO 8601 format).', min_length=1, max_length=4096, json_schema_extra={'format': 'date-time'})
    query: str | None = Field(None, description='Search query for site name or resource ID.', min_length=1, max_length=4096)
    forecast_production: bool | None = Field(None, description='Filter to sites where ML forecast production is enabled (premium only).')


class GetPvPowerResourceConfig(_Input):
    """Get Resource."""
    operation: Literal['get_pv_power_resource'] = Field('get_pv_power_resource', json_schema_extra={"ui:hidden": True})
    resource_id: str = Field(..., description='The unique identifier of the resource.', min_length=1, max_length=4096)


class ZenithCoefficients(_Input):
    day_of_year: int | None = Field(None)
    signed_zenith_coefficients: dict[str, float] | None = Field(None)


class CreatePvPowerResourceConfig(_Input):
    """Create Resource."""
    operation: Literal['create_pv_power_resource'] = Field('create_pv_power_resource', json_schema_extra={"ui:hidden": True})
    name: str = Field(..., description='The name of the resource.', min_length=1, max_length=4096)
    latitude: float = Field(..., description='The latitude of the resource. Must be a decimal number between -90 and 90.', ge=-90, le=90)
    longitude: float = Field(..., description='The longitude of the resource. Must be a decimal number between -180 and 180.', ge=-180, le=180)
    capacity: float = Field(..., description='Total inverter (nameplate) capacity in MW. This is the highest potential output of the system before any Site Export Limit is applied. It is used to model the conversion of DC power to AC by your inverters.', ge=0)
    capacity_dc: float = Field(..., description='Total module capacity in MW. Usually slightly higher than the AC capacity. It is used to model the generation of DC power by your modules.', ge=0)
    tracking_type: str = Field(..., description="The type of sun-tracking or geometry configuration of your site's modules. It is used to calculate the incident irradiance for your modules.", min_length=1, max_length=4096)
    install_date: str = Field(..., description='The date when your site was installed. It is used to derate your module (DC) production gradually with age, at a rate dependent on your Module Type.', min_length=1, max_length=4096, json_schema_extra={'format': 'date-time'})
    entitlement: Literal['advanced', 'premium'] | None = Field(None, description='Entitlement for the site.', min_length=1, max_length=4096)
    resource_id: str | None = Field(None, description='The unique identifier of the resource.', min_length=1, max_length=4096)
    azimuth: float | None = Field(None, description='The angle from true north the modules are facing. North is 0, South is ±180, Eastward facing is negative values. Westward facing is positive values. For example, -90 is due east. It is used to calculate the incident irradiance for your modules.')
    tilt: float | None = Field(None, description='The off-horizontal tilt angle of modules for a fixed-tilt site.', ge=0, le=90)
    grid_export_limit: float | None = Field(None, description="Optional maximum power export allowed by the site's grid connection, in MW. Omit this field when no limit is configured. Values >= 0  configure a limit. Value of -1 is treated as no configured limit. Only impacts your AC power if the grid export limit is set lower than the AC capacity. A configured limit will be in effect the next time predictions are updated.")
    module_type: str | None = Field(None, description="The type of material or technology used in your site's PV modules. It is used to estimate your module temperature derating coefficient (unless you specify your own coefficient), and used to estimate your module age derating.", min_length=1, max_length=4096)
    ground_coverage_ratio: float | None = Field(None, description="The proportion of the site's ground area covered by modules. It is used to calculate the incident irradiance for your modules. Must be at least 0.01 and at most 1.", ge=0.01, le=1)
    derating_temp_module: float | None = Field(None, description='The factor by which your site’s module (DC) production varies with differences in temperature from standard operating conditions ( 25 oC ). Can be found on module spec sheets and its often referred as: temperature coefficient of power or pmp.')
    derating_age_system: float | None = Field(None, description='The factor by which the whole system will be derated per year since Install Date. It is used to calculate time dependent system loss.')
    derating_other_system: float | None = Field(None, description='The total system losses as a fraction of the total energy output. This excludes shading, soiling, snow, inverter, temperature and age. Includes losses such as wiring.')
    inverter_peak_efficiency: float | None = Field(None, description='The peak efficiency value in your inverter efficiency curve. It is used to scale the conversion efficiency of DC to AC, as a function of the inverter load. Must be at least 0.01 and at most 1.', ge=0.01, le=1)
    tracker_axis_azimuth: float | None = Field(None, description='The off north-south azimuth angle for a horizontal single axis tracking site. Most commonly this will be close to zero.  North is 0, South is ±180, Eastward facing is negative values. Westward facing is positive values. For example, -90 is due east. It is used to calculate the incident irradiance for your modules.')
    tracker_max_rotation_angle: float | None = Field(None, description='The maximum off-horizontal angle for a horizontal single axis tracking site. It is used to calculate the incident irradiance for your modules.')
    tracker_back_tracking: bool | None = Field(None, description='Whether the trackers backtrack at low solar elevation angles, for a horizontal single axis tracking site. It is used to calculate the incident irradiance for your modules.')
    tracker_smart_tracking: bool | None = Field(None, description='Whether the trackers move to horizontal during cloudy periods with zero DNI, for a horizontal single axis tracking site. It is used to calculate the incident irradiance for your modules.')
    terrain_slope: float | None = Field(None, description='The average terrain slope in degrees from horizontal of your site. A site with no terrain slope has a value of zero.')
    terrain_azimuth: float | None = Field(None, description='The average terrain slope downhill direction. North is 0, South is ±180, Eastward is negative values. Westward is positive values. For example, -90 is due east. It is used to calculate the incident irradiance for your modules.')
    dust_soiling_average: list[float] | None = Field(None, description='The average proportion of module production lost due to dust soiling. If supplied, must contain exactly 12 monthly values in January-to-December order, each between 0 and 1. The values should reflect the impact of cleaning activity at your site. It is used to calculate the module (DC) production.', min_length=12, max_length=12)
    bifacial_system: bool | None = Field(None, description='Bifacial systems have modules that produce solar power not only from the front, but also the rear side of the panel. Used to create additional parameters that will allow us to model your production more accurately.')
    site_ground_albedo: float | None = Field(None, description='The proportion of the incident downward irradiance reflected by the ground surface in the area underneath the PV modules. Used to calculate local ground-reflected irradiance. Particularly important for bifacial systems.')
    bifaciality_factor: float | None = Field(None, description='For bifacial modules, the module rear efficiency as a proportion of the front efficiency subject to the same irradiance. Used to calculate the module rear production for bifacial systems.')
    pvrow_height: float | None = Field(None, description='The height of the module rows, in metres, measured from the ground to the row center or axis. Used to calculate the module rear incident irradiance and production for bifacial systems.')
    pvrow_width: float | None = Field(None, description='The width of the module rows, in metres. This is the cross-section width of the entire PV row. Used to calculate the module rear incident irradiance and production for bifacial systems.')
    clearsky_zenith_coefficients: list[ZenithCoefficients] | None = Field(None, description='Coefficients used to model clear-sky solar zenith irradiance for the resource.')
    cloudy_zenith_coefficients: list[ZenithCoefficients] | None = Field(None, description='Coefficients used to model cloudy-sky solar zenith irradiance for the resource.')
    forecast_production_status: Literal['PENDING', 'ACTIVE'] | None = Field(None, description='Premium PV only. The forecast production status for this resource. Allowed values: PENDING, ACTIVE.', min_length=1, max_length=4096)
    use_live_measurements: bool | None = Field(None, description='Premium PV only. Indicates whether live measurement blending is enabled for downstream nowcasts.')


class UpdatePvPowerResourceConfig(_Input):
    """Update Resource."""
    operation: Literal['update_pv_power_resource'] = Field('update_pv_power_resource', json_schema_extra={"ui:hidden": True})
    resource_id: str = Field(..., description='The unique identifier of the resource.', min_length=1, max_length=4096)
    name: str = Field(..., description='The name of the resource.', min_length=1, max_length=4096)
    latitude: float = Field(..., description='The latitude of the resource. Must be a decimal number between -90 and 90.', ge=-90, le=90)
    longitude: float = Field(..., description='The longitude of the resource. Must be a decimal number between -180 and 180.', ge=-180, le=180)
    capacity: float = Field(..., description='Total inverter (nameplate) capacity in MW. This is the highest potential output of the system before any Site Export Limit is applied. It is used to model the conversion of DC power to AC by your inverters.', ge=0)
    capacity_dc: float = Field(..., description='Total module capacity in MW. Usually slightly higher than the AC capacity. It is used to model the generation of DC power by your modules.', ge=0)
    tracking_type: str = Field(..., description="The type of sun-tracking or geometry configuration of your site's modules. It is used to calculate the incident irradiance for your modules.", min_length=1, max_length=4096)
    install_date: str = Field(..., description='The date when your site was installed. It is used to derate your module (DC) production gradually with age, at a rate dependent on your Module Type.', min_length=1, max_length=4096, json_schema_extra={'format': 'date-time'})
    azimuth: float | None = Field(None, description='The angle from true north the modules are facing. North is 0, South is ±180, Eastward facing is negative values. Westward facing is positive values. For example, -90 is due east. It is used to calculate the incident irradiance for your modules.')
    tilt: float | None = Field(None, description='The off-horizontal tilt angle of modules for a fixed-tilt site.', ge=0, le=90)
    grid_export_limit: float | None = Field(None, description="Optional maximum power export allowed by the site's grid connection, in MW. Omit this field when no limit is configured. Values >= 0  configure a limit. Value of -1 is treated as no configured limit. Only impacts your AC power if the grid export limit is set lower than the AC capacity. A configured limit will be in effect the next time predictions are updated.")
    module_type: str | None = Field(None, description="The type of material or technology used in your site's PV modules. It is used to estimate your module temperature derating coefficient (unless you specify your own coefficient), and used to estimate your module age derating.", min_length=1, max_length=4096)
    ground_coverage_ratio: float | None = Field(None, description="The proportion of the site's ground area covered by modules. It is used to calculate the incident irradiance for your modules. Must be at least 0.01 and at most 1.", ge=0.01, le=1)
    derating_temp_module: float | None = Field(None, description='The factor by which your site’s module (DC) production varies with differences in temperature from standard operating conditions ( 25 oC ). Can be found on module spec sheets and its often referred as: temperature coefficient of power or pmp.')
    derating_age_system: float | None = Field(None, description='The factor by which the whole system will be derated per year since Install Date. It is used to calculate time dependent system loss.')
    derating_other_system: float | None = Field(None, description='The total system losses as a fraction of the total energy output. This excludes shading, soiling, snow, inverter, temperature and age. Includes losses such as wiring.')
    inverter_peak_efficiency: float | None = Field(None, description='The peak efficiency value in your inverter efficiency curve. It is used to scale the conversion efficiency of DC to AC, as a function of the inverter load. Must be at least 0.01 and at most 1.', ge=0.01, le=1)
    tracker_axis_azimuth: float | None = Field(None, description='The off north-south azimuth angle for a horizontal single axis tracking site. Most commonly this will be close to zero.  North is 0, South is ±180, Eastward facing is negative values. Westward facing is positive values. For example, -90 is due east. It is used to calculate the incident irradiance for your modules.')
    tracker_max_rotation_angle: float | None = Field(None, description='The maximum off-horizontal angle for a horizontal single axis tracking site. It is used to calculate the incident irradiance for your modules.')
    tracker_back_tracking: bool | None = Field(None, description='Whether the trackers backtrack at low solar elevation angles, for a horizontal single axis tracking site. It is used to calculate the incident irradiance for your modules.')
    tracker_smart_tracking: bool | None = Field(None, description='Whether the trackers move to horizontal during cloudy periods with zero DNI, for a horizontal single axis tracking site. It is used to calculate the incident irradiance for your modules.')
    terrain_slope: float | None = Field(None, description='The average terrain slope in degrees from horizontal of your site. A site with no terrain slope has a value of zero.')
    terrain_azimuth: float | None = Field(None, description='The average terrain slope downhill direction. North is 0, South is ±180, Eastward is negative values. Westward is positive values. For example, -90 is due east. It is used to calculate the incident irradiance for your modules.')
    dust_soiling_average: list[float] | None = Field(None, description='The average proportion of module production lost due to dust soiling. If supplied, must contain exactly 12 monthly values in January-to-December order, each between 0 and 1. The values should reflect the impact of cleaning activity at your site. It is used to calculate the module (DC) production.', min_length=12, max_length=12)
    bifacial_system: bool | None = Field(None, description='Bifacial systems have modules that produce solar power not only from the front, but also the rear side of the panel. Used to create additional parameters that will allow us to model your production more accurately.')
    site_ground_albedo: float | None = Field(None, description='The proportion of the incident downward irradiance reflected by the ground surface in the area underneath the PV modules. Used to calculate local ground-reflected irradiance. Particularly important for bifacial systems.')
    bifaciality_factor: float | None = Field(None, description='For bifacial modules, the module rear efficiency as a proportion of the front efficiency subject to the same irradiance. Used to calculate the module rear production for bifacial systems.')
    pvrow_height: float | None = Field(None, description='The height of the module rows, in metres, measured from the ground to the row center or axis. Used to calculate the module rear incident irradiance and production for bifacial systems.')
    pvrow_width: float | None = Field(None, description='The width of the module rows, in metres. This is the cross-section width of the entire PV row. Used to calculate the module rear incident irradiance and production for bifacial systems.')
    clearsky_zenith_coefficients: list[ZenithCoefficients] | None = Field(None, description='Coefficients used to model clear-sky solar zenith irradiance for the resource.')
    cloudy_zenith_coefficients: list[ZenithCoefficients] | None = Field(None, description='Coefficients used to model cloudy-sky solar zenith irradiance for the resource.')
    forecast_production_status: Literal['PENDING', 'ACTIVE'] | None = Field(None, description='Premium PV only. The forecast production status for this resource. Allowed values: PENDING, ACTIVE.', min_length=1, max_length=4096)
    use_live_measurements: bool | None = Field(None, description='Premium PV only. Indicates whether live measurement blending is enabled for downstream nowcasts.')


class PatchPvPowerResourceConfig(_Input):
    """Patch Resource."""
    operation: Literal['patch_pv_power_resource'] = Field('patch_pv_power_resource', json_schema_extra={"ui:hidden": True})
    resource_id: str = Field(..., description='The unique identifier of the resource.', min_length=1, max_length=4096)
    name: str | None = Field(None, description='The name of the resource.', min_length=1, max_length=4096)
    latitude: float | None = Field(None, description='The latitude of the resource. Must be a decimal number between -90 and 90.', ge=-90, le=90)
    longitude: float | None = Field(None, description='The longitude of the resource. Must be a decimal number between -180 and 180.', ge=-180, le=180)
    capacity: float | None = Field(None, description='Total inverter (nameplate) capacity in MW. This is the highest potential output of the system before any Site Export Limit is applied. It is used to model the conversion of DC power to AC by your inverters.', ge=0)
    capacity_dc: float | None = Field(None, description='Total module capacity in MW. Usually slightly higher than the AC capacity. It is used to model the generation of DC power by your modules.', ge=0)
    azimuth: float | None = Field(None, description='The angle from true north the modules are facing. North is 0, South is ±180, Eastward facing is negative values. Westward facing is positive values. For example, -90 is due east. It is used to calculate the incident irradiance for your modules.')
    tilt: float | None = Field(None, description='The off-horizontal tilt angle of modules for a fixed-tilt site.', ge=0, le=90)
    tracking_type: str | None = Field(None, description="The type of sun-tracking or geometry configuration of your site's modules. It is used to calculate the incident irradiance for your modules.", min_length=1, max_length=4096)
    install_date: str | None = Field(None, description='The date when your site was installed. It is used to derate your module (DC) production gradually with age, at a rate dependent on your Module Type.', min_length=1, max_length=4096, json_schema_extra={'format': 'date-time'})
    grid_export_limit: float | None = Field(None, description="Optional maximum power export allowed by the site's grid connection, in MW. Omit this field when no limit is configured. Values >= 0  configure a limit. Value of -1 is treated as no configured limit. Only impacts your AC power if the grid export limit is set lower than the AC capacity. A configured limit will be in effect the next time predictions are updated.")
    module_type: str | None = Field(None, description="The type of material or technology used in your site's PV modules. It is used to estimate your module temperature derating coefficient (unless you specify your own coefficient), and used to estimate your module age derating.", min_length=1, max_length=4096)
    ground_coverage_ratio: float | None = Field(None, description="The proportion of the site's ground area covered by modules. It is used to calculate the incident irradiance for your modules. Must be at least 0.01 and at most 1.", ge=0.01, le=1)
    derating_temp_module: float | None = Field(None, description='The factor by which your site’s module (DC) production varies with differences in temperature from standard operating conditions ( 25 oC ). Can be found on module spec sheets and its often referred as: temperature coefficient of power or pmp.')
    derating_age_system: float | None = Field(None, description='The factor by which the whole system will be derated per year since Install Date. It is used to calculate time dependent system loss.')
    derating_other_system: float | None = Field(None, description='The total system losses as a fraction of the total energy output. This excludes shading, soiling, snow, inverter, temperature and age. Includes losses such as wiring.')
    inverter_peak_efficiency: float | None = Field(None, description='The peak efficiency value in your inverter efficiency curve. It is used to scale the conversion efficiency of DC to AC, as a function of the inverter load. Must be at least 0.01 and at most 1.', ge=0.01, le=1)
    tracker_axis_azimuth: float | None = Field(None, description='The off north-south azimuth angle for a horizontal single axis tracking site. Most commonly this will be close to zero.  North is 0, South is ±180, Eastward facing is negative values. Westward facing is positive values. For example, -90 is due east. It is used to calculate the incident irradiance for your modules.')
    tracker_max_rotation_angle: float | None = Field(None, description='The maximum off-horizontal angle for a horizontal single axis tracking site. It is used to calculate the incident irradiance for your modules.')
    tracker_back_tracking: bool | None = Field(None, description='Whether the trackers backtrack at low solar elevation angles, for a horizontal single axis tracking site. It is used to calculate the incident irradiance for your modules.')
    tracker_smart_tracking: bool | None = Field(None, description='Whether the trackers move to horizontal during cloudy periods with zero DNI, for a horizontal single axis tracking site. It is used to calculate the incident irradiance for your modules.')
    terrain_slope: float | None = Field(None, description='The average terrain slope in degrees from horizontal of your site. A site with no terrain slope has a value of zero.')
    terrain_azimuth: float | None = Field(None, description='The average terrain slope downhill direction. North is 0, South is ±180, Eastward is negative values. Westward is positive values. For example, -90 is due east. It is used to calculate the incident irradiance for your modules.')
    dust_soiling_average: list[float] | None = Field(None, description='The average proportion of module production lost due to dust soiling. If supplied, must contain exactly 12 monthly values in January-to-December order, each between 0 and 1. The values should reflect the impact of cleaning activity at your site. It is used to calculate the module (DC) production.', min_length=12, max_length=12)
    bifacial_system: bool | None = Field(None, description='Bifacial systems have modules that produce solar power not only from the front, but also the rear side of the panel. Used to create additional parameters that will allow us to model your production more accurately.')
    site_ground_albedo: float | None = Field(None, description='The proportion of the incident downward irradiance reflected by the ground surface in the area underneath the PV modules. Used to calculate local ground-reflected irradiance. Particularly important for bifacial systems.')
    bifaciality_factor: float | None = Field(None, description='For bifacial modules, the module rear efficiency as a proportion of the front efficiency subject to the same irradiance. Used to calculate the module rear production for bifacial systems.')
    pvrow_height: float | None = Field(None, description='The height of the module rows, in metres, measured from the ground to the row center or axis. Used to calculate the module rear incident irradiance and production for bifacial systems.')
    pvrow_width: float | None = Field(None, description='The width of the module rows, in metres. This is the cross-section width of the entire PV row. Used to calculate the module rear incident irradiance and production for bifacial systems.')
    clearsky_zenith_coefficients: list[ZenithCoefficients] | None = Field(None, description='Coefficients used to model clear-sky solar zenith irradiance for the resource.')
    cloudy_zenith_coefficients: list[ZenithCoefficients] | None = Field(None, description='Coefficients used to model cloudy-sky solar zenith irradiance for the resource.')
    forecast_production_status: Literal['PENDING', 'ACTIVE'] | None = Field(None, description='Premium PV only. The forecast production status for this resource. Allowed values: PENDING, ACTIVE.', min_length=1, max_length=4096)
    use_live_measurements: bool | None = Field(None, description='Premium PV only. Indicates whether live measurement blending is enabled for downstream nowcasts.')


class DeletePvPowerResourceConfig(_Input):
    """Remove Resource."""
    operation: Literal['delete_pv_power_resource'] = Field('delete_pv_power_resource', json_schema_extra={"ui:hidden": True})
    resource_id: str = Field(..., description='The unique identifier of the resource.', min_length=1, max_length=4096)


class GetLiveRadiationAndWeatherConfig(_Input):
    """Get Live Irradiance."""
    operation: Literal['get_live_radiation_and_weather'] = Field('get_live_radiation_and_weather', json_schema_extra={"ui:hidden": True})
    hours: int | None = Field(None, description='The number of hours to return in the response.', ge=1, le=336)
    period: Literal['PT5M', 'PT10M', 'PT15M', 'PT20M', 'PT30M', 'PT60M'] | None = Field(None, description='Length of the averaging period in ISO 8601 duration format. Default is PT30M.', min_length=1, max_length=4096)
    tilt: float | None = Field(None, description="The angle (degrees) that the PV system is tilted off the horizontal. A tilt of 0 means the system faces directly upwards, and 90 means the system is vertical and facing the horizon. If you don't specify tilt, we use a default tilt angle based on the latitude you specify in your request. Must be between 0 and 90.", ge=0, le=90)
    azimuth: float | None = Field(None, description="The azimuth is defined as the angle (degrees) from true north that the PV system is facing. An azimuth of 0 means the system is facing true north. Positive values are anticlockwise, so azimuth is -90 for an east-facing system and 135 for a southwest-facing system. If you don't specify an azimuth, we use a default value of 0 (north facing) in the southern hemisphere and 180 (south-facing) in the northern hemisphere.")
    array_type: Literal['fixed', 'horizontal_single_axis'] | None = Field(None, description="The type of sun-tracking or geometry configuration of your site's modules.", min_length=1, max_length=4096)
    output_parameters: list[Literal['air_temp', 'albedo', 'azimuth', 'clearsky_dhi', 'clearsky_dni', 'clearsky_ghi', 'clearsky_gti', 'cloud_opacity', 'dewpoint_temp', 'dhi', 'dni', 'ghi', 'gti', 'precipitable_water', 'precipitation_rate', 'relative_humidity', 'surface_pressure', 'snow_soiling_rooftop', 'snow_soiling_ground', 'wind_direction_100m', 'wind_direction_10m', 'wind_speed_100m', 'wind_speed_10m', 'zenith', 'snow_depth', 'snow_water_equivalent', 'snowfall_rate', 'wind_gust', 'cape', 'weather_type', 'min_air_temp', 'max_air_temp', 'pm10', 'pm2.5']] | None = Field(None, description='The output parameters to include in the response.')
    terrain_shading: bool | None = Field(None, description='If true, irradiance parameters are modified based on the surrounding terrain from a 90m-horizontal-resolution digital elevation model. The direct component of irradiance is set to zero when the beam from the sun is blocked by the terrain. The diffuse component of irradiance is reduced throughout the day if the sky view at the location is significantly reduced by the surrounding terrain. Global irradiance incorporates both effects.')
    latitude: float = Field(..., description='The latitude of the location you request data for. Must be a decimal number between -90 and 90.', ge=-90, le=90)
    longitude: float = Field(..., description='The longitude of the location you request data for. Must be a decimal number between -180 and 180.', ge=-180, le=180)


class GetForecastRadiationAndWeatherConfig(_Input):
    """Get Forecast Irradiance."""
    operation: Literal['get_forecast_radiation_and_weather'] = Field('get_forecast_radiation_and_weather', json_schema_extra={"ui:hidden": True})
    output_parameters: list[Literal['air_temp', 'albedo', 'azimuth', 'clearsky_dhi', 'clearsky_dni', 'clearsky_ghi', 'clearsky_gti', 'cloud_opacity', 'cloud_opacity10', 'cloud_opacity90', 'dewpoint_temp', 'dhi', 'dhi10', 'dhi90', 'dni', 'dni10', 'dni90', 'ghi', 'ghi10', 'ghi90', 'gti', 'gti10', 'gti90', 'precipitable_water', 'precipitation_rate', 'relative_humidity', 'surface_pressure', 'snow_depth', 'snow_water_equivalent', 'snow_soiling_rooftop', 'snow_soiling_ground', 'wind_direction_100m', 'wind_direction_10m', 'wind_speed_100m', 'wind_speed_10m', 'zenith', 'snowfall_rate', 'wind_gust', 'cape', 'weather_type', 'min_air_temp', 'max_air_temp', 'pm10', 'pm2.5']] | None = Field(None, description='The output parameters to include in the response.')
    hours: int | None = Field(None, description='The number of hours to return in the response.', ge=1, le=336)
    period: Literal['PT5M', 'PT10M', 'PT15M', 'PT20M', 'PT30M', 'PT60M'] | None = Field(None, description='Length of the averaging period in ISO 8601 duration format. Default is PT30M.', min_length=1, max_length=4096)
    tilt: float | None = Field(None, description="The angle (degrees) that the PV system is tilted off the horizontal. A tilt of 0 means the system faces directly upwards, and 90 means the system is vertical and facing the horizon. If you don't specify tilt, we use a default tilt angle based on the latitude you specify in your request. Must be between 0 and 90.", ge=0, le=90)
    azimuth: float | None = Field(None, description="The azimuth is defined as the angle (degrees) from true north that the PV system is facing. An azimuth of 0 means the system is facing true north. Positive values are anticlockwise, so azimuth is -90 for an east-facing system and 135 for a southwest-facing system. If you don't specify an azimuth, we use a default value of 0 (north facing) in the southern hemisphere and 180 (south-facing) in the northern hemisphere.")
    array_type: Literal['fixed', 'horizontal_single_axis'] | None = Field(None, description="The type of sun-tracking or geometry configuration of your site's modules.", min_length=1, max_length=4096)
    terrain_shading: bool | None = Field(None, description='If true, irradiance parameters are modified based on the surrounding terrain from a 90m-horizontal-resolution digital elevation model. The direct component of irradiance is set to zero when the beam from the sun is blocked by the terrain. The diffuse component of irradiance is reduced throughout the day if the sky view at the location is significantly reduced by the surrounding terrain. Global irradiance incorporates both effects.')
    latitude: float = Field(..., description='The latitude of the location you request data for. Must be a decimal number between -90 and 90.', ge=-90, le=90)
    longitude: float = Field(..., description='The longitude of the location you request data for. Must be a decimal number between -180 and 180.', ge=-180, le=180)


class GetForecastPremiumWindPowerConfig(_Input):
    """Get Forecast Premium Wind."""
    operation: Literal['get_forecast_premium_wind_power'] = Field('get_forecast_premium_wind_power', json_schema_extra={"ui:hidden": True})
    resource_id: str = Field(..., description='The resource id of the resource.', min_length=1, max_length=4096)
    output_parameters: list[Literal['power', 'curtailed_power', 'wind_speed_hub_height', 'wind_direction_hub_height', 'availability', 'curtailment']] | None = Field(None, description='The output parameters to include in the response.')
    period: Literal['PT5M', 'PT10M', 'PT15M', 'PT20M', 'PT30M', 'PT60M'] | None = Field(None, description='Length of the averaging period in ISO 8601 duration format. Default is PT30M.', min_length=1, max_length=4096)
    hours: int | None = Field(None, description='The number of hours to return in the response.', ge=1, le=336)
    request_id: str | None = Field(None, description='Optional request identifier for tracing and log correlation.', min_length=1, max_length=4096)
    issue_time: str | None = Field(None, description='Return the forecast issued at this time (ISO 8601). Must be in the past. When omitted, the latest forecast is returned.', min_length=1, max_length=4096, json_schema_extra={'format': 'date-time'})


class ListPremiumWindResourcesConfig(_Input):
    """List Resources."""
    operation: Literal['list_premium_wind_resources'] = Field('list_premium_wind_resources', json_schema_extra={"ui:hidden": True})
    show_all: bool | None = Field(None, description='When true, returns all sites in the system. Requires admin privileges.')
    query: str | None = Field(None, description='Search query for site name or resource ID.', min_length=1, max_length=4096)
    start: str | None = Field(None, description='Filter to sites created on or after this date (ISO 8601 format).', min_length=1, max_length=4096, json_schema_extra={'format': 'date-time'})
    end: str | None = Field(None, description='Filter to sites created before this date (ISO 8601 format).', min_length=1, max_length=4096, json_schema_extra={'format': 'date-time'})
    forecast_production: bool | None = Field(None, description='Filter to sites where ML forecast production is enabled.')


class GetPremiumWindResourceConfig(_Input):
    """Get Resource."""
    operation: Literal['get_premium_wind_resource'] = Field('get_premium_wind_resource', json_schema_extra={"ui:hidden": True})
    resource_id: str = Field(..., description='The unique identifier of the resource.', min_length=1, max_length=4096)


class ApiPvSiteMeasurement(_Input):
    availability: float | None = Field(None, description='Availability percentage (0-100).', ge=0, le=100)
    curtailment: float | None = Field(None, description='Curtailment ceiling in MW.', ge=0)
    period: str | None = Field(None, description="Duration of the measurement period (ISO-8601 duration, e.g., PT5M). Either 'period' or 'period_start' required.", min_length=1, max_length=4096)
    period_end: str = Field(..., description='End of the measurement period (ISO-8601 with timezone, exclusive).', min_length=1, max_length=4096, json_schema_extra={'format': 'date-time'})
    period_start: str | None = Field(None, description="Start of the measurement period (ISO-8601 with timezone, inclusive). Alternative to 'period'.", min_length=1, max_length=4096, json_schema_extra={'format': 'date-time'})
    power: float = Field(..., description='Power output in MW.', ge=0)

    @model_validator(mode="after")
    def period_present(self):
        if self.period is None and self.period_start is None:
            raise ValueError("Provide period or period_start for every measurement")
        return self


class CreatePvSiteMeasurementsConfig(_Input):
    """Create Site Measurements."""
    operation: Literal['create_pv_site_measurements'] = Field('create_pv_site_measurements', json_schema_extra={"ui:hidden": True})
    measurements: list[ApiPvSiteMeasurement] = Field(..., description='Array of measurement records (1-1000).', min_length=1, max_length=1000)
    resource_id: str = Field(..., description='The unique identifier of the Premium PV Power resource.', min_length=1, max_length=4096)


class GetPvSiteMeasurementsConfig(_Input):
    """Retrieve Site Measurements."""
    operation: Literal['get_pv_site_measurements'] = Field('get_pv_site_measurements', json_schema_extra={"ui:hidden": True})
    resource_id: str = Field(..., description='The unique identifier of the Premium PV Power resource.', min_length=1, max_length=4096)
    start: str | None = Field(None, description='Filter: period_end >= start (ISO-8601).', min_length=1, max_length=4096, json_schema_extra={'format': 'date-time'})
    end: str | None = Field(None, description='Filter: period_end <= end (ISO-8601).', min_length=1, max_length=4096, json_schema_extra={'format': 'date-time'})


class DeletePvSiteMeasurementsConfig(_Input):
    """Delete Site Measurements."""
    operation: Literal['delete_pv_site_measurements'] = Field('delete_pv_site_measurements', json_schema_extra={"ui:hidden": True})
    resource_id: str = Field(..., description='The unique identifier of the Premium PV Power resource.', min_length=1, max_length=4096)
    start: str = Field(..., description='Delete lower bound timestamp (ISO-8601).', min_length=1, max_length=4096, json_schema_extra={'format': 'date-time'})
    end: str = Field(..., description='Delete upper bound timestamp (ISO-8601).', min_length=1, max_length=4096, json_schema_extra={'format': 'date-time'})


class GetResourceScheduleConfig(_Input):
    """Retrieve Current Schedule."""
    operation: Literal['get_resource_schedule'] = Field('get_resource_schedule', json_schema_extra={"ui:hidden": True})
    resource_id: str = Field(..., description='The resource id.', min_length=1, max_length=4096)
    period_start: str = Field(..., description='Start of the query window (ISO 8601). Must be on a 5-minute boundary.', min_length=1, max_length=4096, json_schema_extra={'format': 'date-time'})
    period_end: str = Field(..., description='End of the query window (ISO 8601). Must be on a 5-minute boundary.', min_length=1, max_length=4096, json_schema_extra={'format': 'date-time'})
    issue_time: str | None = Field(None, description='Return the schedule as it existed at this point in time (ISO 8601). When omitted, the latest schedule is returned.', min_length=1, max_length=4096, json_schema_extra={'format': 'date-time'})


class AvailabilityIntervalDto(_Input):
    period_start: str | None = Field(None, description='Start of the availability interval in ISO 8601 format.', min_length=1, max_length=4096, json_schema_extra={'format': 'date-time'})
    period_end: str | None = Field(None, description='End of the availability interval in ISO 8601 format.', min_length=1, max_length=4096, json_schema_extra={'format': 'date-time'})
    availability: float | None = Field(None, description='Availability percentage for the interval, from 0 to 100.', ge=0, le=100)


class CurtailmentIntervalDto(_Input):
    period_start: str | None = Field(None, description='Start of the curtailment interval in ISO 8601 format.', min_length=1, max_length=4096, json_schema_extra={'format': 'date-time'})
    period_end: str | None = Field(None, description='End of the curtailment interval in ISO 8601 format.', min_length=1, max_length=4096, json_schema_extra={'format': 'date-time'})
    curtailment: float | None = Field(None, description='Curtailment power cap for the interval in MW.', ge=0)


class PatchResourceScheduleConfig(_Input):
    """Patch Schedule Intervals."""
    operation: Literal['patch_resource_schedule'] = Field('patch_resource_schedule', json_schema_extra={"ui:hidden": True})
    resource_id: str = Field(..., description='The resource id.', min_length=1, max_length=4096)
    availability_schedule: list[AvailabilityIntervalDto] | None = Field(None, description='Availability schedule entries to merge.', min_length=1, max_length=1000)
    curtailment_schedule: list[CurtailmentIntervalDto] | None = Field(None, description='Curtailment schedule entries to merge.', min_length=1, max_length=1000)


class DeleteResourceScheduleConfig(_Input):
    """Remove Schedule Data."""
    operation: Literal['delete_resource_schedule'] = Field('delete_resource_schedule', json_schema_extra={"ui:hidden": True})
    resource_id: str = Field(..., description='The resource id.', min_length=1, max_length=4096)
    period_start: str = Field(..., description='Start of the delete window (ISO 8601). Must be on a 5-minute boundary.', min_length=1, max_length=4096, json_schema_extra={'format': 'date-time'})
    period_end: str = Field(..., description='End of the delete window (ISO 8601). Must be on a 5-minute boundary.', min_length=1, max_length=4096, json_schema_extra={'format': 'date-time'})
    schedule_type: str = Field(..., description='Comma-separated list of schedule types to delete: availability, curtailment', min_length=1, max_length=4096)


SolcastOperation = Annotated[Union[
    GetForecastAdvancedPvPowerConfig,
    GetLiveAdvancedPvPowerConfig,
    GetHistoricRadiationAndWeatherConfig,
    GetHistoricRooftopPvPowerConfig,
    GetForecastPremiumPvPowerConfig,
    GetLiveRooftopPvPowerConfig,
    GetForecastRooftopPvPowerConfig,
    ListPvPowerResourcesConfig,
    GetPvPowerResourceConfig,
    CreatePvPowerResourceConfig,
    UpdatePvPowerResourceConfig,
    PatchPvPowerResourceConfig,
    DeletePvPowerResourceConfig,
    GetLiveRadiationAndWeatherConfig,
    GetForecastRadiationAndWeatherConfig,
    GetForecastPremiumWindPowerConfig,
    ListPremiumWindResourcesConfig,
    GetPremiumWindResourceConfig,
    CreatePvSiteMeasurementsConfig,
    GetPvSiteMeasurementsConfig,
    DeletePvSiteMeasurementsConfig,
    GetResourceScheduleConfig,
    PatchResourceScheduleConfig,
    DeleteResourceScheduleConfig
], Field(discriminator="operation")]


class SolcastConfig(NodeConfig[SolcastOperation, SolcastAPIKeyCredential]):
    pass


# One explicit provider operation per workflow operation; never accept caller routes.
OPERATIONS = {'get_forecast_advanced_pv_power': ('GET', '/data/forecast/advanced_pv_power'),
 'get_live_advanced_pv_power': ('GET', '/data/live/advanced_pv_power'),
 'get_historic_radiation_and_weather': ('GET', '/data/historic/radiation_and_weather'),
 'get_historic_rooftop_pv_power': ('GET', '/data/historic/rooftop_pv_power'),
 'get_forecast_premium_pv_power': ('GET', '/data/forecast/premium_pv_power'),
 'get_live_rooftop_pv_power': ('GET', '/data/live/rooftop_pv_power'),
 'get_forecast_rooftop_pv_power': ('GET', '/data/forecast/rooftop_pv_power'),
 'list_pv_power_resources': ('GET', '/resources/pv_power_sites'),
 'get_pv_power_resource': ('GET', '/resources/pv_power_site'),
 'create_pv_power_resource': ('POST', '/resources/pv_power_site'),
 'update_pv_power_resource': ('PUT', '/resources/pv_power_site'),
 'patch_pv_power_resource': ('PATCH', '/resources/pv_power_site'),
 'delete_pv_power_resource': ('DELETE', '/resources/pv_power_site'),
 'get_live_radiation_and_weather': ('GET', '/data/live/radiation_and_weather'),
 'get_forecast_radiation_and_weather': ('GET', '/data/forecast/radiation_and_weather'),
 'get_forecast_premium_wind_power': ('GET', '/data/forecast/premium_wind_power'),
 'list_premium_wind_resources': ('GET', '/resources/wind_power_sites'),
 'get_premium_wind_resource': ('GET', '/resources/wind_power_site'),
 'create_pv_site_measurements': ('POST', '/resources/pv_power_site_measurements'),
 'get_pv_site_measurements': ('GET', '/resources/pv_power_site_measurements'),
 'delete_pv_site_measurements': ('DELETE', '/resources/pv_power_site_measurements'),
 'get_resource_schedule': ('GET', '/manage/schedules'),
 'patch_resource_schedule': ('PATCH', '/manage/schedules'),
 'delete_resource_schedule': ('DELETE', '/manage/schedules')}


class SolcastNode(WorkflowNode):
    integration_type = "automation-solcast"
    connection_evidence = ConnectionEvidence(noun="PV power sites", operation="list_pv_power_resources")

    @classmethod
    def get_config_model(cls):
        return SolcastConfig

    async def execute(self, input_data):
        config = self.config
        if not config.credentials:
            raise ValueError("Connect a Solcast API key")
        op = config.config
        method, path = OPERATIONS[op.operation]
        payload = op.model_dump(exclude_none=True, exclude={"operation"}, mode="json")
        headers = {"Authorization": "Bearer " + config.credentials.api_key, "Accept": "application/json"}
        params = {"format": "json"} if method == "GET" else {}
        if method in {"GET", "DELETE"}:
            # OpenAPI form-style query arrays are exploded into repeated keys.
            for name, value in payload.items():
                params[name] = str(value).lower() if isinstance(value, bool) else value
            kwargs = {"params": params}
        else:
            headers["Content-Type"] = "application/json"
            kwargs = {"json": payload}
        try:
            async with guarded_async_client(timeout=30, follow_redirects=False, trust_env=False) as client:
                response = await client.request(method, BASE_URL + path, headers=headers, **kwargs)
        except httpx.HTTPError:
            raise ValueError("Solcast request could not be completed") from None
        if response.status_code >= 300:
            # Preserve provider rejection text for the connect seam, excluding secrets.
            message = response.text[:2000].replace(config.credentials.api_key, "[redacted]")
            raise ValueError(f"Solcast HTTP {response.status_code}: {message}")
        if response.status_code == 204:
            return {"status": "success", "http_status": 204}
        if len(response.content) > 20_000_000:
            raise ValueError("Solcast response exceeds 20 MB; request a shorter period")
        try:
            data = response.json()
        except ValueError:
            raise ValueError("Solcast did not return JSON") from None
        if not isinstance(data, (dict, list)):
            raise ValueError("Unexpected Solcast JSON response")
        if isinstance(data, dict) and isinstance(data.get("response_status"), dict) and data["response_status"].get("error_code"):
            raise ValueError("Solcast: " + str(data["response_status"]).replace(config.credentials.api_key, "[redacted]"))
        return {"status": "success", "data": data, "http_status": response.status_code}
