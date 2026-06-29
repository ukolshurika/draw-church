import json
from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def small_nodes():
    with open(FIXTURES / "small-nodes.json") as f:
        return json.load(f)


@pytest.fixture
def small_edges():
    with open(FIXTURES / "small-edges.json") as f:
        return json.load(f)


@pytest.fixture
def small_components(small_nodes, small_edges):
    from viz.splitter import split_components
    return split_components(small_nodes, small_edges)


@pytest.fixture
def small_colour_map(small_components):
    from viz.styler import assign_settlement_colours
    return assign_settlement_colours(small_components)


@pytest.fixture
def styled_small_components(small_components, small_colour_map):
    from viz.styler import assign_degrees
    assign_degrees(small_components, small_colour_map)
    return small_components
