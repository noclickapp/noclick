"""Billetweb API v1: fixed event, attendee, order, list and CRM operations.

Contract: https://www.billetweb.fr/api/openapi.json?v=1141
Authentication: https://www.billetweb.fr/bo/api.php
Attendee reads are limited by Billetweb to ten requests/minute; use last_update
for incremental sync. Writes are sent once and are never retried automatically.
"""
from __future__ import annotations

import base64
from typing import Annotated, Any, Literal, Union

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from nodes.core.base import NodeConfig, WorkflowNode
from nodes.core.connection_evidence import ConnectionEvidence
from nodes.core.credential_fields import clean_secret
from utils.ssrf import guarded_async_client

BASE_URL = "https://www.billetweb.fr"
CREDENTIAL_TYPE = "billetweb_api_key"


class BilletwebAPIKeyCredential(BaseModel):
    model_config = ConfigDict(
        extra="ignore",
        hide_input_in_errors=True,
        title="Billetweb API Key",
        json_schema_extra={
            "x-credential-url": "https://www.billetweb.fr/bo/api.php",
            "x-credential-instructions": "In Billetweb, open API key management and copy the User ID and API key. Give the key access to the events and actions your workflow needs. Paste each value below. NoClick uses HTTP Basic authentication and lists your events to check the connection. Attendee reads are limited to 10 calls per minute; use incremental filters for syncs.",
        },
    )
    credential_type: Literal["billetweb_api_key"] = Field(
        "billetweb_api_key", json_schema_extra={"ui:hidden": True}
    )
    user_id: str = Field(
        ...,
        title="User ID",
        pattern=r"^[0-9]+$",
        min_length=1,
        max_length=30,
        description="The numeric User value shown on Billetweb's API page.",
    )
    api_key: str = Field(
        ...,
        title="API Key",
        min_length=1,
        max_length=4096,
        json_schema_extra={"ui:widget": "password"},
    )

    @field_validator("api_key", mode="before")
    @classmethod
    def key(cls, value):
        value = clean_secret(value, field_name="API key")
        if any(ch.isspace() for ch in value) or ":" in value:
            raise ValueError("Paste the API key without an Authorization header")
        return value


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class BilletwebListEventsConfig(_Input):
    "Lister les événements"

    operation: Literal["list_events"] = Field(
        "list_events",
        title="List Events",
        description="",
        json_schema_extra={"ui:hidden": True},
    )
    past: Literal[0, 1] | None = Field(
        None, description="Inclure les événements passés (0 par défaut)"
    )
    online: Literal[0, 1] | None = Field(
        None, description="Uniquement les événements publiés"
    )
    description: Literal[0, 1] | None = Field(
        None, description="Inclure la description HTML"
    )
    id: int | None = Field(None, description="Filtrer sur un id d'événement")


class BilletwebListAttendeesConfig(_Input):
    "Participants — tous événements confondus"

    operation: Literal["list_attendees"] = Field(
        "list_attendees",
        title="List Attendees",
        description="⚠️ Limité à 10 appels/minute. Utilisez `last_update` pour récupérer de façon incrémentale.",
        json_schema_extra={"ui:hidden": True},
    )
    last_update: int | None = Field(
        None,
        description="Commandes créées ou modifiées après cette date (UNIX timestamp)",
    )
    since: int | None = Field(
        None, description="Commandes créées ou modifiées durant les X dernières minutes"
    )
    to: int | None = Field(
        None,
        description="Commandes créées ou modifiées avant cette date (UNIX timestamp)",
    )
    created_from: str | None = Field(
        None,
        description="Commandes créées à partir de cette date — UNIX timestamp ou date YYYY-MM-DD",
    )
    created_to: str | None = Field(
        None,
        description="Commandes créées avant cette date — UNIX timestamp (exclu) ou date YYYY-MM-DD (incluse)",
    )
    tag: str | None = Field(
        None, description="Filtrer par mot-clé événement (alphanumérique)"
    )
    futur: Literal[1] | None = Field(
        None, description="1 = événements non terminés seulement"
    )
    email: str | None = Field(None, description="Filtrer sur un acheteur")
    ticket: int | None = Field(None, description="Filtrer sur un id de tarif")
    used: Literal[0, 1, 2, 3] | None = Field(
        None, description="0=non composté, 1=composté, 2=sorti, 3=expiré"
    )
    disabled: Literal[0, 1, 2] | None = Field(
        None, description="1=inclure remboursés, 2=seulement remboursés"
    )


