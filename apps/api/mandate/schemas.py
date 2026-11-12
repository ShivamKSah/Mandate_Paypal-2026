from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictInt


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid")


Cents = Annotated[StrictInt, Field(ge=0, le=100_000_000)]


class MandateInput(Input):
    budget_cents: Annotated[Cents, Field(gt=0)]
    per_transaction_cents: Annotated[Cents, Field(gt=0)]
    allowed_categories: list[Annotated[str, Field(min_length=1, max_length=80)]] = Field(min_length=1, max_length=30)
    allowed_merchants: list[Annotated[str, Field(min_length=1, max_length=80)]] = Field(min_length=1, max_length=30)
    constraints: dict[str, str | StrictInt | bool] = Field(default_factory=dict, max_length=20)
    instruction: str = Field(min_length=1, max_length=4000)
    expires_in_minutes: Annotated[StrictInt, Field(ge=1, le=1440)] = 60
    velocity_limit: Annotated[StrictInt, Field(ge=1, le=100)] = 5


class ItemInput(Input):
    product_id: str = Field(min_length=1, max_length=100)
    quantity: Annotated[StrictInt, Field(ge=1, le=100)]


class ProposalInput(Input):
    mandate_id: str = Field(max_length=80)
    purchase_intent_id: str = Field(min_length=1, max_length=120)
    items: list[ItemInput] = Field(min_length=1, max_length=30)
    currency: str = Field(default="USD", min_length=3, max_length=3)
    claimed_total_cents: Cents | None = None
    instruction: str | None = Field(default=None, max_length=4000)


class ApprovalInput(Input):
    cart_hash: str = Field(min_length=64, max_length=64)


class CaseInput(Input):
    payment_id: str = Field(max_length=80)
    cause: Literal["seller_error", "ambiguous_listing", "agent_error", "vague_instruction"]
    evidence: str = Field(min_length=1, max_length=8000)
    avoided_freight_cents: Cents
    resale_loss_cents: Cents


class AcceptInput(Input):
    offer_hash: str = Field(min_length=64, max_length=64)


class EmptyInput(Input):
    pass


class GrantCompleteInput(Input):
    order_id: str | None = Field(default=None, min_length=1, max_length=100)


class AttackRunInput(Input):
    attack_id: str = Field(min_length=1, max_length=60)


class SuggestCauseInput(Input):
    payment_id: str = Field(min_length=1, max_length=80)
    evidence: str = Field(min_length=1, max_length=8000)


class LoginInput(Input):
    access_key: str = Field(min_length=1, max_length=1024)
