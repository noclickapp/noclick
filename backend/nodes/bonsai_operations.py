"""Bonsai v1 operation models, transcribed from the pinned provider contract."""
from datetime import date as Date
from typing import Annotated, Literal, Union
from uuid import UUID
from pydantic import BaseModel, ConfigDict, Field, model_validator

class _Operation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    @model_validator(mode="after")
    def combinations(self):
        values = self.model_dump()
        if self.operation == "create_task" and values.get("parent_task_uuid") and values.get("project_id"):
            raise ValueError("A subtask inherits its project; omit project_id")
        if values.get("start_date") and values.get("due_date") and values["start_date"] > values["due_date"]:
            raise ValueError("Due date must be on or after start date")
        if self.operation == "create_project":
            billing = values["billing_type"]
            if (values.get("billing_fee") is not None) != (billing in {"fixed_fee", "retainer"}):
                raise ValueError("A billing fee is required only for fixed fee and retainer projects")
            if (values.get("billing_cycle") is not None) != (billing == "retainer"):
                raise ValueError("A billing cycle is required only for retainer projects")
        if "invoice" in self.operation:
            if values.get("due") == "custom" and not values.get("due_date"):
                raise ValueError("Custom payment terms require a due date")
            if values.get("due") == "upon_receipt" and values.get("due_date"):
                raise ValueError("Upon receipt terms cannot include a due date")
            if self.operation == "create_invoice" and values.get("project_id") and not values.get("company_id"):
                raise ValueError("An invoice project requires its company")
        return self

class ListCompaniesConfig(_Operation):
    """List companies."""
    operation: Literal["list_companies"] = "list_companies"
    page: int = Field(1, ge=1, strict=True, description='Page to return, starting at 1.')
    page_size: int = Field(25, ge=1, le=100, strict=True, description='Records per page. Defaults to 25; anything above 100 is reduced to 100.')
    filter_name: str | None = Field(None, max_length=2000, description='Searches company names, matching from the start of any word and ignoring case.', examples=['Acme'])


class CreateCompanyConfig(_Operation):
    """Create a company."""
    operation: Literal["create_company"] = "create_company"
    name: str = Field(..., max_length=2000, min_length=1, description='Company name. Required.', examples=['Acme Corp'])
    default_contact_id: int | None = Field(None, ge=1, strict=True, description="Id of the contact to make this company's primary point of contact. Must be a contact in your account — find one with `GET /public-api/v1/contacts`.", examples=[7])
    description: str | None = Field(None, max_length=100000, description='Free text notes about the company.', examples=['Long standing retainer client.'])
    industry: Literal['arts_and_entertainment', 'business_and_consumer_services', 'community_and_society', 'computers_electronics_and_technology', 'e_commerce_and_shopping', 'finance', 'food_and_drink', 'gambling', 'games', 'health', 'heavy_industry_and_engineering', 'hobbies_and_leisure', 'home_and_garden', 'jobs_and_career', 'law_and_government', 'lifestyle', 'luxury', 'news_and_media', 'pets_and_animals', 'reference_materials', 'science_and_education', 'sports', 'travel_and_tourism', 'vehicles'] | None = Field(None, description='The industry the company operates in. Must be one of the listed values.', examples=['computers_electronics_and_technology'])
    company_size: Literal['size_1_10', 'size_11_50', 'size_51_200', 'size_201_1000', 'size_1000_plus'] | None = Field(None, description='Headcount band for the company. Must be one of the listed values.', examples=['size_201_1000'])
    source: Literal['organic_search', 'paid_search', 'email_marketing', 'organic_social', 'referrals', 'other_campaigns', 'direct_traffic', 'offline_sources', 'paid_social', 'ai_referrals'] | None = Field(None, description='How the client was acquired. Must be one of the listed values.', examples=['organic_search'])
    linkedin: str | None = Field(None, max_length=2000, description="Link to the company's LinkedIn profile.", examples=['https://linkedin.com/company/acme'])
    instagram: str | None = Field(None, max_length=2000, description="Link to the company's Instagram profile.", examples=['https://instagram.com/acme'])
    twitter: str | None = Field(None, max_length=2000, description="Link to the company's X profile.", examples=['https://x.com/acme'])
    facebook: str | None = Field(None, max_length=2000, description="Link to the company's Facebook page.", examples=['https://facebook.com/acme'])
    domains: list[str] | None = Field(None, description='Domains to associate with the company. Each value is lowercased and stripped of any protocol or `www.` prefix before it is stored. A domain can belong to only one company in your account; claiming one that is already taken fails with `422`.', examples=[['example.com', 'example.net']])


class GetCompanyConfig(_Operation):
    """Retrieve a company."""
    operation: Literal["get_company"] = "get_company"
    company_id: int = Field(..., ge=1, strict=True, description='Id of the company to retrieve.')


