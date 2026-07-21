"""extract_resource_id_from_output feeds the agent-create auto-extend writeback
(and validates x-resource-id-path annotations). Regression: it must coerce
NUMERIC ids (PostHog/Monday/GitLab dashboards, cohorts, boards …) to str — it
previously returned only strings, so every int-id create silently failed to
write back."""

from nodes.agent.node_op_tools import extract_resource_id_from_output as extract


def test_string_id():
    assert extract({"data": {"id": "abc"}}, "data.id") == "abc"


def test_int_id_coerced_to_str():
    assert extract({"data": {"id": 1874837}}, "data.id") == "1874837"


def test_nested_path():
    assert extract({"data": {"issueCreate": {"issue": {"id": "iss_1"}}}}, "data.issueCreate.issue.id") == "iss_1"


def test_short_id_string_path():
    assert extract({"data": {"short_id": "CjbMSmgg"}}, "data.short_id") == "CjbMSmgg"


def test_missing_or_empty_returns_none():
    assert extract({"data": {}}, "data.id") is None
    assert extract({"data": {"id": ""}}, "data.id") is None
    assert extract({"data": {"id": None}}, "data.id") is None
    assert extract({}, "data.id") is None
    assert extract(None, "data.id") is None


def test_bool_rejected():
    # a boolean is never a resource id (avoids True -> "True")
    assert extract({"data": {"id": True}}, "data.id") is None


def test_non_dict_midpath_returns_none():
    assert extract({"data": "notadict"}, "data.id") is None


# --- Per-node id-path contract ----------------------------------------------
# Each case is (annotated x-resource-id-path, a realistic execute() return for
# that node's create op, expected extracted id). These lock in that the paths
# shipped on the create ops actually pull the id the picker stores — the
# extraction step the agent-create auto-extend writeback performs after the
# builder's "Create new <resource>" affordance provisions the resource.
import pytest

_CASES = [
    # batch: CRM/ticketing
    ("data.id", {"status": "success", "data": {"id": "abc123"}}, "abc123"),  # trello board
    ("data.group.id", {"data": {"group": {"id": 360}}}, "360"),              # zendesk group (int)
    ("data.webhook.id", {"data": {"webhook": {"id": "whk_1"}}}, "whk_1"),    # zendesk webhook (str)
    ("data.id", {"data": {"id": "64abc"}}, "64abc"),                          # intercom contact
    ("data.id", {"data": {"id": "98304"}}, "98304"),                          # confluence space
    # github
    ("data.full_name", {"data": {"full_name": "owner/repo", "id": 5}}, "owner/repo"),
    # DB / vector
    ("data.datasetReference.datasetId", {"data": {"datasetReference": {"datasetId": "ds1"}}}, "ds1"),
    ("data.tableReference.tableId", {"data": {"tableReference": {"tableId": "t1"}}}, "t1"),
    ("data.name", {"data": {"id": "uuid-x", "name": "col"}}, "col"),          # chroma (name, not id)
    ("collection", {"collection": "mycol"}, "mycol"),                          # mongodb collection (no wrapper)
    ("index_name", {"index_name": "idx_1"}, "idx_1"),                          # mongodb index
    # CRM / sales
    ("data.id", {"data": {"id": 42}}, "42"),                                   # pipedrive deal (int)
    ("data.Customer.Id", {"data": {"Customer": {"Id": "58"}}}, "58"),         # quickbooks customer
    ("data.data.id", {"data": {"data": {"id": "01H"}}}, "01H"),               # klaviyo (JSON:API)
    ("data.api_slug", {"data": {"api_slug": "people", "id": {"object_id": "u"}}}, "people"),  # attio
    ("data.policyID", {"data": {"policyID": "P123"}}, "P123"),                # expensify
    # DevOps / observability
    ("data.slug", {"data": {"slug": "my-proj"}}, "my-proj"),                  # sentry project
    ("data.service.id", {"data": {"service": {"id": "PABC"}}}, "PABC"),       # pagerduty service
    ("data.key", {"data": {"key": "flag-1"}}, "flag-1"),                      # launchdarkly flag
    ("data.id", {"data": {"id": "wh1"}}, "wh1"),                              # databricks warehouse
    ("data.job_id", {"data": {"job_id": 123}}, "123"),                        # databricks job (int)
    ("data.project.id", {"data": {"project": {"id": "prj1"}}}, "prj1"),       # tableau project
    ("data.id", {"data": {"id": "19:abc@thread.tacv2"}}, "19:abc@thread.tacv2"),  # teams channel
    # infra / SaaS  (cloudflare wraps under `result`, not `data`)
    ("result.id", {"result": {"id": "z1"}}, "z1"),                            # cloudflare zone
    ("result.uuid", {"result": {"uuid": "u1"}}, "u1"),                        # cloudflare d1
    ("result.queue_id", {"result": {"queue_id": "q1"}}, "q1"),               # cloudflare queue
    ("result.name", {"result": {"name": "bucket-1"}}, "bucket-1"),           # cloudflare r2 bucket
    ("calendar.id", {"calendar": {"id": "AAMk"}}, "AAMk"),                    # outlook (no data wrapper)
    ("data.workbookId", {"data": {"workbookId": "wb1"}}, "wb1"),             # sigma
    ("id", {"id": "form1"}, "form1"),                                          # typeform (no wrapper)
    ("data.id", {"data": {"id": "dash1"}}, "dash1"),                          # basedash dashboard
    ("data.name", {"data": {"name": "Cluster0"}}, "Cluster0"),               # atlas cluster
    ("data.id", {"data": {"id": "clf_1"}}, "clf_1"),                          # extend classifier
]


@pytest.mark.parametrize("path,output,expected", _CASES)
def test_shipped_id_paths_extract_the_picker_value(path, output, expected):
    assert extract(output, path) == expected
