"""GraphHopper Directions API v1: fixed routes and pasted API-key authentication.

Request model fields follow the pinned published 1.0.0 OpenAPI contract.
GET coordinates use latitude,longitude strings; JSON coordinates use [longitude, latitude].
Async submissions return job IDs; solution operations perform one poll without retrying writes.
"""
from __future__ import annotations

import httpx

from typing import Annotated, Any, Literal, Union
from urllib.parse import quote

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

BASE = "https://graphhopper.com/api/1"


class GraphhopperAPIKeyCredential(BaseModel):
    model_config = ConfigDict(title="GraphHopper API Key", hide_input_in_errors=True,
        json_schema_extra={"x-credential-url": "https://graphhopper.com/dashboard/",
            "x-credential-instructions": "Create an API key in the GraphHopper dashboard and paste it here. Your plan controls available profiles and API limits. NoClick sends the key only to graphhopper.com. Connection testing reads coverage information and proves reachability, not account identity."})
    credential_type: Literal["graphhopper_api_key"] = Field("graphhopper_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., title="API Key", repr=False, min_length=1, max_length=4096,
        json_schema_extra={"ui:widget": "password"})

    @field_validator("api_key", mode="before")
    @classmethod
    def key(cls, value):
        value = clean_secret(value, field_name="API Key")
        if any(c.isspace() for c in value):
            raise ValueError("Paste the API key without spaces")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True, hide_input_in_errors=True)


class MatrixRequest(_Input):
    fail_fast: bool | None = Field(None, alias='fail_fast', description='Specifies whether or not the matrix calculation should return with an error as soon as possible in case some points cannot be found or some points are not connected. If set to `false` the time/weight/distance matrix will be calculated for all valid points and contain the `null` value for all entries that could not be calculated. The `hint` field of the response will also contain additional information about what went wrong (see its documentation).')
    from_curbsides: list[str] | None = Field(None, alias='from_curbsides', description='See `curbsides`of symmetrical matrix')
    from_point_hints: list[str] | None = Field(None, alias='from_point_hints', description='See `point_hints`of symmetrical matrix')
    from_points: list[list[float]] | None = Field(None, alias='from_points', description='The starting points for the routes in an array of `[longitude,latitude]`. For instance, if you want to calculate three routes from point A such as A->1, A->2, A->3 then you have one `from_point` parameter and three `to_point` parameters.')
    out_arrays: list[str] | None = Field(None, alias='out_arrays', description='Specifies which matrices should be included in the response. Specify one or more of the following options `weights`, `times`, `distances`. The units of the entries of `distances` are meters, of `times` are seconds and of `weights` is arbitrary and it can differ for different vehicles or versions of this API.')
    snap_preventions: list[str] | None = Field(None, alias='snap_preventions', description='See `snap_preventions` of symmetrical matrix')
    to_curbsides: list[str] | None = Field(None, alias='to_curbsides', description='See `curbsides`of symmetrical matrix')
    to_point_hints: list[str] | None = Field(None, alias='to_point_hints', description='See `point_hints`of symmetrical matrix')
    to_points: list[list[float]] | None = Field(None, alias='to_points', description='The destination points for the routes in an array of `[longitude,latitude]`.')
    turn_costs: bool | None = Field(None, alias='turn_costs', description='Specifies if turn restrictions should be considered. Enabling this option increases the matrix computation time. Only supported for motor vehicles and OpenStreetMap.')
    vehicle: Literal['car', 'bike', 'foot', 'hike', 'mtb', 'racingbike', 'scooter', 'truck', 'small_truck'] | None = Field(None, alias='vehicle')

class RouteRequest(_Input):
    algorithm: Literal['round_trip', 'alternative_route'] | None = Field(None, alias='algorithm', description='Rather than looking for the shortest or fastest path, this lets you solve two different problems related to routing:\nWith `round_trip`, the route will get you back to where you started. This is meant for fun (think of\na bike trip), so we will add some randomness. This requires `ch.disable=true`.\nWith `alternative_route`, we give you not one but several routes that are close to optimal, but\nnot too similar to each other. You can control both of these features with additional parameters, see below.\n')
    alternative_route_max_paths: int | None = Field(None, alias='alternative_route.max_paths', description='If `algorithm=alternative_route`, this parameter sets the number of maximum paths which should be calculated. Increasing can lead to worse alternatives.\n')
    alternative_route_max_share_factor: float | None = Field(None, alias='alternative_route.max_share_factor', description='If `algorithm=alternative_route`, this parameter specifies how similar an alternative route can be to the optimal route. Increasing can lead to worse alternatives.\n')
    alternative_route_max_weight_factor: float | None = Field(None, alias='alternative_route.max_weight_factor', description='If `algorithm=alternative_route`, this parameter sets the factor by which the alternatives routes can be longer than the optimal route. Increasing can lead to worse alternatives.\n')
    avoid: str | None = Field(None, alias='avoid', description='Specify which road classes and environments you would like to avoid.\nPossible values are `motorway`, `steps`, `track`, `toll`, `ferry`, `tunnel` and `bridge`.\nSeparate several values with `;`. Obviously not all the values make sense for all vehicle profiles e.g. `bike` is already forbidden on a `motorway`. Requires `ch.disable=true`.\n')
    block_area: str | None = Field(None, alias='block_area', description='Block road access via a point with the format `latitude,longitude`\nor an area defined by a circle `lat,lon,radius` or a rectangle `lat1,lon1,lat2,lon2`.\nSeparate several values with `;`. Requires `ch.disable=true`.\n')
    calc_points: bool | None = Field(None, alias='calc_points', description='If the points for the route should be calculated at all.\n')
    ch_disable: bool | None = Field(None, alias='ch.disable', description='Use this parameter in combination with one or more parameters from below.\n')
    curbsides: list[Literal['any', 'right', 'left']] | None = Field(None, alias='curbsides', description='Optional parameter. It specifies on which side a point should be relative to the driver when she leaves/arrives at a start/target/via point. You need to specify this parameter for either none or all points. Only supported for motor vehicles and OpenStreetMap.')
    debug: bool | None = Field(None, alias='debug', description='If `true`, the output will be formatted.\n')
    details: list[str] | None = Field(None, alias='details', description='Optional parameter to retrieve path details. You can request additional details for the route: `street_name`,\n`time`, `distance`, `max_speed`, `toll`, `road_class`, `road_class_link`, `road_access`, `road_environment`, `lanes`, and `surface`. Read more about the usage of path details [here](https://discuss.graphhopper.com/t/2539).\n')
    elevation: bool | None = Field(None, alias='elevation', description='If `true`, a third coordinate, the altitude, is included with all positions in the response.\nThis changes the format of the `points` and `snapped_waypoints` fields of the response, in both their\nencodings. Unless you switch off the `points_encoded` parameter, you need special code on the\nclient side that can handle three-dimensional coordinates.\nA request can fail if the vehicle profile does not support elevation. See the features object for every vehicle profile.\n')
    heading_penalty: int | None = Field(None, alias='heading_penalty', description='Time penalty in seconds for not obeying a specified heading. Requires `ch.disable=true`.\n')
    headings: list[int] | None = Field(None, alias='headings', description='Favour a heading direction for a certain point. Specify either one heading for the start point or as many as there are points.\nIn this case headings are associated by their order to the specific points. Headings are given as north based clockwise angle between 0 and 360 degree.\nThis parameter also influences the tour generated with `algorithm=round_trip` and forces the initial direction.  Requires `ch.disable=true`.\n')
    instructions: bool | None = Field(None, alias='instructions', description='If instructions should be calculated and returned\n')
    locale: str | None = Field(None, alias='locale', description='The locale of the resulting turn instructions. E.g. `pt_PT` for Portuguese or `de` for German.\n')
    optimize: str | None = Field(None, alias='optimize', description='Normally, the calculated route will visit the points in the order you specified them.\nIf you have more than two points, you can set this parameter to `"true"` and the points may be re-ordered to minimize the total travel time.\nKeep in mind that the limits on the number of locations of the Route Optimization API applies, and the request costs more credits.\n')
    pass_through: bool | None = Field(None, alias='pass_through', description='If `true`, u-turns are avoided at via-points with regard to the `heading_penalty`. Requires `ch.disable=true`.\n')
    point_hints: list[str] | None = Field(None, alias='point_hints', description='Optional parameter. Specifies a hint for each point in the `points` array to prefer a certain street for the closest location lookup. E.g. if there is an address or house with two or more neighboring streets you can control for which street the closest location is looked up.')
    points: list[list[float]] | None = Field(None, alias='points', description='The points for the route in an array of `[longitude,latitude]`. For instance, if you want to calculate a route from point A to B to C\nthen you specify `points: [ [A_longitude, A_latitude], [B_longitude, B_latitude], [C_longitude, C_latitude]]\n')
    points_encoded: bool | None = Field(None, alias='points_encoded', description='Allows changing the encoding of location data in the response. The default is polyline encoding, which is compact\nbut requires special client code to unpack. (We provide it in our JavaScript client library!)\nSet this parameter to `false` to switch the encoding to simple coordinate pairs like `[lon,lat]`, or `[lon,lat,elevation]`.\nSee the description of the response format for more information.\n')
    round_trip_distance: int | None = Field(None, alias='round_trip.distance', description='If `algorithm=round_trip`, this parameter configures approximative length of the resulting round trip. Requires `ch.disable=true`.\n')
    round_trip_seed: int | None = Field(None, alias='round_trip.seed', description='If `algorithm=round_trip`, this sets the random seed. Change this to get a different tour for each value.\n')
    snap_preventions: list[str] | None = Field(None, alias='snap_preventions', description='Optional parameter to avoid snapping to a certain road class or road environment. Current supported values `motorway`, `trunk`, `ferry`, `tunnel`, `bridge` and `ford`')
    vehicle: Literal['car', 'bike', 'foot', 'hike', 'mtb', 'racingbike', 'scooter', 'truck', 'small_truck'] | None = Field(None, alias='vehicle')
    weighting: str | None = Field(None, alias='weighting', description="Determines the way the ''best'' route is calculated. Default is `fastest`. Other options are `shortest` (e.g. for `vehicle=foot` or `bike`) and `short_fastest` which finds a reasonable balance between `shortest` and `fastest`. Requires `ch.disable=true`.\n")

