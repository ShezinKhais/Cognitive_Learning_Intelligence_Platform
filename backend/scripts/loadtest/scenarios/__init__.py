"""What a load run does to the server, and what it checks afterwards.

Each scenario returns a Result (common.py). They are grouped by what they
exercise: a class under load, Teams, failures, and the scheduler.
"""

from scripts.loadtest.scenarios.common import Classroom, Result
from scripts.loadtest.scenarios.failures import (
    database_outage,
    model_down,
    planned_restart,
    server_crash,
)
from scripts.loadtest.scenarios.lesson import (
    class_under_load,
    housekeeping_during_class,
    reconnecting,
    signals_and_rooms,
)
from scripts.loadtest.scenarios.scheduler import scheduler_load
from scripts.loadtest.scenarios.teams import teams_meeting

__all__ = [
    "Classroom",
    "Result",
    "class_under_load",
    "reconnecting",
    "signals_and_rooms",
    "housekeeping_during_class",
    "teams_meeting",
    "model_down",
    "server_crash",
    "planned_restart",
    "database_outage",
    "scheduler_load",
]
