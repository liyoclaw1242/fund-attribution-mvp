"""Monte Carlo goal tracking engine.

Simulates 1000 future wealth paths to estimate the probability
of reaching a financial goal (retirement, house, education).

Return assumptions by risk tolerance (annualized):
  conservative: mean=4%, std=5%  (mostly bonds)
  moderate:     mean=7%, std=12% (60/40 equity/bond)
  aggressive:   mean=10%, std=18% (mostly equity)

These are simple normal distribution assumptions for MVP.
Full historical bootstrap from actual portfolio allocation is post-MVP.
"""

import logging
import sqlite3
import uuid
from typing import List, Optional

import numpy as np

from interfaces import GoalConfig, GoalSimResult

logger = logging.getLogger(__name__)

NUM_PATHS = 1000
MONTHS_PER_YEAR = 12

# Annualized return assumptions by risk tolerance
RETURN_ASSUMPTIONS = {
    "conservative": {"mean": 0.04, "std": 0.05},
    "moderate":     {"mean": 0.07, "std": 0.12},
    "aggressive":   {"mean": 0.10, "std": 0.18},
}


def simulate_goal(
    goal: GoalConfig,
    num_paths: int = NUM_PATHS,
    seed: Optional[int] = None,
) -> GoalSimResult:
    """Run Monte Carlo simulation for a financial goal.

    Args:
        goal: Goal configuration with target, timeline, contributions.
        num_paths: Number of simulation paths (default 1000).
        seed: Random seed for reproducibility (optional).

    Returns:
        GoalSimResult with success probability and suggestions.

    Raises:
        ValueError: If risk_tolerance is invalid or target_year is in the past.
    """
    import datetime

    current_year = datetime.datetime.now().year
    years_to_goal = goal.target_year - current_year

    if years_to_goal <= 0:
        raise ValueError(
            f"Target year {goal.target_year} must be in the future "
            f"(current year: {current_year})"
        )

    risk = goal.risk_tolerance.lower()
    if risk not in RETURN_ASSUMPTIONS:
        raise ValueError(
            f"Invalid risk_tolerance: {risk}. "
            f"Must be one of: {list(RETURN_ASSUMPTIONS.keys())}"
        )

    assumptions = RETURN_ASSUMPTIONS[risk]
    annual_mean = assumptions["mean"]
    annual_std = assumptions["std"]

    # Convert annual returns to monthly
    monthly_mean = annual_mean / MONTHS_PER_YEAR
    monthly_std = annual_std / np.sqrt(MONTHS_PER_YEAR)

    total_months = years_to_goal * MONTHS_PER_YEAR

    # Run simulation
    rng = np.random.default_rng(seed)
    final_values = _run_paths(
        rng=rng,
        num_paths=num_paths,
        total_months=total_months,
        monthly_mean=monthly_mean,
        monthly_std=monthly_std,
        monthly_contribution=goal.monthly_contribution,
        initial_balance=goal.current_savings,
    )

    # Calculate statistics
    success_count = np.sum(final_values >= goal.target_amount)
    success_probability = float(success_count / num_paths)

    median_outcome = float(np.median(final_values))
    p10_outcome = float(np.percentile(final_values, 10))
    p90_outcome = float(np.percentile(final_values, 90))

    # Generate suggestions if probability < 80%
    suggestions = []
    if success_probability < 0.80:
        suggestions = _generate_suggestions(
            goal, success_probability, median_outcome,
            years_to_goal, monthly_mean, monthly_std, rng,
        )

    return GoalSimResult(
        success_probability=success_probability,
        median_outcome=median_outcome,
        p10_outcome=p10_outcome,
        p90_outcome=p90_outcome,
        target_amount=goal.target_amount,
        years_to_goal=years_to_goal,
        num_paths=num_paths,
        suggestions=suggestions,
    )


def _run_paths(
    rng: np.random.Generator,
    num_paths: int,
    total_months: int,
    monthly_mean: float,
    monthly_std: float,
    monthly_contribution: float,
    initial_balance: float,
) -> np.ndarray:
    """Simulate wealth paths using vectorized Monte Carlo.

    Returns array of final values for each path.
    """
    # Generate all random returns at once: (num_paths, total_months)
    monthly_returns = rng.normal(monthly_mean, monthly_std, (num_paths, total_months))

    # Simulate wealth accumulation
    balances = np.full(num_paths, initial_balance, dtype=np.float64)

    for month in range(total_months):
        # Apply return, then add contribution
        balances = balances * (1 + monthly_returns[:, month]) + monthly_contribution

    # Floor at zero (can't have negative wealth)
    balances = np.maximum(balances, 0)

    return balances