class BilletwebListEventAttendeesConfig(_Input):
    "Participants d'un événement"

    operation: Literal["list_event_attendees"] = Field(
        "list_event_attendees",
        title="List Event Attendees",
        description="⚠️ Limité à 10 appels/minute.",
        json_schema_extra={"ui:hidden": True},
    )
    event_id: int = Field(..., ge=1, description="ID de l'événement")
    last_update: int | None = Field(
        None,
        description="Commandes créées ou modifiées après cette date (UNIX timestamp)",
    )
    since: int | None = Field(
        None, description="Commandes créées ou modifiées durant les X dernières minutes"
    )
    to: int | None = Field(
        None,
        description="Commandes créées ou modifiées avant cette date (UNIX timestamp)",
    )
    created_from: str | None = Field(
        None,
        description="Commandes créées à partir de cette date — UNIX timestamp ou date YYYY-MM-DD",
    )
    created_to: str | None = Field(
        None,
        description="Commandes créées avant cette date — UNIX timestamp (exclu) ou date YYYY-MM-DD (incluse)",
    )
    session: int | None = Field(None, description="Filtrer sur un id de séance")
    futur_sessions: Literal[1] | None = Field(
        None, description="1 = séances non passées uniquement"
    )
    used: Literal[0, 1, 2, 3] | None = Field(
        None, description="0=non composté, 1=composté, 2=sorti, 3=expiré"
    )
    ticket: int | None = Field(None, description="Filtrer sur un id de tarif")
    ext_id: str | None = Field(None, description="Filtrer sur un id de billet")
    product_id: int | None = Field(
        None, description="Filtrer sur un id interne de billet"
    )
    barcode: str | None = Field(None, description="Filtrer sur un code barre")
    order_id: int | None = Field(
        None, description="Filtrer sur un id interne de commande"
    )
    email: str | None = Field(None, description="Filtrer sur un acheteur")
    disabled: Literal[0, 1, 2] | None = Field(
        None, description="1=inclure remboursés/annulés, 2=seulement remboursés/annulés"
    )


class BilletwebGetAvailabilityConfig(_Input):
    "Disponibilité d'un événement"

    operation: Literal["get_availability"] = Field(
        "get_availability",
        title="Get Availability",
        description="Si mode séance sans id de séance, retourne la disponibilité globale de toutes les séances. -1 = pas de limite.",
        json_schema_extra={"ui:hidden": True},
    )
    event_id: int = Field(..., ge=1, description="Billetweb event id")
    temp: Literal[0, 1] | None = Field(None, description="Inclure les paniers en cours")
    past: Literal[0, 1] | None = Field(None, description="Inclure les séances passées")
    session: str | None = Field(None, description="ID ou heure de début de la séance")


class BilletwebListWaitingConfig(_Input):
    "Liste d'attente d'un événement"

    operation: Literal["list_waiting"] = Field(
        "list_waiting",
        title="List Waiting",
        description="",
        json_schema_extra={"ui:hidden": True},
    )
    event_id: int = Field(..., ge=1, description="Billetweb event id")


class UpdateEventData(_Input):
    @model_validator(mode="after")
    def action_required(self):
        if not self.model_dump(exclude_none=True):
            raise ValueError("Supply at least one event field to update")
        return self

    status: Literal[0, 1] | None = Field(None, description="1=publié, 0=hors ligne")
    title: str | None = Field(None, max_length=100)
    description: str | None = Field(None, description="HTML ou texte")
    location: str | None = Field(None, max_length=85)
    toptitle: str | None = Field(None, max_length=70)
    tags: list[str] | None = Field(None)
    quota: int | None = Field(None)
    quota_message: str | None = Field(None)
    confirmation_message: str | None = Field(None)


class BilletwebUpdateEventConfig(_Input):
    "Modifier un événement"

    operation: Literal["update_event"] = Field(
        "update_event",
        title="Update Event",
        description="",
        json_schema_extra={"ui:hidden": True},
    )
    event_id: int = Field(..., ge=1, description="Billetweb event id")
    data: UpdateEventData = Field(..., json_schema_extra={"ui:widget": "json"})


