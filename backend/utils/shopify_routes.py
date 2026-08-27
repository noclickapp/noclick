"""HTTP routes owned by the public NoClick Shopify app."""

from fastapi import APIRouter, Request

from utils.shopify_compliance import receive_compliance_webhook
from utils.shopify_install import ShopifyInstallExchangeRequest, exchange_public_install

install_router = APIRouter(tags=["shopify"])
compliance_router = APIRouter(tags=["shopify-compliance"])


@compliance_router.post("/shopify/compliance")
async def shopify_compliance(request: Request):
    # Shopify only needs a fast 2xx acknowledgement.  The returned identifiers
    # contain no customer payload and make delivery tests diagnosable.
    return await receive_compliance_webhook(request)


@install_router.post("/shopify/install/exchange")
async def shopify_install_exchange(
    request: Request, body: ShopifyInstallExchangeRequest
):
    return await exchange_public_install(request, body)
