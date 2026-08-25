"""
Mock tests for the Google Maps Platform REST API node.

Exercises every operation with mocked HTTP responses (no live API calls):
- Geocoding: geocode, reverse geocode, geocode v4 by place ID
- Places (New): text search, nearby search, place details, autocomplete, photo
- Routes: compute routes, compute route matrix
- Legacy routing: directions, distance matrix
- Address validation
- Utilities: time zone, elevation
- Roads: snap to roads, nearest roads
- Legacy places: autocomplete, find place
- Error handling: HTTP API errors, legacy textual status errors, missing credentials
"""

import pytest
from unittest.mock import Mock, patch

from nodes.google_maps_node import (
    GoogleMapsNode,
    GoogleMapsNodeConfig,
    GoogleMapsApiKeyCredential,
    GoogleMapsGeocodeConfig,
    GoogleMapsReverseGeocodeConfig,
    GoogleMapsGeocodeV4Config,
    GoogleMapsTextSearchConfig,
    GoogleMapsNearbySearchConfig,
    GoogleMapsPlaceDetailsConfig,
    GoogleMapsAutocompleteConfig,
    GoogleMapsPlacePhotoConfig,
    GoogleMapsComputeRoutesConfig,
    GoogleMapsComputeRouteMatrixConfig,
    GoogleMapsDirectionsConfig,
    GoogleMapsDistanceMatrixConfig,
    GoogleMapsValidateAddressConfig,
    GoogleMapsTimeZoneConfig,
    GoogleMapsElevationConfig,
    GoogleMapsSnapToRoadsConfig,
    GoogleMapsNearestRoadsConfig,
    GoogleMapsLegacyAutocompleteConfig,
    GoogleMapsFindPlaceConfig,
    GoogleMapsAirQualityCurrentConfig,
    GoogleMapsAirQualityForecastConfig,
    GoogleMapsAirQualityHistoryConfig,
    GoogleMapsPollenForecastConfig,
    GoogleMapsWeatherCurrentConfig,
    GoogleMapsWeatherForecastDaysConfig,
    GoogleMapsWeatherForecastHoursConfig,
    GoogleMapsWeatherHistoryHoursConfig,
    GoogleMapsSolarBuildingInsightsConfig,
    GoogleMapsSolarDataLayersConfig,
    GoogleMapsGeolocateConfig,
    GoogleMapsAerialRenderVideoConfig,
    GoogleMapsAerialLookupVideoConfig,
    GoogleMapsComputeInsightsConfig,
)


@pytest.fixture
def api_key_credentials():
    return GoogleMapsApiKeyCredential(api_key="AIza_test_key_12345")


def create_google_maps_node(config):
    return GoogleMapsNode(
        node_id="test-google-maps-node",
        node_type="automation-google-maps",
        node_data={},
        config=config,
        sio=Mock(),
        sid="test-sid",
        workflow_id="test-workflow",
        user_id="test-user",
    )


def create_mock_response(status_code=200, json_data=None):
    mock_response = Mock()
    mock_response.status_code = status_code
    mock_response.text = ""
    mock_response.json = lambda: (json_data if json_data is not None else {})
    return mock_response


def create_mock_client(status_code=200, json_data=None):
    """Mock httpx.AsyncClient whose .request() returns the mock response and
    which works as an async context manager."""
    mock_response = create_mock_response(status_code, json_data)
    mock_client = Mock()

    async def async_request(*args, **kwargs):
        return mock_response

    mock_client.request = async_request

    async def aenter(self):
        return mock_client

    async def aexit(self, *args):
        return None

    mock_client.__aenter__ = aenter
    mock_client.__aexit__ = aexit
    return mock_client


# ============================================================================
# Geocoding
# ============================================================================


