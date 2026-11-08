"""Power BI operation routes pinned to Microsoft's v1.0 Swagger contract.

Each automation maps to one provider operation; this catalog is also used to
build the form variants and permission declarations.
"""
from dataclasses import dataclass

@dataclass(frozen=True)
class Operation:
    method: str
    path: str
    fields: tuple[str, ...]
    operation_id: str
    scope: str

OPERATIONS = {
    'list_workspaces': Operation('GET', '/groups', ('top', 'skip', 'filter'), 'Groups_GetGroups', 'Workspace.Read.All'),
    'list_datasets': Operation('GET', '/groups/{workspace_id}/datasets', ('workspace_id',), 'Datasets_GetDatasetsInGroup', 'Dataset.ReadWrite.All'),
    'get_dataset': Operation('GET', '/groups/{workspace_id}/datasets/{dataset_id}', ('workspace_id', 'dataset_id'), 'Datasets_GetDatasetInGroup', 'Dataset.ReadWrite.All'),
    'create_push_dataset': Operation('POST', '/groups/{workspace_id}/datasets', ('workspace_id', 'name', 'tables'), 'Datasets_PostDatasetInGroup', 'Dataset.ReadWrite.All'),
    'delete_dataset': Operation('DELETE', '/groups/{workspace_id}/datasets/{dataset_id}', ('workspace_id', 'dataset_id'), 'Datasets_DeleteDatasetInGroup', 'Dataset.ReadWrite.All'),
    'list_tables': Operation('GET', '/groups/{workspace_id}/datasets/{dataset_id}/tables', ('workspace_id', 'dataset_id'), 'Datasets_GetTablesInGroup', 'Dataset.ReadWrite.All'),
    'add_rows': Operation('POST', '/groups/{workspace_id}/datasets/{dataset_id}/tables/{table_name}/rows', ('workspace_id', 'dataset_id', 'table_name', 'rows'), 'Datasets_PostRowsInGroup', 'Dataset.ReadWrite.All'),
    'delete_rows': Operation('DELETE', '/groups/{workspace_id}/datasets/{dataset_id}/tables/{table_name}/rows', ('workspace_id', 'dataset_id', 'table_name'), 'Datasets_DeleteRowsInGroup', 'Dataset.ReadWrite.All'),
    'get_refresh_history': Operation('GET', '/groups/{workspace_id}/datasets/{dataset_id}/refreshes', ('workspace_id', 'dataset_id', 'top'), 'Datasets_GetRefreshHistoryInGroup', 'Dataset.ReadWrite.All'),
    'refresh_dataset': Operation('POST', '/groups/{workspace_id}/datasets/{dataset_id}/refreshes', ('workspace_id', 'dataset_id', 'notify_option'), 'Datasets_RefreshDatasetInGroup', 'Dataset.ReadWrite.All'),
    'execute_query': Operation('POST', '/groups/{workspace_id}/datasets/{dataset_id}/executeQueries', ('workspace_id', 'dataset_id', 'query', 'include_nulls'), 'Datasets_ExecuteQueriesInGroup', 'Dataset.ReadWrite.All'),
    'list_reports': Operation('GET', '/groups/{workspace_id}/reports', ('workspace_id',), 'Reports_GetReportsInGroup', 'Report.ReadWrite.All'),
    'get_report': Operation('GET', '/groups/{workspace_id}/reports/{report_id}', ('workspace_id', 'report_id'), 'Reports_GetReportInGroup', 'Report.ReadWrite.All'),
    'delete_report': Operation('DELETE', '/groups/{workspace_id}/reports/{report_id}', ('workspace_id', 'report_id'), 'Reports_DeleteReportInGroup', 'Report.ReadWrite.All'),
    'clone_report': Operation('POST', '/groups/{workspace_id}/reports/{report_id}/Clone', ('workspace_id', 'report_id', 'name', 'target_workspace_id', 'target_dataset_id'), 'Reports_CloneReportInGroup', 'Content.Create'),
    'rebind_report': Operation('POST', '/groups/{workspace_id}/reports/{report_id}/Rebind', ('workspace_id', 'report_id', 'target_dataset_id'), 'Reports_RebindReportInGroup', 'Report.ReadWrite.All'),
    'list_report_pages': Operation('GET', '/groups/{workspace_id}/reports/{report_id}/pages', ('workspace_id', 'report_id'), 'Reports_GetPagesInGroup', 'Report.ReadWrite.All'),
    'list_dashboards': Operation('GET', '/groups/{workspace_id}/dashboards', ('workspace_id',), 'Dashboards_GetDashboardsInGroup', 'Dashboard.Read.All'),
    'create_dashboard': Operation('POST', '/groups/{workspace_id}/dashboards', ('workspace_id', 'name'), 'Dashboards_AddDashboardInGroup', 'Content.Create'),
    'list_tiles': Operation('GET', '/groups/{workspace_id}/dashboards/{dashboard_id}/tiles', ('workspace_id', 'dashboard_id'), 'Dashboards_GetTilesInGroup', 'Dashboard.Read.All'),
}
