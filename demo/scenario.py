"""The planted demo scenario. Edit the numbers, re-run `aiev run-demo`, re-run `aiev exceptions`.

Three plants, by design:
  1. AE:AIEV-001-1042:3  promoted with no review                 -> EX-01
  2. AE:AIEV-001-1017:1  reviewed and approved in 3 seconds      -> EX-02
  3. after 24 coding events the coder becomes 1.1.0 silently     -> EX-03 on every later coding event

Everything else is clean. Two outputs are left in quarantine so there is
something to `aiev review` live.
"""

from aievidence.scenario import Plants

PLANTS = Plants(
    unreviewed_promotion="AE:AIEV-001-1042:3",
    rubber_stamp_record="AE:AIEV-001-1017:1",
    rubber_stamp_seconds=3.0,
    version_bump_after=24,
    version_bump_to="1.1.0",
    leave_pending=["AE:AIEV-001-1096:2", "AE:AIEV-001-1128:2"],
    endorse=["AE:AIEV-001-1001:1", "AE:AIEV-001-1042:1"],
)

if __name__ == "__main__":
    from pathlib import Path

    from aievidence.scenario import run

    summary = run(Path(__file__).parent, plants=PLANTS)
    print(summary)
