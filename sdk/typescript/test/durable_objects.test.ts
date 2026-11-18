// An app's Durable Object classes as the API lists them: each class where it stands and why its objects are stopped,
// a figure the host couldn't read left null and named in `unread`, what they cost this month, and a class deleted to
// the trash.
import assert from "node:assert/strict";
import { test } from "node:test";

import * as nc from "../src/index.ts";
import { json, setup } from "./helpers.ts";

const ROOM = {
  object: "durable_object_class", id: "doc_1", project_id: "prj_1", name: "Room", binding: "ROOM", environment: "preview",
  branch: "seats", status: "stopped", stopped_for: "budget", objects: null, objects_more: false, stored_bytes: 2048,
  added_by_deployment_id: null, created_at: "2026-11-01T10:00:00Z", parked_at: null, trashed_at: null, trash_id: null,
  restorable_until: null,
};

test("the list says where each class stands, what went unread and the month's cost", async () => {
  const { api } = setup();
  api.on("GET", "/v1/projects/prj_1/durable_objects", json({
    object: "list", data: [ROOM], unread: ["objects"], cost: { usd: 0.42, period_start: "2026-11-01T00:00:00+00:00" },
  }));
  const classes = await nc.Project.fromId("prj_1").durableObjects();
  const [room] = classes;
  assert.deepEqual([room.name, room.environment, room.branch, room.status, room.stoppedFor], ["Room", "preview", "seats", "stopped", "budget"]);
  assert.equal(room.objectsCount, null);
  assert.deepEqual(classes.unread, ["objects"]);
  assert.equal(room.storedBytes, 2048);
  assert.deepEqual(classes.cost, { usd: 0.42, periodStart: new Date("2026-11-01T00:00:00Z") });

  api.on("GET", "/v1/projects/prj_2/durable_objects", json({ object: "list", data: [], unread: [], cost: null }));
  const none = await nc.Project.fromId("prj_2").durableObjects();
  assert.equal(none.length, 0);
  assert.equal(none.cost, null);
});

test("deleting a class moves it to the trash", async () => {
  const { api } = setup();
  api.on("GET", "/v1/projects/prj_1/durable_objects", json({ object: "list", data: [ROOM], unread: [], cost: null }));
  const gone = api.on("DELETE", "/v1/projects/prj_1/durable_objects/doc_1", json({
    object: "durable_object_class", id: "doc_1", deleted: true,
    trash: {
      object: "trash_item", id: "tr_1", kind: "durable_object_class", resource_id: "doc_1", name: "booking/Room", user_id: null,
      trashed_at: "2026-11-07T10:00:00Z", purge_after: "2026-12-07T10:00:00Z",
    },
    restorable_until: "2026-12-07T10:00:00Z", operation_id: "op_1",
  }));
  const [room] = await nc.Project.fromId("prj_1").durableObjects();
  const item = await room.delete();
  assert.equal(gone.count, 1);
  assert.deepEqual([item.id, item.kind, item.resourceId], ["tr_1", "durable_object_class", "doc_1"]);
});
