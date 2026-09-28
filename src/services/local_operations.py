from src.database import generate_local_playlists, reset_local_classifications
from src.services.operations import update_operation


async def run_local_playlists_operation(operation_id: str) -> None:
    try:
        update_operation(
            operation_id,
            status="running",
            phase="gerando playlists por gênero",
        )
        result = generate_local_playlists()
        update_operation(
            operation_id,
            status="completed",
            phase="concluído",
            processed=result["playlist_count"],
            total=result["playlist_count"],
            result=result,
        )
    except Exception as error:
        update_operation(operation_id, status="error", phase="erro", error=str(error))


async def run_reset_operation(operation_id: str) -> None:
    try:
        update_operation(
            operation_id,
            status="running",
            phase="removendo classificações locais",
            total=1,
        )
        result = reset_local_classifications()
        update_operation(
            operation_id,
            status="completed",
            phase="concluído",
            processed=1,
            result=result,
        )
    except Exception as error:
        update_operation(operation_id, status="error", phase="erro", error=str(error))