class ClusterRequest(_Input):
    configuration: ClusterConfiguration | None = Field(None, alias='configuration')
    customers: list[ClusterCustomer] | None = Field(None, alias='customers')

class ClusterConfiguration(_Input):
    clustering: ClusterConfigurationClustering | None = Field(None, alias='clustering')
    response_type: str | None = Field(None, alias='response_type', description='Specifies the response format. You can either choose `geojson` or `json`.')
    routing: ClusterConfigurationRouting | None = Field(None, alias='routing')

class ClusterConfigurationClustering(_Input):
    max_quantity: float | None = Field(None, alias='max_quantity', description='Specifies max. quantity in a cluster')
    min_quantity: float | None = Field(None, alias='min_quantity', description='Specifies min. quantity in a cluster')
    num_clusters: float | None = Field(None, alias='num_clusters', description='Specifies the number of clusters')

class ClusterConfigurationRouting(_Input):
    cost_per_meter: float | None = Field(None, alias='cost_per_meter', description='Cost per meter (travel distance)')
    cost_per_second: float | None = Field(None, alias='cost_per_second', description='Cost per second (travel time)')
    profile: str | None = Field(None, alias='profile', description='The routing profile for which the travel times and distances should be calculated. Other profiles are listed [here](#section/Map-Data-and-Routing-Profiles/OpenStreetMap)')

class ClusterCustomer(_Input):
    address: ClusterCustomerAddress | None = Field(None, alias='address')
    id: str | None = Field(None, alias='id', description='id of customer')
    quantity: float | None = Field(None, alias='quantity', description='demand of customer')

class ClusterCustomerAddress(_Input):
    lat: float | None = Field(None, alias='lat', description='Latitude')
    lon: float | None = Field(None, alias='lon', description='Longitude')
    street_hint: str | None = Field(None, alias='street_hint', description='Optional parameter. Specifies a hint for each address to better snap the coordinates (lon,lat) to road network. E.g. if there is an address or house with two or more neighboring streets you can control for which street the closest location is looked up.')

class Request(_Input):
    algorithm: Algorithm | None = Field(None, alias='algorithm')
    configuration: Configuration | None = Field(None, alias='configuration', description='Specifies general configurations.')
    cost_matrices: list[CostMatrix] | None = Field(None, alias='cost_matrices', description='Specifies your own tranport time and distance matrices.')
    objectives: list[Objective] | None = Field(None, alias='objectives', description='Specifies an objective function. The vehicle routing problem is solved in such a way that this objective function is minimized.')
    relations: list[Any] | None = Field(None, alias='relations', description='Defines additional relationships between orders.')
    services: list[Service] | None = Field(None, alias='services', description='Specifies the orders of the type "service". These are, for example, pick-ups, deliveries or other stops that are to be approached by the specified vehicles. Each of these orders contains only one location.')
    shipments: list[Shipment] | None = Field(None, alias='shipments', description='Specifies the available shipments. Each shipment contains a pickup and a delivery stop, which must be processed one after the other.')
    vehicle_types: list[VehicleType] | None = Field(None, alias='vehicle_types', description='Specifies the available vehicle types. These types can be assigned to vehicles.')
    vehicles: list[Vehicle] | None = Field(None, alias='vehicles', description='Specifies the available vehicles.')

class Algorithm(_Input):
    objective: Literal['transport_time', 'completion_time'] | None = Field(None, alias='objective')
    problem_type: Literal['min', 'min-max'] | None = Field(None, alias='problem_type')

class Configuration(_Input):
    routing: Routing | None = Field(None, alias='routing')

class Routing(_Input):
    calc_points: bool | None = Field(None, alias='calc_points', description='It lets you specify whether the API should provide you with route geometries for vehicle routes or not. Thus, you do not need to do extra routing to get the polyline for each route.')
    consider_traffic: bool | None = Field(None, alias='consider_traffic', description='indicates whether historical traffic information should be considered')
    curbside_strictness: Literal['ignore', 'soft', 'strict'] | None = Field(None, alias='curbside_strictness', description='In some cases curbside constraints cannot be fulfilled. For example in one-way streets you cannot arrive at a building that is on the left side of the street such that the building is to the right of you (unless you drove the one-way street the wrong/illegal way). You can set the `curbside_strictness` to `soft` to ignore the curbside constraint in such cases or set it to `strict` to get an error response instead. You can also set it to `ignore` to ignore all curbside constraints (this is useful to compare the results with and without constraints without modifying every single address).')
    fail_fast: bool | None = Field(None, alias='fail_fast', description='indicates whether matrix calculation should fail fast when points cannot be connected')
    network_data_provider: Literal['openstreetmap', 'tomtom'] | None = Field(None, alias='network_data_provider', description='specifies the data provider, read more about it [here](#section/Map-Data-and-Routing-Profiles).')
    return_snapped_waypoints: bool | None = Field(None, alias='return_snapped_waypoints', description='Indicates whether a solution includes snapped waypoints. In contrary to the address coordinate a snapped waypoint is the access point to the (road) network.')
    snap_preventions: list[Literal['motorway', 'trunk', 'bridge', 'ford', 'tunnel', 'ferry']] | None = Field(None, alias='snap_preventions', description='Prevents snapping locations to road links of specified road types, e.g. to motorway.')

