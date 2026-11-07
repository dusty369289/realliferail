"""Real calls to data.rtt.io, to notice when RTT's answers change shape. Costs about 4 calls of the allowance.

Run with `uv run pytest -m live -n 0`. Needs RTT_TOKEN (environment or .env). Skipped without one.
"""

import pytest

from realliferail.domain.engine import build
from realliferail.domain.parse import parse_board, parse_service
from realliferail.services.app import find_token, from_environment
from tests.test_schema import errors

pytestmark = [pytest.mark.live, pytest.mark.timeout(60)]


@pytest.fixture(scope="module")
def core():
    if not find_token():
        pytest.skip("no RTT_TOKEN")
    return from_environment()


def test_token_and_entitlements(core):
    info = core.client.check_token()
    assert info.api_version
    print("entitlements:", info.entitlements)


def test_real_board_and_train_match_the_spec_and_parse(core):
    f = core.client.location("RDG", core.now(), 60)
    assert f.body, "Reading always has trains"
    bad = errors("/gb-nr/location", f.body)
    board = parse_board(f.body, fallback_name="Reading", time_from=core.now(), time_to=core.now())
    assert board.rows
    row = board.rows[0]
    s = core.client.service(row.unique_id)
    bad += errors("/gb-nr/service", s.body)
    svc = parse_service(s.body)
    tl = build(svc, core.now())
    passes = sum(1 for p in svc.points if p.kind.value == "pass")
    print(f"{svc.identity}: {len(svc.points)} points, {passes} passes. {tl.position.headline}")
    print("allowance left this hour:", core.budget.state().remaining["hour"])
    assert bad == [], bad