def _generate_suggestions(
    goal: GoalConfig,
    current_prob: float,
    median_outcome: float,
    years_to_goal: int,
    monthly_mean: float,
    monthly_std: float,
    rng: np.random.Generator,
) -> List[str]:
    """Generate adjustment suggestions when success probability < 80%."""
    suggestions = []
    shortfall = goal.target_amount - median_outcome

    # Suggestion 1: Increase monthly contribution
    if shortfall > 0 and years_to_goal > 0:
        total_months = years_to_goal * MONTHS_PER_YEAR
        # Simple estimate: additional contribution needed
        # Using mean return to estimate required additional monthly amount
        if monthly_mean > 0:
            # Future value of annuity factor
            fv_factor = ((1 + monthly_mean) ** total_months - 1) / monthly_mean
        else:
            fv_factor = total_months

        additional_monthly = shortfall / fv_factor if fv_factor > 0 else shortfall / total_months
        additional_monthly = max(0, additional_monthly)

        suggestions.append(
            f"建議每月增加投入 NT${additional_monthly:,.0f}，"
            f"以提高達標機率至 80% 以上。"
        )

    # Suggestion 2: Extend timeline
    if years_to_goal < 40:
        # Try adding years until probability improves
        for extra_years in [2, 3, 5]:
            extended_months = (years_to_goal + extra_years) * MONTHS_PER_YEAR
            extended_values = _run_paths(
                rng=rng,
                num_paths=500,  # fewer paths for speed
                total_months=extended_months,
                monthly_mean=monthly_mean,
                monthly_std=monthly_std,
                monthly_contribution=goal.monthly_contribution,
                initial_balance=goal.current_savings,
            )
            extended_prob = float(np.sum(extended_values >= goal.target_amount) / 500)

            if extended_prob >= 0.80:
                suggestions.append(
                    f"若將目標延後 {extra_years} 年至 {goal.target_year + extra_years} 年，"
                    f"成功機率可提升至 {extended_prob:.0%}。"
                )
                break

    # Suggestion 3: Risk tolerance upgrade (if not already aggressive)
    if goal.risk_tolerance != "aggressive":
        next_level = "moderate" if goal.risk_tolerance == "conservative" else "aggressive"
        next_label = "穩健型" if next_level == "moderate" else "積極型"
        suggestions.append(
            f"考慮將風險承受度調整為「{next_label}」，"
            f"以提高預期報酬率（但波動也會增加）。"
        )

    return suggestions


# ---------------------------------------------------------------------------
# Goal CRUD
# ---------------------------------------------------------------------------

def create_goal(
    conn: sqlite3.Connection,
    client_id: str,
    goal: GoalConfig,
) -> str:
    """Create a new financial goal. Returns goal_id."""
    goal_id = str(uuid.uuid4())[:8]
    with conn:
        conn.execute(
            """INSERT INTO client_goals
               (goal_id, client_id, goal_type, target_amount, target_year,
                monthly_contribution, risk_tolerance)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                goal_id, client_id, goal.goal_type,
                goal.target_amount, goal.target_year,
                goal.monthly_contribution, goal.risk_tolerance,
            ),
        )
    logger.info("Created goal %s for client %s", goal_id, client_id)
    return goal_id


def get_goals(
    conn: sqlite3.Connection, client_id: str
) -> List[dict]:
    """Get all goals for a client."""
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT * FROM client_goals WHERE client_id = ? ORDER BY created_at",
        (client_id,),
    ).fetchall()
    return [dict(r) for r in rows]


def get_goal(
    conn: sqlite3.Connection, goal_id: str
) -> Optional[dict]:
    """Get a single goal by ID."""
    conn.row_factory = sqlite3.Row
    row = conn.execute(
        "SELECT * FROM client_goals WHERE goal_id = ?", (goal_id,)
    ).fetchone()
    return dict(row) if row else None


def update_goal(
    conn: sqlite3.Connection,
    goal_id: str,
    **kwargs,
) -> bool:
    """Update goal fields. Returns True if updated."""
    allowed = {
        "goal_type", "target_amount", "target_year",
        "monthly_contribution", "risk_tolerance",
    }
    updates = {k: v for k, v in kwargs.items() if k in allowed}
    if not updates:
        return False

    updates["updated_at"] = "datetime('now')"
    set_clause = ", ".join(
        f"{k} = ?" if k != "updated_at" else f"{k} = datetime('now')"
        for k in updates
    )
    values = [v for k, v in updates.items() if k != "updated_at"]
    values.append(goal_id)

    with conn:
        cursor = conn.execute(
            f"UPDATE client_goals SET {set_clause} WHERE goal_id = ?",
            values,
        )
    return cursor.rowcount > 0


def delete_goal(
    conn: sqlite3.Connection, goal_id: str
) -> bool:
    """Delete a goal. Returns True if deleted."""
    with conn:
        cursor = conn.execute(
            "DELETE FROM client_goals WHERE goal_id = ?", (goal_id,)
        )
    return cursor.rowcount > 0