class CostMatrix(_Input):
    data: dict[str, Any] | None = Field(None, alias='data', description='JSON data of matrix response')
    location_ids: list[str] | None = Field(None, alias='location_ids')
    profile: str | None = Field(None, alias='profile', description='vehicle profile or empty if catch all fallback')
    type_: Literal['default', 'google'] | None = Field(None, alias='type', description='type of cost matrix, currently default or google are supported')

class Objective(_Input):
    type_: Literal['min', 'min-max'] = Field(..., alias='type', description='Type of objective function, i.e. `min` or `min-max`.\n\n * `min`: Minimizes the objective value.\n * `min-max`: Minimizes the maximum objective value.\n\nFor instance, `min` -> `vehicles` minimizes the number of employed vehicles.\n`min` -> `completion_time` minimizes the sum of your vehicle routes\' completion time.\n\nIf you use, for example, `min-max` -> `completion_time`, it minimizes the maximum of your vehicle routes\' completion time, i.e. it minimizes the overall makespan.\nThis only makes sense if you have more than one vehicle. In case of one vehicle, switching from `min` to `min-max` should not have any impact.\nIf you have more than one vehicle, then the algorithm tries to constantly move stops from one vehicle to another such that\nthe completion time of longest vehicle route can be further reduced. For example, if you have one vehicle that takes 8 hours\nto serve all customers, adding another vehicle (and using `min-max`) might halve the time to serve all customers to 4 hours. However,\nthis usually comes with higher transport costs.\n\nIf you want to minimize `vehicles` first and, second, `completion_time`, you can also combine different objectives like this:\n\n```json\n"objectives" : [\n   {\n      "type": "min",\n      "value": "vehicles"\n   },\n   {\n      "type": "min",\n      "value": "completion_time"\n   }\n]\n```\n\nIf you want to balance activities or the number of stops among all employed drivers, you need to specify it as follows:\n\n```json\n"objectives" : [\n   {\n      "type": "min-max",\n      "value": "completion_time"\n   },\n   {\n      "type": "min-max",\n      "value": "activities"\n   }\n]\n```\n')
    value: Literal['completion_time', 'transport_time', 'vehicles', 'activities'] = Field(..., alias='value', description="The value of the objective function.\nThe objective value `transport_time` solely considers the time\nyour drivers spend on the road, i.e. transport time. In contrary to `transport_time`, `completion_time` also takes waiting times at customer sites into account.\nThe `completion_time` of a route is defined as the time from starting to ending the route,\ni.e. the route's transport time, the sum of waiting times plus the sum of activity durations.\nNote that choosing `transport_time` or `completion_time` only makes a difference if you specified time windows for your services/shipments since only in\nscenarios with time windows waiting times can occur.\nThe objective value `vehicles` can only be used along with `min` and minimizes vehicles.\n")

class JobRelation(_Input):
    ids: list[str] = Field(..., alias='ids', description='Specifies an array of shipment and/or service ids that are in relation. If you deal with services then you need to use the id of your services in ids. To also consider sequences of the pickups and deliveries of your shipments, you need to use a special ID, i.e. use your shipment id plus the keyword `_pickup` or `_delivery`. If you want to place a service or shipment activity at the beginning of your route, use the special ID `start`. In turn, use `end` to place it at the end of the route.')
    type_: str = Field(..., alias='type', description='Specifies the type of relation. It must be either of type `in_same_route`, `in_sequence` or `in_direct_sequence`.\n\n`in_same_route`: As the name suggest, it enforces the specified services or shipments to be in the same route. It can be specified as follows:\n\n```json\n{\n   "type": "in_same_route",\n   "ids": ["serv_i_id","serv_j_id"]\n}\n```\n\nThis enforces service i to be in the same route as service j no matter which vehicle will be employed. If a specific vehicle (driver) is required to conduct this, just add a `vehicle_id` like this:\n\n```\n{\n   "type": "in_same_route",\n   "ids": ["serv_i_id","serv_j_id"],\n   "vehicle_id": "vehicle1"\n}\n```\n\nThis not only enforce service i and j to be in the same route, but also makes sure that both services are in the route of `vehicle1`.\n\n*Tip*: This way initial loads and vehicle routes can be modelled. For example, if your vehicles are already on the road and new orders come in, then vehicles can still be rescheduled subject to the orders that have already been assigned to these vehicles.\n\n\n\n`in_sequence`: This relation type enforces n jobs to be in sequence. It can be specified as\n\n```json\n{\n   "type": "in_sequence",\n   "ids": ["serv_i_id","serv_j_id"]\n}\n```\n\nwhich means that service j need to be in the same route as service i AND it needs to occur somewhere after service i. As described above if a specific vehicle needs to conduct this, just add `vehicle_id`.\n\n\n`in_direct_sequence`: This enforces n services or shipments to be in direct sequence. It can be specified as\n\n```json\n{\n   "type": "in_direct_sequence",\n   "ids": ["serv_i_id","serv_j_id","serv_k_id"]\n}\n```\n\nyielding service j to occur directly after service i, and service k to occur directly after service j i.e. in strong order. Again, a vehicle can be assigned a priority by adding a `vehicle_id` to the relation.\n\n\n*Special IDs*:\nIf you look at the previous example and you want service i to be the first in the route, use the special ID `start` as follows:\n\n```json\n{\n   "type": "in_direct_sequence",\n   "ids": ["start","serv_i_id","serv_j_id","serv_k_id"]\n}\n```\n\nLatter enforces the direct sequence of i, j and k at the beginning of the route. If this sequence should be bound to the end of the route, use the special ID `end` like this:\n\n```json\n{\n   "type": "in_direct_sequence",\n   "ids": ["serv_i_id","service_j_id","serv_k_id","end"]\n}\n```\n\nIf you deal with services then you need to use the \'id\' of your services in the field \'ids\'. To also consider sequences of the pickups and deliveries of your shipments, you need to use a special ID, i.e. use the shipment id plus the keyword `_pickup` or `_delivery`. For example, to ensure that the pickup and delivery of the shipment with the id \'my_shipment\' are direct neighbors, you need the following specification:\n\n```\n{\n   "type": "in_direct_sequence",\n   "ids": ["my_ship_pickup","my_ship_delivery"]\n}\n```\n\n')
    vehicle_id: str | None = Field(None, alias='vehicle_id', description='Id of pre-assigned vehicle, i.e. the vehicle id that is determined to conduct the services and shipments in this relation.')

class GroupRelation(_Input):
    groups: list[str] = Field(..., alias='groups', description='An array of groups that should be related')
    type_: str = Field(..., alias='type', description='Specifies the type of relation. It must be either of type `in_sequence` or `in_direct_sequence`.\n')