class TestGoogleMapsGeocodingMock:
    @pytest.mark.asyncio
    async def test_geocode(self, api_key_credentials):
        config = GoogleMapsNodeConfig(
            config=GoogleMapsGeocodeConfig(address="1600 Amphitheatre Pkwy"),
            credentials=api_key_credentials,
        )
        node = create_google_maps_node(config)
        body = {"status": "OK", "results": [{"geometry": {"location": {"lat": 37.42, "lng": -122.08}}}]}
        mock_client = create_mock_client(200, body)
        with patch("nodes.google_maps_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "geocode"
        assert result["data"]["results"][0]["geometry"]["location"]["lat"] == 37.42

    @pytest.mark.asyncio
    async def test_reverse_geocode(self, api_key_credentials):
        config = GoogleMapsNodeConfig(
            config=GoogleMapsReverseGeocodeConfig(latlng="37.4224,-122.0841"),
            credentials=api_key_credentials,
        )
        node = create_google_maps_node(config)
        body = {"status": "OK", "results": [{"formatted_address": "Mountain View, CA"}]}
        mock_client = create_mock_client(200, body)
        with patch("nodes.google_maps_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "reverse_geocode"
        assert result["data"]["results"][0]["formatted_address"] == "Mountain View, CA"

    @pytest.mark.asyncio
    async def test_geocode_v4_place(self, api_key_credentials):
        config = GoogleMapsNodeConfig(
            config=GoogleMapsGeocodeV4Config(place_id="ChIJ123"),
            credentials=api_key_credentials,
        )
        node = create_google_maps_node(config)
        mock_client = create_mock_client(200, {"placeId": "ChIJ123", "location": {}})
        with patch("nodes.google_maps_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "geocode_v4_place"
        assert result["data"]["placeId"] == "ChIJ123"


# ============================================================================
# Places (New)
# ============================================================================


class TestGoogleMapsPlacesMock:
    @pytest.mark.asyncio
    async def test_text_search(self, api_key_credentials):
        config = GoogleMapsNodeConfig(
            config=GoogleMapsTextSearchConfig(text_query="pizza in Sydney", max_result_count="5"),
            credentials=api_key_credentials,
        )
        node = create_google_maps_node(config)
        mock_client = create_mock_client(200, {"places": [{"id": "p1"}, {"id": "p2"}]})
        with patch("nodes.google_maps_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "text_search"
        assert len(result["data"]["places"]) == 2

    @pytest.mark.asyncio
    async def test_nearby_search(self, api_key_credentials):
        config = GoogleMapsNodeConfig(
            config=GoogleMapsNearbySearchConfig(
                latitude="37.42", longitude="-122.08", radius="500", included_types="restaurant"
            ),
            credentials=api_key_credentials,
        )
        node = create_google_maps_node(config)
        mock_client = create_mock_client(200, {"places": [{"id": "p1"}]})
        with patch("nodes.google_maps_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "nearby_search"
        assert result["data"]["places"][0]["id"] == "p1"

    @pytest.mark.asyncio
    async def test_place_details(self, api_key_credentials):
        config = GoogleMapsNodeConfig(
            config=GoogleMapsPlaceDetailsConfig(place_id="ChIJ456"),
            credentials=api_key_credentials,
        )
        node = create_google_maps_node(config)
        mock_client = create_mock_client(200, {"id": "ChIJ456", "displayName": {"text": "Cafe"}})
        with patch("nodes.google_maps_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "place_details"
        assert result["data"]["id"] == "ChIJ456"

    @pytest.mark.asyncio
    async def test_autocomplete(self, api_key_credentials):
        config = GoogleMapsNodeConfig(
            config=GoogleMapsAutocompleteConfig(input_text="123 Main"),
            credentials=api_key_credentials,
        )
        node = create_google_maps_node(config)
        mock_client = create_mock_client(200, {"suggestions": [{"placePrediction": {"placeId": "p9"}}]})
        with patch("nodes.google_maps_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "autocomplete"
        assert result["data"]["suggestions"][0]["placePrediction"]["placeId"] == "p9"

    @pytest.mark.asyncio
    async def test_place_photo(self, api_key_credentials):
        config = GoogleMapsNodeConfig(
            config=GoogleMapsPlacePhotoConfig(photo_name="places/p1/photos/photo_ref"),
            credentials=api_key_credentials,
        )
        node = create_google_maps_node(config)
        mock_client = create_mock_client(200, {"photoUri": "https://example.com/img.jpg"})
        with patch("nodes.google_maps_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "place_photo"
        assert result["data"]["photoUri"].endswith(".jpg")


# ============================================================================
# Routes
# ============================================================================


class TestGoogleMapsRoutesMock:
    @pytest.mark.asyncio
    async def test_compute_routes(self, api_key_credentials):
        config = GoogleMapsNodeConfig(
            config=GoogleMapsComputeRoutesConfig(
                origin="37.42,-122.08", destination="37.77,-122.41", travel_mode="DRIVE"
            ),
            credentials=api_key_credentials,
        )
        node = create_google_maps_node(config)
        mock_client = create_mock_client(200, {"routes": [{"distanceMeters": 50000, "duration": "3600s"}]})
        with patch("nodes.google_maps_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "compute_routes"
        assert result["data"]["routes"][0]["distanceMeters"] == 50000

    @pytest.mark.asyncio
    async def test_compute_route_matrix(self, api_key_credentials):
        config = GoogleMapsNodeConfig(
            config=GoogleMapsComputeRouteMatrixConfig(
                origins="37.42,-122.08;37.50,-122.20",
                destinations="37.77,-122.41",
                travel_mode="DRIVE",
            ),
            credentials=api_key_credentials,
        )
        node = create_google_maps_node(config)
        mock_client = create_mock_client(
            200, [{"originIndex": 0, "destinationIndex": 0, "distanceMeters": 1000}]
        )
        with patch("nodes.google_maps_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "compute_route_matrix"
        assert result["data"][0]["distanceMeters"] == 1000


# ============================================================================
# Legacy routing
# ============================================================================


class TestGoogleMapsLegacyRoutingMock:
    @pytest.mark.asyncio
    async def test_directions(self, api_key_credentials):
        config = GoogleMapsNodeConfig(
            config=GoogleMapsDirectionsConfig(
                origin="Toronto", destination="Montreal", mode="driving"
            ),
            credentials=api_key_credentials,
        )
        node = create_google_maps_node(config)
        body = {"status": "OK", "routes": [{"legs": [{"distance": {"text": "541 km"}}]}]}
        mock_client = create_mock_client(200, body)
        with patch("nodes.google_maps_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "directions"
        assert result["data"]["routes"][0]["legs"][0]["distance"]["text"] == "541 km"

    @pytest.mark.asyncio
    async def test_distance_matrix(self, api_key_credentials):
        config = GoogleMapsNodeConfig(
            config=GoogleMapsDistanceMatrixConfig(
                origins="Vancouver", destinations="Seattle", mode="driving"
            ),
            credentials=api_key_credentials,
        )
        node = create_google_maps_node(config)
        body = {"status": "OK", "rows": [{"elements": [{"distance": {"text": "230 km"}}]}]}
        mock_client = create_mock_client(200, body)
        with patch("nodes.google_maps_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "distance_matrix"
        assert result["data"]["rows"][0]["elements"][0]["distance"]["text"] == "230 km"


# ============================================================================
# Address validation
# ============================================================================


class TestGoogleMapsAddressValidationMock:
    @pytest.mark.asyncio
    async def test_validate_address(self, api_key_credentials):
        config = GoogleMapsNodeConfig(
            config=GoogleMapsValidateAddressConfig(
                address_lines="1600 Amphitheatre Pkwy", region_code="US"
            ),
            credentials=api_key_credentials,
        )
        node = create_google_maps_node(config)
        mock_client = create_mock_client(200, {"result": {"verdict": {"addressComplete": True}}})
        with patch("nodes.google_maps_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "validate_address"
        assert result["data"]["result"]["verdict"]["addressComplete"] is True


# ============================================================================
# Utilities
# ============================================================================


class TestGoogleMapsUtilitiesMock:
    @pytest.mark.asyncio
    async def test_timezone(self, api_key_credentials):
        config = GoogleMapsNodeConfig(
            config=GoogleMapsTimeZoneConfig(location="37.4224,-122.0841", timestamp="1331161200"),
            credentials=api_key_credentials,
        )
        node = create_google_maps_node(config)
        body = {"status": "OK", "timeZoneId": "America/Los_Angeles"}
        mock_client = create_mock_client(200, body)
        with patch("nodes.google_maps_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "timezone"
        assert result["data"]["timeZoneId"] == "America/Los_Angeles"

    @pytest.mark.asyncio
    async def test_elevation(self, api_key_credentials):
        config = GoogleMapsNodeConfig(
            config=GoogleMapsElevationConfig(locations="39.7391,-104.9847"),
            credentials=api_key_credentials,
        )
        node = create_google_maps_node(config)
        body = {"status": "OK", "results": [{"elevation": 1608.6}]}
        mock_client = create_mock_client(200, body)
        with patch("nodes.google_maps_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "elevation"
        assert result["data"]["results"][0]["elevation"] == 1608.6


# ============================================================================
# Roads
# ============================================================================


class TestGoogleMapsRoadsMock:
    @pytest.mark.asyncio
    async def test_snap_to_roads(self, api_key_credentials):
        config = GoogleMapsNodeConfig(
            config=GoogleMapsSnapToRoadsConfig(
                path="-35.27801,149.12958|-35.28032,149.12907", interpolate="true"
            ),
            credentials=api_key_credentials,
        )
        node = create_google_maps_node(config)
        mock_client = create_mock_client(200, {"snappedPoints": [{"placeId": "road1"}]})
        with patch("nodes.google_maps_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "snap_to_roads"
        assert result["data"]["snappedPoints"][0]["placeId"] == "road1"

    @pytest.mark.asyncio
    async def test_nearest_roads(self, api_key_credentials):
        config = GoogleMapsNodeConfig(
            config=GoogleMapsNearestRoadsConfig(points="60.170880,24.942795"),
            credentials=api_key_credentials,
        )
        node = create_google_maps_node(config)
        mock_client = create_mock_client(200, {"snappedPoints": [{"placeId": "road2"}]})
        with patch("nodes.google_maps_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "nearest_roads"
        assert result["data"]["snappedPoints"][0]["placeId"] == "road2"


# ============================================================================
# Legacy places
# ============================================================================


class TestGoogleMapsLegacyPlacesMock:
    @pytest.mark.asyncio
    async def test_legacy_autocomplete(self, api_key_credentials):
        config = GoogleMapsNodeConfig(
            config=GoogleMapsLegacyAutocompleteConfig(input_text="Paris"),
            credentials=api_key_credentials,
        )
        node = create_google_maps_node(config)
        body = {"status": "OK", "predictions": [{"description": "Paris, France"}]}
        mock_client = create_mock_client(200, body)
        with patch("nodes.google_maps_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "legacy_autocomplete"
        assert result["data"]["predictions"][0]["description"] == "Paris, France"

    @pytest.mark.asyncio
    async def test_find_place(self, api_key_credentials):
        config = GoogleMapsNodeConfig(
            config=GoogleMapsFindPlaceConfig(input_text="Museum of Modern Art"),
            credentials=api_key_credentials,
        )
        node = create_google_maps_node(config)
        body = {"status": "OK", "candidates": [{"place_id": "cand1"}]}
        mock_client = create_mock_client(200, body)
        with patch("nodes.google_maps_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["action"] == "find_place"
        assert result["data"]["candidates"][0]["place_id"] == "cand1"


# ============================================================================
# Error handling
# ============================================================================


class TestGoogleMapsErrorHandlingMock:
    @pytest.mark.asyncio
    async def test_http_api_error(self, api_key_credentials):
        """New services return standard HTTP error codes with an error object."""
        config = GoogleMapsNodeConfig(
            config=GoogleMapsPlaceDetailsConfig(place_id="missing"),
            credentials=api_key_credentials,
        )
        node = create_google_maps_node(config)
        mock_client = create_mock_client(404, {"error": {"message": "Place not found"}})
        with patch("nodes.google_maps_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "error"
        assert result["status_code"] == 404
        assert "not found" in str(result["error"]).lower()

    @pytest.mark.asyncio
    async def test_legacy_status_error(self, api_key_credentials):
        """Legacy services embed a textual status in a 200 body; REQUEST_DENIED is a hard failure."""
        config = GoogleMapsNodeConfig(
            config=GoogleMapsGeocodeConfig(address="nowhere"),
            credentials=api_key_credentials,
        )
        node = create_google_maps_node(config)
        body = {"status": "REQUEST_DENIED", "error_message": "API key invalid"}
        mock_client = create_mock_client(200, body)
        with patch("nodes.google_maps_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "error"
        assert result["google_status"] == "REQUEST_DENIED"
        assert "invalid" in str(result["error"]).lower()

    @pytest.mark.asyncio
    async def test_legacy_zero_results_is_success(self, api_key_credentials):
        """ZERO_RESULTS is a soft empty result, not a hard error."""
        config = GoogleMapsNodeConfig(
            config=GoogleMapsGeocodeConfig(address="zzzz"),
            credentials=api_key_credentials,
        )
        node = create_google_maps_node(config)
        body = {"status": "ZERO_RESULTS", "results": []}
        mock_client = create_mock_client(200, body)
        with patch("nodes.google_maps_node.httpx.AsyncClient", return_value=mock_client):
            result = await node.execute({})
        assert result["status"] == "success"
        assert result["data"]["status"] == "ZERO_RESULTS"

    @pytest.mark.asyncio
    async def test_missing_credentials(self):
        config = GoogleMapsNodeConfig(
            config=GoogleMapsGeocodeConfig(address="anywhere"), credentials=None
        )
        node = create_google_maps_node(config)
        with pytest.raises(ValueError, match="Credentials are required"):
            await node.execute({})


# ============================================================================
# Request-capturing client (verifies URL / method / auth / body shaping)
# ============================================================================


def create_capturing_client(captured, status_code=200, json_data=None):
    """Mock httpx.AsyncClient that records the request kwargs into `captured`."""
    mock_response = create_mock_response(status_code, json_data)
    mock_client = Mock()

    async def async_request(*args, **kwargs):
        captured.update(kwargs)
        return mock_response

    mock_client.request = async_request

    async def aenter(self):
        return mock_client

    async def aexit(self, *args):
        return None

    mock_client.__aenter__ = aenter
    mock_client.__aexit__ = aexit
    return mock_client


async def _run_capture(node, json_data=None):
    captured = {}
    client = create_capturing_client(captured, 200, json_data if json_data is not None else {})
    with patch("nodes.google_maps_node.httpx.AsyncClient", return_value=client):
        result = await node.execute({})
    return result, captured


# ============================================================================
# Environment: Air Quality
# ============================================================================


class TestGoogleMapsAirQualityMock:
    @pytest.mark.asyncio
    async def test_air_quality_current(self, api_key_credentials):
        config = GoogleMapsNodeConfig(
            config=GoogleMapsAirQualityCurrentConfig(
                latitude="37.42", longitude="-122.08",
                extra_computations="HEALTH_RECOMMENDATIONS,LOCAL_AQI",
            ),
            credentials=api_key_credentials,
        )
        node = create_google_maps_node(config)
        result, cap = await _run_capture(node, {"indexes": [{"aqi": 42}]})
        assert result["status"] == "success"
        assert result["action"] == "air_quality_current"
        # POST + key in query (not header) + nested location body
        assert cap["method"] == "POST"
        assert cap["url"].endswith("/currentConditions:lookup")
        assert cap["params"]["key"] == "AIza_test_key_12345"
        assert "X-Goog-Api-Key" not in cap["headers"]
        assert cap["json"]["location"] == {"latitude": 37.42, "longitude": -122.08}
        assert cap["json"]["extraComputations"] == ["HEALTH_RECOMMENDATIONS", "LOCAL_AQI"]
        assert cap["json"]["universalAqi"] is True

    @pytest.mark.asyncio
    async def test_air_quality_forecast_period(self, api_key_credentials):
        config = GoogleMapsNodeConfig(
            config=GoogleMapsAirQualityForecastConfig(
                latitude="37.42", longitude="-122.08",
                start_time="2026-02-09T08:00:00Z", end_time="2026-02-09T12:00:00Z",
            ),
            credentials=api_key_credentials,
        )
        node = create_google_maps_node(config)
        result, cap = await _run_capture(node, {"hourlyForecasts": []})
        assert result["status"] == "success"
        assert cap["json"]["period"] == {
            "startTime": "2026-02-09T08:00:00Z",
            "endTime": "2026-02-09T12:00:00Z",
        }
        assert "dateTime" not in cap["json"]

    @pytest.mark.asyncio
    async def test_air_quality_forecast_requires_time(self, api_key_credentials):
        config = GoogleMapsNodeConfig(
            config=GoogleMapsAirQualityForecastConfig(latitude="37.42", longitude="-122.08"),
            credentials=api_key_credentials,
        )
        node = create_google_maps_node(config)
        with pytest.raises(ValueError, match="forecast requires a time"):
            await node.execute({})

    @pytest.mark.asyncio
    async def test_air_quality_history_hours(self, api_key_credentials):
        config = GoogleMapsNodeConfig(
            config=GoogleMapsAirQualityHistoryConfig(
                latitude="37.42", longitude="-122.08", hours="4"
            ),
            credentials=api_key_credentials,
        )
        node = create_google_maps_node(config)
        result, cap = await _run_capture(node, {"hoursInfo": []})
        assert result["status"] == "success"
        assert result["action"] == "air_quality_history"
        assert cap["json"]["hours"] == 4

    @pytest.mark.asyncio
    async def test_air_quality_history_requires_time(self, api_key_credentials):
        config = GoogleMapsNodeConfig(
            config=GoogleMapsAirQualityHistoryConfig(latitude="37.42", longitude="-122.08"),
            credentials=api_key_credentials,
        )
        node = create_google_maps_node(config)
        with pytest.raises(ValueError, match="history requires a time"):
            await node.execute({})


# ============================================================================
# Environment: Pollen
# ============================================================================


class TestGoogleMapsPollenMock:
    @pytest.mark.asyncio
    async def test_pollen_forecast(self, api_key_credentials):
        config = GoogleMapsNodeConfig(
            config=GoogleMapsPollenForecastConfig(
                latitude="32.32", longitude="35.32", days="3"
            ),
            credentials=api_key_credentials,
        )
        node = create_google_maps_node(config)
        result, cap = await _run_capture(node, {"dailyInfo": [{"date": {}}]})
        assert result["status"] == "success"
        assert result["action"] == "pollen_forecast"
        # GET + flat dotted query keys + key in query
        assert cap["method"] == "GET"
        assert cap["params"]["location.latitude"] == "32.32"
        assert cap["params"]["location.longitude"] == "35.32"
        assert cap["params"]["days"] == "3"
        assert cap["params"]["key"] == "AIza_test_key_12345"


# ============================================================================
# Environment: Weather
# ============================================================================


class TestGoogleMapsWeatherMock:
    @pytest.mark.asyncio
    async def test_weather_current(self, api_key_credentials):
        config = GoogleMapsNodeConfig(
            config=GoogleMapsWeatherCurrentConfig(
                latitude="37.42", longitude="-122.08", units_system="IMPERIAL"
            ),
            credentials=api_key_credentials,
        )
        node = create_google_maps_node(config)
        result, cap = await _run_capture(node, {"temperature": {"degrees": 20}})
        assert result["status"] == "success"
        assert result["action"] == "weather_current"
        assert cap["method"] == "GET"
        assert cap["url"].endswith("/currentConditions:lookup")
        assert cap["params"]["unitsSystem"] == "IMPERIAL"

    @pytest.mark.asyncio
    async def test_weather_forecast_days(self, api_key_credentials):
        config = GoogleMapsNodeConfig(
            config=GoogleMapsWeatherForecastDaysConfig(
                latitude="37.42", longitude="-122.08", days="3"
            ),
            credentials=api_key_credentials,
        )
        node = create_google_maps_node(config)
        result, cap = await _run_capture(node, {"forecastDays": []})
        assert result["status"] == "success"
        assert cap["url"].endswith("/forecast/days:lookup")
        assert cap["params"]["days"] == "3"

    @pytest.mark.asyncio
    async def test_weather_forecast_hours(self, api_key_credentials):
        config = GoogleMapsNodeConfig(
            config=GoogleMapsWeatherForecastHoursConfig(
                latitude="37.42", longitude="-122.08", hours="6"
            ),
            credentials=api_key_credentials,
        )
        node = create_google_maps_node(config)
        result, cap = await _run_capture(node, {"forecastHours": []})
        assert result["status"] == "success"
        assert cap["url"].endswith("/forecast/hours:lookup")
        assert cap["params"]["hours"] == "6"

    @pytest.mark.asyncio
    async def test_weather_history_hours(self, api_key_credentials):
        config = GoogleMapsNodeConfig(
            config=GoogleMapsWeatherHistoryHoursConfig(
                latitude="37.42", longitude="-122.08", hours="6"
            ),
            credentials=api_key_credentials,
        )
        node = create_google_maps_node(config)
        result, cap = await _run_capture(node, {"historyHours": []})
        assert result["status"] == "success"
        assert cap["url"].endswith("/history/hours:lookup")


# ============================================================================
# Environment: Solar
# ============================================================================


class TestGoogleMapsSolarMock:
    @pytest.mark.asyncio
    async def test_solar_building_insights(self, api_key_credentials):
        config = GoogleMapsNodeConfig(
            config=GoogleMapsSolarBuildingInsightsConfig(
                latitude="37.445", longitude="-122.139", required_quality="HIGH"
            ),
            credentials=api_key_credentials,
        )
        node = create_google_maps_node(config)
        result, cap = await _run_capture(node, {"name": "buildings/123", "solarPotential": {}})
        assert result["status"] == "success"
        assert result["action"] == "solar_building_insights"
        assert cap["url"].endswith("/buildingInsights:findClosest")
        assert cap["params"]["requiredQuality"] == "HIGH"
        assert cap["params"]["location.latitude"] == "37.445"

    @pytest.mark.asyncio
    async def test_solar_data_layers(self, api_key_credentials):
        config = GoogleMapsNodeConfig(
            config=GoogleMapsSolarDataLayersConfig(
                latitude="37.445", longitude="-122.139", radius_meters="100", view="FULL_LAYERS"
            ),
            credentials=api_key_credentials,
        )
        node = create_google_maps_node(config)
        result, cap = await _run_capture(node, {"imageryDate": {}, "dsmUrl": "https://x"})
        assert result["status"] == "success"
        assert cap["url"].endswith("/dataLayers:get")
        assert cap["params"]["radiusMeters"] == "100"
        assert cap["params"]["view"] == "FULL_LAYERS"


# ============================================================================
# Geolocation
# ============================================================================


class TestGoogleMapsGeolocationMock:
    @pytest.mark.asyncio
    async def test_geolocate_ip(self, api_key_credentials):
        config = GoogleMapsNodeConfig(
            config=GoogleMapsGeolocateConfig(consider_ip="true"),
            credentials=api_key_credentials,
        )
        node = create_google_maps_node(config)
        result, cap = await _run_capture(
            node, {"location": {"lat": 37.42, "lng": -122.08}, "accuracy": 1200}
        )
        assert result["status"] == "success"
        assert result["action"] == "geolocate"
        assert cap["method"] == "POST"
        assert cap["json"]["considerIp"] is True
        assert cap["params"]["key"] == "AIza_test_key_12345"

    @pytest.mark.asyncio
    async def test_geolocate_wifi(self, api_key_credentials):
        config = GoogleMapsNodeConfig(
            config=GoogleMapsGeolocateConfig(
                consider_ip="false",
                wifi_access_points='[{"macAddress":"00:11:22:33:44:55"}]',
            ),
            credentials=api_key_credentials,
        )
        node = create_google_maps_node(config)
        result, cap = await _run_capture(node, {"location": {}, "accuracy": 50})
        assert result["status"] == "success"
        assert cap["json"]["considerIp"] is False
        assert cap["json"]["wifiAccessPoints"] == [{"macAddress": "00:11:22:33:44:55"}]

    @pytest.mark.asyncio
    async def test_geolocate_invalid_json(self, api_key_credentials):
        config = GoogleMapsNodeConfig(
            config=GoogleMapsGeolocateConfig(consider_ip="true", cell_towers="{not json"),
            credentials=api_key_credentials,
        )
        node = create_google_maps_node(config)
        with pytest.raises(ValueError, match="Cell Towers must be valid JSON"):
            await node.execute({})


# ============================================================================
# Aerial View (header auth)
# ============================================================================


class TestGoogleMapsAerialViewMock:
    @pytest.mark.asyncio
    async def test_aerial_render_video(self, api_key_credentials):
        config = GoogleMapsNodeConfig(
            config=GoogleMapsAerialRenderVideoConfig(address="500 W 2nd St, Austin, TX 78701"),
            credentials=api_key_credentials,
        )
        node = create_google_maps_node(config)
        result, cap = await _run_capture(node, {"state": "PROCESSING"})
        assert result["status"] == "success"
        assert result["action"] == "aerial_render_video"
        assert cap["method"] == "POST"
        # header auth, NOT query key
        assert cap["headers"]["X-Goog-Api-Key"] == "AIza_test_key_12345"
        assert "key" not in cap["params"]
        assert cap["json"]["address"] == "500 W 2nd St, Austin, TX 78701"

    @pytest.mark.asyncio
    async def test_aerial_lookup_video(self, api_key_credentials):
        config = GoogleMapsNodeConfig(
            config=GoogleMapsAerialLookupVideoConfig(video_id="vid_abc"),
            credentials=api_key_credentials,
        )
        node = create_google_maps_node(config)
        result, cap = await _run_capture(node, {"state": "ACTIVE", "uris": {}})
        assert result["status"] == "success"
        assert cap["method"] == "GET"
        assert cap["params"]["videoId"] == "vid_abc"
        assert cap["headers"]["X-Goog-Api-Key"] == "AIza_test_key_12345"

    @pytest.mark.asyncio
    async def test_aerial_lookup_requires_id_or_address(self, api_key_credentials):
        config = GoogleMapsNodeConfig(
            config=GoogleMapsAerialLookupVideoConfig(),
            credentials=api_key_credentials,
        )
        node = create_google_maps_node(config)
        with pytest.raises(ValueError, match="either a Video ID or an Address"):
            await node.execute({})


# ============================================================================
# Places Aggregate (header auth)
# ============================================================================


class TestGoogleMapsComputeInsightsMock:
    @pytest.mark.asyncio
    async def test_compute_insights_region(self, api_key_credentials):
        config = GoogleMapsNodeConfig(
            config=GoogleMapsComputeInsightsConfig(
                insights="INSIGHT_COUNT,INSIGHT_PLACES",
                included_types="restaurant",
                region_place_id="ChIJabc",
            ),
            credentials=api_key_credentials,
        )
        node = create_google_maps_node(config)
        result, cap = await _run_capture(node, {"count": "42"})
        assert result["status"] == "success"
        assert result["action"] == "compute_insights"
        assert cap["headers"]["X-Goog-Api-Key"] == "AIza_test_key_12345"
        assert cap["json"]["insights"] == ["INSIGHT_COUNT", "INSIGHT_PLACES"]
        assert cap["json"]["filter"]["locationFilter"]["region"]["place"] == "places/ChIJabc"
        assert cap["json"]["filter"]["typeFilter"]["includedTypes"] == ["restaurant"]

    @pytest.mark.asyncio
    async def test_compute_insights_circle_with_rating(self, api_key_credentials):
        config = GoogleMapsNodeConfig(
            config=GoogleMapsComputeInsightsConfig(
                insights="INSIGHT_COUNT",
                included_types="cafe",
                latitude="51.508", longitude="-0.128", radius="200",
                min_rating="4.0",
            ),
            credentials=api_key_credentials,
        )
        node = create_google_maps_node(config)
        result, cap = await _run_capture(node, {"count": "5"})
        assert result["status"] == "success"
        circle = cap["json"]["filter"]["locationFilter"]["circle"]
        assert circle["latLng"] == {"latitude": 51.508, "longitude": -0.128}
        assert circle["radius"] == 200.0
        assert cap["json"]["filter"]["ratingFilter"] == {"minRating": 4.0}

    @pytest.mark.asyncio
    async def test_compute_insights_requires_location(self, api_key_credentials):
        config = GoogleMapsNodeConfig(
            config=GoogleMapsComputeInsightsConfig(
                insights="INSIGHT_COUNT", included_types="restaurant"
            ),
            credentials=api_key_credentials,
        )
        node = create_google_maps_node(config)
        with pytest.raises(ValueError, match="Region Place ID or a circle"):
            await node.execute({})