class BilletwebCloneEventConfig(_Input):
    "Dupliquer un événement"

    operation: Literal["clone_event"] = Field(
        "clone_event",
        title="Clone Event",
        description="Duplicate an event (Billetweb limit: 100 calls per year). Use sessions for repeated dates.",
        json_schema_extra={"ui:hidden": True},
    )
    event_id: int = Field(..., ge=1, description="Billetweb event id")
    name: str = Field(
        ...,
        min_length=3,
        max_length=100,
        description="**Obligatoire** — Nom du nouvel événement (min. 3 caractères)",
    )
    place: str | None = Field(None, max_length=85)
    start: int | None = Field(
        None, description="Date de début en UNIX timestamp (ignoré si `clone_dates=1`)"
    )
    end: int | None = Field(
        None, description="Date de fin en UNIX timestamp (ignoré si `clone_dates=1`)"
    )
    clone_dates: Literal[0, 1] | None = Field(
        None, description="Dupliquer les séances (0 par défaut)"
    )
    clone_tickets: Literal[0, 1] | None = Field(
        None, description="Dupliquer les tarifs (1 par défaut)"
    )
    clone_lists: Literal[0, 1] | None = Field(
        None, description="Dupliquer les opérations liées (1 par défaut)"
    )
    clone_seating: Literal[0, 1] | None = Field(
        None, description="Dupliquer le plan de placement (1 par défaut)"
    )


class BilletwebListTicketsConfig(_Input):
    "Lister les tarifs d'un événement"

    operation: Literal["list_tickets"] = Field(
        "list_tickets",
        title="List Tickets",
        description="Les tarifs sont retournés dans leur ordre d'affichage. Avec `categories=1`, les catégories sont incluses (`is_category` = 1) : c'est la liste à renvoyer, réordonnée, à `/api/event/{id}/tickets_reorder`.",
        json_schema_extra={"ui:hidden": True},
    )
    event_id: int = Field(..., ge=1, description="Billetweb event id")
    categories: Literal[1] | None = Field(
        None, description="1 = inclure les catégories dans la liste"
    )


class BilletwebListEventFormsConfig(_Input):
    "Lister les formulaires d'un événement"

    operation: Literal["list_event_forms"] = Field(
        "list_event_forms",
        title="List Event Forms",
        description="Retourne les formulaires utilisés par les tarifs de l'événement, avec les champs demandés par billet (`ticket_fields`) et par commande (`buyer_fields`). Les ids de champs sont ceux attendus dans l'objet `custom` de `add_order`, `update_order` et `update_product`. Un tarif dont le `form` vaut `0` dans `/api/event/{id}/tickets` utilise le formulaire par défaut (`default` = 1).\n\nPour un guichet de vente, ne demander que les champs avec `counter` = 1 : ils sont obligatoires si `mandatory` = 1, les autres ne sont pas demandés.",
        json_schema_extra={"ui:hidden": True},
    )
    event_id: int = Field(..., ge=1, description="Billetweb event id")


class UpdateTicketsDataItem(_Input):
    @model_validator(mode="after")
    def creation_name(self):
        if self.id == 0 and not self.name:
            raise ValueError("New ticket types and categories require a name")
        return self

    id: int = Field(
        ..., ge=0, description="0 creates a resource; an existing ID updates it"
    )
    category: Literal[0, 1] | None = Field(
        None,
        description="1 = créer une catégorie au lieu d'un tarif (uniquement avec `id: 0`). Sur un id existant, doit correspondre au type actuel : un tarif ne devient pas une catégorie, ni l'inverse.",
    )
    name: str | None = Field(
        None, max_length=100, description="Obligatoire à la création"
    )
    price: float | None = Field(None, ge=0, description="Tarifs uniquement")
    description: str | None = Field(
        None, max_length=1000, description="500 caractères max pour une catégorie"
    )
    quota: int | None = Field(None, ge=0, description="0 = pas de quota")
    visibility: Literal[0, 1, 2, 3, 4] | None = Field(
        None,
        description="Tarifs uniquement. 0=visible, 1=web, 2=guichet, 3=lien secret, 4=masqué",
    )
    sales_start: int | None = Field(None, description="UNIX timestamp")
    sales_end: int | None = Field(None)
    label: str | None = Field(None, max_length=25, description="Tarifs uniquement")
    instructions: str | None = Field(None, description="Tarifs uniquement")
    form: int | None = Field(
        None, description="Tarifs uniquement. ID du formulaire partagé"
    )
    after_id: int | None = Field(
        None,
        description="Identifiant de l'élément (tarif ou catégorie) qui sert de repère. Un tarif : l'élément est placé juste après lui, au même niveau. Une catégorie : l'élément est rangé dedans, après son dernier élément. Refusé quand l'élément modifié (`id`) est une catégorie existante (erreur `has_children`) : pour déplacer une catégorie, utiliser `/api/event/{id}/tickets_reorder`. Accepté à la création d'une catégorie : elle devient alors une sous-catégorie si `after_id` est une catégorie. 3 niveaux d'imbrication au maximum, tarifs compris.",
    )
    delete: Literal[1] | None = Field(
        None,
        description="1 = supprimer ce tarif ou cette catégorie. Une catégorie ne se supprime qu'avec tout son contenu, dans le même appel.",
    )


