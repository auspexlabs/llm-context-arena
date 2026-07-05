"""Background worker with queue handoff."""

import queue

task_queue = queue.Queue()


def enqueue_task(payload: dict) -> None:
    task_queue.put(payload)


def process_tasks() -> None:
    while True:
        item = task_queue.get()
        handle_task(item)


def handle_task(item: dict) -> None:
    print(item)