class UpdateCompanyConfig(_Operation):
    """Update a company."""
    operation: Literal["update_company"] = "update_company"
    company_id: int = Field(..., ge=1, strict=True, description='Id of the company to update.')
    name: str | None = Field(None, max_length=2000, description='New company name. A company must have a name, so `null` or an empty string is ignored rather than clearing it.', examples=['Acme Corp'])
    default_contact_id: int | None = Field(None, ge=1, strict=True, description="Id of the contact to make this company's primary point of contact. Must be a contact in your account. A company keeps whichever primary contact it already has, so `null` is ignored rather than clearing it.", examples=[7])
    description: str | None = Field(None, max_length=100000, description='Free text notes about the company. Send `null` to clear it.', examples=['Long standing retainer client.'])
    industry: Literal['arts_and_entertainment', 'business_and_consumer_services', 'community_and_society', 'computers_electronics_and_technology', 'e_commerce_and_shopping', 'finance', 'food_and_drink', 'gambling', 'games', 'health', 'heavy_industry_and_engineering', 'hobbies_and_leisure', 'home_and_garden', 'jobs_and_career', 'law_and_government', 'lifestyle', 'luxury', 'news_and_media', 'pets_and_animals', 'reference_materials', 'science_and_education', 'sports', 'travel_and_tourism', 'vehicles'] | None = Field(None, description='The industry the company operates in. Must be one of the listed values. Send `null` to clear it.', examples=['computers_electronics_and_technology'])
    company_size: Literal['size_1_10', 'size_11_50', 'size_51_200', 'size_201_1000', 'size_1000_plus'] | None = Field(None, description='Headcount band for the company. Must be one of the listed values. Send `null` to clear it.', examples=['size_201_1000'])
    source: Literal['organic_search', 'paid_search', 'email_marketing', 'organic_social', 'referrals', 'other_campaigns', 'direct_traffic', 'offline_sources', 'paid_social', 'ai_referrals'] | None = Field(None, description='How the client was acquired. Must be one of the listed values. Send `null` to clear it.', examples=['organic_search'])
    linkedin: str | None = Field(None, max_length=2000, description="Link to the company's LinkedIn profile. Send `null` to clear it.", examples=['https://linkedin.com/company/acme'])
    instagram: str | None = Field(None, max_length=2000, description="Link to the company's Instagram profile. Send `null` to clear it.", examples=['https://instagram.com/acme'])
    twitter: str | None = Field(None, max_length=2000, description="Link to the company's X profile. Send `null` to clear it.", examples=['https://x.com/acme'])
    facebook: str | None = Field(None, max_length=2000, description="Link to the company's Facebook page. Send `null` to clear it.", examples=['https://facebook.com/acme'])
    domains: list[str] | None = Field(None, description='Domains to add to the company. This is additive, not a replacement: the values you send are added, and re-sending one the company already has changes nothing. To remove every domain, send an empty array. Leave the field out to keep the current domains.', examples=[['example.net']])


class ListContactsConfig(_Operation):
    """List contacts."""
    operation: Literal["list_contacts"] = "list_contacts"
    page: int = Field(1, ge=1, strict=True, description='Page to return, starting at 1.')
    page_size: int = Field(25, ge=1, le=100, strict=True, description='Records per page. Defaults to 25; anything above 100 is reduced to 100.')
    filter_name: str | None = Field(None, max_length=2000, description='Searches contact names, matching anywhere in the name and ignoring case.', examples=['Alex'])
    filter_email: str | None = Field(None, max_length=2000, description='Searches email addresses, matching anywhere in the address and ignoring case.', examples=['alex@example.com'])
    filter_company_id: str | None = Field(None, max_length=2000, description='One or more company ids, comma-separated or repeated. Returns the contacts linked to those companies.', examples=['42'])


class CreateContactConfig(_Operation):
    """Create a contact."""
    operation: Literal["create_contact"] = "create_contact"
    name: str = Field(..., max_length=2000, min_length=1, description='Full name. Required.', examples=['Alex Johnson'])
    email: str = Field(..., max_length=2000, min_length=1, description='Email address. Required, and must be unique among your contacts.', examples=['alex@example.com'])
    job_title: str | None = Field(None, max_length=2000, description='Job title.', examples=['CTO'])
    phone_number: str | None = Field(None, max_length=2000, description='Phone number, stored as given.', examples=['+1-415-555-0100'])
    company_id: int | None = Field(None, ge=1, strict=True, description='Id of the company to link the contact to. Find one with `GET /public-api/v1/companies`.', examples=[42])


class GetContactConfig(_Operation):
    """Retrieve a contact."""
    operation: Literal["get_contact"] = "get_contact"
    contact_id: int = Field(..., ge=1, strict=True, description='Id of the contact to retrieve.')


class UpdateContactConfig(_Operation):
    """Update a contact."""
    operation: Literal["update_contact"] = "update_contact"
    contact_id: int = Field(..., ge=1, strict=True, description='Id of the contact to update.')
    name: str | None = Field(None, max_length=2000, description='New full name. A contact must have a name, so `null` or an empty string is ignored rather than clearing it.', examples=['Alex Johnson'])
    email: str | None = Field(None, max_length=2000, description='New email address. A contact must have an email, so `null` or an empty string is ignored rather than clearing it. Must stay unique among your contacts.', examples=['alex@example.com'])
    job_title: str | None = Field(None, max_length=2000, description='New job title. Send `null` or an empty string to clear it; leave the field out to keep it.', examples=['CTO'])
    phone_number: str | None = Field(None, max_length=2000, description='New phone number. Send `null` or an empty string to clear it; leave the field out to keep it.', examples=['+1-415-555-0100'])


class ListDealsConfig(_Operation):
    """List deals."""
    operation: Literal["list_deals"] = "list_deals"
    page: int = Field(1, ge=1, strict=True, description='Page to return, starting at 1.')
    page_size: int = Field(25, ge=1, le=100, strict=True, description='Records per page. Defaults to 25; anything above 100 is reduced to 100.')
    filter_title: str | None = Field(None, max_length=2000, description='Searches deal titles, matching from the start of any word and ignoring case.', examples=['Acme'])
    filter_deal_number: str | None = Field(None, max_length=2000, description='Searches deal references, matching from the start of any word.', examples=['DL-42'])
    filter_assignee_member_id: str | None = Field(None, max_length=2000, description='One or more team member ids, comma-separated or repeated. Pass `me` for whoever the token belongs to.', examples=['me'])
    filter_board_group_id: str | None = Field(None, max_length=2000, description='One or more pipeline stage ids, comma-separated or repeated. Returns the deals sitting in those stages.', examples=['8feddf83-f0dc-4587-ac77-3236d509a5c4'])


class CreateDealConfig(_Operation):
    """Create a deal."""
    operation: Literal["create_deal"] = "create_deal"
    title: str = Field(..., max_length=2000, min_length=1, description='Deal title. Required.', examples=['Acme Website Redesign'])
    company_id: int = Field(..., ge=1, strict=True, description='Id of the client company the deal is with. Required.', examples=[42])
    contact_id: int | None = Field(None, ge=1, strict=True, description="Id of a contact at that company to attach to the deal. Defaults to the company's primary contact.", examples=[7])
    assignee_member_id: int | Literal["me"] | None = Field(None, description='Who owns the deal: a team member id, or `me` for whoever the token belongs to. Send `null` or leave it out for an unassigned deal.', examples=['me'])
    board_group_id: UUID | None = Field(None, description='Id of the pipeline stage to put the deal in. Defaults to the first stage of your deal board.', examples=['8feddf83-f0dc-4587-ac77-3236d509a5c4'])
    deal_value: str | None = Field(None, max_length=2000, pattern='^\\d+(?:\\.\\d+)?$', description='What the deal is worth, as a decimal string. Must be zero or greater.', examples=['5000.00'])