class BilletwebUpdateTicketsConfig(_Input):
    "Créer ou modifier des tarifs et des catégories"

    operation: Literal["update_tickets"] = Field(
        "update_tickets",
        title="Update Tickets",
        description="**Créer un tarif ou une catégorie**\n\nUn élément avec `id: 0` et un `name`. Ajouter `category: 1` pour créer une catégorie au lieu d'un tarif. `after_id` le place (voir *Mise à jour des positions*).\n\n**Créer plusieurs tarifs et/ou catégories**\n\nPlusieurs éléments dans `data`. Les ids créés sont renvoyés dans le même ordre.\n\nPour une arborescence complète (catégorie, sous-catégorie, tarifs), faire 3 appels successifs : chacun place ses éléments avec `after_id` = un id renvoyé par l'appel précédent.\n\n**Mise à jour**\n\nUn élément avec son `id` existant : seuls les champs envoyés sont modifiés. `delete: 1` le supprime.\n\n**Mise à jour des positions**\n\n- **Un tarif** : `after_id` = l'identifiant du tarif après lequel le placer, ou de la catégorie dans laquelle le ranger (en dernier).\n- **Tous les éléments** : `/api/event/{id}/tickets_reorder`, avec la liste complète dans l'ordre voulu. Seul moyen de déplacer une catégorie existante.\n\n**Validation**\n\nTout le lot est vérifié avant d'écrire : en cas d'erreur, rien n'est enregistré.",
        json_schema_extra={"ui:hidden": True},
    )
    event_id: int = Field(..., ge=1, description="Billetweb event id")
    data: list[UpdateTicketsDataItem] = Field(
        ..., min_length=1, json_schema_extra={"ui:widget": "json"}
    )


class BilletwebListFormsConfig(_Input):
    "Lister les formulaires partagés"

    operation: Literal["list_forms"] = Field(
        "list_forms",
        title="List Forms",
        description="",
        json_schema_extra={"ui:hidden": True},
    )


class BilletwebListFieldsConfig(_Input):
    "Lister les champs de formulaire de l'organisateur"

    operation: Literal["list_fields"] = Field(
        "list_fields",
        title="List Fields",
        description="Retourne les champs standard (`basic` = 1, ids identiques pour tous les organisateurs) et les champs personnalisés de l'organisateur. L'`id` est la clé à utiliser dans l'objet `custom` des méthodes `add_order`, `update_order` et `update_product`. Pour savoir quels champs s'appliquent à un tarif donné, voir `/api/event/{id}/forms`.",
        json_schema_extra={"ui:hidden": True},
    )


class BilletwebListSessionsConfig(_Input):
    "Lister les séances d'un événement"

    operation: Literal["list_sessions"] = Field(
        "list_sessions",
        title="List Sessions",
        description="",
        json_schema_extra={"ui:hidden": True},
    )
    event_id: int = Field(..., ge=1, description="Billetweb event id")
    past: Literal[0, 1] | None = Field(None, description="Billetweb past")
    last_update: int | None = Field(None, description="Billetweb last update")
    disabled: int | None = Field(
        None, description="0=ouvert, 1=masqué, 2=guichet, 3=web, 4=lien, 5=annulé"
    )
    past_by: int | None = Field(None, description="Séances terminées depuis X jours")
    start_from: int | None = Field(
        None, description="UNIX timestamp — à partir de cette date"
    )
    start_to: int | None = Field(
        None, description="UNIX timestamp — jusqu'à cette date"
    )


