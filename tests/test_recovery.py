from datetime import date

from app.services.scenario import _recovery_days
from app.simulator.disruptions import DemandSpike, DisruptionConfig


def test_recovery_days_is_first_post_disruption_day_at_baseline_fill_rate():
    disruptions = DisruptionConfig(
        demand_spikes=[
            DemandSpike(
                multiplier=2.0,
                start_date=date(2026, 1, 1),
                end_date=date(2026, 1, 2),
            )
        ]
    )
    baseline = [
        {"kpi_date": "2026-01-01", "fill_rate": 0.95},
        {"kpi_date": "2026-01-02", "fill_rate": 0.95},
        {"kpi_date": "2026-01-03", "fill_rate": 0.95},
        {"kpi_date": "2026-01-04", "fill_rate": 0.95},
    ]
    scenario = [
        {"kpi_date": "2026-01-01", "fill_rate": 0.70},
        {"kpi_date": "2026-01-02", "fill_rate": 0.75},
        {"kpi_date": "2026-01-03", "fill_rate": 0.90},
        {"kpi_date": "2026-01-04", "fill_rate": 0.96},
    ]

    assert _recovery_days(baseline, scenario, disruptions) == 2


def test_recovery_days_is_none_when_scenario_does_not_recover_in_window():
    disruptions = DisruptionConfig(
        demand_spikes=[
            DemandSpike(
                multiplier=2.0,
                start_date=date(2026, 1, 1),
                end_date=date(2026, 1, 2),
            )
        ]
    )
    baseline = [
        {"kpi_date": "2026-01-03", "fill_rate": 0.95},
        {"kpi_date": "2026-01-04", "fill_rate": 0.95},
    ]
    scenario = [
        {"kpi_date": "2026-01-03", "fill_rate": 0.90},
        {"kpi_date": "2026-01-04", "fill_rate": 0.91},
    ]

    assert _recovery_days(baseline, scenario, disruptions) is None
