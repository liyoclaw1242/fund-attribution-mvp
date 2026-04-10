"""Thin wrapper for calling the FastAPI service layer.

All Streamlit pages should use this module instead of importing
from data/ or engine/ directly for data fetching.
"""

import logging
import os

import requests

logger = logging.getLogger(__name__)

API_BASE = os.getenv("API_BASE", "http://service:8000")
_TIMEOUT_SHORT = 10
_TIMEOUT_LONG = 30


class APIError(Exception):
    """Raised when the API returns a non-2xx response."""


class APIUnavailableError(APIError):
    """Raised when the API service cannot be reached."""


# --- HTTP helpers ---

def _get(path: str, params: dict | None = None, timeout: int = _TIMEOUT_SHORT):
    try:
        resp = requests.get(f"{API_BASE}{path}", params=params, timeout=timeout)
        resp.raise_for_status()
        return resp.json()
    except requests.ConnectionError:
        raise APIUnavailableError(
            f"無法連線至 API 服務 ({API_BASE})。\n"
            "請確認 FastAPI 服務已啟動 (uvicorn service.main:app)。"
        )
    except requests.HTTPError as e:
        detail = ""
        try:
            detail = e.response.json().get("detail", e.response.text)
        except Exception:
            detail = e.response.text
        raise APIError(f"API 錯誤 ({e.response.status_code}): {detail}")


def _post(path: str, json: dict | None = None, timeout: int = _TIMEOUT_LONG):
    try:
        resp = requests.post(f"{API_BASE}{path}", json=json, timeout=timeout)
        resp.raise_for_status()
        return resp.json()
    except requests.ConnectionError:
        raise APIUnavailableError(
            f"無法連線至 API 服務 ({API_BASE})。\n"
            "請確認 FastAPI 服務已啟動 (uvicorn service.main:app)。"
        )
    except requests.HTTPError as e:
        detail = ""
        try:
            detail = e.response.json().get("detail", e.response.text)
        except Exception:
            detail = e.response.text
        raise APIError(f"API 錯誤 ({e.response.status_code}): {detail}")


def _put(path: str, json: dict | None = None, timeout: int = _TIMEOUT_SHORT):
    try:
        resp = requests.put(f"{API_BASE}{path}", json=json, timeout=timeout)
        resp.raise_for_status()
        return resp.json()
    except requests.ConnectionError:
        raise APIUnavailableError(
            f"無法連線至 API 服務 ({API_BASE})。\n"
            "請確認 FastAPI 服務已啟動 (uvicorn service.main:app)。"
        )
    except requests.HTTPError as e:
        detail = ""
        try:
            detail = e.response.json().get("detail", e.response.text)
        except Exception:
            detail = e.response.text
        raise APIError(f"API 錯誤 ({e.response.status_code}): {detail}")


def _delete(path: str, params: dict | None = None, timeout: int = _TIMEOUT_SHORT):
    try:
        resp = requests.delete(
            f"{API_BASE}{path}", params=params, timeout=timeout
        )
        resp.raise_for_status()
        return None
    except requests.ConnectionError:
        raise APIUnavailableError(
            f"無法連線至 API 服務 ({API_BASE})。\n"
            "請確認 FastAPI 服務已啟動 (uvicorn service.main:app)。"
        )
    except requests.HTTPError as e:
        detail = ""
        try:
            detail = e.response.json().get("detail", e.response.text)
        except Exception:
            detail = e.response.text
        raise APIError(f"API 錯誤 ({e.response.status_code}): {detail}")


# --- Fund endpoints ---

def get_fund(identifier: str) -> dict:
    """Look up a fund by code, ISIN, or ticker."""
    return _get(f"/api/fund/{identifier}")


def search_funds(query: str) -> list[dict]:
    """Search funds by name or code."""
    data = _get("/api/fund/search", params={"q": query})
    return data.get("results", [])


# --- Attribution endpoint ---

def run_attribution(
    holdings: list[dict],
    mode: str = "BF2",
    benchmark: str = "auto",
) -> dict:
    """Run Brinson-Fachler attribution via the API.

    Args:
        holdings: List of {"identifier": "0050", "shares": 1}.
        mode: "BF2" or "BF3".
        benchmark: "auto" or specific benchmark name.

    Returns:
        Attribution result dict with keys: fund_return, bench_return,
        excess_return, allocation_total, selection_total, interaction_total,
        brinson_mode, detail, top_contributors, bottom_contributors,
        unmapped_weight.
    """
    return _post("/api/attribution", json={
        "holdings": holdings,
        "mode": mode,
        "benchmark": benchmark,
    })


# --- Goal endpoints ---

def list_goals(client_id: str) -> list[dict]:
    """List all goals for a client."""
    return _get(f"/api/goal/{client_id}")


def create_goal(
    client_id: str,
    goal_type: str,
    target_amount: float,
    target_year: int,
    monthly_contribution: float,
    risk_tolerance: str,
    current_savings: float = 0,
) -> dict:
    """Create a new financial goal."""
    return _post("/api/goal", json={
        "client_id": client_id,
        "goal_type": goal_type,
        "target_amount": target_amount,
        "target_year": target_year,
        "monthly_contribution": monthly_contribution,
        "risk_tolerance": risk_tolerance,
        "current_savings": current_savings,
    })


def update_goal(goal_id: str, **kwargs) -> dict:
    """Update goal parameters."""
    return _put(f"/api/goal/{goal_id}", json=kwargs)


def delete_goal(goal_id: str) -> None:
    """Delete a goal."""
    _delete(f"/api/goal/{goal_id}")


def simulate_goal(goal_id: str) -> dict:
    """Run Monte Carlo simulation for a goal."""
    return _get(f"/api/goal/{goal_id}/simulate", timeout=_TIMEOUT_LONG)


# --- Portfolio endpoints ---

def list_clients() -> list[dict]:
    """List all clients with holding counts."""
    return _get("/api/portfolio")


def get_portfolio(client_id: str) -> dict:
    """Get a client's full portfolio with cross-bank aggregation."""
    return _get(f"/api/portfolio/{client_id}")


# --- Health ---

def check_health() -> dict:
    """Check API service health."""
    return _get("/api/health")