class UpdateSessionsDataItem(_Input):
    id: int = Field(
        ..., ge=0, description="0 creates a resource; an existing ID updates it"
    )
    start: int | None = Field(None, description="UNIX timestamp")
    end: int | None = Field(None)
    name: str | None = Field(None, max_length=75)
    place: str | None = Field(None, max_length=75)
    description: str | None = Field(None, max_length=1000)
    instructions: str | None = Field(None)
    quota: int | None = Field(None)
    tickets: list[int] | Literal["all"] | None = Field(
        None, description="Tableau d'IDs de tarifs ou 'all' pour tous"
    )
    disabled: Literal[0, 1, 2, 3, 4, 5] | None = Field(
        None, description="0=ouvert, 1=masqué, 2=guichet, 3=web, 4=lien seul, 5=annulé"
    )
    delete: Literal[1] | None = Field(None)


class BilletwebUpdateSessionsConfig(_Input):
    "Créer ou modifier des séances"

    operation: Literal["update_sessions"] = Field(
        "update_sessions",
        title="Update Sessions",
        description="**id** est obligatoire. `id: 0` crée une nouvelle séance.",
        json_schema_extra={"ui:hidden": True},
    )
    event_id: int = Field(..., ge=1, description="Billetweb event id")
    data: list[UpdateSessionsDataItem] = Field(
        ..., min_length=1, json_schema_extra={"ui:widget": "json"}
    )


class CheckTicketsDataItem(_Input):
    id: int = Field(..., ge=1, description="Ticket ID")
    used: Literal[0, 1, 2] = Field(
        ..., description="0 not checked in, 1 checked in, 2 exited"
    )
    lane: str | None = Field(None, description="Nom du poste de contrôle (optionnel)")
    used_date_unix: int | None = Field(
        None, description="Heure du compostage en UNIX (optionnel)"
    )


class BilletwebCheckTicketsConfig(_Input):
    "Composter un ou des billets"

    operation: Literal["check_tickets"] = Field(
        "check_tickets",
        title="Check Tickets",
        description="Set ticket check-in state: 0 not checked in, 1 checked in, 2 exited.",
        json_schema_extra={"ui:hidden": True},
    )
    event_id: int = Field(..., ge=1, description="Billetweb event id")
    data: list[CheckTicketsDataItem] = Field(
        ..., min_length=1, json_schema_extra={"ui:widget": "json"}
    )


class AddOrdersDataItemProductsItem(_Input):
    ticket: str = Field(
        ..., description="**Obligatoire** — ID ou nom (si unique dans l'événement)"
    )
    name: str | None = Field(None)
    firstname: str | None = Field(None)
    email: str | None = Field(None)
    price: float | None = Field(
        None, description="Prix personnalisé (utilise le prix du tarif par défaut)"
    )
    used: Literal[0, 1, 2, 3] | None = Field(
        None, description="0=non composté (défaut), 1=composté, 2=sorti, 3=expiré"
    )
    barcode: str | None = Field(None, description="Code barre personnalisé")
    reference: str | None = Field(None, description="Référence interne du billet")
    lane: str | None = Field(
        None, description="Nom du poste de compostage (si `used` > 0)"
    )
    request_id: str | None = Field(
        None,
        description="Votre identifiant interne du billet, retourné dans `products_eq`",
    )
    custom: dict[str, Any] | None = Field(
        None,
        description='Champs personnalisés du billet : `{ id_champ: valeur }`. L\'id du champ s\'obtient via `/api/fields` ou `/api/event/{id}/forms` (`ticket_fields`). Ex : `{ "4567": "M" }`',
    )


