"""TWSE OpenAPI Health Check — validates endpoint availability and JSON responses."""

import json
import sys
import time
from datetime import datetime

import requests
import urllib3

# TWSE's SSL certificate is missing Subject Key Identifier — suppress warning
# for this known government open-data API.
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

ENDPOINTS = {
    "MI_INDEX": {
        "url": "https://openapi.twse.com.tw/v1/exchangeReport/MI_INDEX",
        "description": "Market industry indices (收盤指數, 漲跌百分比)",
        "expected_fields": ["日期", "指數", "收盤指數", "漲跌百分比"],
    },
    "TWT49U": {
        "url": "https://openapi.twse.com.tw/v1/exchangeReport/TWT49U",
        "description": "Weighted return index by industry",
        "expected_fields": [],
    },
    "BWIBBU_d": {
        "url": "https://openapi.twse.com.tw/v1/exchangeReport/BWIBBU_d",
        "description": "Individual stock P/E, P/B, dividend yield (fallback data source)",
        "expected_fields": ["Code", "Name", "ClosePrice", "DividendYield"],
    },
}

RATE_LIMIT_DELAY = 2.0  # seconds between requests


def check_endpoint(name: str, config: dict) -> dict:
    """Check a single endpoint. Returns status dict."""
    result = {"name": name, "url": config["url"], "description": config["description"]}
    try:
        resp = requests.get(config["url"], timeout=10, headers={"Accept": "application/json"}, verify=False)
        result["http_status"] = resp.status_code

        # Check if response is valid JSON
        try:
            data = resp.json()
        except (json.JSONDecodeError, requests.exceptions.JSONDecodeError):
            result["status"] = "FAIL"
            result["reason"] = "Response is not valid JSON (likely HTML error page)"
            return result

        if not isinstance(data, list) or len(data) == 0:
            result["status"] = "WARN"
            result["reason"] = "JSON response is empty or not an array"
            return result

        # Check expected fields
        missing = [f for f in config["expected_fields"] if f not in data[0]]
        if missing:
            result["status"] = "WARN"
            result["reason"] = f"Missing expected fields: {missing}"
        else:
            result["status"] = "OK"
            result["record_count"] = len(data)
            result["sample_fields"] = list(data[0].keys())

    except requests.RequestException as e:
        result["status"] = "FAIL"
        result["reason"] = str(e)

    return result


def main():
    print(f"TWSE OpenAPI Health Check — {datetime.now().isoformat()}")
    print("=" * 60)

    results = []
    for i, (name, config) in enumerate(ENDPOINTS.items()):
        if i > 0:
            time.sleep(RATE_LIMIT_DELAY)
        print(f"\nChecking {name}...")
        result = check_endpoint(name, config)
        results.append(result)

        status = result["status"]
        if status == "OK":
            print(f"  ✓ {status} — {result.get('record_count', '?')} records, fields: {result.get('sample_fields', [])}")
        else:
            print(f"  ✗ {status} — {result.get('reason', 'unknown')}")

    print("\n" + "=" * 60)
    ok_count = sum(1 for r in results if r["status"] == "OK")
    print(f"Summary: {ok_count}/{len(results)} endpoints healthy")

    return 0 if ok_count >= 1 else 1


if __name__ == "__main__":
    sys.exit(main())