class UpdateDealConfig(_Operation):
    """Update a deal."""
    operation: Literal["update_deal"] = "update_deal"
    deal_id: int = Field(..., ge=1, strict=True, description='Id of the deal to update.')
    title: str | None = Field(None, max_length=2000, description='New deal title.', examples=['Acme Website Redesign'])
    company_id: int | None = Field(None, ge=1, strict=True, description='Id of the client company the deal is with. Find one with `GET /public-api/v1/companies`.', examples=[42])
    contact_ids: list[int] | None = Field(None, description="The contacts on the deal, replacing whatever is there now. Send an empty array to remove them all. Leave the field out to keep the deal's current contacts.", examples=[[7, 12]])
    assignee_member_id: int | Literal["me"] | None = Field(None, description='Who owns the deal: a team member id, or `me` for whoever the token belongs to. Send `null` to leave it unassigned.', examples=['me'])
    board_group_id: UUID | None = Field(None, description='Id of the pipeline stage to move the deal to. Find one with `GET /public-api/v1/board_groups`.', examples=['8feddf83-f0dc-4587-ac77-3236d509a5c4'])
    deal_value: str | None = Field(None, max_length=2000, pattern='^\\d+(?:\\.\\d+)?$', description='What the deal is worth, as a decimal string. Must be zero or greater. `null` is ignored rather than clearing the value.', examples=['7500.00'])
    probability: int | None = Field(None, ge=0, le=100, strict=True, description='Chance of winning the deal, as a whole percentage from 0 to 100. `null` is ignored rather than clearing the value.', examples=[60])
    close_date: Date | None = Field(None, description='Date the deal is expected to close. Send `null` to clear it.', examples=['2026-09-30'])


class ListInvoicesConfig(_Operation):
    """List invoices."""
    operation: Literal["list_invoices"] = "list_invoices"
    page: int = Field(1, ge=1, strict=True, description='Page to return, starting at 1.')
    page_size: int = Field(25, ge=1, le=100, strict=True, description='Records per page. Defaults to 25; anything above 100 is reduced to 100.')
    filter_invoice_number: str | None = Field(None, max_length=2000, description='One or more exact invoice numbers, comma-separated or repeated.', examples=['INV-001'])
    filter_project_id: str | None = Field(None, max_length=2000, description='One or more project ids, comma-separated or repeated.', examples=['51'])
    filter_company_id: str | None = Field(None, max_length=2000, description='One or more client company ids, comma-separated or repeated. Find them with `GET /public-api/v1/companies`.', examples=['42'])
    filter_contact_id: str | None = Field(None, max_length=2000, description="One or more contact ids, comma-separated or repeated. Returns the invoices whose `contact_id` matches, with or without a company; an invoice that doesn't record a contact is left out. Find them with `GET /public-api/v1/contacts`.", examples=['7'])


class CreateInvoiceConfig(_Operation):
    """Create an invoice."""
    operation: Literal["create_invoice"] = "create_invoice"
    company_id: int | None = Field(None, ge=1, strict=True, description='Id of the client company to invoice. Leave it out to bill the contact on their own, with no company on the invoice. Must be a company in your account.', examples=[42])
    contact_id: int = Field(..., ge=1, strict=True, description="Id of the contact to address the invoice to. Required. Must be a contact in your account; without `company_id` it is the person billed, and can't be a supplier's contact.", examples=[7])
    project_id: int | None = Field(None, ge=1, strict=True, description='Id of the project to invoice. Leave it out for an invoice with no project. Needs `company_id`, and must already exist and belong to that company.', examples=[51])
    currency: str | None = Field(None, max_length=2000, description="Three-letter ISO 4217 currency code. Defaults to the project's currency, or to your account's currency when there is no project; send it to override.", examples=['USD'])
    title: str | None = Field(None, max_length=2000, description='Invoice title shown to the client. Defaults to the client name followed by "Invoice".', examples=['Acme Corp Invoice'])
    due: Literal['upon_receipt', 'custom'] | None = Field(None, description="When payment is due. Leave it out to use your account's default payment terms, which may work out to a number of days after issue.")
    due_date: Date | None = Field(None, description='The exact date payment is due. Required when `due` is `custom`, and must be left out when `due` is `upon_receipt`.', examples=['2026-04-28'])


class UpdateInvoiceConfig(_Operation):
    """Update an invoice."""
    operation: Literal["update_invoice"] = "update_invoice"
    invoice_id: int = Field(..., ge=1, strict=True, description='Id of the invoice to update.')
    contact_id: int | None = Field(None, ge=1, strict=True, description="Id of the contact to address the invoice to, which also refreshes the client name and email printed on it. Must be a contact at the invoice's client company. On an invoice with no company the contact is who it bills and can't change; create a new invoice to bill someone else.", examples=[7])
    currency: str | None = Field(None, max_length=2000, description='Three-letter ISO 4217 currency code.', examples=['USD'])
    title: str | None = Field(None, max_length=2000, description='Invoice title shown to the client.', examples=['Acme Corp Invoice'])
    due: Literal['upon_receipt', 'custom'] | None = Field(None, description='When payment is due.')
    due_date: Date | None = Field(None, description='The exact date payment is due. Required when `due` is `custom`, and must be left out when `due` is `upon_receipt`. Sending it on its own is treated as `custom`.', examples=['2026-04-28'])


