import pytest

from app.agents.router import heuristic_plan
from tests.conftest import SCENARIOS

ROUTED = [s for s in SCENARIOS if "expected_steps" in s]


@pytest.mark.parametrize("scenario", ROUTED, ids=[s["id"] for s in ROUTED])
def test_heuristic_routing_matches_golden_set(scenario):
    plan = heuristic_plan(scenario["message"])
    assert [st.agent.value for st in plan.steps] == scenario["expected_steps"]


def test_out_of_scope():
    assert heuristic_plan("Write me a poem about dragons.").primary.value == "out_of_scope"
