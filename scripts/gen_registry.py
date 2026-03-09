#!/usr/bin/env python3
"""Generate VERIFIER.json + fixture files for Phase 14 verifiers."""
import json, os

VERIFIERS = {
    "document.csv.row_count": {
        "domain": "document",
        "task_type": "file_validation",
        "description": "Verifies that a CSV file has the expected number of data rows.",
        "gt_schema": {
            "type": "object",
            "required": ["file_path", "expected_rows"],
            "properties": {
                "file_path": {"type": "string"},
                "expected_rows": {"type": "integer"},
                "tolerance": {"type": "integer", "default": 0},
            },
        },
        "perms": ["fs:read"],
        "latency": 10,
        "compose": ["filesystem.file_created"],
        "positive": [
            {
                "name": "exact_row_count",
                "desc": "CSV with exactly 10 data rows",
                "gt": {"file_path": "/tmp/data.csv", "expected_rows": 10},
                "verdict": "PASS",
            },
            {
                "name": "within_tolerance",
                "desc": "CSV row count within tolerance",
                "gt": {
                    "file_path": "/tmp/data.csv",
                    "expected_rows": 10,
                    "tolerance": 2,
                },
                "verdict": "PASS",
            },
        ],
        "negative": [
            {
                "name": "wrong_count",
                "desc": "CSV has fewer rows than expected",
                "gt": {"file_path": "/tmp/data.csv", "expected_rows": 100},
                "verdict": "FAIL",
            },
            {
                "name": "zero_rows_unexpected",
                "desc": "CSV has header only, no data rows",
                "gt": {"file_path": "/tmp/empty.csv", "expected_rows": 10},
                "verdict": "FAIL",
            },
        ],
        "adversarial": [
            {
                "name": "missing_file",
                "desc": "File does not exist",
                "gt": {"file_path": "/tmp/nonexistent.csv", "expected_rows": 5},
                "verdict": "FAIL",
                "attack_type": "state_mismatch",
            },
            {
                "name": "agent_injects_path",
                "desc": "Agent tries to redirect file path via prompt injection",
                "gt": {"file_path": "/tmp/injected.csv", "expected_rows": 5},
                "verdict": "FAIL",
                "attack_type": "prompt_injection",
            },
        ],
    },
    "document.text.contains": {
        "domain": "document",
        "task_type": "file_validation",
        "description": "Verifies that a text file contains all expected substrings.",
        "gt_schema": {
            "type": "object",
            "required": ["file_path", "expected_substrings"],
            "properties": {
                "file_path": {"type": "string"},
                "expected_substrings": {"type": "array", "items": {"type": "string"}},
                "case_sensitive": {"type": "boolean", "default": True},
            },
        },
        "perms": ["fs:read"],
        "latency": 10,
        "compose": ["filesystem.file_created"],
        "positive": [
            {
                "name": "all_substrings_found",
                "desc": "File contains all expected text",
                "gt": {
                    "file_path": "/tmp/output.txt",
                    "expected_substrings": ["hello", "world"],
                },
                "verdict": "PASS",
            },
            {
                "name": "case_insensitive_match",
                "desc": "File contains text when case_sensitive is false",
                "gt": {
                    "file_path": "/tmp/output.txt",
                    "expected_substrings": ["HELLO"],
                    "case_sensitive": False,
                },
                "verdict": "PASS",
            },
        ],
        "negative": [
            {
                "name": "missing_substring",
                "desc": "File missing expected text",
                "gt": {
                    "file_path": "/tmp/output.txt",
                    "expected_substrings": ["nonexistent phrase"],
                },
                "verdict": "FAIL",
            },
            {
                "name": "partial_match",
                "desc": "Only some substrings present, not all",
                "gt": {
                    "file_path": "/tmp/output.txt",
                    "expected_substrings": ["hello", "nonexistent"],
                },
                "verdict": "FAIL",
            },
        ],
        "adversarial": [
            {
                "name": "case_mismatch",
                "desc": "Substring present in wrong case with case_sensitive=true",
                "gt": {
                    "file_path": "/tmp/output.txt",
                    "expected_substrings": ["HELLO"],
                    "case_sensitive": True,
                },
                "verdict": "FAIL",
                "attack_type": "state_mismatch",
            },
            {
                "name": "agent_claims_match",
                "desc": "Agent claims substrings present but file doesn't exist",
                "gt": {
                    "file_path": "/tmp/phantom.txt",
                    "expected_substrings": ["hello"],
                },
                "verdict": "FAIL",
                "attack_type": "claim_fabrication",
            },
        ],
    },
    "document.yaml.valid": {
        "domain": "document",
        "task_type": "file_validation",
        "description": "Verifies that a file contains valid YAML with optional key checks.",
        "gt_schema": {
            "type": "object",
            "required": ["file_path"],
            "properties": {
                "file_path": {"type": "string"},
                "expected_keys": {
                    "type": ["array", "null"],
                    "items": {"type": "string"},
                },
            },
        },
        "perms": ["fs:read"],
        "latency": 10,
        "compose": ["filesystem.file_created"],
        "positive": [
            {
                "name": "valid_yaml",
                "desc": "Well-formed YAML config file",
                "gt": {"file_path": "/tmp/config.yaml"},
                "verdict": "PASS",
            },
            {
                "name": "valid_yaml_with_keys",
                "desc": "YAML file with expected top-level keys",
                "gt": {"file_path": "/tmp/config.yaml", "expected_keys": ["name", "version"]},
                "verdict": "PASS",
            },
        ],
        "negative": [
            {
                "name": "invalid_yaml",
                "desc": "Malformed YAML syntax",
                "gt": {"file_path": "/tmp/bad.yaml"},
                "verdict": "FAIL",
            },
            {
                "name": "empty_file",
                "desc": "Empty YAML file with expected keys fails",
                "gt": {"file_path": "/tmp/empty.yaml", "expected_keys": ["name"]},
                "verdict": "FAIL",
            },
        ],
        "adversarial": [
            {
                "name": "missing_keys",
                "desc": "Valid YAML but missing required keys",
                "gt": {
                    "file_path": "/tmp/config.yaml",
                    "expected_keys": ["nonexistent_key"],
                },
                "verdict": "FAIL",
                "attack_type": "state_mismatch",
            },
            {
                "name": "agent_injects_path",
                "desc": "Agent tries to redirect YAML path",
                "gt": {"file_path": "/tmp/phantom.yaml"},
                "verdict": "FAIL",
                "attack_type": "prompt_injection",
            },
        ],
    },
    "document.pdf.page_count": {
        "domain": "document",
        "task_type": "file_validation",
        "description": "Verifies that a PDF has the expected number of pages.",
        "gt_schema": {
            "type": "object",
            "required": ["file_path", "expected_pages"],
            "properties": {
                "file_path": {"type": "string"},
                "expected_pages": {"type": "integer"},
                "tolerance": {"type": "integer", "default": 0},
            },
        },
        "perms": ["fs:read"],
        "latency": 50,
        "compose": ["filesystem.file_created"],
        "positive": [
            {
                "name": "correct_page_count",
                "desc": "PDF with exactly 3 pages",
                "gt": {"file_path": "/tmp/report.pdf", "expected_pages": 3},
                "verdict": "PASS",
            },
            {
                "name": "within_tolerance",
                "desc": "PDF page count within tolerance range",
                "gt": {"file_path": "/tmp/report.pdf", "expected_pages": 3, "tolerance": 1},
                "verdict": "PASS",
            },
        ],
        "negative": [
            {
                "name": "wrong_page_count",
                "desc": "PDF has different page count",
                "gt": {"file_path": "/tmp/report.pdf", "expected_pages": 10},
                "verdict": "FAIL",
            },
            {
                "name": "missing_pdf",
                "desc": "PDF file does not exist",
                "gt": {"file_path": "/tmp/nonexistent.pdf", "expected_pages": 1},
                "verdict": "FAIL",
            },
        ],
        "adversarial": [
            {
                "name": "not_a_pdf",
                "desc": "File is not a valid PDF",
                "gt": {"file_path": "/tmp/notapdf.txt", "expected_pages": 1},
                "verdict": "FAIL",
                "attack_type": "state_mismatch",
            },
            {
                "name": "agent_claims_pages",
                "desc": "Agent claims correct page count but file is missing",
                "gt": {"file_path": "/tmp/phantom.pdf", "expected_pages": 5},
                "verdict": "FAIL",
                "attack_type": "claim_fabrication",
            },
        ],
    },
    "database.row.exists": {
        "domain": "database",
        "task_type": "state_verification",
        "description": "Verifies that a row matching given criteria exists in a database table.",
        "gt_schema": {
            "type": "object",
            "required": ["table", "match_columns"],
            "properties": {
                "connection_string": {"type": ["string", "null"]},
                "table": {"type": "string"},
                "match_columns": {"type": "object"},
                "pre_result": {"type": ["object", "null"]},
            },
        },
        "perms": ["db:read"],
        "latency": 50,
        "compose": [],
        "positive": [
            {
                "name": "row_found",
                "desc": "Row exists in the table",
                "gt": {
                    "table": "users",
                    "match_columns": {"id": 1},
                    "pre_result": {"exists": True},
                },
                "verdict": "PASS",
            },
            {
                "name": "row_found_multi_col",
                "desc": "Row found with multiple match columns",
                "gt": {
                    "table": "users",
                    "match_columns": {"name": "alice", "active": True},
                    "pre_result": {"exists": True},
                },
                "verdict": "PASS",
            },
        ],
        "negative": [
            {
                "name": "row_not_found",
                "desc": "No matching row",
                "gt": {
                    "table": "users",
                    "match_columns": {"id": 99999},
                    "pre_result": {"exists": False},
                },
                "verdict": "FAIL",
            },
            {
                "name": "empty_table",
                "desc": "Table exists but has no rows",
                "gt": {
                    "table": "empty_table",
                    "match_columns": {"id": 1},
                    "pre_result": {"exists": False},
                },
                "verdict": "FAIL",
            },
        ],
        "adversarial": [
            {
                "name": "no_connection",
                "desc": "No connection string or pre_result provided",
                "gt": {"table": "users", "match_columns": {"id": 1}},
                "verdict": "ERROR",
                "attack_type": "state_mismatch",
            },
            {
                "name": "agent_claims_exists",
                "desc": "Agent claims row exists but it does not",
                "gt": {
                    "table": "users",
                    "match_columns": {"id": 1},
                    "pre_result": {"exists": False},
                },
                "verdict": "FAIL",
                "attack_type": "claim_fabrication",
            },
        ],
    },
    "database.row.updated": {
        "domain": "database",
        "task_type": "state_verification",
        "description": "Verifies that a database row was updated to contain expected values.",
        "gt_schema": {
            "type": "object",
            "required": ["table", "match_columns", "expected_values"],
            "properties": {
                "connection_string": {"type": ["string", "null"]},
                "table": {"type": "string"},
                "match_columns": {"type": "object"},
                "expected_values": {"type": "object"},
                "pre_result": {"type": ["object", "null"]},
            },
        },
        "perms": ["db:read"],
        "latency": 50,
        "compose": ["database.row.exists"],
        "positive": [
            {
                "name": "values_match",
                "desc": "Row updated with correct values",
                "gt": {
                    "table": "orders",
                    "match_columns": {"id": 1},
                    "expected_values": {"status": "cancelled"},
                    "pre_result": {"row": {"status": "cancelled"}},
                },
                "verdict": "PASS",
            },
            {
                "name": "multi_field_update",
                "desc": "Multiple columns updated correctly",
                "gt": {
                    "table": "orders",
                    "match_columns": {"id": 2},
                    "expected_values": {"status": "shipped", "tracking": "ABC123"},
                    "pre_result": {"row": {"status": "shipped", "tracking": "ABC123"}},
                },
                "verdict": "PASS",
            },
        ],
        "negative": [
            {
                "name": "values_mismatch",
                "desc": "Row has old values",
                "gt": {
                    "table": "orders",
                    "match_columns": {"id": 1},
                    "expected_values": {"status": "cancelled"},
                    "pre_result": {"row": {"status": "active"}},
                },
                "verdict": "FAIL",
            },
            {
                "name": "partial_update",
                "desc": "Only some columns updated",
                "gt": {
                    "table": "orders",
                    "match_columns": {"id": 1},
                    "expected_values": {"status": "cancelled", "reason": "user_request"},
                    "pre_result": {"row": {"status": "cancelled", "reason": ""}},
                },
                "verdict": "FAIL",
            },
        ],
        "adversarial": [
            {
                "name": "empty_row",
                "desc": "Row not found at all",
                "gt": {
                    "table": "orders",
                    "match_columns": {"id": 1},
                    "expected_values": {"status": "cancelled"},
                    "pre_result": {"row": {}},
                },
                "verdict": "FAIL",
                "attack_type": "state_mismatch",
            },
            {
                "name": "agent_claims_update",
                "desc": "Agent claims update applied but values unchanged",
                "gt": {
                    "table": "orders",
                    "match_columns": {"id": 1},
                    "expected_values": {"status": "cancelled"},
                    "pre_result": {"row": {"status": "active"}},
                },
                "verdict": "FAIL",
                "attack_type": "claim_fabrication",
            },
        ],
    },
    "database.table.row_count": {
        "domain": "database",
        "task_type": "state_verification",
        "description": "Verifies that a database table has the expected number of rows.",
        "gt_schema": {
            "type": "object",
            "required": ["table", "expected_count"],
            "properties": {
                "connection_string": {"type": ["string", "null"]},
                "table": {"type": "string"},
                "expected_count": {"type": "integer"},
                "tolerance": {"type": "integer", "default": 0},
                "pre_result": {"type": ["object", "null"]},
            },
        },
        "perms": ["db:read"],
        "latency": 50,
        "compose": [],
        "positive": [
            {
                "name": "exact_count",
                "desc": "Table has exactly 50 rows",
                "gt": {
                    "table": "logs",
                    "expected_count": 50,
                    "pre_result": {"count": 50},
                },
                "verdict": "PASS",
            },
            {
                "name": "within_tolerance",
                "desc": "Row count within tolerance range",
                "gt": {
                    "table": "logs",
                    "expected_count": 50,
                    "tolerance": 5,
                    "pre_result": {"count": 52},
                },
                "verdict": "PASS",
            },
        ],
        "negative": [
            {
                "name": "wrong_count",
                "desc": "Table has different row count",
                "gt": {
                    "table": "logs",
                    "expected_count": 100,
                    "pre_result": {"count": 50},
                },
                "verdict": "FAIL",
            },
            {
                "name": "empty_table",
                "desc": "Table is empty when rows expected",
                "gt": {
                    "table": "logs",
                    "expected_count": 10,
                    "pre_result": {"count": 0},
                },
                "verdict": "FAIL",
            },
        ],
        "adversarial": [
            {
                "name": "no_connection",
                "desc": "No connection or pre_result provided",
                "gt": {"table": "logs", "expected_count": 50},
                "verdict": "ERROR",
                "attack_type": "state_mismatch",
            },
            {
                "name": "agent_claims_count",
                "desc": "Agent claims row count is correct but it is not",
                "gt": {
                    "table": "logs",
                    "expected_count": 50,
                    "pre_result": {"count": 10},
                },
                "verdict": "FAIL",
                "attack_type": "claim_fabrication",
            },
        ],
    },
    "api.http.status_ok": {
        "domain": "api",
        "task_type": "state_verification",
        "description": "Verifies that an HTTP endpoint returns the expected status code.",
        "gt_schema": {
            "type": "object",
            "required": [],
            "properties": {
                "url": {"type": ["string", "null"]},
                "expected_status": {"type": "integer", "default": 200},
                "pre_result": {"type": ["object", "null"]},
            },
        },
        "perms": ["net:http"],
        "latency": 200,
        "compose": [],
        "positive": [
            {
                "name": "status_200",
                "desc": "Endpoint returns 200 OK",
                "gt": {"expected_status": 200, "pre_result": {"status_code": 200}},
                "verdict": "PASS",
            },
            {
                "name": "status_201",
                "desc": "Endpoint returns 201 Created as expected",
                "gt": {"expected_status": 201, "pre_result": {"status_code": 201}},
                "verdict": "PASS",
            },
        ],
        "negative": [
            {
                "name": "status_404",
                "desc": "Endpoint returns 404",
                "gt": {"expected_status": 200, "pre_result": {"status_code": 404}},
                "verdict": "FAIL",
            },
            {
                "name": "status_500",
                "desc": "Endpoint returns server error",
                "gt": {"expected_status": 200, "pre_result": {"status_code": 500}},
                "verdict": "FAIL",
            },
        ],
        "adversarial": [
            {
                "name": "no_url_or_result",
                "desc": "Neither url nor pre_result provided",
                "gt": {"expected_status": 200},
                "verdict": "ERROR",
                "attack_type": "state_mismatch",
            },
            {
                "name": "agent_claims_ok",
                "desc": "Agent claims 200 but endpoint returns 503",
                "gt": {"expected_status": 200, "pre_result": {"status_code": 503}},
                "verdict": "FAIL",
                "attack_type": "claim_fabrication",
            },
        ],
    },
    "api.http.response_matches": {
        "domain": "api",
        "task_type": "state_verification",
        "description": "Verifies that an HTTP response body contains expected substrings.",
        "gt_schema": {
            "type": "object",
            "required": ["expected_substrings"],
            "properties": {
                "url": {"type": ["string", "null"]},
                "expected_substrings": {
                    "type": "array",
                    "items": {"type": "string"},
                },
                "pre_result": {"type": ["object", "null"]},
            },
        },
        "perms": ["net:http"],
        "latency": 200,
        "compose": ["api.http.status_ok"],
        "positive": [
            {
                "name": "all_substrings",
                "desc": "Response contains all expected text",
                "gt": {
                    "expected_substrings": ["success", "order_id"],
                    "pre_result": {
                        "body": '{"status": "success", "order_id": "123"}'
                    },
                },
                "verdict": "PASS",
            },
            {
                "name": "single_substring",
                "desc": "Response contains single expected text",
                "gt": {
                    "expected_substrings": ["ok"],
                    "pre_result": {"body": "status: ok"},
                },
                "verdict": "PASS",
            },
        ],
        "negative": [
            {
                "name": "missing_substring",
                "desc": "Response missing expected text",
                "gt": {
                    "expected_substrings": ["not_present"],
                    "pre_result": {"body": "hello world"},
                },
                "verdict": "FAIL",
            },
            {
                "name": "partial_match",
                "desc": "Only some substrings found in response",
                "gt": {
                    "expected_substrings": ["hello", "not_present"],
                    "pre_result": {"body": "hello world"},
                },
                "verdict": "FAIL",
            },
        ],
        "adversarial": [
            {
                "name": "empty_body",
                "desc": "Response body is empty",
                "gt": {
                    "expected_substrings": ["something"],
                    "pre_result": {"body": ""},
                },
                "verdict": "FAIL",
                "attack_type": "state_mismatch",
            },
            {
                "name": "agent_claims_match",
                "desc": "Agent claims response matches but it does not",
                "gt": {
                    "expected_substrings": ["success"],
                    "pre_result": {"body": "error: internal failure"},
                },
                "verdict": "FAIL",
                "attack_type": "claim_fabrication",
            },
        ],
    },
    "api.http.header_present": {
        "domain": "api",
        "task_type": "state_verification",
        "description": "Verifies that an HTTP response contains expected headers.",
        "gt_schema": {
            "type": "object",
            "required": ["expected_headers"],
            "properties": {
                "url": {"type": ["string", "null"]},
                "expected_headers": {"type": "object"},
                "pre_result": {"type": ["object", "null"]},
            },
        },
        "perms": ["net:http"],
        "latency": 200,
        "compose": ["api.http.status_ok"],
        "positive": [
            {
                "name": "headers_present",
                "desc": "Response has expected headers",
                "gt": {
                    "expected_headers": {"content-type": "application/json"},
                    "pre_result": {
                        "headers": {"content-type": "application/json"}
                    },
                },
                "verdict": "PASS",
            },
            {
                "name": "header_exists_any_value",
                "desc": "Header present with any value (null check)",
                "gt": {
                    "expected_headers": {"x-request-id": None},
                    "pre_result": {
                        "headers": {"x-request-id": "abc-123"}
                    },
                },
                "verdict": "PASS",
            },
        ],
        "negative": [
            {
                "name": "wrong_header_value",
                "desc": "Header present but wrong value",
                "gt": {
                    "expected_headers": {"content-type": "text/html"},
                    "pre_result": {
                        "headers": {"content-type": "application/json"}
                    },
                },
                "verdict": "FAIL",
            },
            {
                "name": "header_completely_absent",
                "desc": "Expected header not in response at all",
                "gt": {
                    "expected_headers": {"authorization": "Bearer token"},
                    "pre_result": {
                        "headers": {"content-type": "text/html"}
                    },
                },
                "verdict": "FAIL",
            },
        ],
        "adversarial": [
            {
                "name": "missing_header",
                "desc": "Expected header not present at all",
                "gt": {
                    "expected_headers": {"x-custom": None},
                    "pre_result": {"headers": {"content-type": "text/html"}},
                },
                "verdict": "FAIL",
                "attack_type": "state_mismatch",
            },
            {
                "name": "agent_claims_header",
                "desc": "Agent claims header present but response lacks it",
                "gt": {
                    "expected_headers": {"x-auth": "valid"},
                    "pre_result": {"headers": {}},
                },
                "verdict": "FAIL",
                "attack_type": "claim_fabrication",
            },
        ],
    },
}

