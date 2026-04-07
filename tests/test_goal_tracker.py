"""Tests for engine/goal_tracker.py — Monte Carlo goal tracking engine."""

import sqlite3
import time

import numpy as np
import pytest

from engine.goal_tracker import (
    simulate_goal,
    create_goal,
    get_goals,
    get_goal,
    update_goal,
    delete_goal,
    RETURN_ASSUMPTIONS,
    _run_paths,
)
from interfaces import GoalConfig, GoalSimResult


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def db_conn():
    """In-memory SQLite DB with goal schema."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript("""
        CREATE TABLE clients (
            client_id TEXT PRIMARY KEY,
            name TEXT NOT NULL
        );
        CREATE TABLE client_goals (
            goal_id TEXT PRIMARY KEY,
            client_id TEXT NOT NULL,
            goal_type TEXT NOT NULL DEFAULT 'retirement',
            target_amount REAL NOT NULL,
            target_year INTEGER NOT NULL,
            monthly_contribution REAL NOT NULL DEFAULT 0,
            risk_tolerance TEXT NOT NULL DEFAULT 'moderate',
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            updated_at TEXT NOT NULL DEFAULT (datetime('now')),
            FOREIGN KEY (client_id) REFERENCES clients(client_id)
        );
        INSERT INTO clients VALUES ('C001', 'Test Client');
    """)
    return conn


def _easy_goal() -> GoalConfig:
    """Conservative goal that should be easily achievable (near 100%)."""
    return GoalConfig(
        target_amount=100_000,   # only 100K TWD
        target_year=2046,        # 20 years
        monthly_contribution=5000,
        risk_tolerance="moderate",
        current_savings=500_000,  # already halfway there
    )


def _hard_goal() -> GoalConfig:
    """Aggressive goal that's very hard to achieve (<50%)."""
    return GoalConfig(
        target_amount=50_000_000,  # 50M TWD
        target_year=2036,          # only 10 years
        monthly_contribution=10000,
        risk_tolerance="conservative",
        current_savings=100_000,
    )


def _moderate_goal() -> GoalConfig:
    """Moderate goal for testing suggestions."""
    return GoalConfig(
        target_amount=5_000_000,
        target_year=2041,         # 15 years
        monthly_contribution=15000,
        risk_tolerance="moderate",
        current_savings=500_000,
    )


# ---------------------------------------------------------------------------
# Simulation — happy path
# ---------------------------------------------------------------------------

class TestSimulation:
    def test_easy_goal_high_probability(self):
        """Easy goal should have high success probability."""
        result = simulate_goal(_easy_goal(), seed=42)
        assert isinstance(result, GoalSimResult)
        assert result.success_probability >= 0.90

    def test_hard_goal_low_probability(self):
        """Hard goal should have low success probability."""
        result = simulate_goal(_hard_goal(), seed=42)
        assert result.success_probability < 0.50

    def test_result_fields(self):
        """All GoalSimResult fields populated correctly."""
        goal = _easy_goal()
        result = simulate_goal(goal, seed=42)

        assert result.target_amount == goal.target_amount
        assert result.num_paths == 1000
        assert result.years_to_goal > 0
        assert result.p10_outcome <= result.median_outcome <= result.p90_outcome
        assert 0.0 <= result.success_probability <= 1.0

    def test_reproducible_with_seed(self):
        """Same seed produces same results."""
        r1 = simulate_goal(_moderate_goal(), seed=123)
        r2 = simulate_goal(_moderate_goal(), seed=123)

        assert r1.success_probability == r2.success_probability
        assert r1.median_outcome == r2.median_outcome

    def test_different_seeds_different_results(self):
        """Different seeds produce different results."""
        r1 = simulate_goal(_moderate_goal(), seed=1)
        r2 = simulate_goal(_moderate_goal(), seed=2)

        # Very unlikely to be exactly equal with different seeds
        assert r1.median_outcome != r2.median_outcome

    def test_custom_num_paths(self):
        """Custom number of paths works."""
        result = simulate_goal(_easy_goal(), num_paths=500, seed=42)
        assert result.num_paths == 500

    def test_more_savings_increases_probability(self):
        """Higher starting savings → higher success probability."""
        goal_low = GoalConfig(
            target_amount=3_000_000, target_year=2041,
            monthly_contribution=10000, current_savings=100_000,
        )
        goal_high = GoalConfig(
            target_amount=3_000_000, target_year=2041,
            monthly_contribution=10000, current_savings=2_000_000,
        )
        r_low = simulate_goal(goal_low, seed=42)
        r_high = simulate_goal(goal_high, seed=42)

        assert r_high.success_probability > r_low.success_probability


# ---------------------------------------------------------------------------
# Risk tolerance affects results
# ---------------------------------------------------------------------------

