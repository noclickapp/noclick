"""An app's Durable Object classes as the API lists them: each class where it stands and why its objects are
stopped, a figure the host couldn't read left None and named in ``unread``, what they cost this month, and a class
deleted to the trash."""

import noclick as nc

ROOM = {"object": "durable_object_class", "id": "doc_1", "project_id": "prj_1", "name": "Room", "binding": "ROOM",
        "environment": "preview", "branch": "seats", "status": "stopped", "stopped_for": "budget", "objects": None,
        "objects_more": False, "stored_bytes": 2048, "added_by_deployment_id": None,
        "created_at": "2026-11-01T10:00:00Z", "parked_at": None, "trashed_at": None, "trash_id": None,
        "restorable_until": None}


def test_the_list_says_where_each_class_stands_what_went_unread_and_the_month_s_cost(api, client):
    api.get("/v1/projects/prj_1/durable_objects").respond(json={
        "object": "list", "data": [ROOM], "unread": ["objects"],
        "cost": {"usd": 0.42, "period_start": "2026-11-01T00:00:00+00:00"}})
    classes = nc.Project.from_id("prj_1").durable_objects()
    [room] = classes
    assert (room.name, room.environment, room.branch, room.status, room.stopped_for) == (
        "Room", "preview", "seats", "stopped", "budget")
    assert room.objects_count is None and classes.unread == ["objects"] and room.stored_bytes == 2048
    assert classes.cost == {"usd": 0.42, "period_start": "2026-11-01T00:00:00+00:00"}

    api.get("/v1/projects/prj_2/durable_objects").respond(json={"object": "list", "data": [], "unread": [],
                                                                "cost": None})
    none = nc.Project.from_id("prj_2").durable_objects()
    assert list(none) == [] and none.cost is None


def test_deleting_a_class_moves_it_to_the_trash(api, client):
    api.get("/v1/projects/prj_1/durable_objects").respond(json={"object": "list", "data": [ROOM], "unread": [],
                                                                "cost": None})
    gone = api.delete("/v1/projects/prj_1/durable_objects/doc_1").respond(json={
        "object": "durable_object_class", "id": "doc_1", "deleted": True,
        "trash": {"object": "trash_item", "id": "tr_1", "kind": "durable_object_class", "resource_id": "doc_1",
                  "name": "booking/Room", "user_id": None, "trashed_at": "2026-11-07T10:00:00Z",
                  "purge_after": "2026-12-07T10:00:00Z"},
        "restorable_until": "2026-12-07T10:00:00Z", "operation_id": "op_1"})
    [room] = nc.Project.from_id("prj_1").durable_objects()
    item = room.delete()
    assert gone.called and (item.id, item.kind, item.resource_id) == ("tr_1", "durable_object_class", "doc_1")
