import pytest
import numpy as np
import stk

from ....case_data import CaseData
from .utilities import (
    get_closest_point,
    get_fg_position,
    get_edges,
    get_points,
)


vertices = stk.macrocycle.vertices


@pytest.fixture
def no_flip(position, building_block_2, angle):

    point1, point2 = points = tuple(get_points(position, angle))

    def get_fg0_point(building_block):
        return get_closest_point(
            points=points,
            point=get_fg_position(0, building_block),
        )

    def get_fg1_point(building_block):
        return get_closest_point(
            points=points,
            point=get_fg_position(1, building_block),
        )

    vertex = vertices._CycleVertex(0, position, False, angle+np.pi/2)
    return CaseData(
        vertex=vertex,
        edges=tuple(get_edges(vertex, angle)),
        building_block=building_block_2,
        position=position,
        alignment_tests={
            get_fg0_point: point1,
            get_fg1_point: point2,
        },
        functional_group_edges={0: 0, 1: 1},
    )