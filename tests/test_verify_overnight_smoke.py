import json
import zipfile

import pytest

from tools.cluster.overnight_smoke import scenario_for_days
from tools.cluster.verify_overnight_smoke import inspect_archive


@pytest.mark.parametrize('bad_cost,missing_trip,passed', [(False, False, True), (True, False, False), (False, True, False)])
def test_archive_checks_independent_bill_and_service_coverage(tmp_path, bad_cost, missing_trip, passed):
    scenario = scenario_for_days(1)
    trips = [row['trip_id'] for row in scenario['timetable_rows']]
    documents = {
        'effective_scenario.json': scenario,
        'physical_schedule_validation.json': {'accepted': True},
        'rolling_hourly_chain/rolling_chain_summary.json': {
            'research_run': False, 'step_count': 24, 'expected_step_count': 24,
            'chain_accepted': True, 'all_steps_feasible': True},
        'rolling_hourly_chain/executed_plan.json': {
            'served_trip_ids': trips[:-1] if missing_trip else trips, 'unserved_trip_ids': [],
            'grid_to_bus_kwh_by_depot_slot': {'SMOKE_DEPOT': {'0': 10.0}}},
        'rolling_hourly_chain/executed_day_accounting.json': {
            'executed_slot_count': 48, 'expected_slot_count': 48, 'eligible': True,
            'missing_slots': [], 'duplicate_slots': [], 'bev_terminal_energy_balanced': True,
            'cost_breakdown': {'grid_import_kwh': 10.0, 'electricity_cost': 0.0 if bad_cost else 200.0,
                               'total_cost': 200.0, 'pv_generated_kwh': 0.0, 'pv_to_bus_kwh': 0.0,
                               'bess_to_bus_kwh': 0.0}},
    }
    archive = tmp_path / 'test.zip'
    with zipfile.ZipFile(archive, 'w') as output:
        for name, data in documents.items():
            output.writestr('output/test-run/' + name, json.dumps(data))
    result = inspect_archive(archive)
    assert result['passed'] is passed
    assert result['research_approval'] == 'NOT_GRANTED_BY_TEST'
