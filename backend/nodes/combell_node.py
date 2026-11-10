"""Combell reseller Public API v2: one documented request per operation.

Contract and HMAC protocol: https://api.combell.com/v2/documentation
Lists return a single page. Provisioning is asynchronous; a 202 acknowledges
acceptance and does not claim that the resource has been provisioned.
No webhooks or created/updated list filtering are published in this contract.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from typing import Annotated, Literal, Union
from urllib.parse import quote
from uuid import UUID, uuid4

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

BASE_URL = "https://api.combell.com/v2"


class CombellAPIKeyCredential(BaseModel):
    model_config = ConfigDict(title="Combell API Key", extra="ignore", hide_input_in_errors=True,
        json_schema_extra={
            "x-credential-url": "https://api.combell.com/v2/documentation",
            "x-credential-instructions": "In your Combell reseller control panel, copy your API key and secret and whitelist the IP addresses NoClick uses to connect. Paste both values below. NoClick signs requests with HMAC-SHA256 and reads your accounts to check access. Write access depends on your reseller permissions.",
        })
    credential_type: Literal["combell_api_key"] = Field("combell_api_key", json_schema_extra={"ui:hidden": True})
    api_key: str = Field(..., title="API key", min_length=1, max_length=4096, repr=False, json_schema_extra={"ui:widget": "password"})
    api_secret: str = Field(..., title="API secret", min_length=1, max_length=4096, repr=False, json_schema_extra={"ui:widget": "password"})

    @field_validator("api_key", "api_secret", mode="before")
    @classmethod
    def secret(cls, value):
        value = clean_secret(value, field_name="API key or secret")
        if not value.isascii() or any(c.isspace() for c in value) or ":" in value:
            raise ValueError("Paste the key or secret alone, without whitespace or a header prefix")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class CombellListAccounts(_Input):
    operation: Literal['list_accounts'] = Field('list_accounts', title='List Accounts', json_schema_extra={"ui:hidden": True})
    skip: int | None = Field(None, title='Skip', description='The number of items to skip in the resultset.', ge=0, le=1000000)
    take: int | None = Field(None, title='Take', description='The number of items to return in the resultset. The returned count can be equal or less than this number.', ge=1, le=1000000)
    asset_type: Literal['domain', 'linux_hosting', 'mysql', 'dns', 'mailbox', 'windows_hosting'] | None = Field(None, title='Asset Type', description='Filters the list, returning only accounts containing the specified asset type.')
    identifier: str | None = Field(None, title='Identifier', description='Return only accounts, matching the specified identifier.')

class CombellGetAccount(_Input):
    operation: Literal['get_account'] = Field('get_account', title='Get Account', json_schema_extra={"ui:hidden": True})
    account_id: int = Field(..., title='Account Id', description='The id of the account.', ge=1)

class CombellCreateAccount(_Input):
    operation: Literal['create_account'] = Field('create_account', title='Create Account', json_schema_extra={"ui:hidden": True})
    identifier: str = Field(..., title='Identifier', description='An identifier for the account.\r\n\r\nShould be a domain name for hosting accounts.')
    servicepack_id: int = Field(..., title='Servicepack Id', description='The servicepack id that defines the account.', ge=1)
    ftp_password: str | None = Field(None, title='Ftp Password', description='Ftp password for the account.\r\n\r\nApplies only if the servicepack contains hosting.\r\n\r\nPasswords have to adhere to following rules:\r\n<ul><li>Between 8-20 characters.</li><li>Must be a mix of letters and digits.</li><li>Must contain at least one digit (0-9).</li><li>Must contain at least one letter (a-z).</li><li>Cannot contain spaces.</li><li>Cannot contain characters: * € $ & + } { \' " \\ </li></ul>', repr=False, json_schema_extra={"ui:widget": "password"})

class CombellListDnsRecords(_Input):
    operation: Literal['list_dns_records'] = Field('list_dns_records', title='List Dns Records', json_schema_extra={"ui:hidden": True})
    domain_name: str = Field(..., title='Domain Name', description='The domain name.', min_length=1, max_length=512, pattern=r"^[^/\\?#\x00-\x20]+$")
    skip: int | None = Field(None, title='Skip', description='The number of items to skip in the resultset.', ge=0, le=1000000)
    take: int | None = Field(None, title='Take', description='The number of items to return in the resultset. The returned count can be equal or less than this number.', ge=1, le=1000000)
    type: str | None = Field(None, title='Type', description='Filters records matching the type. Most other filters only apply when this filter is specified.')
    record_name: str | None = Field(None, title='Record Name', description='Filters records matching the record name. This filter only applies to lookups of A, AAAA, CAA, CNAME, MX, TXT, SRV, ALIAS and TLSA records.')
    service: str | None = Field(None, title='Service', description='Filters records for the service. This filter only applies to lookups of SRV records.')

class CombellGetDnsRecord(_Input):
    operation: Literal['get_dns_record'] = Field('get_dns_record', title='Get Dns Record', json_schema_extra={"ui:hidden": True})
    domain_name: str = Field(..., title='Domain Name', description='The domain name.', min_length=1, max_length=512, pattern=r"^[^/\\?#\x00-\x20]+$")
    record_id: str = Field(..., title='Record Id', description='The id of the record.', min_length=1, max_length=512, pattern=r"^[^/\\?#\x00-\x20]+$")

class CombellCreateDnsRecord(_Input):
    operation: Literal['create_dns_record'] = Field('create_dns_record', title='Create Dns Record', json_schema_extra={"ui:hidden": True})
    domain_name: str = Field(..., title='Domain Name', description='The domain name.', min_length=1, max_length=512, pattern=r"^[^/\\?#\x00-\x20]+$")
    id: str | None = Field(None, title='Id', description='The id of the record\r\nThis value is ignored for creation of new records.')
    type: str = Field(..., title='Type', description='The type of the record (A, AAAA, CAA, CNAME, MX, TXT, SRV, ALIAS and TLSA).')
    record_name: str | None = Field(None, title='Record Name', description="The name of the record.\r\n\r\nThis is the host name, alias defined by the record.\r\n\r\nAn empty record or '@' is equal to the domain name.\r\n\r\nApplies to A, AAAA, MX, CNAME, TXT, CAA, ALIAS and TLSA records.\r\n\r\nWhen type is TLSA the recommended value format is port number, protocol and host: _25._tcp.\r\n\r\nDoes not apply for SRV records.")
    ttl: int = Field(3600, title='Ttl', description='Time to live of the record in seconds.\r\n\r\nIt defines the time frame that clients can cache the information.\r\n\r\nThe value MUST be between 60 and 86400. The default value is 3600 (= 1 hour).', ge=60, le=86400)
    content: str | None = Field(None, title='Content', description='Variable data depending on the record type.\r\n<ul><li>A: the IPv4 address.</li><li>AAAA: the IPv6 address.</li><li>CNAME: canonical name of an alias.</li><li>MX: fully qualified domain name of a mail host.</li><li>SRV: does not apply. Data for the SRV records can be found in specific properties.</li><li>TXT: free form text data.</li><li>CAA: format should match specific values for flag, tag and ca: "{flag} {tag} {ca}".\r\n        <ul><li>The flag. The values 128 (critical) or 0 (non-critical) are expected, with 0 as the default.</li><li>The tag. A tag specifies which actions an authorized CA can take in terms of issuing SSL/TLS certificates.\r\n<ul><li>The value "issue": explicitly authorizes a single certificate authority to issue a certificate (any type) for the hostname.</li><li>The value "issuewild": explicitly authorizes a single certificate authority to issue a wildcard certificate (and only wildcard) for the hostname.</li><li>The value "iodef": specifies a URL to which a certificate authority may report policy violations.</li></ul></li><li>The ca. This is the domain of the CA (Certification Authority) that has the authority to issue certificates for the domain in question. If the value is a semicolon (;), it means that no CA has the authority to issue a certificate for that domain.</li></ul></li><li>ALIAS: canonical name of an alias.</li><li>TLSA: format should match specific values for usage, selector, matching type and data: "{usage} {selector} {matching_type} {data}"\r\n        <ul><li>The usage. The first field after the TLSA text in the DNS RR, specifies how to verify the certificate.\r\n<ul><li>A value of 0 is for what is commonly called CA constraint (and PKIX-TA). The certificate provided when establishing TLS must be issued by the listed root-CA or one of its intermediate CAs, with a valid certification path to a root-CA already trusted by the application doing the verification.</li><li>A value of 1 is for what is commonly called Service certificate constraint (and PKIX-EE). The certificate used must match the TLSA record exactly, and it must also pass PKIX certification path validation to a trusted root-CA.</li><li>A value of 2 is for what is commonly called Trust Anchor Assertion (and DANE-TA). The certificate used has a valid certification path pointing back to the certificate mention in this record, but there is no need for it to pass the PKIX certification path validation to a trusted root-CA.</li><li>A value of 3 is for what is commonly called Domain issued certificate (and DANE-EE). The services uses a self-signed certificate. It is not signed by anyone else, and is exactly this record.</li></ul></li><li>The selector. When connecting to the service and a certificate is received, the selector field specifies which parts of it should be checked.\r\n<ul><li>A value of 0 means to select the entire certificate for matching.</li><li>A value of 1 means to select just the public key for certificate matching. Matching the public key is often sufficient, as this is likely to be unique.</li></ul></li><li>The matching type.\r\n<ul><li>A type of 0 means the entire information selected is present in the certificate association data.</li><li>A type of 1 means to do a SHA-256 hash of the selected data.</li><li>A type of 2 means to do a SHA-512 hash of the selected data.</li></ul></li><li>The actual data to be matched given the settings of the other fields. This is a long text string of hexadecimal data.</li></ul></li></ul>')
    priority: int = Field(10, title='Priority', description='The priority for MX or SRV records.\r\n\r\nA lower value means more preferred.\r\n\r\nThe value MUST be a positive integer less or equal to 9999.', ge=1, le=9999)
    service: str | None = Field(None, title='Service', description='The symbolic name of the desired service for SRV records.\r\n\r\nEditing the value is not possible. You should add a new SRV record and can delete the existing record.')
    weight: int = Field(0, title='Weight', description='The weight for SRV records with the same priority.\r\n\r\nA higher value means more preferred.')
    target: str | None = Field(None, title='Target', description='The canonical hostname of the machine providing the service for SRV records.\r\n\r\nEditing the value is not possible. You should add a new SRV record and delete the existing record.')
    protocol: str = Field('TCP', title='Protocol', description='Used for the creation of SRV records. Possible options: TCP, UDP, ...\r\n\r\nEditing the value is not possible. You should add a new SRV record and delete the existing record.')
    port: int | None = Field(None, title='Port', description='The port for SRV records.\r\n\r\nThe value MUST be a positive integer.\r\n\r\nEditing the value is not possible. You should add a new SRV record and delete the existing record.')

class CombellUpdateDnsRecord(_Input):
    operation: Literal['update_dns_record'] = Field('update_dns_record', title='Update Dns Record', json_schema_extra={"ui:hidden": True})
    domain_name: str = Field(..., title='Domain Name', description='The domain name.', min_length=1, max_length=512, pattern=r"^[^/\\?#\x00-\x20]+$")
    record_id: str = Field(..., title='Record Id', description='The id of the record.', min_length=1, max_length=512, pattern=r"^[^/\\?#\x00-\x20]+$")
    id: str | None = Field(None, title='Id', description='The id of the record\r\nThis value is ignored for creation of new records.')
    type: str = Field(..., title='Type', description='The type of the record (A, AAAA, CAA, CNAME, MX, TXT, SRV, ALIAS and TLSA).')
    record_name: str | None = Field(None, title='Record Name', description="The name of the record.\r\n\r\nThis is the host name, alias defined by the record.\r\n\r\nAn empty record or '@' is equal to the domain name.\r\n\r\nApplies to A, AAAA, MX, CNAME, TXT, CAA, ALIAS and TLSA records.\r\n\r\nWhen type is TLSA the recommended value format is port number, protocol and host: _25._tcp.\r\n\r\nDoes not apply for SRV records.")
    ttl: int = Field(3600, title='Ttl', description='Time to live of the record in seconds.\r\n\r\nIt defines the time frame that clients can cache the information.\r\n\r\nThe value MUST be between 60 and 86400. The default value is 3600 (= 1 hour).', ge=60, le=86400)
    content: str | None = Field(None, title='Content', description='Variable data depending on the record type.\r\n<ul><li>A: the IPv4 address.</li><li>AAAA: the IPv6 address.</li><li>CNAME: canonical name of an alias.</li><li>MX: fully qualified domain name of a mail host.</li><li>SRV: does not apply. Data for the SRV records can be found in specific properties.</li><li>TXT: free form text data.</li><li>CAA: format should match specific values for flag, tag and ca: "{flag} {tag} {ca}".\r\n        <ul><li>The flag. The values 128 (critical) or 0 (non-critical) are expected, with 0 as the default.</li><li>The tag. A tag specifies which actions an authorized CA can take in terms of issuing SSL/TLS certificates.\r\n<ul><li>The value "issue": explicitly authorizes a single certificate authority to issue a certificate (any type) for the hostname.</li><li>The value "issuewild": explicitly authorizes a single certificate authority to issue a wildcard certificate (and only wildcard) for the hostname.</li><li>The value "iodef": specifies a URL to which a certificate authority may report policy violations.</li></ul></li><li>The ca. This is the domain of the CA (Certification Authority) that has the authority to issue certificates for the domain in question. If the value is a semicolon (;), it means that no CA has the authority to issue a certificate for that domain.</li></ul></li><li>ALIAS: canonical name of an alias.</li><li>TLSA: format should match specific values for usage, selector, matching type and data: "{usage} {selector} {matching_type} {data}"\r\n        <ul><li>The usage. The first field after the TLSA text in the DNS RR, specifies how to verify the certificate.\r\n<ul><li>A value of 0 is for what is commonly called CA constraint (and PKIX-TA). The certificate provided when establishing TLS must be issued by the listed root-CA or one of its intermediate CAs, with a valid certification path to a root-CA already trusted by the application doing the verification.</li><li>A value of 1 is for what is commonly called Service certificate constraint (and PKIX-EE). The certificate used must match the TLSA record exactly, and it must also pass PKIX certification path validation to a trusted root-CA.</li><li>A value of 2 is for what is commonly called Trust Anchor Assertion (and DANE-TA). The certificate used has a valid certification path pointing back to the certificate mention in this record, but there is no need for it to pass the PKIX certification path validation to a trusted root-CA.</li><li>A value of 3 is for what is commonly called Domain issued certificate (and DANE-EE). The services uses a self-signed certificate. It is not signed by anyone else, and is exactly this record.</li></ul></li><li>The selector. When connecting to the service and a certificate is received, the selector field specifies which parts of it should be checked.\r\n<ul><li>A value of 0 means to select the entire certificate for matching.</li><li>A value of 1 means to select just the public key for certificate matching. Matching the public key is often sufficient, as this is likely to be unique.</li></ul></li><li>The matching type.\r\n<ul><li>A type of 0 means the entire information selected is present in the certificate association data.</li><li>A type of 1 means to do a SHA-256 hash of the selected data.</li><li>A type of 2 means to do a SHA-512 hash of the selected data.</li></ul></li><li>The actual data to be matched given the settings of the other fields. This is a long text string of hexadecimal data.</li></ul></li></ul>')
    priority: int = Field(10, title='Priority', description='The priority for MX or SRV records.\r\n\r\nA lower value means more preferred.\r\n\r\nThe value MUST be a positive integer less or equal to 9999.', ge=1, le=9999)
    service: str | None = Field(None, title='Service', description='The symbolic name of the desired service for SRV records.\r\n\r\nEditing the value is not possible. You should add a new SRV record and can delete the existing record.')
    weight: int = Field(0, title='Weight', description='The weight for SRV records with the same priority.\r\n\r\nA higher value means more preferred.')
    target: str | None = Field(None, title='Target', description='The canonical hostname of the machine providing the service for SRV records.\r\n\r\nEditing the value is not possible. You should add a new SRV record and delete the existing record.')
    protocol: str = Field('TCP', title='Protocol', description='Used for the creation of SRV records. Possible options: TCP, UDP, ...\r\n\r\nEditing the value is not possible. You should add a new SRV record and delete the existing record.')
    port: int | None = Field(None, title='Port', description='The port for SRV records.\r\n\r\nThe value MUST be a positive integer.\r\n\r\nEditing the value is not possible. You should add a new SRV record and delete the existing record.')

class CombellDeleteDnsRecord(_Input):
    operation: Literal['delete_dns_record'] = Field('delete_dns_record', title='Delete Dns Record', json_schema_extra={"ui:hidden": True})
    domain_name: str = Field(..., title='Domain Name', description='The domain name.', min_length=1, max_length=512, pattern=r"^[^/\\?#\x00-\x20]+$")
    record_id: str = Field(..., title='Record Id', description='The id of the record.', min_length=1, max_length=512, pattern=r"^[^/\\?#\x00-\x20]+$")

class CombellListDomains(_Input):
    operation: Literal['list_domains'] = Field('list_domains', title='List Domains', json_schema_extra={"ui:hidden": True})
    skip: int | None = Field(None, title='Skip', description='The number of items to skip in the resultset.', ge=0, le=1000000)
    take: int | None = Field(None, title='Take', description='The number of items to return in the resultset. The returned count can be equal or less than this number.', ge=1, le=1000000)

class CombellGetDomain(_Input):
    operation: Literal['get_domain'] = Field('get_domain', title='Get Domain', json_schema_extra={"ui:hidden": True})
    domain_name: str = Field(..., title='Domain Name', description='The domain name', min_length=1, max_length=512, pattern=r"^[^/\\?#\x00-\x20]+$")

class CombellUpdateNameservers(_Input):
    operation: Literal['update_nameservers'] = Field('update_nameservers', title='Update Nameservers', json_schema_extra={"ui:hidden": True})
    domain_name: str = Field(..., title='Domain Name', description='The domain name', min_length=1, max_length=512, pattern=r"^[^/\\?#\x00-\x20]+$")
    name_servers: list[str] = Field(..., title='Name Servers', description='List of name servers.')

class CombellUpdateDomainRenewal(_Input):
    operation: Literal['update_domain_renewal'] = Field('update_domain_renewal', title='Update Domain Renewal', json_schema_extra={"ui:hidden": True})
    domain_name: str = Field(..., title='Domain Name', description='The domain name', min_length=1, max_length=512, pattern=r"^[^/\\?#\x00-\x20]+$")
    will_renew: bool = Field(..., title='Will Renew', description='Indication of renewal.')

class CombellListLinuxHostings(_Input):
    operation: Literal['list_linux_hostings'] = Field('list_linux_hostings', title='List Linux Hostings', json_schema_extra={"ui:hidden": True})
    skip: int | None = Field(None, title='Skip', description='The number of items to skip in the resultset.', ge=0, le=1000000)
    take: int | None = Field(None, title='Take', description='The number of items to return in the resultset. The returned count can be equal or less than this number.', ge=1, le=1000000)

class CombellGetLinuxHosting(_Input):
    operation: Literal['get_linux_hosting'] = Field('get_linux_hosting', title='Get Linux Hosting', json_schema_extra={"ui:hidden": True})
    domain_name: str = Field(..., title='Domain Name', description='The Linux hosting domain name.', min_length=1, max_length=512, pattern=r"^[^/\\?#\x00-\x20]+$")

class CombellUpdatePhpVersion(_Input):
    operation: Literal['update_php_version'] = Field('update_php_version', title='Update Php Version', json_schema_extra={"ui:hidden": True})
    domain_name: str = Field(..., title='Domain Name', description='Linux hosting domain name.', min_length=1, max_length=512, pattern=r"^[^/\\?#\x00-\x20]+$")
    version: str = Field(..., title='Version', description='Php version')

class CombellListMailboxes(_Input):
    operation: Literal['list_mailboxes'] = Field('list_mailboxes', title='List Mailboxes', json_schema_extra={"ui:hidden": True})
    domain_name: str = Field(..., title='Domain Name', description='Obligated domain name for getting mailboxes.')

class CombellGetMailbox(_Input):
    operation: Literal['get_mailbox'] = Field('get_mailbox', title='Get Mailbox', json_schema_extra={"ui:hidden": True})
    mailbox_name: str = Field(..., title='Mailbox Name', description='Mailbox name.', min_length=1, max_length=512, pattern=r"^[^/\\?#\x00-\x20]+$")

class CombellCreateMailbox(_Input):
    operation: Literal['create_mailbox'] = Field('create_mailbox', title='Create Mailbox', json_schema_extra={"ui:hidden": True})
    email_address: str = Field(..., title='Email Address', description='E-mail address')
    account_id: int = Field(..., title='Account Id', description='Mail zone account id', ge=1)
    password: str = Field(..., title='Password', description='The password for the mailbox.\r\n\r\nPasswords have to adhere to following rules:\r\n<ul><li>Between 8-20 characters.</li><li>Must be a mix of letters and digits.</li><li>Must contain at least one digit (0-9).</li><li>Must contain at least one letter (a-z).</li><li>Cannot contain spaces.</li><li>Cannot contain characters: * € $ & + } { \' " \\ </li></ul>', repr=False, json_schema_extra={"ui:widget": "password"})

class CombellDeleteMailbox(_Input):
    operation: Literal['delete_mailbox'] = Field('delete_mailbox', title='Delete Mailbox', json_schema_extra={"ui:hidden": True})
    mailbox_name: str = Field(..., title='Mailbox Name', description='Mailbox name.', min_length=1, max_length=512, pattern=r"^[^/\\?#\x00-\x20]+$")

class CombellUpdateMailboxAutoreply(_Input):
    operation: Literal['update_mailbox_autoreply'] = Field('update_mailbox_autoreply', title='Update Mailbox Autoreply', json_schema_extra={"ui:hidden": True})
    mailbox_name: str = Field(..., title='Mailbox Name', description='Mailbox name.', min_length=1, max_length=512, pattern=r"^[^/\\?#\x00-\x20]+$")
    enabled: bool = Field(..., title='Enabled', description='Enabled')
    subject: str | None = Field(None, title='Subject', description='Subject')
    message: str | None = Field(None, title='Message', description='Message')

class CombellUpdateMailboxAutoforward(_Input):
    operation: Literal['update_mailbox_autoforward'] = Field('update_mailbox_autoforward', title='Update Mailbox Autoforward', json_schema_extra={"ui:hidden": True})
    mailbox_name: str = Field(..., title='Mailbox Name', description='Mailbox name.', min_length=1, max_length=512, pattern=r"^[^/\\?#\x00-\x20]+$")
    enabled: bool = Field(..., title='Enabled', description='Enabled')
    email_addresses: list[str] | None = Field(None, title='Email Addresses', description='E-mail addresses to which e-mails are forwarded')
    copy_to_myself: bool | None = Field(None, title='Copy To Myself', description='Copy to myself')

class CombellListMysqlDatabases(_Input):
    operation: Literal['list_mysql_databases'] = Field('list_mysql_databases', title='List Mysql Databases', json_schema_extra={"ui:hidden": True})
    skip: int | None = Field(None, title='Skip', description='The number of items to skip in the resultset.', ge=0, le=1000000)
    take: int | None = Field(None, title='Take', description='The number of items to return in the resultset. The returned count can be equal or less than this number.', ge=1, le=1000000)

class CombellGetMysqlDatabase(_Input):
    operation: Literal['get_mysql_database'] = Field('get_mysql_database', title='Get Mysql Database', json_schema_extra={"ui:hidden": True})
    database_name: str = Field(..., title='Database Name', min_length=1, max_length=512, pattern=r"^[^/\\?#\x00-\x20]+$")

class CombellGetProvisioningJob(_Input):
    operation: Literal['get_provisioning_job'] = Field('get_provisioning_job', title='Get Provisioning Job', json_schema_extra={"ui:hidden": True})
    job_id: UUID = Field(..., title='Job Id')

class CombellListServicepacks(_Input):
    operation: Literal['list_servicepacks'] = Field('list_servicepacks', title='List Servicepacks', json_schema_extra={"ui:hidden": True})


CombellOperation = Annotated[Union[
    CombellListAccounts,
    CombellGetAccount,
    CombellCreateAccount,
    CombellListDnsRecords,
    CombellGetDnsRecord,
    CombellCreateDnsRecord,
    CombellUpdateDnsRecord,
    CombellDeleteDnsRecord,
    CombellListDomains,
    CombellGetDomain,
    CombellUpdateNameservers,
    CombellUpdateDomainRenewal,
    CombellListLinuxHostings,
    CombellGetLinuxHosting,
    CombellUpdatePhpVersion,
    CombellListMailboxes,
    CombellGetMailbox,
    CombellCreateMailbox,
    CombellDeleteMailbox,
    CombellUpdateMailboxAutoreply,
    CombellUpdateMailboxAutoforward,
    CombellListMysqlDatabases,
    CombellGetMysqlDatabase,
    CombellGetProvisioningJob,
    CombellListServicepacks
], Field(discriminator="operation")]


class CombellFullConfig(NodeConfig[CombellOperation, CombellAPIKeyCredential]):
    pass


ROUTES = {'list_accounts': {'method': 'GET',
                   'path': '/accounts',
                   'paths': {},
                   'query': ['skip', 'take', 'asset_type', 'identifier'],
                   'body': [],
                   'responses': {200: 'list'},
                   'operation_id': 'GetAccounts'},
 'get_account': {'method': 'GET',
                 'path': '/accounts/{accountId}',
                 'paths': {'accountId': 'account_id'},
                 'query': [],
                 'body': [],
                 'responses': {200: 'object'},
                 'operation_id': 'GetAccount'},
 'create_account': {'method': 'POST',
                    'path': '/accounts',
                    'paths': {},
                    'query': [],
                    'body': ['identifier', 'servicepack_id', 'ftp_password'],
                    'responses': {202: 'empty'},
                    'operation_id': 'CreateAccount'},
 'list_dns_records': {'method': 'GET',
                      'path': '/dns/{domainName}/records',
                      'paths': {'domainName': 'domain_name'},
                      'query': ['skip', 'take', 'type', 'record_name', 'service'],
                      'body': [],
                      'responses': {200: 'list'},
                      'operation_id': 'GetRecords'},
 'get_dns_record': {'method': 'GET',
                    'path': '/dns/{domainName}/records/{recordId}',
                    'paths': {'domainName': 'domain_name', 'recordId': 'record_id'},
                    'query': [],
                    'body': [],
                    'responses': {200: 'object'},
                    'operation_id': 'GetRecord'},
 'create_dns_record': {'method': 'POST',
                       'path': '/dns/{domainName}/records',
                       'paths': {'domainName': 'domain_name'},
                       'query': [],
                       'body': ['id',
                                'type',
                                'record_name',
                                'ttl',
                                'content',
                                'priority',
                                'service',
                                'weight',
                                'target',
                                'protocol',
                                'port'],
                       'responses': {201: 'empty'},
                       'operation_id': 'CreateRecord'},
 'update_dns_record': {'method': 'PUT',
                       'path': '/dns/{domainName}/records/{recordId}',
                       'paths': {'domainName': 'domain_name', 'recordId': 'record_id'},
                       'query': [],
                       'body': ['id',
                                'type',
                                'record_name',
                                'ttl',
                                'content',
                                'priority',
                                'service',
                                'weight',
                                'target',
                                'protocol',
                                'port'],
                       'responses': {200: 'empty'},
                       'operation_id': 'EditRecord'},
 'delete_dns_record': {'method': 'DELETE',
                       'path': '/dns/{domainName}/records/{recordId}',
                       'paths': {'domainName': 'domain_name', 'recordId': 'record_id'},
                       'query': [],
                       'body': [],
                       'responses': {204: 'empty'},
                       'operation_id': 'DeleteRecord'},
 'list_domains': {'method': 'GET',
                  'path': '/domains',
                  'paths': {},
                  'query': ['skip', 'take'],
                  'body': [],
                  'responses': {200: 'list'},
                  'operation_id': 'GetDomains'},
 'get_domain': {'method': 'GET',
                'path': '/domains/{domainName}',
                'paths': {'domainName': 'domain_name'},
                'query': [],
                'body': [],
                'responses': {200: 'object'},
                'operation_id': 'GetDomain'},
 'update_nameservers': {'method': 'PUT',
                        'path': '/domains/{domainName}/nameservers',
                        'paths': {'domainName': 'domain_name'},
                        'query': [],
                        'body': ['domain_name', 'name_servers'],
                        'responses': {204: 'empty'},
                        'operation_id': 'EditNameServers'},
 'update_domain_renewal': {'method': 'PUT',
                           'path': '/domains/{domainName}/renew',
                           'paths': {'domainName': 'domain_name'},
                           'query': [],
                           'body': ['will_renew'],
                           'responses': {204: 'empty'},
                           'operation_id': 'ConfigureDomain'},
 'list_linux_hostings': {'method': 'GET',
                         'path': '/linuxhostings',
                         'paths': {},
                         'query': ['skip', 'take'],
                         'body': [],
                         'responses': {200: 'list'},
                         'operation_id': 'GetLinuxHostings'},
 'get_linux_hosting': {'method': 'GET',
                       'path': '/linuxhostings/{domainName}',
                       'paths': {'domainName': 'domain_name'},
                       'query': [],
                       'body': [],
                       'responses': {200: 'object'},
                       'operation_id': 'GetLinuxHosting'},
 'update_php_version': {'method': 'PUT',
                        'path': '/linuxhostings/{domainName}/phpsettings/version',
                        'paths': {'domainName': 'domain_name'},
                        'query': [],
                        'body': ['version'],
                        'responses': {204: 'empty'},
                        'operation_id': 'ChangePhpVersion'},
 'list_mailboxes': {'method': 'GET',
                    'path': '/mailboxes',
                    'paths': {},
                    'query': ['domain_name'],
                    'body': [],
                    'responses': {200: 'list'},
                    'operation_id': 'GetMailboxes'},
 'get_mailbox': {'method': 'GET',
                 'path': '/mailboxes/{mailboxName}',
                 'paths': {'mailboxName': 'mailbox_name'},
                 'query': [],
                 'body': [],
                 'responses': {200: 'object'},
                 'operation_id': 'GetMailbox'},
 'create_mailbox': {'method': 'POST',
                    'path': '/mailboxes',
                    'paths': {},
                    'query': [],
                    'body': ['email_address', 'account_id', 'password'],
                    'responses': {201: 'empty'},
                    'operation_id': 'CreateMailbox'},
 'delete_mailbox': {'method': 'DELETE',
                    'path': '/mailboxes/{mailboxName}',
                    'paths': {'mailboxName': 'mailbox_name'},
                    'query': [],
                    'body': [],
                    'responses': {204: 'empty'},
                    'operation_id': 'DeleteMailbox'},
 'update_mailbox_autoreply': {'method': 'PUT',
                              'path': '/mailboxes/{mailboxName}/autoreply',
                              'paths': {'mailboxName': 'mailbox_name'},
                              'query': [],
                              'body': ['enabled', 'subject', 'message'],
                              'responses': {204: 'empty'},
                              'operation_id': 'ConfigureMailboxAutoReply'},
 'update_mailbox_autoforward': {'method': 'PUT',
                                'path': '/mailboxes/{mailboxName}/autoforward',
                                'paths': {'mailboxName': 'mailbox_name'},
                                'query': [],
                                'body': ['enabled', 'email_addresses', 'copy_to_myself'],
                                'responses': {204: 'empty'},
                                'operation_id': 'ConfigureMailboxAutoForward'},
 'list_mysql_databases': {'method': 'GET',
                          'path': '/mysqldatabases',
                          'paths': {},
                          'query': ['skip', 'take'],
                          'body': [],
                          'responses': {200: 'list'},
                          'operation_id': 'GetMySqlDatabases'},
 'get_mysql_database': {'method': 'GET',
                        'path': '/mysqldatabases/{databaseName}',
                        'paths': {'databaseName': 'database_name'},
                        'query': [],
                        'body': [],
                        'responses': {200: 'object'},
                        'operation_id': 'GetMySqlDatabase'},
 'get_provisioning_job': {'method': 'GET',
                          'path': '/provisioningjobs/{jobId}',
                          'paths': {'jobId': 'job_id'},
                          'query': [],
                          'body': [],
                          'responses': {200: 'object', 201: 'object'},
                          'operation_id': 'GetProvisioningJob'},
 'list_servicepacks': {'method': 'GET',
                       'path': '/servicepacks',
                       'paths': {},
                       'query': [],
                       'body': [],
                       'responses': {200: 'list'},
                       'operation_id': 'Servicepacks'}}


def authorization(request, credential, *, nonce=None, timestamp=None):
    """Sign the exact outgoing URL and bytes, per the published HMAC protocol."""
    nonce = nonce or uuid4().hex
    timestamp = str(int(time.time())) if timestamp is None else str(timestamp)
    path_query = request.url.raw_path.decode('ascii')
    encoded_uri = quote(path_query.lower(), safe='')
    body_hash = base64.b64encode(hashlib.md5(request.content).digest()).decode() if request.content else ''
    message = credential.api_key + request.method.lower() + encoded_uri + timestamp + nonce + body_hash
    signature = base64.b64encode(hmac.new(credential.api_secret.encode(), message.encode(), hashlib.sha256).digest()).decode()
    return f'hmac {credential.api_key}:{signature}:{nonce}:{timestamp}'


def _redact(value, secrets):
    if isinstance(value, str):
        for secret in secrets:
            value = value.replace(secret, '[redacted]')
        return value
    if isinstance(value, list):
        return [_redact(item, secrets) for item in value]
    if isinstance(value, dict):
        return {_redact(str(key), secrets): _redact(item, secrets) for key, item in value.items()
                if str(key).lower() not in {'authorization', 'api_key', 'api_secret', 'password', 'ftp_password'}}
    return value


class CombellNode(WorkflowNode):
    integration_type = 'automation-combell'
    connection_evidence = ConnectionEvidence(noun='Combell accounts', operation='list_accounts', label_keys=('identifier', 'id'))

    @classmethod
    def get_config_model(cls):
        return CombellFullConfig

    async def execute(self, inputs):
        if self.config is None or self.config.credentials is None:
            raise ValueError('Connect your Combell API key and secret')
        config = self.config.config
        credential = self.config.credentials
        route = ROUTES[config.operation]
        values = config.model_dump(mode='json', exclude_none=True, exclude={'operation'})
        path = route['path']
        for placeholder, name in route['paths'].items():
            path = path.replace('{' + placeholder + '}', quote(str(values[name]), safe=''))
        params = {key: values[key] for key in route['query'] if key in values}
        body = {key: values[key] for key in route['body'] if key in values}
        content = json.dumps(body, ensure_ascii=False, separators=(',', ':')).encode() if route['body'] else b''
        writing = route['method'] != 'GET'
        secrets = [credential.api_key, credential.api_secret] + [values[k] for k in ('password', 'ftp_password') if values.get(k)]
        try:
            async with guarded_async_client(timeout=30, follow_redirects=False, trust_env=False) as client:
                request = client.build_request(route['method'], BASE_URL + path, params=params,
                    content=content, headers={'Accept': 'application/json', **({'Content-Type': 'application/json'} if route['body'] else {})})
                request.headers['Authorization'] = authorization(request, credential)
                response = await client.send(request)
            status = response.status_code
            shape = route['responses'].get(status)
            if shape is None:
                message = 'Combell returned an unexpected HTTP status'
                try:
                    error = response.json()
                    if isinstance(error, dict):
                        message = error.get('error_text') or error.get('message') or message
                except (ValueError, UnicodeError):
                    pass
                output = {'status': 'error', 'success': False, 'http_status': status, 'status_code': status, 'error': str(message)[:1000]}
                if writing:
                    output['write_outcome'] = 'unverified' if status < 400 or status >= 500 else 'rejected'
            else:
                payload = None
                if shape != 'empty':
                    if len(response.content) > 10_000_000:
                        raise ValueError('Response exceeds the supported size')
                    payload = response.json()
                    if (shape == 'list' and (not isinstance(payload, list) or any(not isinstance(row, dict) for row in payload))) or (shape == 'object' and not isinstance(payload, dict)):
                        raise ValueError('Unexpected Combell resource shape')
                    if isinstance(payload, dict) and (payload.get('error_code') or payload.get('validation_errors')):
                        raise ValueError('Combell returned an error envelope')
                output = {'status': 'success', 'success': True, 'http_status': status, 'status_code': status, 'data': payload}
                if shape == 'list' and 'skip' in route['query']:
                    # A short page cannot establish completion. Only Combell's
                    # paging headers provide authoritative offsets and totals.
                    paging = {}
                    for header, key in [('X-Paging-Skipped', 'skip'), ('X-Paging-Take', 'count'), ('X-Paging-TotalResults', 'total')]:
                        raw = response.headers.get(header)
                        if raw is not None:
                            if not raw.isdigit():
                                raise ValueError('Invalid paging header')
                            paging[key] = int(raw)
                    complete = set(paging) == {'skip', 'count', 'total'}
                    if complete and (paging['count'] != len(payload) or paging['skip'] != values.get('skip', 0) or paging['skip'] + paging['count'] > paging['total']):
                        raise ValueError('Inconsistent paging headers')
                    output['pagination'] = {**paging, 'completion_known': complete,
                        'next_skip': paging['skip'] + paging['count'] if complete and paging['count'] and paging['skip'] + paging['count'] < paging['total'] else None,
                        'has_more': paging['skip'] + paging['count'] < paging['total'] if complete else None}
                if writing:
                    output['write_outcome'] = 'accepted' if status == 202 else 'acknowledged'
                if response.headers.get('Location'):
                    # Return the provider's reference; never follow it implicitly.
                    output['location'] = response.headers['Location']
        except httpx.RequestError:
            output = {'status': 'error', 'success': False, 'error': 'Combell request could not be completed'}
            if writing:
                output['write_outcome'] = 'unverified'
        except (ValueError, UnicodeError):
            output = {'status': 'error', 'success': False, 'error': 'Combell response could not be interpreted'}
            if writing:
                output['write_outcome'] = 'unverified'
        output = _redact(output, secrets)
        await self.emit(output)
        return output
