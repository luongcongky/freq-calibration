"""
core/__init__.py
Gói lõi cho hệ thống kịch bản grid step-by-step (đa thiết bị).

Luồng file .txt cũ (sequence/measurement/report/simulation) đã được loại bỏ;
toàn bộ kịch bản nay dùng mô hình Scenario (grid) + ScenarioRunner.
"""

from .scenario import (
    Scenario, ScenarioStep, LoopBlock, IfBlock, Branch, Condition,
    ACTION_SPECS, OPERATORS, OP_LABELS, MEASURE_ACTIONS,
    actions_for_category, actions_for_devices, validate_scenario,
    node_kind,
)
from .scenario_runner import (
    ScenarioRunner, StepResult, execute_action, evaluate_condition,
)
from .discovery import (
    scan_resources, identify_resource, match_driver, scan_and_identify,
    snapshot_resources, diff_new_resources, test_connection,
    DiscoveredDevice, ConnectionTest,
)
from .profile import ConnectionProfile, ProfileEntry

__all__ = [
    # scenario model
    "Scenario", "ScenarioStep", "LoopBlock", "IfBlock", "Branch", "Condition",
    "ACTION_SPECS", "OPERATORS", "OP_LABELS", "MEASURE_ACTIONS",
    "actions_for_category", "actions_for_devices", "validate_scenario", "node_kind",
    # runner
    "ScenarioRunner", "StepResult", "execute_action", "evaluate_condition",
    # discovery
    "scan_resources", "identify_resource", "match_driver", "scan_and_identify",
    "snapshot_resources", "diff_new_resources", "test_connection",
    "DiscoveredDevice", "ConnectionTest",
    # profile
    "ConnectionProfile", "ProfileEntry",
]