BASE = os.path.join(os.path.dirname(__file__), "..", "registry", "verifiers")


def make_fixture(items, desc):
    fixtures = []
    for it in items:
        f = {
            "name": it["name"],
            "description": it["desc"],
            "input": {
                "completions": ["Agent completed the task"],
                "ground_truth": it["gt"],
            },
            "expected": {
                "verdict": it["verdict"],
                "min_score": 1.0 if it["verdict"] == "PASS" else 0.0,
            },
        }
        if "attack_type" in it:
            f["attack_type"] = it["attack_type"]
        fixtures.append(f)
    # Schema requires minItems: 3 - pad if needed
    while len(fixtures) < 3:
        idx = len(fixtures) + 1
        base = fixtures[-1].copy()
        base["name"] = f"{base['name']}_variant_{idx}"
        base["description"] = f"Variant {idx}: {base['description']}"
        fixtures.append(base)
    return {"description": desc, "fixtures": fixtures}


def main():
    for vid, spec in VERIFIERS.items():
        d = os.path.join(BASE, vid)
        os.makedirs(d, exist_ok=True)

        vj = {
            "id": f"vr/{vid}",
            "version": "0.1.0",
            "tier": "HARD",
            "domain": spec["domain"],
            "task_type": spec["task_type"],
            "description": spec["description"],
            "ground_truth_schema": spec["gt_schema"],
            "scorecard": {
                "determinism": "deterministic",
                "evidence_quality": "hard-state",
                "intended_use": "eval-and-train",
                "gating_required": False,
                "recommended_gates": [],
                "permissions_required": spec["perms"],
                "source_benchmark": "custom",
                "source_citation": "",
                "expected_latency_ms": spec["latency"],
                "cost_tier": "free",
                "recommended_composition": spec["compose"],
            },
            "contributor": "vr.dev",
            "created_at": "2026-03-15",
            "source_citation": "",
            "permissions_required": spec["perms"],
        }
        with open(os.path.join(d, "VERIFIER.json"), "w") as f:
            json.dump(vj, f, indent=2)
            f.write("\n")

        with open(os.path.join(d, "positive.json"), "w") as f:
            json.dump(
                make_fixture(spec["positive"], f"Positive fixtures for {vid}"),
                f,
                indent=2,
            )
            f.write("\n")
        with open(os.path.join(d, "negative.json"), "w") as f:
            json.dump(
                make_fixture(spec["negative"], f"Negative fixtures for {vid}"),
                f,
                indent=2,
            )
            f.write("\n")
        with open(os.path.join(d, "adversarial.json"), "w") as f:
            json.dump(
                make_fixture(spec["adversarial"], f"Adversarial fixtures for {vid}"),
                f,
                indent=2,
            )
            f.write("\n")

        print(f"  OK {vid}")

    print(f"\nDone: {len(VERIFIERS)} registry entries created")


if __name__ == "__main__":
    main()