class Service(_Input):
    address: Address | None = Field(None, alias='address')
    allowed_vehicles: list[str] | None = Field(None, alias='allowed_vehicles', description='Specifies an array of allowed vehicles, i.e. array of vehicle ids. For example, if this service can only be conducted EITHER by `technician_peter` OR `technician_stefan` specify this as follows: `["technician_peter","technician_stefan"]`.')
    disallowed_vehicles: list[str] | None = Field(None, alias='disallowed_vehicles', description='Specifies an array of disallowed vehicles, i.e. array of vehicle ids.')
    duration: int | None = Field(None, alias='duration', description='Specifies the duration of the service in seconds, i.e. how long it takes at the customer site.')
    group: str | None = Field(None, alias='group', description='Group this service belongs to. See the group relation and [this post](https://discuss.graphhopper.com/t/4040) on how to utilize this.')
    id: str = Field(..., alias='id', description='Specifies the id of the service. Ids need to be unique so there must not be two services/shipments with the same id.')
    max_time_in_vehicle: int | None = Field(None, alias='max_time_in_vehicle', description='Specifies the maximum time in seconds a delivery can stay in the vehicle. Currently, it only works with services of "type":"delivery".')
    name: str | None = Field(None, alias='name', description='Meaningful name for service, e.g. `"deliver pizza"`.')
    preparation_time: int | None = Field(None, alias='preparation_time', description='Specifies the preparation time in seconds. It can be used to model parking lot search time since if you have 3 identical locations in a row, it only falls due once.')
    priority: int | None = Field(None, alias='priority', description='Specifies the priority. Can be 1 = high priority to 10 = low priority. Often there are more services/shipments than the available vehicle fleet can handle. Then you can set priorities to differentiate high priority tasks from those that could be left unassigned. I.e. the lower the priority the earlier these tasks are omitted in the solution.')
    required_skills: list[str] | None = Field(None, alias='required_skills', description='Specifies an array of required skills, i.e. array of string (not case sensitive). For example, if this service needs to be conducted by a technician having a `drilling_machine` and a `screw_driver` then specify the array as follows: `["drilling_machine","screw_driver"]`. This means that the service can only be done by a vehicle (technician) that has the skills `drilling_machine` AND `screw_driver` in its skill array. Otherwise it remains unassigned.')
    size: list[int] | None = Field(None, alias='size', description='Size can have multiple dimensions and should be in line with the capacity dimension array of the vehicle type. For example, if the item that needs to be delivered has two size dimension, volume and weight, then specify it as follow [ 20, 5 ] assuming a volume of 20 and a weight of 5.')
    time_windows: list[TimeWindow] | None = Field(None, alias='time_windows', description='Specifies an array of time window objects (see time_window object below). Specify the time either with the recommended Unix time stamp (the number of seconds since 1970-01-01) or you can also count the seconds relative to Monday morning 00:00 and define the whole week in seconds. For example, Monday 9am is then represented by 9hour * 3600sec/hour = 32400. In turn, Wednesday 1pm corresponds to 2day * 24hour/day * 3600sec/hour + 1day * 13hour/day * 3600sec/hour = 219600. See this tutorial for more information.')
    type_: Literal['service', 'pickup', 'delivery'] | None = Field(None, alias='type', description='Specifies type of service. This makes a difference if items are loaded or unloaded, i.e. if one of the size dimensions > 0. If it is specified as `service` or `pickup`, items are loaded and will stay in the vehicle for the rest of the route (and thus consumes capacity for the rest of the route). If it is a `delivery`, items are implicitly loaded at the beginning of the route and will stay in the route until delivery (and thus releases capacity for the rest of the route).')

class Address(_Input):
    curbside: Literal['right', 'left', 'any'] | None = Field(None, alias='curbside', description='Optional parameter. Specifies on which side a point should be relative to the driver when she leaves/arrives at a start/target/via point. Only supported for motor vehicles and OpenStreetMap.')
    lat: float = Field(..., alias='lat', description='Latitude of location.')
    location_id: str = Field(..., alias='location_id', description='Specifies the id of the location.')
    lon: float = Field(..., alias='lon', description='Longitude of location.')
    name: str | None = Field(None, alias='name', description='Name of location.')
    street_hint: str | None = Field(None, alias='street_hint', description='Optional parameter. Specifies a hint for each address to better snap the coordinates (lon,lat) to road network. E.g. if there is an address or house with two or more neighboring streets you can control for which street the closest location is looked up.')

class TimeWindow(_Input):
    earliest: int | None = Field(None, alias='earliest', description='Specifies the opening time of the time window in seconds, i.e. the earliest time the service can start.')
    latest: int | None = Field(None, alias='latest', description='Specifies the closing time of the time window in seconds, i.e. the latest time the service can start.')

class Shipment(_Input):
    allowed_vehicles: list[str] | None = Field(None, alias='allowed_vehicles', description='Specifies an array of allowed vehicles, i.e. array of vehicle ids. For example, if this shipment can only be conducted EITHER by "technician_peter" OR "technician_stefan" specify this as follows: ["technician_peter","technician_stefan"].')
    delivery: Stop = Field(..., alias='delivery')
    disallowed_vehicles: list[str] | None = Field(None, alias='disallowed_vehicles', description='Specifies an array of disallowed vehicles, i.e. array of vehicle ids.')
    id: str = Field(..., alias='id', description='Specifies the id of the shipment. Ids need to be unique so there must not be two services/shipments with the same id.')
    max_time_in_vehicle: int | None = Field(None, alias='max_time_in_vehicle', description='Specifies the maximum time in seconds a shipment can stay in the vehicle.')
    name: str | None = Field(None, alias='name', description='Meaningful name for shipment, e.g. "pickup and deliver pizza to Peter".')
    pickup: Stop = Field(..., alias='pickup')
    priority: int | None = Field(None, alias='priority', description='Specifies the priority. Can be 1 = high priority to 10 = low priority. Often there are more services/shipments than the available vehicle fleet can handle. Then you can set priorities to differentiate high priority tasks from those that could be left unassigned. I.e. the lower the priority the earlier these tasks are omitted in the solution.')
    required_skills: list[str] | None = Field(None, alias='required_skills', description='Specifies an array of required skills, i.e. array of string (not case sensitive). For example, if this shipment needs to be conducted by a technician having a `drilling_machine` and a `screw_driver` then specify the array as follows: `["drilling_machine","screw_driver"]`. This means that the service can only be done by a vehicle (technician) that has the skills `drilling_machine` AND `screw_driver` in its skill array. Otherwise it remains unassigned.')
    size: list[int] | None = Field(None, alias='size', description='Size can have multiple dimensions and should be in line with the capacity dimension array of the vehicle type. For example, if the item that needs to be delivered has two size dimension, volume and weight, then specify it as follow [ 20, 5 ] assuming a volume of 20 and a weight of 5.')

class Stop(_Input):
    address: Address | None = Field(None, alias='address', description='Specifies pickup or delivery address.')
    duration: int | None = Field(None, alias='duration', description='Specifies the duration of the pickup or delivery in seconds, e.g. how long it takes unload items at the customer site.')
    group: str | None = Field(None, alias='group', description='Group this stop belongs to. See the group relation and [this post](https://discuss.graphhopper.com/t/4040) on how to utilize this.')
    preparation_time: int | None = Field(None, alias='preparation_time', description='Specifies the preparation time in seconds. It can be used to model parking lot search time since if you have 3 identical locations in a row, it only falls due once.')
    time_windows: list[TimeWindow] | None = Field(None, alias='time_windows', description='Specifies an array of time window objects (see time window object below). For example, if an item needs to be delivered between 7am and 10am then specify the array as follows: [ { "earliest": 25200, "latest" : 32400 } ] (starting the day from 0 in seconds).')

class VehicleType(_Input):
    capacity: list[int] | None = Field(None, alias='capacity', description='Specifies an array of capacity dimension values which need to be int values. For example, if there are two dimensions such as volume and weight then it needs to be defined as [ 1000, 300 ] assuming a maximum volume of 1000 and a maximum weight of 300.')
    consider_traffic: bool | None = Field(None, alias='consider_traffic', description='Specifies whether traffic should be considered. if "tomtom" is used and this is false, free flow travel times from "tomtom" are calculated. If this is true, historical traffic info are used. We do not yet have traffic data for "openstreetmap", thus, setting this true has no effect at all.')
    cost_per_activation: float | None = Field(None, alias='cost_per_activation', description='**_BETA feature_**! Cost parameter vehicle activation, i.e. fixed costs per vehicle')
    cost_per_meter: float | None = Field(None, alias='cost_per_meter', description='**_BETA feature_**! Cost parameter per distance unit, here meter is used')
    cost_per_second: float | None = Field(None, alias='cost_per_second', description='**_BETA feature_**! Cost parameter per time unit, here second is used')
    network_data_provider: Literal['openstreetmap', 'tomtom'] | None = Field(None, alias='network_data_provider', description='Specifies the network data provider. Either use [`openstreetmap`](#section/Map-Data-and-Routing-Profiles/OpenStreetMap) (default) or [`tomtom`](#section/Map-Data-and-Routing-Profiles/TomTom) (add-on required).')
    profile: Literal['car', 'bike', 'foot', 'hike', 'mtb', 'racingbike', 'scooter', 'truck', 'small_truck'] | None = Field(None, alias='profile')
    service_time_factor: float | None = Field(None, alias='service_time_factor', description='Specifies a service time factor for this vehicle type. If the vehicle/driver that uses this type is able to conduct the service as double as fast as it is determined in the corresponding service or shipment then set it to 0.5.')
    speed_factor: float | None = Field(None, alias='speed_factor', description='Specifies a speed factor for this vehicle type. If the vehicle that uses this type needs to be only half as fast as what is actually calculated with our routing engine then set the speed factor to 0.5.')
    type_id: str = Field(..., alias='type_id', description='Specifies the id of the vehicle type. If a vehicle needs to be of this type, it should refer to this with its type_id attribute.')