class ListProjectsConfig(_Operation):
    """List projects."""
    operation: Literal["list_projects"] = "list_projects"
    page: int = Field(1, ge=1, strict=True, description='Page to return, starting at 1.')
    page_size: int = Field(25, ge=1, le=100, strict=True, description='Records per page. Defaults to 25; anything above 100 is reduced to 100.')
    filter_title: str | None = Field(None, max_length=2000, description='Searches project titles, matching from the start of any word and ignoring case.', examples=['Acme'])
    filter_public_url_token: str | None = Field(None, max_length=2000, description='One or more URL tokens, comma-separated or repeated.', examples=['acme-website-x4n2'])
    filter_board_group_id: str | None = Field(None, max_length=2000, description='One or more pipeline stage ids, comma-separated or repeated. Returns the projects whose board card sits in those stages.', examples=['0c8f1e2a-3b4c-4d5e-6f70-8192a3b4c5d6'])
    filter_status: Literal['active', 'archived', 'not_archived', 'completed', 'all'] | None = Field(None, description='Which projects to include. Defaults to `active`.', examples=['all'])
    filter_has_budget: Literal['true', 'false'] | None = Field(None, description='Return only projects that do (`true`) or do not (`false`) track a budget. Needs permission to see budgets; without it this filter returns 403.', examples=['true'])
    filter_budget_amount_min: str | None = Field(None, max_length=2000, description='Return projects whose budget is this amount or more. Needs permission to see budgets; without it this filter returns 403.', examples=['5000'])
    filter_budget_amount_max: str | None = Field(None, max_length=2000, description='Return projects whose budget is this amount or less. Needs permission to see budgets; without it this filter returns 403.', examples=['20000'])


class CreateProjectConfig(_Operation):
    """Create a project."""
    operation: Literal["create_project"] = "create_project"
    title: str = Field(..., max_length=2000, min_length=1, description='Project title. Required.', examples=['Acme Website'])
    company_id: int = Field(..., ge=1, strict=True, description='Id of the client company the project is for. Required.', examples=[42])
    currency: str | None = Field(None, max_length=2000, description="Three-letter ISO 4217 currency code the project bills in. Defaults to the client's currency.", examples=['USD'])
    start_date: Date | None = Field(None, description='Date work starts. Defaults to today.', examples=['2026-05-01'])
    finish_date: Date | None = Field(None, description='Date work ends. Left open when omitted.', examples=['2026-09-30'])
    billing_type: Literal['time', 'fixed_fee', 'retainer', 'not_billable'] = Field(..., description='How the project bills. Required. See the table above for which fee fields each type takes.', examples=['fixed_fee'])
    billing_fee: str | None = Field(None, max_length=2000, pattern='^\\d+(?:\\.\\d+)?$', description='The agreed fee, as a decimal string. Required for `fixed_fee` and `retainer`, rejected for the other types.', examples=['5000'])
    billing_cycle: Literal['weekly', 'monthly', 'quarterly', 'biannually', 'yearly'] | None = Field(None, description='How often a retainer bills. Required for `retainer`, rejected for the other types.', examples=['monthly'])


class UpdateProjectConfig(_Operation):
    """Update a project."""
    operation: Literal["update_project"] = "update_project"
    project_id: int = Field(..., ge=1, strict=True, description="The project's `id`.")
    title: str | None = Field(None, max_length=2000, description='Project title. A project must have one, so it cannot be blank.', examples=['Acme Website'])
    start_date: Date | None = Field(None, description='Date work starts. Cannot be cleared.', examples=['2026-05-01'])
    finish_date: Date | None = Field(None, description='Date work ends. Send `null` to clear it.', examples=['2026-09-30'])
    billing_type: Literal['time', 'fixed_fee', 'retainer', 'not_billable'] | None = Field(None, description='How the project bills. See the table above for which fee fields each type takes.', examples=['retainer'])
    billing_fee: str | None = Field(None, max_length=2000, pattern='^\\d+(?:\\.\\d+)?$', description='The agreed fee, as a decimal string. Send `null` to clear it.', examples=['5000'])
    billing_cycle: Literal['weekly', 'monthly', 'quarterly', 'biannually', 'yearly'] | None = Field(None, description='How often a retainer bills. Send `null` to clear it.', examples=['monthly'])
    board_group_id: UUID | None = Field(None, description='Id of the stage to move the project to, on the project board it already sits on.', examples=['0c8f1e2a-3b4c-4d5e-6f70-8192a3b4c5d6'])


class ListTasksConfig(_Operation):
    """List tasks."""
    operation: Literal["list_tasks"] = "list_tasks"
    page: int = Field(1, ge=1, strict=True, description='Page to return, starting at 1.')
    page_size: int = Field(25, ge=1, le=100, strict=True, description='Records per page. Defaults to 25; anything above 100 is reduced to 100.')
    filter_assignee_id: str | None = Field(None, max_length=2000, description='One or more user ids, comma-separated or repeated. Pass `me` for whoever the token belongs to.', examples=['me'])
    filter_scope: Literal['active', 'completed', 'archived', 'all', 'upcoming_and_overdue', 'unplanned', 'planned', 'my_tasks'] | None = Field(None, description='Which tasks to include. Defaults to `active`.')
    filter_due: Literal['today', 'overdue', 'today_or_overdue', 'this_week', 'this_month', 'upcoming'] | None = Field(None, description='A named due-date window. Cannot be combined with `filter[due_from]` or `filter[due_to]`.')
    filter_due_from: Date | None = Field(None, description='Return tasks due on or after this date.', examples=['2026-05-01'])
    filter_due_to: Date | None = Field(None, description='Return tasks due on or before this date.', examples=['2026-05-31'])
    filter_billable: Literal['true', 'false'] | None = Field(None, description='Return only billable (`true`) or only non-billable (`false`) tasks. Needs permission to see billing; without it this filter returns 403.', examples=['true'])
    filter_deal_id: str | None = Field(None, max_length=2000, description='One or more deal ids, comma-separated or repeated. Needs permission to see deals; without it this filter returns 403.', examples=['17'])
    filter_priority: str | None = Field(None, max_length=2000, description='One or more priorities, comma-separated or repeated.', examples=['high,medium'])
    filter_project_id: str | None = Field(None, max_length=2000, description='One or more project ids, comma-separated or repeated.', examples=['51'])
    filter_tag_id: str | None = Field(None, max_length=2000, description='One or more tag ids, comma-separated or repeated.', examples=['7'])
    filter_task_status_id: str | None = Field(None, max_length=2000, description='One or more task status ids, comma-separated or repeated. Returns tasks in those columns whether they are active, completed or archived.', examples=['e1c4b06e-3a0f-4a52-9c8f-6a1d2b3c4d5e'])
    filter_title: str | None = Field(None, max_length=2000, description='Searches task titles, ignoring case.', examples=['Homepage'])


