import asyncio
import uuid
from collections.abc import Awaitable, Callable


operations: dict[str, dict[str, object]] = {}


def create_operation(name: str) -> dict[str, object]:
    operation_id = uuid.uuid4().hex
    operation = {
        "operation_id": operation_id,
        "name": name,
        "status": "queued",
        "phase": "aguardando início",
        "processed": 0,
        "total": 0,
    }
    operations[operation_id] = operation
    return operation


def update_operation(operation_id: str, **fields: object) -> None:
    if operation_id in operations:
        operations[operation_id].update(fields)


def get_operation(operation_id: str) -> dict[str, object] | None:
    return operations.get(operation_id)


def start_operation(
    operation_id: str,
    runner: Callable[[str], Awaitable[None]],
) -> None:
    asyncio.create_task(runner(operation_id))