class Vehicle(_Input):
    break_: Any | None = Field(None, alias='break')
    earliest_start: int | None = Field(None, alias='earliest_start', description='Earliest start of vehicle in seconds. It is recommended to use the unix timestamp.')
    end_address: Address | None = Field(None, alias='end_address', description='If this is omitted AND return_to_depot is true then the vehicle needs to return to its start_address.')
    latest_end: int | None = Field(None, alias='latest_end', description='Latest end of vehicle in seconds, i.e. the time the vehicle needs to be at its end location at latest.')
    max_activities: int | None = Field(None, alias='max_activities', description='Specifies the maximum number of activities a vehicle can conduct.')
    max_distance: int | None = Field(None, alias='max_distance', description='Specifies the maximum distance (in meters) a vehicle can go.')
    max_driving_time: int | None = Field(None, alias='max_driving_time', description='Specifies the maximum drive time (in seconds) a vehicle/driver can go, i.e. the maximum time on the road (service and waiting times are not included here)')
    max_jobs: int | None = Field(None, alias='max_jobs', description='Specifies the maximum number of jobs a vehicle can load.')
    min_jobs: int | None = Field(None, alias='min_jobs', description='Specifies the minimum number of jobs a vehicle should load. This is a soft constraint, i.e. if it is not possible to fulfill “min_jobs”, we will still try to get as close as possible to this constraint.')
    move_to_end_address: bool | None = Field(None, alias='move_to_end_address', description='Indicates whether a vehicle should be moved even though it has not been assigned any jobs.')
    return_to_depot: bool | None = Field(None, alias='return_to_depot', description="If it is false, the algorithm decides where to end the vehicle route. It ends in one of your customers' locations. The end is chosen such that it contributes to the overall objective function, e.g. min transport_time. If it is true, you can either specify a specific end location (which is then regarded as end depot) or you can leave it and the driver returns to its start location.")
    skills: list[str] | None = Field(None, alias='skills', description='Array of skills, i.e. array of string (not case sensitive).')
    start_address: Address = Field(..., alias='start_address')
    type_id: str | None = Field(None, alias='type_id', description='The type ID assigns a vehicle type to this vehicle. You can specify types in the array of vehicle types. If you omit the type ID, the default type is used. The default type is a `car` with a capacity of 0.')
    vehicle_id: str = Field(..., alias='vehicle_id', description='Specifies the ID of the vehicle. Ids must be unique, i.e. if there are two vehicles with the same ID, an error is returned.')

class TimeWindowBreak(_Input):
    duration: int = Field(..., alias='duration', description='Specifies the duration of the break in seconds.')
    earliest: int = Field(..., alias='earliest', description='Specifies the earliest start time of the break in seconds.')
    latest: int = Field(..., alias='latest', description='Specifies the latest start time of break in seconds.')

class DriveTimeBreak(_Input):
    duration: int = Field(..., alias='duration', description='Specifies the duration of the break in seconds.')
    initial_driving_time: int | None = Field(None, alias='initial_driving_time', description='Specifies the initial (current) driving time of a driver to allow dynamic adaptations in seconds.')
    max_driving_time: int = Field(..., alias='max_driving_time', description='Specifies the max driving time (in a row) without break in seconds.')
    possible_split: list[int] | None = Field(None, alias='possible_split', description='Array specifying how a break duration (in seconds) can be split into several smaller breaks')

MatrixRequest.model_rebuild()

RouteRequest.model_rebuild()

ClusterRequest.model_rebuild()

ClusterConfiguration.model_rebuild()

ClusterConfigurationClustering.model_rebuild()

ClusterConfigurationRouting.model_rebuild()

ClusterCustomer.model_rebuild()

ClusterCustomerAddress.model_rebuild()

Request.model_rebuild()

Algorithm.model_rebuild()

Configuration.model_rebuild()

Routing.model_rebuild()

CostMatrix.model_rebuild()

Objective.model_rebuild()

JobRelation.model_rebuild()

GroupRelation.model_rebuild()

Service.model_rebuild()

Address.model_rebuild()

TimeWindow.model_rebuild()

Shipment.model_rebuild()

Stop.model_rebuild()

VehicleType.model_rebuild()

Vehicle.model_rebuild()

TimeWindowBreak.model_rebuild()

DriveTimeBreak.model_rebuild()


