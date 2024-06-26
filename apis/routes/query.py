"""
Query routes.
"""
import re
import json

from datetime import datetime
from typing import List

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse, Response
from starlette.responses import FileResponse

from apis.models.response import AllModelNamesResponse
from apis.utils.api_utils import api_key_auth
from apis.utils.call_worker import current_task, session
from apis.utils.file_utils import delete_tasks
from apis.utils.sql_client import GenerateRecord
from modules.async_worker import async_tasks


def date_to_timestamp(date: str) -> int | None:
    """
    Converts the date to a timestamp.
    :param date: The ISO 8601 date to convert.
    :return: The timestamp in millisecond.
    """
    pattern = r'\A\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}'
    if date is None:
        return None
    try:
        date = re.match(pattern, date).group()
    except AttributeError:
        return None
    return int(datetime.fromisoformat(date).timestamp()) * 1000


async def tasks_info(task_id: str = None):
    """
    Returns the tasks.
    :param task_id: The task ID to filter by.
    :return: The tasks.
    """
    if task_id:
        query = session.query(GenerateRecord).filter_by(task_id=task_id).first()
        if query is None:
            return []
        result = json.loads(str(query))
        result["req_params"] = json.loads(result["req_params"])
        return result
    return async_tasks


secure_router = APIRouter(
    dependencies=[Depends(api_key_auth)]
)


@secure_router.get("/tasks", tags=["Query"])
async def get_tasks(
        query: str = "all",
        page: int = 0,
        page_size: int = 10,
        start_at: str = None,
        end_at: str = datetime.now().isoformat(),
        action: str = None):
    """
    Get all tasks.
    :param query: The type of tasks to filter by. One of all, history, current, pending
    :param page: The page number to return. used for history and pending
    :param page_size: The number of tasks to return per page.
    :param start_at: The start time to filter by.
    :param end_at: The end time to filter by.
    :param action: Delete only.
    :return: The tasks.
    """
    start_at = date_to_timestamp(start_at)
    end_at = date_to_timestamp(end_at)
    action = action.lower() if action is not None else None
    if start_at is None or start_at >= end_at:
        start_at, end_at = None, None

    if action == 'delete':
        try:
            query_result = session.query(GenerateRecord).filter(GenerateRecord.in_queue_mills >= start_at).filter(GenerateRecord.in_queue_mills <= end_at).all()
            tasks = [json.loads(str(task)) for task in query_result]
            delete_tasks(tasks)
            session.query(GenerateRecord).filter(GenerateRecord.in_queue_mills >= start_at).filter(GenerateRecord.in_queue_mills <= end_at).delete()
            session.commit()
        except Exception as e:
            print(e)
        return

    historys, current, pending = [], [], []
    if query in ('all', 'history') and action != "delete":
        if start_at is not None:
            query_history = session.query(GenerateRecord).filter(GenerateRecord.in_queue_mills >= start_at).filter(GenerateRecord.in_queue_mills <= end_at).all()
        else:
            query_history = session.query(GenerateRecord).order_by(GenerateRecord.id.desc()).limit(page_size).offset(page * page_size).all()
        for q in query_history:
            result = json.loads(str(q))
            historys.append(result)
    if query in ('all', 'current'):
        current = await current_task()
    if query in ('all', 'pending'):
        pending = [task.task_id for task in async_tasks]
        start_index = page * page_size
        end_index = (page + 1) * page_size
        max_page = len(pending) / page_size if len(pending) / page_size == len(pending) // page_size else len(pending) // page_size + 1
        if page > max_page:
            pending = []
        else:
            pending = pending[start_index:end_index]

    return JSONResponse({
        "history": historys,
        "current": current,
        "pending": pending
    })


@secure_router.get("/tasks/{task_id}", tags=["Query"])
async def get_task(task_id: str):
    """
    Get a specific task by its ID.
    """
    return JSONResponse(await tasks_info(task_id))


@secure_router.get("/outputs/{data}/{file_name}", tags=["Query"])
async def get_output(data: str, file_name: str):
    """
    Get a specific output by its ID.
    """
    if not file_name.endswith(('.png', '.jpg', '.jpeg', '.webp')):
        return Response(status_code=404)
    return FileResponse(f"outputs/{data}/{file_name}")


@secure_router.get("/inputs/{file_name}", tags=["Query"])
async def get_input(file_name: str):
    """
    Get a specific input by its ID.
    """
    return FileResponse(f"inputs/{file_name}")


@secure_router.get(
        path="/v1/engines/all-models",
        response_model=AllModelNamesResponse,
        description="Get all filenames of base model and lora",
        tags=["Query"])
def all_models():
    """Refresh and return all models"""
    from modules import config
    config.update_files()
    models = AllModelNamesResponse(
        model_filenames=config.model_filenames,
        lora_filenames=config.lora_filenames)
    return models


@secure_router.get(
        path="/v1/engines/styles",
        response_model=List[str],
        description="Get all legal Fooocus styles",
        tags=['Query'])
def all_styles():
    """Return all available styles"""
    from modules.sdxl_styles import legal_style_names
    return legal_style_names