class AddOrdersDataItem(_Input):
    name: str | None = Field(None)
    firstname: str | None = Field(None)
    email: str | None = Field(None)
    session: str | None = Field(
        None, description="ID ou date de début (YYYY-MM-DD HH:MM) si mode séance"
    )
    payment_type: str = Field(
        ...,
        description="**Obligatoire** — `card`, `cash`, `check`, `invitation`, `reservation`, `other`, `multiple`, ou un moyen personnalisé",
    )
    payment_split: dict[str, float] | None = Field(
        None,
        description="Requis si `payment_type=multiple`. Clés = types de paiement, valeurs = montants. Ex\xa0: `{ cash: 10, card: 5 }`",
    )
    request_id: str | None = Field(
        None, description="Votre identifiant interne, retourné dans la réponse"
    )
    ship: Literal[1] | None = Field(
        None, description="1 = envoyer le billet par email après création"
    )
    language: str | None = Field(None, description="Code langue (ex\xa0: fr, en)")
    custom: dict[str, Any] | None = Field(
        None,
        description='Champs personnalisés de la commande : `{ id_champ: valeur }`. L\'id du champ s\'obtient via `/api/fields` ou `/api/event/{id}/forms` (`buyer_fields`). Ex : `{ "5": "0612345678" }`',
    )
    products: list[AddOrdersDataItemProductsItem] = Field(
        ..., min_length=1, max_length=100
    )

    @model_validator(mode="after")
    def split_required(self):
        if self.payment_type == "multiple" and not self.payment_split:
            raise ValueError("Multiple payments require payment_split")
        return self


class BilletwebAddOrdersConfig(_Input):
    "Ajouter une ou plusieurs commandes hors ligne"

    operation: Literal["add_orders"] = Field(
        "add_orders",
        title="Add Orders",
        description="Create offline orders; ship=1 sends tickets by email.",
        json_schema_extra={"ui:hidden": True},
    )
    event_id: int = Field(..., ge=1, description="Billetweb event id")
    data: list[AddOrdersDataItem] = Field(
        ..., max_length=100, min_length=1, json_schema_extra={"ui:widget": "json"}
    )


class BilletwebDeleteOrdersConfig(_Input):
    "Supprimer une ou plusieurs commandes hors ligne"

    operation: Literal["delete_orders"] = Field(
        "delete_orders",
        title="Delete Orders",
        description="Delete offline orders. This permanently removes the selected orders.",
        json_schema_extra={"ui:hidden": True},
    )
    event_id: int = Field(..., ge=1, description="Billetweb event id")
    data: list[int] = Field(..., min_length=1, json_schema_extra={"ui:widget": "json"})


class PayOrdersDataItem(_Input):
    id: int = Field(..., ge=1)
    payment_type: Literal[
        "reservation", "other", "card", "cash", "check"
    ] | None = Field(None)
    notification: Literal[0, 1] | None = Field(
        None, description="1 = envoyer email de confirmation avec billets"
    )


class BilletwebPayOrdersConfig(_Input):
    "Valider le paiement d'une réservation"

    operation: Literal["pay_orders"] = Field(
        "pay_orders",
        title="Pay Orders",
        description="Mark reservations as paid; notification=1 emails confirmation and tickets.",
        json_schema_extra={"ui:hidden": True},
    )
    event_id: int = Field(..., ge=1, description="Billetweb event id")
    data: list[PayOrdersDataItem] = Field(
        ..., min_length=1, json_schema_extra={"ui:widget": "json"}
    )


class UpdateOrdersDataItem(_Input):
    id: int = Field(..., ge=1)
    accredited: Literal[2, 3] | None = Field(
        None, description="3=valider accréditation, 2=refuser"
    )
    notification: Literal[0, 1] | None = Field(
        None,
        description="1 = envoyer email à l'acheteur lors de la modification de l'accréditation",
    )
    name: str | None = Field(None)
    firstname: str | None = Field(None)
    ship: Literal[1] | None = Field(
        None, description="1 = renvoyer la commande par email à l'acheteur"
    )
    custom: dict[str, Any] | None = Field(
        None,
        description="Champs personnalisés de la commande : `{ id_champ: valeur }`. L'id du champ s'obtient via `/api/fields` ou `/api/event/{id}/forms` (`buyer_fields`)",
    )


class BilletwebUpdateOrdersConfig(_Input):
    "Modifier une commande ou valider/refuser une accréditation"

    operation: Literal["update_orders"] = Field(
        "update_orders",
        title="Update Orders",
        description="Update buyer details or accreditation; ship=1 resends the order by email.",
        json_schema_extra={"ui:hidden": True},
    )
    event_id: int = Field(..., ge=1, description="Billetweb event id")
    data: list[UpdateOrdersDataItem] = Field(
        ..., min_length=1, json_schema_extra={"ui:widget": "json"}
    )


class UpdateProductsDataItem(_Input):
    id: int = Field(..., ge=1)
    name: str | None = Field(None)
    firstname: str | None = Field(None)
    custom: dict[str, str] | None = Field(
        None,
        description="Champs personnalisés du billet : `{ id_champ: valeur }`. L'id du champ s'obtient via `/api/fields` ou `/api/event/{id}/forms` (`ticket_fields`)",
    )