class GeocodeConfig(_Input):
    """Geocoding Endpoint."""
    operation: Literal['geocode'] = Field('geocode', json_schema_extra={"ui:hidden": True})
    q: str | None = Field(None, alias='q', description='If you do forward geocoding, this is `required` and is a textual description of the address you are looking for.')
    locale: str | None = Field(None, alias='locale', description="Display the search results for the specified locale. Currently French (fr), English (en), German (de) and Italian (it) are supported. If the locale wasn't found the default (en) is used.")
    limit: int | None = Field(None, alias='limit', description='Specify the maximum number of results to return')
    reverse: bool | None = Field(None, alias='reverse', description='It is `required` to be `true` if you want to do a reverse geocoding request. If it is `true`, `point` must be defined as well, and `q` must not be used.')
    debug: bool | None = Field(None, alias='debug', description='If `true`, the output will be formatted.')
    point: str | None = Field(None, alias='point', description="_Forward geocoding_: The location bias in the format 'latitude,longitude' e.g. point=45.93272,11.58803. _Reverse geocoding_: The location to find amenities, cities.")
    provider: str | None = Field(None, alias='provider', description='The provider parameter is currently under development and can fall back to `default` at any time.\nThe intend is to provide alternatives to our default geocoder. Each provider has its own strenghts and might fit better for certain scenarios, so it\'s worth to compare the different providers.\nTo try it append the `provider`parameter to the URL like `&provider=nominatim`,\nthe result structure should be identical in all cases - if not, please report this back to us.\nKeep in mind that some providers do not support certain parameters or don\'t return some fields, for example `osm_id` and `osm_type` are not supported by every geocoding provider.\nIf you would like to use additional parameters of one of the providers, but it\'s not available for the GraphHopper Geocoding API, yet? Please contact us.\n\nThe credit costs can be different for all providers - see [here](https://support.graphhopper.com/support/solutions/articles/44000718211-what-is-one-credit-) for more information about it.\n\nCurrently, only the default provider and gisgraphy supports autocompletion of partial search strings.\n\nAll providers support normal "forward" geocoding and reverse geocoding via `reverse=true`.\n\n#### Default (`provider=default`)\n\nThis provider returns results of our internal geocoding engine, as described above.\nIn addition to the above documented parameters the following parameters are possible:\n* `bbox` - the expected format is `minLon,minLat,maxLon,maxLat`\n* `osm_tag` - you can filter `key:value` or exclude places with certain OpenStreetMap tags `!key:value`. E.g. `osm_tag=tourism:museum` or just the key `osm_tag=tourism`. To exclude multiple tags you add multiple `osm_tag` parameters.\n\n#### Nominatim (`provider=nominatim`)\n\nThe GraphHopper Directions API uses a commercially hosted Nominatim geocoder. You can try this provider [here](https://nominatim.openstreetmap.org/). The provider does **not** fall under the [restrictions](https://operations.osmfoundation.org/policies/nominatim/) of the Nominatim instance hosted by OpenStreetMap.\n\nIn addition to the above documented parameters Nominatim allows to use the following parameters, which can be used as documented [here](https://github.com/openstreetmap/Nominatim/blob/master/docs/api/Search.md#parameters):\n\n* `viewbox` - the expected format is `minLon,minLat,maxLon,maxLat`\n* `bounded` - If 1 and a viewbox is given, restrict the result to items contained within that viewbox. Default is 0.\n\n#### Gisgraphy (`provider=gisgraphy`)\n\nThis provider returns results from the Gisgraphy geocoder which you can try [here](https://services.gisgraphy.com/static/leaflet/index.html).\n\n**Limitations:** The `locale` parameter is not supported. Gisgraphy does not return OSM tags or an extent.\n\nGisgraphy has a special autocomplete API, which you can use by adding `autocomplete=true` (does not work with `reverse=true`). The autocomplete API is optimized on predicting text input, but returns less information.\n\nIn addition to the above documented parameters Gisgraphy allows to use the following parameters, which can be used as documented [here](https://www.gisgraphy.com/documentation/user-guide.php#geocodingservice):\n\n* `radius` - radius in meters\n* `country` - restrict search for the specified country. The value must be the ISO 3166 Alpha 2 code of the country.\n\n#### NetToolKit (`provider=nettoolkit`)\n\nThis provider returns results from the NetToolKit provider which is specialized for US addresses and provides a wrapper around Nominatim for other addresses. You can try it [here](https://www.nettoolkit.com/geo/demo).\n\nThe following additional NetToolKit parameters are supported (read [here](https://www.nettoolkit.com/docs/geo/geocoding) for more details):\n- `source`: User can choose which source provider to geocode the address, this value is "NetToolKit" by default\n- `country_code`: an iso-3166-2 country code (e.g : US) filter the results to the specify country code\n\n**Limitations:** NetToolKit does not support the `locale` parameter. NetToolKit does not return OSM tags (e.g. osm_id, osm_type, osm_value).\n\n#### OpenCage Data (`provider=opencagedata`)\n\nThis provider returns results from the OpenCageData geocoder which you can try [here](https://geocoder.opencagedata.com/demo).\n\nIn addition to the above documented parameters OpenCage Data allows to use the following parameters, which can be used as documented [here](https://geocoder.opencagedata.com/api#forward-opt):\n\n* countrycode - The country code is a two letter code as defined by the ISO 3166-1 Alpha 2 standard. E.g. gb for the United Kingdom, fr for France, us for United States. \n* bounds - the expected format is `minLon,minLat,maxLon,maxLat`\n')

    @model_validator(mode="after")
    def query_or_point(self):
        if self.reverse and not self.point:
            raise ValueError("Reverse geocoding requires point as latitude,longitude")
        if not self.reverse and not self.q:
            raise ValueError("Forward geocoding requires a search query")
        return self


class GetIsochroneConfig(_Input):
    """Isochrone Endpoint."""
    operation: Literal['get_isochrone'] = Field('get_isochrone', json_schema_extra={"ui:hidden": True})
    point: str = Field(..., alias='point', description='Specify the start coordinate')
    time_limit: int | None = Field(None, alias='time_limit', description='Specify which time the vehicle should travel. In seconds.')
    distance_limit: int | None = Field(None, alias='distance_limit', description='Specify which distance the vehicle should travel. In meters.')
    vehicle: Literal['car', 'bike', 'foot', 'hike', 'mtb', 'racingbike', 'scooter', 'truck', 'small_truck'] | None = Field(None, alias='vehicle', description='The vehicle profile for which the route should be calculated.\n')
    buckets: int | None = Field(None, alias='buckets', description='Number by which to divide the given `time_limit` to create `buckets` nested isochrones of time intervals `time_limit-n*time_limit/buckets`. Applies analogously to `distance_limit`.')
    reverse_flow: bool | None = Field(None, alias='reverse_flow', description='If `false` the flow goes from point to the polygon, if `true` the flow goes from the polygon "inside" to the point.\nExample use case for `false`&#58; *How many potential customer can be reached within 30min travel time from your store* vs. `true`&#58; *How many customers can reach your store within 30min travel time.*\n')
    weighting: Literal['fastest', 'shortest'] | None = Field(None, alias='weighting', description='Use `"shortest"` to get an isodistance line instead of an isochrone.')


class GetMatrixConfig(_Input):
    """GET Matrix Endpoint."""
    operation: Literal['get_matrix'] = Field('get_matrix', json_schema_extra={"ui:hidden": True})
    point: list[str] | None = Field(None, alias='point', description='Specify multiple points in `latitude,longitude` for which the weight-, route-, time- or distance-matrix should be calculated. In this case the starts are identical to the destinations. If there are N points, then NxN entries will be calculated. The order of the point parameter is important. Specify at least three points. Cannot be used together with from_point or to_point.')
    from_point: list[str] | None = Field(None, alias='from_point', description='The starting points for the routes in `latitude,longitude`. E.g. if you want to calculate the three routes A-&gt;1, A-&gt;2, A-&gt;3 then you have one from_point parameter and three to_point parameters.')
    to_point: list[str] | None = Field(None, alias='to_point', description='The destination points for the routes in `latitude,longitude`.')
    point_hint: list[str] | None = Field(None, alias='point_hint', description='Optional parameter. Specifies a hint for each `point` parameter to prefer a certain street for the closest location lookup. E.g. if there is an address or house with two or more neighboring streets you can control for which street the closest location is looked up.')
    from_point_hint: list[str] | None = Field(None, alias='from_point_hint', description='For the from_point parameter. See point_hint')
    to_point_hint: list[str] | None = Field(None, alias='to_point_hint', description='For the to_point parameter. See point_hint')
    snap_prevention: list[str] | None = Field(None, alias='snap_prevention', description='Optional parameter to avoid snapping to a certain road class or road environment. Current supported values `motorway`, `trunk`, `ferry`, `tunnel`, `bridge` and `ford`. Multiple values are specified like `snap_prevention=ferry&snap_prevention=motorway`\n')
    curbside: list[Literal['any', 'right', 'left']] | None = Field(None, alias='curbside', description='Optional parameter. It specifies on which side a point should be relative to the driver when she leaves/arrives at a start/target/via point. You need to specify this parameter for either none or all points. Only supported for motor vehicles and OpenStreetMap.')
    from_curbside: list[Literal['any', 'right', 'left']] | None = Field(None, alias='from_curbside', description='Curbside setting for the from_point parameter. See curbside.')
    to_curbside: list[Literal['any', 'right', 'left']] | None = Field(None, alias='to_curbside', description='Curbside setting for the to_point parameter. See curbside.')
    out_array: list[str] | None = Field(None, alias='out_array', description="Specifies which arrays should be included in the response. Specify one or more of the following options 'weights', 'times', 'distances'. To specify more than one array use e.g. out_array=times&out_array=distances. The units of the entries of distances are meters, of times are seconds and of weights is arbitrary and it can differ for different vehicles or versions of this API.")
    vehicle: Literal['car', 'bike', 'foot', 'hike', 'mtb', 'racingbike', 'scooter', 'truck', 'small_truck'] | None = Field(None, alias='vehicle', description='The vehicle profile for which the matrix should be calculated.')
    fail_fast: bool | None = Field(None, alias='fail_fast', description='Specifies whether or not the matrix calculation should return with an error as soon as possible in case some points cannot be found or some points are not connected. If set to `false` the time/weight/distance matrix will be calculated for all valid points and contain the `null` value for all entries that could not be calculated. The `hint` field of the response will also contain additional information about what went wrong (see its documentation).')
    turn_costs: bool | None = Field(None, alias='turn_costs', description='Specifies if turn restrictions should be considered. Enabling this option increases the matrix computation time. Only supported for motor vehicles and OpenStreetMap.')


