"""Typed Estimate Rocket v1 operations.

Contract: https://estimaterocketapi.com/api-docs/v1/swagger-production.yaml
Lists return the provider's collection; the contract declares no paging inputs.
"""
from datetime import date, datetime
from typing import Annotated, Literal, Union
from pydantic import BaseModel, ConfigDict, Field, field_validator



class Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True, allow_inf_nan=False)

    @field_validator("*", mode="after", check_fields=False)
    @classmethod
    def safe_identifier(cls, value, info):
        if info.field_name.endswith("_id") and value is not None:
            if value in {".", ".."} or not value.strip() or any(ord(c) < 32 for c in value):
                raise ValueError("Use an Estimate Rocket resource ID")
        return value



class ListAssignments(Input):
    operation: Literal["list_assignments"] = Field("list_assignments", title="List Assignments")
    project_id: str | None = Field(None, max_length=512, description="Documented filter[project_id].")


class GetAssignment(Input):
    operation: Literal["get_assignment"] = Field("get_assignment", title="Get Assignment")
    assignment_id: str = Field(..., min_length=1, max_length=512)


class ListClients(Input):
    operation: Literal["list_clients"] = Field("list_clients", title="List Clients")
    email: str | None = Field(None, max_length=512, description="Documented filter[email].")


class GetClient(Input):
    operation: Literal["get_client"] = Field("get_client", title="Get Client")
    client_id: str = Field(..., min_length=1, max_length=512)


class ListEmployees(Input):
    operation: Literal["list_employees"] = Field("list_employees", title="List Employees")


class GetEmployee(Input):
    operation: Literal["get_employee"] = Field("get_employee", title="Get Employee")
    employee_id: str = Field(..., min_length=1, max_length=512)


class ListExpenses(Input):
    operation: Literal["list_expenses"] = Field("list_expenses", title="List Expenses")


class GetExpense(Input):
    operation: Literal["get_expense"] = Field("get_expense", title="Get Expense")
    expense_id: str = Field(..., min_length=1, max_length=512)


class ListInvoices(Input):
    operation: Literal["list_invoices"] = Field("list_invoices", title="List Invoices")
    number: str | None = Field(None, max_length=512, description="Documented filter[number].")


class GetInvoice(Input):
    operation: Literal["get_invoice"] = Field("get_invoice", title="Get Invoice")
    invoice_id: str = Field(..., min_length=1, max_length=512)


class ListPayments(Input):
    operation: Literal["list_payments"] = Field("list_payments", title="List Payments")


class GetPayment(Input):
    operation: Literal["get_payment"] = Field("get_payment", title="Get Payment")
    payment_id: str = Field(..., min_length=1, max_length=512)


class ListProjects(Input):
    operation: Literal["list_projects"] = Field("list_projects", title="List Projects")
    name: str | None = Field(None, max_length=512, description="Documented filter[name].")


class GetProject(Input):
    operation: Literal["get_project"] = Field("get_project", title="Get Project")
    project_id: str = Field(..., min_length=1, max_length=512)


class ListProposals(Input):
    operation: Literal["list_proposals"] = Field("list_proposals", title="List Proposals")
    project_id: str | None = Field(None, max_length=512, description="Documented filter[project_id].")


class GetProposal(Input):
    operation: Literal["get_proposal"] = Field("get_proposal", title="Get Proposal")
    proposal_id: str = Field(..., min_length=1, max_length=512)


class ListTimeEntries(Input):
    operation: Literal["list_time_entries"] = Field("list_time_entries", title="List Time Entries")


class GetTimeEntry(Input):
    operation: Literal["get_time_entry"] = Field("get_time_entry", title="Get Time Entry")
    time_entry_id: str = Field(..., min_length=1, max_length=512)


class GetCurrentEmployee(Input):
    operation: Literal["get_current_employee"] = Field("get_current_employee", title="Get Current Employee")


class CreateClient(Input):
    operation: Literal["create_client"] = Field("create_client", title="Create Client")
    address1: str = Field(..., min_length=1, max_length=1000)
    city: str = Field(..., min_length=1, max_length=512)
    first_name: str = Field(..., min_length=1, max_length=512)
    last_name: str = Field(..., min_length=1, max_length=512)
    state: str = Field(..., min_length=1, max_length=512)
    zip: str = Field(..., min_length=1, max_length=128)
    address2: str | None = None
    company_name: str | None = None
    email: str | None = None
    internal_notes: str | None = None
    owner_id: str | None = None
    phone: str | None = None
    source: str | None = None
    tax_rate: float | None = Field(None, ge=0)


