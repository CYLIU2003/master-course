from src.dispatch.graph_builder import ConnectionGraphBuilder
from src.dispatch.models import DispatchContext, Trip


def test_complete_graph_keeps_far_future_successors_and_exact_turnaround_boundary():
    trips = [Trip(trip_id=key, route_id='r', origin='A', destination='A',
                  departure_time=start, arrival_time=end, distance_km=1,
                  allowed_vehicle_types=('BEV',))
             for key,start,end in [('a','23:00','23:20'),('b','23:25','23:45'),('c','24:00','24:20')]]
    context = DispatchContext(service_date='2025-08-04',trips=trips,turnaround_rules={},
                              deadhead_rules={},vehicle_profiles={},default_turnaround_min=5)
    builder = ConnectionGraphBuilder()
    assert builder.build(context,'BEV') == {'a':['b','c'],'b':['c'],'c':[]}
    diagnostics = builder.analyze(context,'BEV')
    assert len(diagnostics) == 6
    assert sum(arc.feasible for arc in diagnostics) == 3
    assert builder.build(context,'ICE') == {}
