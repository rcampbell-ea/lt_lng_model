"""Session 0 smoke test: the package skeleton imports."""

import lt_lng_flows
import lt_lng_flows.geo
import lt_lng_flows.ingest
import lt_lng_flows.model
import lt_lng_flows.output
import lt_lng_flows.pipe
import lt_lng_flows.validate


def test_submodules_importable():
    assert lt_lng_flows.geo
    assert lt_lng_flows.ingest
    assert lt_lng_flows.pipe
    assert lt_lng_flows.model
    assert lt_lng_flows.validate
    assert lt_lng_flows.output