class CalculateMatrixConfig(MatrixRequest):
    """POST Matrix Endpoint."""
    operation: Literal['calculate_matrix'] = Field('calculate_matrix', json_schema_extra={"ui:hidden": True})

    @model_validator(mode="after")
    def matrix_points(self):
        if not self.from_points or not self.to_points:
            raise ValueError("Supply from_points and to_points in longitude,latitude order")
        return self


class SubmitMatrixConfig(MatrixRequest):
    """Batch Matrix Endpoint."""
    operation: Literal['submit_matrix'] = Field('submit_matrix', json_schema_extra={"ui:hidden": True})

    @model_validator(mode="after")
    def matrix_points(self):
        if not self.from_points or not self.to_points:
            raise ValueError("Supply from_points and to_points in longitude,latitude order")
        return self


class GetMatrixSolutionConfig(_Input):
    """GET Batch Matrix Endpoint."""
    operation: Literal['get_matrix_solution'] = Field('get_matrix_solution', json_schema_extra={"ui:hidden": True})
    job_id: str = Field(..., min_length=1, max_length=200, pattern=r"^[A-Za-z0-9_-]+$", description="Job ID returned by the corresponding submission operation.")


class GetRouteConfig(_Input):
    """GET Route Endpoint."""
    operation: Literal['get_route'] = Field('get_route', json_schema_extra={"ui:hidden": True})
    point: list[str] = Field(..., alias='point', description='The points for which the route should be calculated. Format: `[latitude,longitude]`. Specify at least an origin and a destination. Via points are possible.\nThe maximum number depends on your plan.\n')
    point_hint: list[str] | None = Field(None, alias='point_hint', description='The `point_hint` is typically a road name to which the associated `point` parameter should be snapped to. Specify no `point_hint` parameter or the same number as you have `point` parameters.\n')
    snap_prevention: list[str] | None = Field(None, alias='snap_prevention', description='Optional parameter to avoid snapping to a certain road class or road environment. Currently supported values are `motorway`, `trunk`, `ferry`, `tunnel`, `bridge` and `ford`. Multiple values are specified like `snap_prevention=ferry&snap_prevention=motorway`.\n')
    vehicle: Literal['car', 'bike', 'foot', 'hike', 'mtb', 'racingbike', 'scooter', 'truck', 'small_truck'] | None = Field(None, alias='vehicle', description='The vehicle profile for which the route should be calculated.\n')
    curbside: list[Literal['any', 'right', 'left']] | None = Field(None, alias='curbside', description='Optional parameter. It specifies on which side a point should be relative to the driver when she leaves/arrives at a start/target/via point. You need to specify this parameter for either none or all points. Only supported for motor vehicles and OpenStreetMap.\n')
    turn_costs: bool | None = Field(None, alias='turn_costs', description='Specifies if turn restrictions should be considered. Enabling this option increases the route computation time. Only supported for motor vehicles and OpenStreetMap.\n')
    locale: str | None = Field(None, alias='locale', description='The locale of the resulting turn instructions. E.g. `pt_PT` for Portuguese or `de` for German.\n')
    elevation: bool | None = Field(None, alias='elevation', description='If `true`, a third coordinate, the altitude, is included with all positions in the response.\nThis changes the format of the `points` and `snapped_waypoints` fields of the response, in both their\nencodings. Unless you switch off the `points_encoded` parameter, you need special code on the\nclient side that can handle three-dimensional coordinates.\nA request can fail if the vehicle profile does not support elevation. See the features object for every vehicle profile.\n')
    details: list[str] | None = Field(None, alias='details', description='Optional parameter to retrieve path details. You can request additional details for the route: `street_name`, \n`time`, `distance`, `max_speed`, `toll`, `road_class`, `road_class_link`, `road_access`, `road_environment`, `lanes`, and `surface`. Read more about the usage of path details [here](https://discuss.graphhopper.com/t/2539).\n')
    optimize: str | None = Field(None, alias='optimize', description='Normally, the calculated route will visit the points in the order you specified them.\nIf you have more than two points, you can set this parameter to `"true"` and the points may be re-ordered to minimize the total travel time.\nKeep in mind that the limits on the number of locations of the Route Optimization API applies, and the request costs more credits.\n')
    instructions: bool | None = Field(None, alias='instructions', description='If instructions should be calculated and returned\n')
    calc_points: bool | None = Field(None, alias='calc_points', description='If the points for the route should be calculated at all.\n')
    debug: bool | None = Field(None, alias='debug', description='If `true`, the output will be formatted.\n')
    points_encoded: bool | None = Field(None, alias='points_encoded', description='Allows changing the encoding of location data in the response. The default is polyline encoding, which is compact\nbut requires special client code to unpack. (We provide it in our JavaScript client library!)\nSet this parameter to `false` to switch the encoding to simple coordinate pairs like `[lon,lat]`, or `[lon,lat,elevation]`.\nSee the description of the response format for more information.\n')
    ch_disable: bool | None = Field(None, alias='ch.disable', description='Use this parameter in combination with one or more parameters from below.\n')
    weighting: str | None = Field(None, alias='weighting', description='Determines the way the "best" route is calculated. Besides `fastest` you can use `short_fastest` which finds a reasonable balance between the distance influence (`shortest`) and the time (`fastest`). You could also use `shortest` but is deprecated and not recommended for motor vehicles. All except `fastest` require `ch.disable=true`.\n')
    heading: list[int] | None = Field(None, alias='heading', description='Favour a heading direction for a certain point. Specify either one heading for the start point or as many as there are points.\nIn this case headings are associated by their order to the specific points. Headings are given as north based clockwise angle between 0 and 360 degree.\nThis parameter also influences the tour generated with `algorithm=round_trip` and forces the initial direction.  Requires `ch.disable=true`.\n')
    heading_penalty: int | None = Field(None, alias='heading_penalty', description='Time penalty in seconds for not obeying a specified heading. Requires `ch.disable=true`.\n')
    pass_through: bool | None = Field(None, alias='pass_through', description='If `true`, u-turns are avoided at via-points with regard to the `heading_penalty`. Requires `ch.disable=true`.\n')
    block_area: str | None = Field(None, alias='block_area', description='Block road access by specifying a point close to the road segment to be blocked, with the format `lat,lon`.\nYou can also block all road segments crossing a geometric shape. Specify a circle using the format `lat,lon,radius`, or a polygon using the format `lat1,lon1,lat2,lon2,...,latN,lonN`.\nYou can specify several shapes, separating them with `;`. Requires `ch.disable=true`.\n')
    avoid: str | None = Field(None, alias='avoid', description='Specify which road classes and environments you would like to avoid. \nPossible values are `motorway`, `steps`, `track`, `toll`, `ferry`, `tunnel` and `bridge`.\nSeparate several values with `;`. Obviously not all the values make sense for all vehicle profiles e.g. `bike` is already forbidden on a `motorway`. Requires `ch.disable=true`.\n')
    algorithm: Literal['round_trip', 'alternative_route'] | None = Field(None, alias='algorithm', description='Rather than looking for the shortest or fastest path, this parameter lets you solve two different problems related to routing:\nWith `alternative_route`, we give you not one but several routes that are close to optimal, but\nnot too similar to each other. \nWith `round_trip`, the route will get you back to where you started. This is meant for fun (think of\na bike trip), so we will add some randomness. The `round_trip` option requires `ch.disable=true`.\nYou can control both of these features with additional parameters, see below. \n')
    round_trip_distance: int | None = Field(None, alias='round_trip.distance', description='If `algorithm=round_trip`, this parameter configures approximative length of the resulting round trip. Requires `ch.disable=true`.\n')
    round_trip_seed: int | None = Field(None, alias='round_trip.seed', description='If `algorithm=round_trip`, this sets the random seed. Change this to get a different tour for each value.\n')
    alternative_route_max_paths: int | None = Field(None, alias='alternative_route.max_paths', description='If `algorithm=alternative_route`, this parameter sets the number of maximum paths which should be calculated. Increasing can lead to worse alternatives.\n')
    alternative_route_max_weight_factor: float | None = Field(None, alias='alternative_route.max_weight_factor', description='If `algorithm=alternative_route`, this parameter sets the factor by which the alternatives routes can be longer than the optimal route. Increasing can lead to worse alternatives.\n')
    alternative_route_max_share_factor: float | None = Field(None, alias='alternative_route.max_share_factor', description='If `algorithm=alternative_route`, this parameter specifies how similar an alternative route can be to the optimal route. Increasing can lead to worse alternatives.\n')

    @model_validator(mode="after")
    def route_points(self):
        if not self.point or len(self.point) < (1 if self.algorithm == "round_trip" else 2):
            raise ValueError("Supply an origin and destination, or one origin for a round trip")
        return self