class CreateTaskConfig(_Operation):
    """Create a task."""
    operation: Literal["create_task"] = "create_task"
    title: str = Field(..., max_length=2000, min_length=1, description='Task title. Required.', examples=['Finalize homepage mockups'])
    project_id: int | None = Field(None, ge=1, strict=True, description='Id of the project the task belongs to. Leave it out for a task that stands on its own. Cannot be combined with `parent_task_uuid` — a subtask takes its project from its parent. Find one with `GET /public-api/v1/projects`.', examples=[51])
    deal_id: int | None = Field(None, ge=1, strict=True, description='Id of the deal to put the task on. Independent of `project_id` — a task can sit on a deal, a project, both or neither. Needs permission to create deals; without it the request fails with `422 not_accessible`. A deal that is not in your account fails the same way. Find one with `GET /public-api/v1/deals`.', examples=[17])
    parent_task_uuid: UUID | None = Field(None, max_length=2000, description='`uuid` of the task to nest this one under. The subtask takes its project and billable setting from the parent, so `project_id` cannot be sent with it. A parent that is not in your account fails with `422 not_accessible`; a parent already two levels deep fails with `422 invalid_value`.', examples=['ad3fdad8-5072-46df-8800-bb57299179df'])
    assignee_member_id: int | Literal["me"] | None = Field(None, description='Who the task is for: a team member id, or `me` for whoever the token belongs to. Send `null` or leave it out for an unassigned task. Find ids with `GET /public-api/v1/team_members` — use the `company_member_id` field.', examples=['me'])
    priority: Literal['urgent', 'high', 'medium', 'low'] | None = Field(None, description='How urgent the task is.', examples=['high'])
    due_date: Date | None = Field(None, description='Date the task is due. Leave it out for an unscheduled task. Cannot be earlier than `start_date` when you send both.', examples=['2026-05-15'])
    start_date: Date | None = Field(None, description='Date work on the task starts. Cannot be later than `due_date` when you send both.', examples=['2026-05-01'])
    description: str | None = Field(None, max_length=100000, description='What the task involves. Accepts an HTML fragment for formatting — `<p>`, `<strong>`, `<ul>`/`<li>` and `<a>` among others. Read it back as `description_html` (sanitized) or `description_plain_text` (tags removed) on single-task responses; neither appears in a list.', examples=['<p>Draft the <strong>brief</strong></p>'])
    time_estimate_in_minutes: int | None = Field(None, ge=1, strict=True, description='Estimated effort in whole minutes — 90 for an hour and a half. Must be positive.', examples=[90])
    task_status_id: str | None = Field(None, max_length=2000, description='Id of the board column to put the task in. Defaults to your `To Do` column. Find one with `GET /public-api/v1/task_statuses`.', examples=['e1c4b06e-3a0f-4a52-9c8f-6a1d2b3c4d5e'])
    billable: bool | None = Field(None, description='Whether time tracked on the task is billable. Left out, it defaults the way the app does: a subtask inherits its parent, a task on a not-billable project is not billable, and everything else is billable. Only honoured for a token allowed to set billing, on a plan that includes task billing — otherwise the value is ignored and the default applies. `permissions.tasks.billing_update` from `GET /public-api/v1/permissions/me` tells you which you have; note that `permissions.tasks.billing` only covers reading it back.', examples=[True])
    tag_ids: list[int] | None = Field(None, description='Tags to put on the task. Must be `task` tags from your account — find them with `GET /public-api/v1/company_tags`. Read them back under `company_tags`.', examples=[[7, 12]])


class GetTaskConfig(_Operation):
    """Retrieve a task."""
    operation: Literal["get_task"] = "get_task"
    task_uuid: UUID = Field(..., description="The task's `uuid`.")


class UpdateTaskConfig(_Operation):
    """Update a task."""
    operation: Literal["update_task"] = "update_task"
    task_uuid: UUID = Field(..., description="The task's `uuid`.")
    title: str | None = Field(None, max_length=2000, description='New task title. A task must have one, so it cannot be blank.', examples=['Finalize homepage mockups'])
    project_id: int | None = Field(None, ge=1, strict=True, description='Move the task to another project, or send `null` to detach it from the one it is on. Find one with `GET /public-api/v1/projects`.', examples=[51])
    deal_id: int | None = Field(None, ge=1, strict=True, description='Move the task to another deal, or send `null` to take it off the one it is on. Independent of `project_id`. Needs permission to create deals; without it the request fails with `422 not_accessible`. A deal that is not in your account fails the same way. Find one with `GET /public-api/v1/deals`.', examples=[17])
    assignee_member_id: int | Literal["me"] | None = Field(None, description='Who the task is for: a team member id, or `me` for whoever the token belongs to. Send `null` to unassign it. Find ids with `GET /public-api/v1/team_members` — use the `company_member_id` field.', examples=['me'])
    priority: Literal['urgent', 'high', 'medium', 'low'] | None = Field(None, description='How urgent the task is. Can be changed but not cleared once set.', examples=['high'])
    due_date: Date | None = Field(None, description='Date the task is due. Send `null` to clear it.', examples=['2026-05-15'])
    start_date: Date | None = Field(None, description='Date work on the task starts. Send `null` to clear it.', examples=['2026-05-01'])
    description: str | None = Field(None, max_length=100000, description='What the task involves, as an HTML fragment. Send `null` to clear it. Read it back as `description_html` or `description_plain_text`.', examples=['<p>Draft the <strong>brief</strong></p>'])
    time_estimate_in_minutes: int | None = Field(None, ge=1, strict=True, description='Estimated effort in whole minutes. Must be positive, or `null` to clear it.', examples=[90])
    task_status_id: str | None = Field(None, max_length=2000, description='Id of the board column to move the task to. Find one with `GET /public-api/v1/task_statuses`.', examples=['e1c4b06e-3a0f-4a52-9c8f-6a1d2b3c4d5e'])
    billable: bool | None = Field(None, description="Whether time tracked on the task is billable. Sent alongside `project_id`, your value wins over the new project's default; left out, moving the task to another project re-derives it from that project. Only honoured for a token allowed to set billing, on a plan that includes task billing — otherwise the value is ignored. Check `permissions.tasks.billing_update` from `GET /public-api/v1/permissions/me` before relying on it.", examples=[True])
    tag_ids: list[int] | None = Field(None, description='The tags on the task, replacing whatever is there now. Send an empty array to remove them all. Must be `task` tags from your account — find them with `GET /public-api/v1/company_tags`.', examples=[[7, 12]])