class BilletwebUpdateProductsConfig(_Input):
    "Modifier les données d'un billet ou produit"

    operation: Literal["update_products"] = Field(
        "update_products",
        title="Update Products",
        description="",
        json_schema_extra={"ui:hidden": True},
    )
    event_id: int = Field(..., ge=1, description="Billetweb event id")
    data: list[UpdateProductsDataItem] = Field(
        ..., min_length=1, json_schema_extra={"ui:widget": "json"}
    )


class BilletwebListListsConfig(_Input):
    "Lister les listes existantes"

    operation: Literal["list_lists"] = Field(
        "list_lists",
        title="List Lists",
        description="",
        json_schema_extra={"ui:hidden": True},
    )


class BilletwebGetListConfig(_Input):
    "Obtenir le contenu d'une liste"

    operation: Literal["get_list"] = Field(
        "get_list",
        title="Get List",
        description="",
        json_schema_extra={"ui:hidden": True},
    )
    list_id: int = Field(..., ge=1, description="Billetweb list id")


class BilletwebAddListEntriesConfig(_Input):
    "Ajouter des entrées dans une liste"

    operation: Literal["add_list_entries"] = Field(
        "add_list_entries",
        title="Add List Entries",
        description="",
        json_schema_extra={"ui:hidden": True},
    )
    list_id: int = Field(..., ge=1, description="Billetweb list id")
    data: list[list[str]] = Field(
        ..., min_length=1, json_schema_extra={"ui:widget": "json"}
    )


class BilletwebRemoveListEntriesConfig(_Input):
    "Retirer des entrées d'une liste (par clé)"

    operation: Literal["remove_list_entries"] = Field(
        "remove_list_entries",
        title="Remove List Entries",
        description="",
        json_schema_extra={"ui:hidden": True},
    )
    list_id: int = Field(..., ge=1, description="Billetweb list id")
    data: list[list[str]] = Field(
        ..., min_length=1, json_schema_extra={"ui:widget": "json"}
    )


class BilletwebListContactsConfig(_Input):
    "Retourner les contacts"

    operation: Literal["list_contacts"] = Field(
        "list_contacts",
        title="List Contacts",
        description="",
        json_schema_extra={"ui:hidden": True},
    )
    last_update: int | None = Field(None, description="Billetweb last update")
    since: int | None = Field(None, description="Billetweb since")
    to: int | None = Field(None, description="Billetweb to")
    email: str | None = Field(None, description="Billetweb email")
    segment: int | None = Field(
        None, description="Filtrer sur un segment (voir /crm/segments)"
    )


Operation = Annotated[
    Union[
        BilletwebListEventsConfig,
        BilletwebListAttendeesConfig,
        BilletwebListEventAttendeesConfig,
        BilletwebGetAvailabilityConfig,
        BilletwebListWaitingConfig,
        BilletwebUpdateEventConfig,
        BilletwebCloneEventConfig,
        BilletwebListTicketsConfig,
        BilletwebListEventFormsConfig,
        BilletwebUpdateTicketsConfig,
        BilletwebListFormsConfig,
        BilletwebListFieldsConfig,
        BilletwebListSessionsConfig,
        BilletwebUpdateSessionsConfig,
        BilletwebCheckTicketsConfig,
        BilletwebAddOrdersConfig,
        BilletwebDeleteOrdersConfig,
        BilletwebPayOrdersConfig,
        BilletwebUpdateOrdersConfig,
        BilletwebUpdateProductsConfig,
        BilletwebListListsConfig,
        BilletwebGetListConfig,
        BilletwebAddListEntriesConfig,
        BilletwebRemoveListEntriesConfig,
        BilletwebListContactsConfig,
    ],
    Field(discriminator="operation"),
]


class BilletwebFullConfig(NodeConfig[Operation, BilletwebAPIKeyCredential]):
    model_config = ConfigDict(hide_input_in_errors=True)