class CreateProject(Input):
    operation: Literal["create_project"] = Field("create_project", title="Create Project")
    billing_address1: str = Field(..., min_length=1, max_length=1000)
    billing_city: str = Field(..., min_length=1, max_length=512)
    billing_state: str = Field(..., min_length=1, max_length=512)
    billing_zip: str = Field(..., min_length=1, max_length=128)
    billing_same_as_location: bool | None = None
    owner_id: str = Field(..., min_length=1, max_length=512)
    type: str = Field(..., min_length=1, max_length=512, description="Project type, for example Pending.")
    client_id: str = Field(..., min_length=1, max_length=512)


class CreateInvoice(Input):
    operation: Literal["create_invoice"] = Field("create_invoice", title="Create Invoice")
    project_id: str = Field(..., min_length=1, max_length=512)
    date: date
    name: str = Field(..., min_length=1, max_length=512)
    subtotal: float = Field(..., ge=0)
    number: str | None = None
    description: str | None = None
    tax: float = Field(0, ge=0)


class CreatePayment(Input):
    operation: Literal["create_payment"] = Field("create_payment", title="Create Payment")
    invoice_id: str = Field(..., min_length=1, max_length=512)
    date: date
    amount: float = Field(..., gt=0)
    reference: str | None = None
    notes: str | None = None


class CreateExpense(Input):
    operation: Literal["create_expense"] = Field("create_expense", title="Create Expense")
    project_id: str = Field(..., min_length=1, max_length=512)
    vendor_id: str = Field(..., min_length=1, max_length=512)
    date: date
    type: Literal["Material", "Labor"]
    subtotal: float = Field(..., ge=0)
    tax: float = Field(0, ge=0)
    hours: float | None = Field(None, ge=0)
    description: str | None = None
    paid: bool = False


class CreateTimeEntry(Input):
    operation: Literal["create_time_entry"] = Field("create_time_entry", title="Create Time Entry")
    employee_id: str = Field(..., min_length=1, max_length=512)
    in_at: datetime
    project_id: str | None = None
    work_code_id: str | None = None
    out_at: datetime | None = None
    notes: str | None = None


Operations = Annotated[Union[
    ListAssignments,
    GetAssignment,
    ListClients,
    GetClient,
    ListEmployees,
    GetEmployee,
    ListExpenses,
    GetExpense,
    ListInvoices,
    GetInvoice,
    ListPayments,
    GetPayment,
    ListProjects,
    GetProject,
    ListProposals,
    GetProposal,
    ListTimeEntries,
    GetTimeEntry,
    GetCurrentEmployee,
    CreateClient,
    CreateProject,
    CreateInvoice,
    CreatePayment,
    CreateExpense,
    CreateTimeEntry
], Field(discriminator="operation")]

# method, route, response envelope key, optional query filter
ROUTES = {
    'list_assignments': ('GET', '/api/v1/assignments', 'assignments', 'project_id'),
    'get_assignment': ('GET', '/api/v1/assignments/{assignment_id}', 'assignment', None),
    'list_clients': ('GET', '/api/v1/clients', 'clients', 'email'),
    'get_client': ('GET', '/api/v1/clients/{client_id}', 'client', None),
    'list_employees': ('GET', '/api/v1/employees', 'employees', None),
    'get_employee': ('GET', '/api/v1/employees/{employee_id}', 'employee', None),
    'list_expenses': ('GET', '/api/v1/expenses', 'expenses', None),
    'get_expense': ('GET', '/api/v1/expenses/{expense_id}', 'expense', None),
    'list_invoices': ('GET', '/api/v1/invoices', 'invoices', 'number'),
    'get_invoice': ('GET', '/api/v1/invoices/{invoice_id}', 'invoice', None),
    'list_payments': ('GET', '/api/v1/payments', 'payments', None),
    'get_payment': ('GET', '/api/v1/payments/{payment_id}', 'payment', None),
    'list_projects': ('GET', '/api/v1/projects', 'projects', 'name'),
    'get_project': ('GET', '/api/v1/projects/{project_id}', 'project', None),
    'list_proposals': ('GET', '/api/v1/proposals', 'proposals', 'project_id'),
    'get_proposal': ('GET', '/api/v1/proposals/{proposal_id}', 'proposal', None),
    'list_time_entries': ('GET', '/api/v1/time_entries', 'time_entries', None),
    'get_time_entry': ('GET', '/api/v1/time_entries/{time_entry_id}', 'time_entry', None),
    'get_current_employee': ('GET', '/api/v1/me', 'employee', None),
    'create_client': ('POST', '/api/v1/clients', 'client', None),
    'create_project': ('POST', '/api/v1/projects', 'project', None),
    'create_invoice': ('POST', '/api/v1/invoices', 'invoice', None),
    'create_payment': ('POST', '/api/v1/payments', 'payment', None),
    'create_expense': ('POST', '/api/v1/expenses', 'expense', None),
    'create_time_entry': ('POST', '/api/v1/time_entries', 'time_entry', None),
}