class ListTimeEntriesConfig(_Operation):
    """List time entries."""
    operation: Literal["list_time_entries"] = "list_time_entries"
    page: int = Field(1, ge=1, strict=True, description='Page to return, starting at 1.')
    page_size: int = Field(25, ge=1, le=100, strict=True, description='Records per page. Defaults to 25; anything above 100 is reduced to 100.')
    filter_date_from: Date | None = Field(None, description='Return entries dated on or after this day.', examples=['2026-01-01'])
    filter_date_to: Date | None = Field(None, description='Return entries dated on or before this day.', examples=['2026-01-31'])
    filter_owner_member_id: str | None = Field(None, max_length=2000, description="One or more team member ids, comma-separated or repeated. Pass `me` for whoever the token belongs to. Reaching another member's time needs permission to see the whole team's time.", examples=['me'])
    filter_project_id: str | None = Field(None, max_length=2000, description='One or more project ids, comma-separated or repeated.', examples=['51'])
    filter_company_id: str | None = Field(None, max_length=2000, description="One or more client company ids, comma-separated or repeated. Matched through each entry's project.", examples=['42'])
    filter_billing_status: Literal['billed', 'unbilled', 'non_billable'] | None = Field(None, description='Return entries in one or more billing states, comma-separated or repeated. Needs permission to see billing; without it this filter returns 403.', examples=['unbilled'])
    filter_currency: str | None = Field(None, max_length=2000, description='One or more three-letter ISO 4217 currency codes, comma-separated or repeated.', examples=['USD'])


class CreateTimeEntryConfig(_Operation):
    """Log a time entry."""
    operation: Literal["create_time_entry"] = "create_time_entry"
    seconds: int = Field(..., ge=0, strict=True, description='How long the work took, in seconds. Required.', examples=[3600])
    date: Date = Field(..., description='The day the work was done. Required.', examples=['2026-06-17'])
    project_id: int | None = Field(None, ge=1, strict=True, description='Id of the project to log against. Ignored when you also send `task_uuid`. Sample projects are not accepted. Find one with `GET /public-api/v1/projects`.', examples=[51])
    task_uuid: UUID | None = Field(None, description='`uuid` of the task to log against. The project is taken from the task. Tasks on sample projects, and template tasks, are not accepted. Find one with `GET /public-api/v1/tasks`.', examples=['ad3fdad8-5072-46df-8800-bb57299179df'])
    notes: str | None = Field(None, max_length=100000, description='What the time was spent on.', examples=['Homepage build'])
    rate: str | None = Field(None, max_length=2000, pattern='^\\d+(?:\\.\\d+)?$', description='Hourly rate to bill at, as a decimal string. Must be zero or greater. Only honoured for a token allowed to set billing; otherwise it comes from the project or member rate.', examples=['150.00'])
    non_billable: bool | None = Field(None, description="Whether to exclude the entry from billing. Only honoured for a token allowed to set billing; otherwise it comes from the task or project's billing type.", examples=[False])
    owner_member_id: int | Literal["me"] | None = Field(None, description="Who the time is for: a team member id, or `me` for whoever the token belongs to. Defaults to the token's own member. Logging for someone else needs permission to manage the whole team's time. Find ids with `GET /public-api/v1/team_members`.", examples=['me'])


class UpdateTimeEntryConfig(_Operation):
    """Update a time entry."""
    operation: Literal["update_time_entry"] = "update_time_entry"
    time_entry_key: str = Field(..., pattern=r"^[A-Za-z0-9_-]+$", max_length=2000, min_length=1, description="The entry's `key`, as returned in a time entry response.")
    seconds: int | None = Field(None, ge=0, strict=True, description='How long the work took, in seconds.', examples=[5400])
    date: Date | None = Field(None, description='The day the work was done.', examples=['2026-06-17'])
    project_id: int | None = Field(None, ge=1, strict=True, description='Id of the project to log against, or `null` to detach the entry from the one it is on. Ignored while the entry is linked to a task. Sample projects are not accepted.', examples=[51])
    task_uuid: UUID | None = Field(None, description='`uuid` of the task to log against — the project comes with it. Send `null` to unlink the task, which also clears the project it brought.', examples=['ad3fdad8-5072-46df-8800-bb57299179df'])
    notes: str | None = Field(None, max_length=100000, description='What the time was spent on. Send an empty string to clear it.', examples=['Homepage build'])
    rate: str | None = Field(None, max_length=2000, pattern='^\\d+(?:\\.\\d+)?$', description='Hourly rate to bill at, as a decimal string. Must be zero or greater. Only honoured for a token allowed to set billing.', examples=['150.00'])
    non_billable: bool | None = Field(None, description='Whether to exclude the entry from billing. Only honoured for a token allowed to set billing.', examples=[False])
    billing_status: Literal['billed', 'unbilled'] | None = Field(None, description='Mark the entry `billed`, or move it back to `unbilled`. Requires a token allowed to set billing — unlike `rate` and `non_billable`, a value here from a token without that permission fails the whole request with `422 not_accessible` rather than being ignored. `non_billable` is not accepted here — use the `non_billable` flag for that.', examples=['billed'])
    owner_member_id: int | Literal["me"] | None = Field(None, description="Who the time is for: a team member id, or `me` for whoever the token belongs to. Reassigning to someone else needs permission to manage the whole team's time.", examples=['me'])


BonsaiOperation = Annotated[Union[ListCompaniesConfig, CreateCompanyConfig, GetCompanyConfig, UpdateCompanyConfig, ListContactsConfig, CreateContactConfig, GetContactConfig, UpdateContactConfig, ListDealsConfig, CreateDealConfig, UpdateDealConfig, ListInvoicesConfig, CreateInvoiceConfig, UpdateInvoiceConfig, ListProjectsConfig, CreateProjectConfig, UpdateProjectConfig, ListTasksConfig, CreateTaskConfig, GetTaskConfig, UpdateTaskConfig, ListTimeEntriesConfig, CreateTimeEntryConfig, UpdateTimeEntryConfig], Field(discriminator="operation")]

