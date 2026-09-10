import hashlib
import math
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


class DelayedSumPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    numbers: list[float] = Field(min_length=1, max_length=100)
    delay_ms: int = Field(default=0, ge=0, le=2000)

    @field_validator("numbers")
    @classmethod
    def finite_numbers(cls, value: list[float]) -> list[float]:
        if any(not math.isfinite(number) for number in value):
            raise ValueError("numbers must contain only finite values")
        return value


class BatchTransformPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    items: list[str] = Field(min_length=1, max_length=100)

    @field_validator("items")
    @classmethod
    def bounded_items(cls, value: list[str]) -> list[str]:
        if any(not item.strip() or len(item) > 256 for item in value):
            raise ValueError("items must be non-empty strings of at most 256 characters")
        return value


class UnstableDemoPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    fail_until_attempt: int = Field(default=1, ge=1, le=20)


@dataclass
class HandlerContext:
    attempt: int
    update_progress: Callable[[int, str | None], None]


class RetryableJobError(RuntimeError):
    """Expected failure that may be retried by the worker."""


def run_delayed_sum(payload: DelayedSumPayload, context: HandlerContext) -> dict[str, Any]:
    total = 0.0
    for index, number in enumerate(payload.numbers, start=1):
        if payload.delay_ms:
            time.sleep(payload.delay_ms / 1000)
        total += number
        context.update_progress(round(index / len(payload.numbers) * 100), f"Processed {index} items")
    return {"sum": int(total) if total.is_integer() else total, "items_processed": len(payload.numbers)}


def run_batch_transform(payload: BatchTransformPayload, context: HandlerContext) -> dict[str, Any]:
    transformed = []
    for index, item in enumerate(payload.items, start=1):
        transformed.append(
            {
                "input": item,
                "output": item.upper(),
                "checksum": hashlib.sha256(item.encode("utf-8")).hexdigest()[:12],
            }
        )
        context.update_progress(round(index / len(payload.items) * 100), f"Transformed {index} items")
    return {"items": transformed}


def run_unstable_demo(payload: UnstableDemoPayload, context: HandlerContext) -> dict[str, Any]:
    context.update_progress(50, f"Attempt {context.attempt} evaluated")
    if context.attempt < payload.fail_until_attempt:
        raise RetryableJobError(
            f"Intentional retryable failure on attempt {context.attempt}"
        )
    context.update_progress(100, "Unstable demo completed")
    return {"attempt": context.attempt, "message": "unstable_demo succeeded"}


JOB_REGISTRY = {
    "delayed_sum": (DelayedSumPayload, run_delayed_sum),
    "batch_transform": (BatchTransformPayload, run_batch_transform),
    "unstable_demo": (UnstableDemoPayload, run_unstable_demo),
}