ROUTES = {
    "list_events": ("GET", "/api/events"),
    "list_attendees": ("GET", "/api/attendees"),
    "list_event_attendees": ("GET", "/api/event/{id}/attendees"),
    "get_availability": ("GET", "/api/event/{id}/avail"),
    "list_waiting": ("GET", "/api/event/{id}/waiting"),
    "update_event": ("POST", "/api/event/{id}/update"),
    "clone_event": ("POST", "/api/event/{id}/clone"),
    "list_tickets": ("GET", "/api/event/{id}/tickets"),
    "list_event_forms": ("GET", "/api/event/{id}/forms"),
    "update_tickets": ("POST", "/api/event/{id}/tickets_update"),
    "list_forms": ("GET", "/api/forms"),
    "list_fields": ("GET", "/api/fields"),
    "list_sessions": ("GET", "/api/event/{id}/dates"),
    "update_sessions": ("POST", "/api/event/{id}/dates_update"),
    "check_tickets": ("POST", "/api/event/{id}/check"),
    "add_orders": ("POST", "/api/event/{id}/add_order"),
    "delete_orders": ("POST", "/api/event/{id}/delete_order"),
    "pay_orders": ("POST", "/api/event/{id}/pay_order"),
    "update_orders": ("POST", "/api/event/{id}/update_order"),
    "update_products": ("POST", "/api/event/{id}/update_product"),
    "list_lists": ("GET", "/api/lists"),
    "get_list": ("GET", "/api/list/{id}/data"),
    "add_list_entries": ("POST", "/api/list/{id}/push"),
    "remove_list_entries": ("POST", "/api/list/{id}/remove"),
    "list_contacts": ("GET", "/api/crm/contacts"),
}


class BilletwebNode(WorkflowNode):
    integration_type = "automation-billetweb"
    connection_evidence = ConnectionEvidence(noun="events", operation="list_events")

    @classmethod
    def get_config_model(cls):
        return BilletwebFullConfig

    async def execute(self, inputs):
        if self.config is None or self.config.credentials is None:
            raise ValueError("Connect a Billetweb API key")
        config = self.config.config
        credential = self.config.credentials
        method, path = ROUTES[config.operation]
        values = config.model_dump(exclude_none=True, exclude={"operation"})
        resource = values.pop("event_id", values.pop("list_id", None))
        if resource is not None:
            path = path.replace("{id}", str(resource))
        auth = "Basic " + base64.b64encode(
            (credential.user_id + ":" + credential.api_key).encode()
        ).decode("ascii")
        try:
            async with guarded_async_client(
                timeout=30, trust_env=False, follow_redirects=False
            ) as client:
                response = await client.request(
                    method,
                    BASE_URL + path,
                    headers={"Authorization": auth, "Accept": "application/json"},
                    **({"params": values} if method == "GET" else {"json": values}),
                )
            if response.status_code != 200:
                message = "Billetweb returned HTTP " + str(response.status_code)
                try:
                    error = response.json()
                    if isinstance(error, dict):
                        message = str(
                            error.get("description") or error.get("error") or message
                        )
                except ValueError:
                    pass
                result = {
                    "status": "error",
                    "http_status": response.status_code,
                    "error": message,
                    "write_outcome": "unverified" if method != "GET" else None,
                }
            else:
                if not response.content and method == "POST":
                    result = {"status": "success", "data": None, "http_status": 200}
                    await self.emit(result)
                    return result
                if "json" not in response.headers.get("content-type", "").lower():
                    raise ValueError("Expected JSON from Billetweb")
                body = response.json()
                if isinstance(body, dict) and (
                    body.get("error")
                    or body.get("errors")
                    or body.get("success") is False
                ):
                    result = {
                        "status": "error",
                        "http_status": 200,
                        "error": str(
                            body.get("description")
                            or body.get("error")
                            or body.get("errors")
                            or "Billetweb rejected the request"
                        ),
                    }
                else:
                    result = {"status": "success", "data": body}
                    if isinstance(body, list):
                        result["items"] = body
        except (httpx.HTTPError, ValueError):
            result = {
                "status": "error",
                "error": "Billetweb response could not be confirmed; inspect before retrying a write",
                "write_outcome": "unverified" if method != "GET" else None,
            }

        # Provider errors must never echo the credential or its Authorization form.
        def redact(value):
            if isinstance(value, str):
                return value.replace(credential.api_key, "[redacted]").replace(
                    auth, "[redacted]"
                )
            if isinstance(value, list):
                return [redact(v) for v in value]
            if isinstance(value, dict):
                return {k: redact(v) for k, v in value.items()}
            return value

        result = redact(result)
        await self.emit(result)
        return result