ROUTES = {'list_companies': {'method': 'GET',
                    'path': '/public-api/v1/companies',
                    'path_fields': {},
                    'params': {'page': 'page[number]',
                               'page_size': 'page[size]',
                               'filter_name': 'filter[name]'},
                    'wrapper': None,
                    'body_fields': [],
                    'nullable': []},
 'create_company': {'method': 'POST',
                    'path': '/public-api/v1/companies',
                    'path_fields': {},
                    'params': {},
                    'wrapper': 'company',
                    'body_fields': ['name',
                                    'default_contact_id',
                                    'description',
                                    'industry',
                                    'company_size',
                                    'source',
                                    'linkedin',
                                    'instagram',
                                    'twitter',
                                    'facebook',
                                    'domains'],
                    'nullable': ['default_contact_id',
                                 'description',
                                 'industry',
                                 'company_size',
                                 'source',
                                 'linkedin',
                                 'instagram',
                                 'twitter',
                                 'facebook',
                                 'domains']},
 'get_company': {'method': 'GET',
                 'path': '/public-api/v1/companies/{id}',
                 'path_fields': {'company_id': 'id'},
                 'params': {},
                 'wrapper': None,
                 'body_fields': [],
                 'nullable': []},
 'update_company': {'method': 'PATCH',
                    'path': '/public-api/v1/companies/{id}',
                    'path_fields': {'company_id': 'id'},
                    'params': {},
                    'wrapper': 'company',
                    'body_fields': ['name',
                                    'default_contact_id',
                                    'description',
                                    'industry',
                                    'company_size',
                                    'source',
                                    'linkedin',
                                    'instagram',
                                    'twitter',
                                    'facebook',
                                    'domains'],
                    'nullable': ['default_contact_id',
                                 'description',
                                 'industry',
                                 'company_size',
                                 'source',
                                 'linkedin',
                                 'instagram',
                                 'twitter',
                                 'facebook',
                                 'domains']},
 'list_contacts': {'method': 'GET',
                   'path': '/public-api/v1/contacts',
                   'path_fields': {},
                   'params': {'page': 'page[number]',
                              'page_size': 'page[size]',
                              'filter_name': 'filter[name]',
                              'filter_email': 'filter[email]',
                              'filter_company_id': 'filter[company_id]'},
                   'wrapper': None,
                   'body_fields': [],
                   'nullable': []},
 'create_contact': {'method': 'POST',
                    'path': '/public-api/v1/contacts',
                    'path_fields': {},
                    'params': {},
                    'wrapper': 'contact',
                    'body_fields': ['name', 'email', 'job_title', 'phone_number', 'company_id'],
                    'nullable': ['job_title', 'phone_number', 'company_id']},
 'get_contact': {'method': 'GET',
                 'path': '/public-api/v1/contacts/{id}',
                 'path_fields': {'contact_id': 'id'},
                 'params': {},
                 'wrapper': None,
                 'body_fields': [],
                 'nullable': []},
 'update_contact': {'method': 'PATCH',
                    'path': '/public-api/v1/contacts/{id}',
                    'path_fields': {'contact_id': 'id'},
                    'params': {},
                    'wrapper': 'contact',
                    'body_fields': ['name', 'email', 'job_title', 'phone_number'],
                    'nullable': ['job_title', 'phone_number']},
 'list_deals': {'method': 'GET',
                'path': '/public-api/v1/deals',
                'path_fields': {},
                'params': {'page': 'page[number]',
                           'page_size': 'page[size]',
                           'filter_title': 'filter[title]',
                           'filter_deal_number': 'filter[deal_number]',
                           'filter_assignee_member_id': 'filter[assignee_member_id]',
                           'filter_board_group_id': 'filter[board_group_id]'},
                'wrapper': None,
                'body_fields': [],
                'nullable': []},
 'create_deal': {'method': 'POST',
                 'path': '/public-api/v1/deals',
                 'path_fields': {},
                 'params': {},
                 'wrapper': 'deal',
                 'body_fields': ['title',
                                 'company_id',
                                 'contact_id',
                                 'assignee_member_id',
                                 'board_group_id',
                                 'deal_value'],
                 'nullable': ['contact_id', 'assignee_member_id', 'board_group_id', 'deal_value']},
 'update_deal': {'method': 'PATCH',
                 'path': '/public-api/v1/deals/{id}',
                 'path_fields': {'deal_id': 'id'},
                 'params': {},
                 'wrapper': 'deal',
                 'body_fields': ['title',
                                 'company_id',
                                 'contact_ids',
                                 'assignee_member_id',
                                 'board_group_id',
                                 'deal_value',
                                 'probability',
                                 'close_date'],
                 'nullable': ['company_id',
                              'assignee_member_id',
                              'board_group_id',
                              'deal_value',
                              'probability',
                              'close_date']},
 'list_invoices': {'method': 'GET',
                   'path': '/public-api/v1/invoices',
                   'path_fields': {},
                   'params': {'page': 'page[number]',
                              'page_size': 'page[size]',
                              'filter_invoice_number': 'filter[invoice_number]',
                              'filter_project_id': 'filter[project_id]',
                              'filter_company_id': 'filter[company_id]',
                              'filter_contact_id': 'filter[contact_id]'},
                   'wrapper': None,
                   'body_fields': [],
                   'nullable': []},
 'create_invoice': {'method': 'POST',
                    'path': '/public-api/v1/invoices',
                    'path_fields': {},
                    'params': {},
                    'wrapper': 'invoice',
                    'body_fields': ['company_id',
                                    'contact_id',
                                    'project_id',
                                    'currency',
                                    'title',
                                    'due',
                                    'due_date'],
                    'nullable': []},
 'update_invoice': {'method': 'PATCH',
                    'path': '/public-api/v1/invoices/{id}',
                    'path_fields': {'invoice_id': 'id'},
                    'params': {},
                    'wrapper': 'invoice',
                    'body_fields': ['contact_id', 'currency', 'title', 'due', 'due_date'],
                    'nullable': []},
 'list_projects': {'method': 'GET',
                   'path': '/public-api/v1/projects',
                   'path_fields': {},
                   'params': {'page': 'page[number]',
                              'page_size': 'page[size]',
                              'filter_title': 'filter[title]',
                              'filter_public_url_token': 'filter[public_url_token]',
                              'filter_board_group_id': 'filter[board_group_id]',
                              'filter_status': 'filter[status]',
                              'filter_has_budget': 'filter[has_budget]',
                              'filter_budget_amount_min': 'filter[budget_amount_min]',
                              'filter_budget_amount_max': 'filter[budget_amount_max]'},
                   'wrapper': None,
                   'body_fields': [],
                   'nullable': []},
 'create_project': {'method': 'POST',
                    'path': '/public-api/v1/projects',
                    'path_fields': {},
                    'params': {},
                    'wrapper': 'project',
                    'body_fields': ['title',
                                    'company_id',
                                    'currency',
                                    'start_date',
                                    'finish_date',
                                    'billing_type',
                                    'billing_fee',
                                    'billing_cycle'],
                    'nullable': ['currency', 'start_date', 'finish_date', 'billing_fee', 'billing_cycle']},
 'update_project': {'method': 'PATCH',
                    'path': '/public-api/v1/projects/{id}',
                    'path_fields': {'project_id': 'id'},
                    'params': {},
                    'wrapper': 'project',
                    'body_fields': ['title',
                                    'start_date',
                                    'finish_date',
                                    'billing_type',
                                    'billing_fee',
                                    'billing_cycle',
                                    'board_group_id'],
                    'nullable': ['finish_date', 'billing_fee', 'billing_cycle']},
 'list_tasks': {'method': 'GET',
                'path': '/public-api/v1/tasks',
                'path_fields': {},
                'params': {'page': 'page[number]',
                           'page_size': 'page[size]',
                           'filter_assignee_id': 'filter[assignee_id]',
                           'filter_scope': 'filter[scope]',
                           'filter_due': 'filter[due]',
                           'filter_due_from': 'filter[due_from]',
                           'filter_due_to': 'filter[due_to]',
                           'filter_billable': 'filter[billable]',
                           'filter_deal_id': 'filter[deal_id]',
                           'filter_priority': 'filter[priority]',
                           'filter_project_id': 'filter[project_id]',
                           'filter_tag_id': 'filter[tag_id]',
                           'filter_task_status_id': 'filter[task_status_id]',
                           'filter_title': 'filter[title]'},
                'wrapper': None,
                'body_fields': [],
                'nullable': []},
 'create_task': {'method': 'POST',
                 'path': '/public-api/v1/tasks',
                 'path_fields': {},
                 'params': {},
                 'wrapper': 'task',
                 'body_fields': ['title',
                                 'project_id',
                                 'deal_id',
                                 'parent_task_uuid',
                                 'assignee_member_id',
                                 'priority',
                                 'due_date',
                                 'start_date',
                                 'description',
                                 'time_estimate_in_minutes',
                                 'task_status_id',
                                 'billable',
                                 'tag_ids'],
                 'nullable': ['project_id',
                              'deal_id',
                              'parent_task_uuid',
                              'assignee_member_id',
                              'priority',
                              'due_date',
                              'start_date',
                              'description',
                              'time_estimate_in_minutes',
                              'task_status_id']},
 'get_task': {'method': 'GET',
              'path': '/public-api/v1/tasks/{uuid}',
              'path_fields': {'task_uuid': 'uuid'},
              'params': {},
              'wrapper': None,
              'body_fields': [],
              'nullable': []},
 'update_task': {'method': 'PATCH',
                 'path': '/public-api/v1/tasks/{uuid}',
                 'path_fields': {'task_uuid': 'uuid'},
                 'params': {},
                 'wrapper': 'task',
                 'body_fields': ['title',
                                 'project_id',
                                 'deal_id',
                                 'assignee_member_id',
                                 'priority',
                                 'due_date',
                                 'start_date',
                                 'description',
                                 'time_estimate_in_minutes',
                                 'task_status_id',
                                 'billable',
                                 'tag_ids'],
                 'nullable': ['project_id',
                              'deal_id',
                              'assignee_member_id',
                              'due_date',
                              'start_date',
                              'description',
                              'time_estimate_in_minutes']},
 'list_time_entries': {'method': 'GET',
                       'path': '/public-api/v1/time_entries',
                       'path_fields': {},
                       'params': {'page': 'page[number]',
                                  'page_size': 'page[size]',
                                  'filter_date_from': 'filter[date_from]',
                                  'filter_date_to': 'filter[date_to]',
                                  'filter_owner_member_id': 'filter[owner_member_id]',
                                  'filter_project_id': 'filter[project_id]',
                                  'filter_company_id': 'filter[company_id]',
                                  'filter_billing_status': 'filter[billing_status]',
                                  'filter_currency': 'filter[currency]'},
                       'wrapper': None,
                       'body_fields': [],
                       'nullable': []},
 'create_time_entry': {'method': 'POST',
                       'path': '/public-api/v1/time_entries',
                       'path_fields': {},
                       'params': {},
                       'wrapper': 'time_entry',
                       'body_fields': ['seconds',
                                       'date',
                                       'project_id',
                                       'task_uuid',
                                       'notes',
                                       'rate',
                                       'non_billable',
                                       'owner_member_id'],
                       'nullable': ['project_id',
                                    'task_uuid',
                                    'notes',
                                    'rate',
                                    'non_billable',
                                    'owner_member_id']},
 'update_time_entry': {'method': 'PATCH',
                       'path': '/public-api/v1/time_entries/{key}',
                       'path_fields': {'time_entry_key': 'key'},
                       'params': {},
                       'wrapper': 'time_entry',
                       'body_fields': ['seconds',
                                       'date',
                                       'project_id',
                                       'task_uuid',
                                       'notes',
                                       'rate',
                                       'non_billable',
                                       'billing_status',
                                       'owner_member_id'],
                       'nullable': ['project_id',
                                    'task_uuid',
                                    'notes',
                                    'rate',
                                    'non_billable',
                                    'owner_member_id']}}