class CalculateRouteConfig(RouteRequest):
    """POST Route Endpoint."""
    operation: Literal['calculate_route'] = Field('calculate_route', json_schema_extra={"ui:hidden": True})

    @model_validator(mode="after")
    def route_points(self):
        if not self.points or len(self.points) < (1 if self.algorithm == "round_trip" else 2):
            raise ValueError("Supply an origin and destination, or one origin for a round trip")
        return self


class GetCoverageConfig(_Input):
    """Coverage information."""
    operation: Literal['get_coverage'] = Field('get_coverage', json_schema_extra={"ui:hidden": True})


class SolveClusteringConfig(ClusterRequest):
    """POST Cluster Endpoint."""
    operation: Literal['solve_clustering'] = Field('solve_clustering', json_schema_extra={"ui:hidden": True})

    @model_validator(mode="after")
    def cluster_customers(self):
        if not self.customers or not self.configuration:
            raise ValueError("Supply customers and clustering configuration")
        return self


class SubmitClusteringConfig(ClusterRequest):
    """Batch Cluster Endpoint."""
    operation: Literal['submit_clustering'] = Field('submit_clustering', json_schema_extra={"ui:hidden": True})

    @model_validator(mode="after")
    def cluster_customers(self):
        if not self.customers or not self.configuration:
            raise ValueError("Supply customers and clustering configuration")
        return self


class GetClusteringSolutionConfig(_Input):
    """GET Batch Solution Endpoint."""
    operation: Literal['get_clustering_solution'] = Field('get_clustering_solution', json_schema_extra={"ui:hidden": True})
    job_id: str = Field(..., min_length=1, max_length=200, pattern=r"^[A-Za-z0-9_-]+$", description="Job ID returned by the corresponding submission operation.")


class SolveOptimizationConfig(Request):
    """POST route optimization problem."""
    operation: Literal['solve_optimization'] = Field('solve_optimization', json_schema_extra={"ui:hidden": True})

    @model_validator(mode="after")
    def optimization_problem(self):
        if not self.vehicles or not (self.services or self.shipments):
            raise ValueError("Supply vehicles and services or shipments")
        return self


class SubmitOptimizationConfig(Request):
    """POST route optimization problem (batch mode)."""
    operation: Literal['submit_optimization'] = Field('submit_optimization', json_schema_extra={"ui:hidden": True})

    @model_validator(mode="after")
    def optimization_problem(self):
        if not self.vehicles or not (self.services or self.shipments):
            raise ValueError("Supply vehicles and services or shipments")
        return self


class GetOptimizationSolutionConfig(_Input):
    """GET the solution (batch mode)."""
    operation: Literal['get_optimization_solution'] = Field('get_optimization_solution', json_schema_extra={"ui:hidden": True})
    job_id: str = Field(..., min_length=1, max_length=200, pattern=r"^[A-Za-z0-9_-]+$", description="Job ID returned by the corresponding submission operation.")

GraphhopperOperation = Annotated[Union[GeocodeConfig, GetIsochroneConfig, GetMatrixConfig, CalculateMatrixConfig, SubmitMatrixConfig, GetMatrixSolutionConfig, GetRouteConfig, CalculateRouteConfig, GetCoverageConfig, SolveClusteringConfig, SubmitClusteringConfig, GetClusteringSolutionConfig, SolveOptimizationConfig, SubmitOptimizationConfig, GetOptimizationSolutionConfig], Field(discriminator="operation")]


class GraphhopperConfig(NodeConfig[GraphhopperOperation, GraphhopperAPIKeyCredential]):
    pass


OPERATIONS = {'geocode': ('GET', '/geocode'), 'get_isochrone': ('GET', '/isochrone'), 'get_matrix': ('GET', '/matrix'), 'calculate_matrix': ('POST', '/matrix'), 'submit_matrix': ('POST', '/matrix/calculate'), 'get_matrix_solution': ('GET', '/matrix/solution/{jobId}'), 'get_route': ('GET', '/route'), 'calculate_route': ('POST', '/route'), 'get_coverage': ('GET', '/route/info'), 'solve_clustering': ('POST', '/cluster'), 'submit_clustering': ('POST', '/cluster/calculate'), 'get_clustering_solution': ('GET', '/cluster/solution/{jobId}'), 'solve_optimization': ('POST', '/vrp'), 'submit_optimization': ('POST', '/vrp/optimize'), 'get_optimization_solution': ('GET', '/vrp/solution/{jobId}')}


class GraphhopperNode(WorkflowNode):
    integration_type = "automation-graphhopper"
    connection_evidence = ConnectionEvidence(operation="get_coverage", noun="GraphHopper coverage", proves="reachability")

    @classmethod
    def get_config_model(cls):
        return GraphhopperConfig

    async def execute(self, inputs):
        if not self.config or not self.config.credentials:
            raise ValueError("Connect a GraphHopper API key")
        config = self.config.config
        key = self.config.credentials.api_key
        method, path = OPERATIONS[config.operation]
        payload = config.model_dump(mode="json", by_alias=True, exclude_none=True, exclude={"operation", "job_id"})
        if "{jobId}" in path:
            path = path.replace("{jobId}", quote(config.job_id, safe=""))
        params = [("key", key)]
        if method == "GET":
            for name, value in payload.items():
                for item in value if isinstance(value, list) else [value]:
                    params.append((name, str(item).lower() if isinstance(item, bool) else str(item)))
        # Never retry: submission operations allocate a job and consume credits.
        try:
            async with guarded_async_client(timeout=60, follow_redirects=False, trust_env=False) as client:
                response = await client.request(method, BASE + path, params=params,
                    headers={"Accept": "application/json"}, **({"json": payload} if method == "POST" else {}))
        except httpx.HTTPError:
            raise ValueError("GraphHopper request did not complete; check job status before submitting again") from None
        if not 200 <= response.status_code < 300:
            # Retain the provider's text for connection verdicts while removing the secret.
            message = response.text.replace(key, "[redacted]")[:2000]
            raise ValueError(f"GraphHopper HTTP {response.status_code}: {message}")
        if "json" not in response.headers.get("content-type", "").lower():
            raise ValueError("Expected a JSON response from GraphHopper")
        body = response.json()
        if not isinstance(body, dict):
            raise ValueError("Expected a GraphHopper response object")
        output = {"status": "success", "data": body}
        await self.emit(output)
        return output
