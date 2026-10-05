"""Every task type the API can queue has a job to run it."""

import pytest

from appstore_shared.models import TaskType
from appstore_worker.runner import JOBS


@pytest.mark.unit
def test_every_queued_task_type_has_a_job():
    # UPDATE exists in the schema but nothing queues it yet; the runner
    # fails such a task with "no job for task type" rather than crashing.
    assert set(JOBS) == set(TaskType) - {TaskType.UPDATE}