class TestRiskTolerance:
    def test_aggressive_higher_median(self):
        """Aggressive has higher median outcome than conservative."""
        goal_con = GoalConfig(
            target_amount=5_000_000, target_year=2046,
            monthly_contribution=10000, risk_tolerance="conservative",
            current_savings=500_000,
        )
        goal_agg = GoalConfig(
            target_amount=5_000_000, target_year=2046,
            monthly_contribution=10000, risk_tolerance="aggressive",
            current_savings=500_000,
        )
        r_con = simulate_goal(goal_con, seed=42)
        r_agg = simulate_goal(goal_agg, seed=42)

        assert r_agg.median_outcome > r_con.median_outcome

    def test_aggressive_wider_spread(self):
        """Aggressive has wider p10-p90 spread (more volatile)."""
        goal_con = GoalConfig(
            target_amount=5_000_000, target_year=2046,
            monthly_contribution=10000, risk_tolerance="conservative",
            current_savings=500_000,
        )
        goal_agg = GoalConfig(
            target_amount=5_000_000, target_year=2046,
            monthly_contribution=10000, risk_tolerance="aggressive",
            current_savings=500_000,
        )
        r_con = simulate_goal(goal_con, seed=42)
        r_agg = simulate_goal(goal_agg, seed=42)

        spread_con = r_con.p90_outcome - r_con.p10_outcome
        spread_agg = r_agg.p90_outcome - r_agg.p10_outcome
        assert spread_agg > spread_con


# ---------------------------------------------------------------------------
# Suggestions
# ---------------------------------------------------------------------------

class TestSuggestions:
    def test_suggestions_when_low_probability(self):
        """Hard goals produce at least 2 suggestions."""
        result = simulate_goal(_hard_goal(), seed=42)
        assert len(result.suggestions) >= 2

    def test_no_suggestions_when_high_probability(self):
        """Easy goals produce no suggestions."""
        result = simulate_goal(_easy_goal(), seed=42)
        assert len(result.suggestions) == 0

    def test_suggestion_content(self):
        """Suggestions contain actionable Chinese text."""
        result = simulate_goal(_hard_goal(), seed=42)
        # Should mention increasing monthly contribution
        has_contribution = any("每月增加" in s for s in result.suggestions)
        assert has_contribution

    def test_no_risk_upgrade_for_aggressive(self):
        """Aggressive goals don't suggest upgrading risk further."""
        goal = GoalConfig(
            target_amount=50_000_000, target_year=2036,
            monthly_contribution=10000, risk_tolerance="aggressive",
            current_savings=100_000,
        )
        result = simulate_goal(goal, seed=42)
        has_risk_upgrade = any("積極型" in s for s in result.suggestions)
        assert not has_risk_upgrade


# ---------------------------------------------------------------------------
# Input validation
# ---------------------------------------------------------------------------

class TestValidation:
    def test_past_target_year(self):
        """Reject target year in the past."""
        goal = GoalConfig(
            target_amount=1_000_000, target_year=2020,
            monthly_contribution=10000,
        )
        with pytest.raises(ValueError, match="must be in the future"):
            simulate_goal(goal)

    def test_invalid_risk_tolerance(self):
        """Reject invalid risk tolerance."""
        goal = GoalConfig(
            target_amount=1_000_000, target_year=2040,
            monthly_contribution=10000, risk_tolerance="yolo",
        )
        with pytest.raises(ValueError, match="Invalid risk_tolerance"):
            simulate_goal(goal)


# ---------------------------------------------------------------------------
# Performance
# ---------------------------------------------------------------------------

class TestPerformance:
    def test_under_5_seconds(self):
        """1000-path simulation completes in <5 seconds."""
        goal = _moderate_goal()
        start = time.monotonic()
        simulate_goal(goal, num_paths=1000, seed=42)
        elapsed = time.monotonic() - start
        assert elapsed < 5.0, f"Simulation took {elapsed:.2f}s (limit: 5s)"


# ---------------------------------------------------------------------------
# Goal CRUD
# ---------------------------------------------------------------------------

class TestGoalCRUD:
    def test_create_and_get(self, db_conn):
        goal = _moderate_goal()
        goal_id = create_goal(db_conn, "C001", goal)

        assert goal_id is not None
        retrieved = get_goal(db_conn, goal_id)
        assert retrieved is not None
        assert retrieved["client_id"] == "C001"
        assert retrieved["target_amount"] == 5_000_000
        assert retrieved["risk_tolerance"] == "moderate"

    def test_get_goals_for_client(self, db_conn):
        create_goal(db_conn, "C001", _easy_goal())
        create_goal(db_conn, "C001", _hard_goal())

        goals = get_goals(db_conn, "C001")
        assert len(goals) == 2

    def test_get_goals_empty(self, db_conn):
        goals = get_goals(db_conn, "C001")
        assert goals == []

    def test_update_goal(self, db_conn):
        goal_id = create_goal(db_conn, "C001", _moderate_goal())
        updated = update_goal(db_conn, goal_id, target_amount=8_000_000)

        assert updated is True
        retrieved = get_goal(db_conn, goal_id)
        assert retrieved["target_amount"] == 8_000_000

    def test_update_nonexistent(self, db_conn):
        updated = update_goal(db_conn, "FAKE_ID", target_amount=1)
        assert updated is False

    def test_delete_goal(self, db_conn):
        goal_id = create_goal(db_conn, "C001", _easy_goal())
        deleted = delete_goal(db_conn, goal_id)

        assert deleted is True
        assert get_goal(db_conn, goal_id) is None

    def test_delete_nonexistent(self, db_conn):
        deleted = delete_goal(db_conn, "FAKE_ID")
        assert deleted is False

    def test_get_nonexistent_goal(self, db_conn):
        assert get_goal(db_conn, "FAKE_ID") is None
