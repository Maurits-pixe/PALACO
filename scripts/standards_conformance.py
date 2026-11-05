#!/usr/bin/env python3
"""GO-13: RIO + VisitCard + PALACO standards conformance gate (fail-closed).

Checks, in one run:
  1. Parser regression tests (duplicate JSON keys, Status metadata parser).
  2. Status + Last Updated metadata on every docs/standards/{rio,visitcard}/**/*.md.
  3. Non-empty, unique `$id` across docs/schemas/{rio,visitcard,palaco}/**/*.json.
  4. RIO fixtures valid against RIO-SCHEMA-BUNDLE-001 (Draft 2020-12 +
     FormatChecker), plus negative tests per definition.
  5. VisitCard + BeaconPayload fixtures valid against the VisitCard bundle,
     plus negative tests for required fields and structural disclosure bounds.
  6. PALACO canonical schemas and fixtures, with typed object/relationship
     contracts and negative tests, resolving references locally only.
  7. PCR-000 closed registry snapshots: unique IDs, resolved object references,
     owned relationships, consistency with dedicated reference fields, and
     acyclic dependency and upstream graphs (checked separately), and consistent
     lifecycle dates and approval state.
  8. Optional previous-registry comparison: retained identities, adjacent forward
     lifecycle transitions and monotonic audit timestamps.
  9. Read-only upstream/downstream trace queries on validated closed snapshots.
 10. Read-only object-type queries using the PMS-001 object family vocabulary.
 11. Read-only lineage orphan diagnostics for isolated upstream-graph nodes.
 12. Read-only control/VER verification-status diagnostics on validated snapshots.
 13. Read-only evidence audit-link diagnostics on validated snapshots.

Any failure exits non-zero.
"""

import argparse
import copy
import json
import re
import subprocess
import sys
import tempfile
from datetime import date, datetime, time, timezone
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker
from referencing import Registry, Resource

ROOT = Path(__file__).resolve().parents[1]
STANDARDS_DIRS = (
    ROOT / "docs/standards/rio",
    ROOT / "docs/standards/visitcard",
)
REQUIRED_DOC_FIELDS = ["Status", "Last Updated"]
RIO_SCHEMA_DIR = ROOT / "docs/schemas/rio"
RIO_BUNDLE = RIO_SCHEMA_DIR / "RIO-SCHEMA-BUNDLE-001.json"
RIO_FIXTURE_DIR = ROOT / "docs/fixtures/rio"
VISITCARD_SCHEMA_DIR = ROOT / "docs/schemas/visitcard"
VISITCARD_BUNDLE = VISITCARD_SCHEMA_DIR / "VISITCARD-SCHEMA-BUNDLE-001.json"
VISITCARD_FIXTURE_DIR = ROOT / "docs/fixtures/visitcard"
PALACO_SCHEMA_DIR = ROOT / "docs/schemas/palaco"
PALACO_FIXTURE_DIR = ROOT / "docs/fixtures/palaco"
DIALECT = "https://json-schema.org/draft/2020-12/schema"

FIXTURES = {
    "Conversation": "conversation.fixture.json",
    "Message": "message.fixture.json",
    "IntentAction": "intent_action.fixture.json",
}
VISITCARD_FIXTURES = {
    "VisitCard": "visitcard.fixture.json",
    "BeaconPayload": "beacon_payload.fixture.json",
}
VISITCARD_REQUIRED_FIELDS = {
    "VisitCard": (
        "identity_ref", "object_type", "introduction", "rio_endpoint",
        "watermerk_ref", "hologram_ref", "provenance", "validity",
        "presentation_hints", "discovery_methods",
    ),
    "BeaconPayload": ("P", "V", "T", "D", "E", "R"),
}

STATUS_HEADING_RE = re.compile(r" {0,3}#{1,6}[ \t]+status[ \t]*#*[ \t]*", re.IGNORECASE)
HEADING_RE = re.compile(r" {0,3}#{1,6}(?:[ \t]|$)")
FENCE_OPEN_RE = re.compile(r" {0,3}(`{3,}|~{3,})")


class ConformanceError(Exception):
    pass


def require(condition, message):
    if not condition:
        raise ConformanceError(message)


def rel(path):
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return str(path)


# --------------------------------------------------------------------------
# Strict JSON parsing
# --------------------------------------------------------------------------

def unique_keys(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ConformanceError(f"Duplicate JSON key: {key!r}")
        result[key] = value
    return result


def reject_constant(value):
    raise ConformanceError(f"Invalid JSON constant: {value}")


def parse_json(text):
    return json.loads(
        text,
        object_pairs_hook=unique_keys,
        parse_constant=reject_constant,
    )


def read_json(path):
    try:
        return parse_json(path.read_text(encoding="utf-8"))
    except (ConformanceError, ValueError) as error:
        raise ConformanceError(f"{rel(path)}: {error}") from error


# --------------------------------------------------------------------------
# Markdown standards metadata
# --------------------------------------------------------------------------

def strip_fenced_code(text):
    """Return lines outside fenced code blocks. Unclosed fences run to EOF."""
    kept = []
    fence = None
    for line in text.splitlines():
        if fence is None:
            match = FENCE_OPEN_RE.match(line)
            if match:
                fence = match.group(1)
                continue
            kept.append(line)
        else:
            stripped = line.strip()
            if (
                stripped
                and set(stripped) == {fence[0]}
                and len(stripped) >= len(fence)
                and len(line) - len(line.lstrip(" ")) <= 3
            ):
                fence = None
    return kept


def extract_status(text):
    """Return the single Status value; raise if missing, duplicate or empty."""
    lines = strip_fenced_code(text)
    headings = [i for i, line in enumerate(lines) if STATUS_HEADING_RE.fullmatch(line)]
    require(headings, "missing Status heading")
    require(len(headings) == 1, f"expected exactly one Status heading, found {len(headings)}")

    following = next(
        (line.strip() for line in lines[headings[0] + 1:] if line.strip()),
        "",
    )
    require(following, "Status heading has no value")
    require(
        not HEADING_RE.match(following) and not following.startswith("<!--"),
        f"Status heading has no value (next line: {following!r})",
    )
    return following


def check_metadata():
    count = 0
    for directory in STANDARDS_DIRS:
        files = sorted(directory.rglob("*.md"))
        require(files, f"No Markdown standards found in {rel(directory)}")
        for path in files:
            try:
                text = path.read_text(encoding="utf-8")
                status = extract_status(text)
                for field in REQUIRED_DOC_FIELDS:
                    require(field in text, f"missing required metadata {field!r}")
            except ConformanceError as error:
                raise ConformanceError(f"{rel(path)}: {error}") from error
            print(f"  ok {rel(path)} (Status: {status})")
            count += 1
    return f"Status + Last Updated metadata in {count} documents"


# --------------------------------------------------------------------------
# RIO + VisitCard + PALACO schema $id uniqueness
# --------------------------------------------------------------------------

def check_schema_ids():
    files = []
    for directory in (RIO_SCHEMA_DIR, VISITCARD_SCHEMA_DIR, PALACO_SCHEMA_DIR):
        schema_files = sorted(directory.rglob("*.json"))
        require(schema_files, f"No JSON schemas found in {rel(directory)}")
        files.extend(schema_files)
    seen = {}
    for path in files:
        schema = read_json(path)
        require(isinstance(schema, dict), f"{rel(path)}: schema must be a JSON object")
        sid = schema.get("$id")
        require(
            isinstance(sid, str) and sid.strip(),
            f"{rel(path)}: missing or empty $id",
        )
        require(sid == sid.strip(), f"{rel(path)}: $id has leading/trailing whitespace")
        if sid in seen:
            raise ConformanceError(
                f"Duplicate $id {sid!r} in {rel(path)} and {rel(seen[sid])}"
            )
        seen[sid] = path
        print(f"  ok {rel(path)} ($id: {sid})")
    return f"$id unique across {len(files)} RIO + VisitCard + PALACO schema file(s)"


# --------------------------------------------------------------------------
# RIO fixtures + negative tests
# --------------------------------------------------------------------------

def expect_rejection(validator, instance, keyword, label):
    keywords = {error.validator for error in validator.iter_errors(instance)}
    require(
        keyword in keywords,
        f"negative test not rejected via '{keyword}': {label} (got {sorted(keywords)})",
    )
    print(f"  ok rejected {label} ({keyword})")


def check_rio_fixtures():
    bundle = read_json(RIO_BUNDLE)
    require(isinstance(bundle, dict), "Schema bundle must be a JSON object")
    require(
        bundle.get("$schema", DIALECT) == DIALECT,
        "Unexpected $schema dialect in bundle; review GO-13 validator",
    )
    Draft202012Validator.check_schema(bundle)
    definitions = bundle.get("definitions")
    require(isinstance(definitions, dict), "Schema bundle has no definitions")

    for definition, filename in FIXTURES.items():
        require(definition in definitions, f"Missing definition: {definition}")
        selected = {**bundle, "$schema": DIALECT, "$ref": f"#/definitions/{definition}"}
        Draft202012Validator.check_schema(selected)
        validator = Draft202012Validator(selected, format_checker=FormatChecker())

        path = RIO_FIXTURE_DIR / filename
        require(path.is_file(), f"Missing fixture: {rel(path)}")
        instance = read_json(path)
        require(isinstance(instance, dict), f"{rel(path)}: fixture must be a JSON object")
        errors = sorted(validator.iter_errors(instance), key=lambda e: list(e.path))
        require(
            not errors,
            f"{rel(path)} invalid against {definition}: "
            + "; ".join(f"{list(e.path)}: {e.message}" for e in errors),
        )
        print(f"  ok {rel(path)} valid against {definition}")

        extra = copy.deepcopy(instance)
        require("_go13_extra" not in extra, f"{rel(path)}: reserved test field present")
        extra["_go13_extra"] = True
        expect_rejection(validator, extra, "additionalProperties", f"{definition}: extra property")

        required = definitions[definition].get("required", [])
        require(required, f"{definition}: no required fields declared")
        for field in required:
            missing = copy.deepcopy(instance)
            missing.pop(field, None)
            expect_rejection(validator, missing, "required", f"{definition}: missing {field}")

        require("created_at" in instance, f"{rel(path)}: fixture lacks created_at")
        bad_timestamp = copy.deepcopy(instance)
        bad_timestamp["created_at"] = "not-a-timestamp"
        expect_rejection(validator, bad_timestamp, "format", f"{definition}: invalid created_at")

        if "state" in instance:
            bad_state = copy.deepcopy(instance)
            bad_state["state"] = "GO13_INVALID_STATE"
            expect_rejection(validator, bad_state, "enum", f"{definition}: invalid state")

    return f"RIO fixtures valid + negative tests for {len(FIXTURES)} definitions"


# --------------------------------------------------------------------------
# VisitCard fixtures + structural boundary tests
# --------------------------------------------------------------------------

def check_visitcard_fixtures():
    bundle = read_json(VISITCARD_BUNDLE)
    require(isinstance(bundle, dict), "VisitCard bundle must be a JSON object")
    require(bundle.get("$schema") == DIALECT, "Unexpected VisitCard $schema dialect")
    Draft202012Validator.check_schema(bundle)
    definitions = bundle.get("definitions")
    require(isinstance(definitions, dict), "VisitCard bundle has no definitions")
    root_validator = Draft202012Validator(bundle, format_checker=FormatChecker())
    validators = {}
    instances = {}
    negative_count = 0

    def reject(validator, instance, keyword, label):
        nonlocal negative_count
        expect_rejection(validator, instance, keyword, label)
        negative_count += 1

    for definition, filename in VISITCARD_FIXTURES.items():
        require(definition in definitions, f"Missing VisitCard definition: {definition}")
        selected = {**bundle, "$ref": f"#/definitions/{definition}"}
        Draft202012Validator.check_schema(selected)
        validator = Draft202012Validator(selected, format_checker=FormatChecker())
        path = VISITCARD_FIXTURE_DIR / filename
        require(path.is_file(), f"Missing fixture: {rel(path)}")
        instance = read_json(path)
        require(isinstance(instance, dict), f"{rel(path)}: fixture must be a JSON object")
        errors = sorted(validator.iter_errors(instance), key=lambda e: tuple(map(str, e.path)))
        require(
            not errors,
            f"{rel(path)} invalid against {definition}: "
            + "; ".join(f"{list(e.path)}: {e.message}" for e in errors),
        )
        require(root_validator.is_valid(instance), f"{rel(path)} invalid against bundle root")
        validators[definition] = validator
        instances[definition] = instance
        print(f"  ok {rel(path)} valid against {definition} and bundle root")

        extra = copy.deepcopy(instance)
        require("_go13_extra" not in extra, f"{rel(path)}: reserved test field present")
        extra["_go13_extra"] = True
        reject(validator, extra, "additionalProperties", f"{definition}: extra property")
        required = VISITCARD_REQUIRED_FIELDS[definition]
        for field in required:
            missing = copy.deepcopy(instance)
            missing.pop(field, None)
            reject(validator, missing, "required", f"{definition}: missing {field}")
            wrong_type = copy.deepcopy(instance)
            wrong_type[field] = None
            reject(validator, wrong_type, "type", f"{definition}: null {field}")

    card = instances["VisitCard"]
    card_validator = validators["VisitCard"]
    card_cases = (
        ("invalid identity namespace", ("identity_ref",), "person.demo", "pattern"),
        ("unknown validity", ("validity",), "AUTHORIZED", "enum"),
        ("invalid RIO endpoint", ("rio_endpoint",), "not-a-uri", "format"),
        ("empty introduction", ("introduction",), "", "minLength"),
        ("unknown discovery method", ("discovery_methods",), ["UNKNOWN"], "enum"),
        ("empty discovery methods", ("discovery_methods",), [], "minItems"),
        ("duplicate discovery methods", ("discovery_methods",), ["QR", "QR"], "uniqueItems"),
        ("missing origin evidence", ("provenance", "evidence_refs"), [], "minItems"),
        ("empty evidence reference", ("provenance", "evidence_refs"), [""], "minLength"),
        ("unknown origin surface", ("provenance", "origin_surface"), "trusted", "enum"),
        ("invalid origin endpoint", ("provenance", "origin_endpoint"), "not-a-uri", "format"),
        ("empty presentation label", ("presentation_hints", "display_name"), "", "minLength"),
    )
    for label, path, value, keyword in card_cases:
        invalid = copy.deepcopy(card)
        target = invalid
        for component in path[:-1]:
            target = target[component]
        target[path[-1]] = value
        reject(card_validator, invalid, keyword, f"VisitCard: {label}")

    for parent, field in (
        ("provenance", "origin_surface"),
        ("provenance", "origin_endpoint"),
        ("provenance", "evidence_refs"),
        ("presentation_hints", "display_name"),
    ):
        invalid = copy.deepcopy(card)
        invalid[parent].pop(field, None)
        reject(card_validator, invalid, "required", f"VisitCard: missing {parent}.{field}")

    for parent in ("provenance", "presentation_hints"):
        invalid = copy.deepcopy(card)
        invalid[parent]["authorization"] = {"grant": True}
        reject(card_validator, invalid, "additionalProperties", f"VisitCard: {parent} authority field")

    for state in ("EXPIRED", "REVOKED"):
        variant = copy.deepcopy(card)
        variant["validity"] = state
        require(card_validator.is_valid(variant), f"VisitCard: declared validity {state} rejected")
        print(f"  ok VisitCard {state} is structural data, not an authorization decision")

    beacon = instances["BeaconPayload"]
    beacon_validator = validators["BeaconPayload"]
    for field, value in (
        ("identity_profile", {"name": "Demo"}),
        ("contact_data", {"email": "demo@example.invalid"}),
        ("visitcard", card),
        ("authorization", {"grant": True}),
    ):
        invalid = copy.deepcopy(beacon)
        invalid[field] = value
        reject(beacon_validator, invalid, "additionalProperties", f"BeaconPayload: forbidden {field}")
    for field in ("V", "T", "D", "E"):
        invalid = copy.deepcopy(beacon)
        invalid[field] = ""
        reject(beacon_validator, invalid, "minLength", f"BeaconPayload: empty {field}")
    invalid = copy.deepcopy(beacon)
    invalid["P"] = "OTHER"
    reject(beacon_validator, invalid, "const", "BeaconPayload: invalid protocol family")
    invalid = copy.deepcopy(beacon)
    invalid["R"] = "not-a-uri"
    reject(beacon_validator, invalid, "format", "BeaconPayload: invalid resolver endpoint")

    reject(root_validator, {}, "oneOf", "VisitCard bundle: unmatched empty object")
    reject(root_validator, "PALACO", "type", "VisitCard bundle: non-object payload")
    return (
        f"VisitCard fixtures valid + {negative_count} negative tests "
        f"for {len(VISITCARD_FIXTURES)} definitions"
    )

# --------------------------------------------------------------------------
# PALACO canonical fixtures + structural boundary tests
# --------------------------------------------------------------------------

def palaco_validators():
    schemas = {}
    for filename in ("PMS-001.schema.json", "PMS-002.schema.json", "PCR-000.schema.json"):
        schema = read_json(PALACO_SCHEMA_DIR / filename)
        require(schema.get("$schema") == DIALECT, f"{filename}: unexpected dialect")
        Draft202012Validator.check_schema(schema)
        schemas[filename] = schema
    registry = Registry().with_resources(
        (schema["$id"], Resource.from_contents(schema)) for schema in schemas.values()
    )
    return {
        filename: Draft202012Validator(schema, registry=registry, format_checker=FormatChecker())
        for filename, schema in schemas.items()
    }


def check_palaco_fixtures():
    validators = palaco_validators()
    validator = validators["PMS-001.schema.json"]
    edge_validator = validators["PMS-002.schema.json"]
    bundle = validator.schema
    instances = {}
    negative_count = 0

    def reject(instance, keyword, label, selected=validator):
        nonlocal negative_count
        expect_rejection(selected, instance, keyword, label)
        negative_count += 1

    for family in ("FE", "ADR", "SVC", "COM", "REQ"):
        path = PALACO_FIXTURE_DIR / f"{family}-00001.fixture.json"
        instance = read_json(path)
        errors = list(validator.iter_errors(instance))
        require(not errors, f"{rel(path)}: " + "; ".join(error.message for error in errors))
        require(instance["object_type"] == family, f"{rel(path)}: wrong object_type")
        instances[family] = instance
        print(f"  ok {rel(path)} valid against PMS-001")

        for field in bundle["required"]:
            invalid = copy.deepcopy(instance)
            del invalid[field]
            reject(invalid, "required", f"{family}: missing {field}")
        invalid = copy.deepcopy(instance)
        invalid["_go13_extra"] = True
        reject(invalid, "additionalProperties", f"{family}: extra property")

    special_fields = {
        "ADR": ("decision", "context", "consequences", "approved_by", "architecture_ref"),
        "SVC": ("requirement_refs", "architecture_ref", "repository", "runtime",
                "service_level", "dependencies", "observability"),
        "COM": ("control_type", "risk", "evidence"),
        "REQ": ("capability_ref", "acceptance_criteria"),
    }
    for family, fields in special_fields.items():
        for field in fields:
            invalid = copy.deepcopy(instances[family])
            del invalid[field]
            reject(invalid, "required", f"{family}: missing specialization {field}")

    for block in ("metadata", "ownership", "lifecycle", "approval", "classification",
                  "traceability", "verification", "audit", "repository", "runtime",
                  "service_level", "observability"):
        instance = instances["SVC"]
        definition = bundle["properties"][block].get("$ref")
        contract = bundle["$defs"][definition.rsplit("/", 1)[1]] if definition else bundle["properties"][block]
        for field in contract["required"]:
            invalid = copy.deepcopy(instance)
            del invalid[block][field]
            reject(invalid, "required", f"SVC: missing {block}.{field}")
        invalid = copy.deepcopy(instance)
        invalid[block]["_go13_extra"] = True
        reject(invalid, "additionalProperties", f"SVC: extra {block} property")

    families = (
        "FE", "PDP", "PCS", "GOV", "CAP", "DOM", "OBJ", "POL", "RSK", "REQ",
        "ARC", "ADR", "INT", "DAT", "APP", "SVC", "API", "MOD", "REP", "CFG",
        "COM", "VER", "TST", "EVD", "AUD", "RUN", "MON", "EVT", "INC", "CHG",
    )
    require(set(bundle["properties"]["object_type"]["enum"]) == set(families),
            "PMS-001: unexpected object family vocabulary")
    for family in families:
        instance = copy.deepcopy(instances.get(family, instances["FE"]))
        instance["object_type"] = family
        instance["metadata"]["id"] = f"{family}-00001"
        if family == "AUD":
            invalid = copy.deepcopy(instance)
            reject(invalid, "required", "AUD: missing evidence")
            instance["evidence"] = ["EVD-00001"]
            invalid = copy.deepcopy(instance)
            invalid["evidence"] = []
            reject(invalid, "minItems", "AUD: empty evidence")
        require(validator.is_valid(instance), f"PMS-001: valid {family} rejected")
        instance["metadata"]["id"] = "SVC-00001" if family == "FE" else "FE-00001"
        reject(instance, "oneOf", f"{family}: mismatched identifier prefix")

    mutations = (
        ("FE", ("object_type",), "UNKNOWN", "enum"),
        ("FE", ("metadata", "id"), "FE-001", "pattern"),
        ("FE", ("metadata", "id"), "FE-000001", "pattern"),
        ("FE", ("metadata", "id"), "FE-00001\n", "pattern"),
        ("FE", ("metadata", "id"), "XYZ-00001", "pattern"),
        ("FE", ("metadata", "name"), "   ", "pattern"),
        ("FE", ("metadata", "version"), "latest", "pattern"),
        ("FE", ("ownership", "business"), "", "minLength"),
        ("FE", ("lifecycle", "status"), "Unknown", "enum"),
        ("FE", ("lifecycle", "created"), "2026-02-30", "format"),
        ("FE", ("lifecycle", "next_review"), "tomorrow", "format"),
        ("FE", ("approval", "status"), "Approved", "required"),
        ("FE", ("classification", "confidentiality"), "Unknown", "enum"),
        ("FE", ("traceability", "upstream"), ["CAP-00001", "CAP-00001"], "uniqueItems"),
        ("FE", ("audit", "updated_at"), "not-a-timestamp", "format"),
        ("FE", ("audit", "audit_refs"), ["REQ-00001"], "pattern"),
        ("ADR", ("architecture_ref",), "REQ-00001", "pattern"),
        ("ADR", ("approved_by",), "APP-00001", "pattern"),
        ("SVC", ("requirement_refs",), [], "minItems"),
        ("SVC", ("requirement_refs",), ["CAP-00001"], "pattern"),
        ("SVC", ("repository", "repository_url"), "not-a-uri", "format"),
        ("SVC", ("repository", "repository_ref"), "APP-00001", "pattern"),
        ("SVC", ("runtime", "runtime_ref"), "APP-00001", "pattern"),
        ("SVC", ("runtime", "environment"), "Unknown", "enum"),
        ("SVC", ("service_level", "availability_target"), -1, "minimum"),
        ("SVC", ("service_level", "availability_target"), 101, "maximum"),
        ("SVC", ("service_level", "recovery_target"), "four hours", "pattern"),
        ("SVC", ("observability", "logging"), "yes", "type"),
        ("COM", ("risk",), "REQ-00001", "pattern"),
        ("COM", ("verification", "verification_ref"), "TST-00001", "pattern"),
        ("COM", ("evidence",), [], "minItems"),
        ("COM", ("evidence",), ["VER-00001"], "pattern"),
        ("REQ", ("capability_ref",), "OBJ-00001", "pattern"),
        ("REQ", ("acceptance_criteria",), [], "minItems"),
    )
    for family, path, value, keyword in mutations:
        invalid = copy.deepcopy(instances[family])
        target = invalid
        for field in path[:-1]:
            target = target[field]
        target[path[-1]] = value
        reject(invalid, keyword, f"{family}: invalid {'.'.join(path)}")
    invalid = copy.deepcopy(instances["COM"])
    del invalid["verification"]["verification_ref"]
    reject(invalid, "required", "COM: missing verification reference")

    approved = copy.deepcopy(instances["FE"])
    approved["approval"] = {
        "status": "Approved",
        "authority": "Example governance team",
        "approval_ref": "example-approval-001",
    }
    require(validator.is_valid(approved), "PMS-001: complete approval rejected")
    for field in ("authority", "approval_ref"):
        invalid = copy.deepcopy(approved)
        del invalid["approval"][field]
        reject(invalid, "required", f"PMS-001: approved without {field}")

    for state in bundle["$defs"]["Lifecycle"]["properties"]["status"]["enum"]:
        instance = copy.deepcopy(instances["FE"])
        instance["lifecycle"]["status"] = state
        require(validator.is_valid(instance), f"PMS-001: declared lifecycle state {state} rejected")

    edges = (
        ("IMPLEMENTS", "APP", "REQ"), ("IMPLEMENTS", "SVC", "REQ"),
        ("REALIZES", "SVC", "CAP"), ("SATISFIES", "REQ", "OBJ"),
        ("CONSTRAINED_BY", "APP", "POL"), ("DEFINED_BY", "APP", "ARC"),
        ("DEFINED_BY", "SVC", "ARC"), ("DEFINED_BY", "ADR", "ARC"),
        ("APPROVED_BY", "ADR", "GOV"), ("VERIFIED_BY", "COM", "VER"),
        ("PROVEN_BY", "VER", "EVD"), ("AUDITED_BY", "EVD", "AUD"),
        ("DEPENDS_ON", "FE", "CHG"),
    )
    for relation, source, target in edges:
        edge = {"source": f"{source}-00001", "relation": relation, "target": f"{target}-00001"}
        require(edge_validator.is_valid(edge), f"PMS-002: valid {relation} rejected")
        for field in ("source", "target"):
            invalid = {**edge, field: "FE-00001" if relation != "DEPENDS_ON" else "UNKNOWN-00001"}
            reject(invalid, "oneOf" if relation != "DEPENDS_ON" else "pattern",
                   f"{relation}: invalid {field} type", edge_validator)
        for field in ("source", "relation", "target"):
            invalid = dict(edge)
            del invalid[field]
            reject(invalid, "required", f"{relation}: missing {field}", edge_validator)
    edge = {"source": "APP-00001", "relation": "UNKNOWN", "target": "REQ-00001"}
    reject(edge, "enum", "PMS-002: unknown relation", edge_validator)
    edge["relation"] = "IMPLEMENTS"
    edge["_go13_extra"] = True
    reject(edge, "additionalProperties", "PMS-002: extra property", edge_validator)
    invalid = copy.deepcopy(instances["FE"])
    invalid["traceability"]["relationships"] = [
        {"source": "APP-00001", "relation": "IMPLEMENTS", "target": "CAP-00001"}
    ]
    reject(invalid, "oneOf", "PMS-001: invalid embedded relationship")
    return f"PALACO: 2 schemas, 5 fixtures, 30 object families + {negative_count} negative tests"


# --------------------------------------------------------------------------
# Closed PALACO registry integrity
# --------------------------------------------------------------------------

OBJECT_REFERENCE_FIELDS = (
    ("risk",), ("approved_by",), ("architecture_ref",), ("capability_ref",),
    ("requirement_refs",), ("dependencies",), ("evidence",), ("compliance",),
    ("traceability", "upstream"), ("verification", "verification_ref"),
    ("audit", "audit_refs"), ("repository", "repository_ref"),
    ("runtime", "runtime_ref"),
)
RELATION_REFERENCE_FIELDS = {
    "IMPLEMENTS": ("requirement_refs",),
    "REALIZES": ("capability_ref",),
    "DEFINED_BY": ("architecture_ref",),
    "APPROVED_BY": ("approved_by",),
    "VERIFIED_BY": ("verification", "verification_ref"),
    "PROVEN_BY": ("evidence",),
    "AUDITED_BY": ("audit", "audit_refs"),
    "DEPENDS_ON": ("dependencies",),
}


def reference_value(record, path):
    value = record
    for field in path:
        if field not in value:
            return None
        value = value[field]
    return value


def direct_dependency_targets(record):
    """Extract dependency targets from a structurally validated record."""
    return set(record.get("dependencies", [])) | {
        edge["target"] for edge in record["traceability"]["relationships"]
        if edge["relation"] == "DEPENDS_ON"
    }


def direct_upstream_targets(record):
    """Extract upstream targets from a structurally validated record."""
    return set(record["traceability"]["upstream"])


def weak_components(graph, object_id=None):
    """Return sorted weak components, optionally only for a known object ID."""
    neighbors = {source: set(targets) for source, targets in graph.items()}
    for source, targets in graph.items():
        for target in targets:
            neighbors[target].add(source)
    remaining = set(graph)
    components = []
    roots = (object_id,) if object_id is not None else graph
    for root in roots:
        if root not in remaining:
            continue
        remaining.remove(root)
        members = {root}
        pending = [root]
        while pending:
            unseen = neighbors[pending.pop()] & remaining
            members.update(unseen)
            remaining.difference_update(unseen)
            pending.extend(unseen)
        components.append(sorted(members))
    return sorted(components)


def weak_component_sizes(graph):
    """Return sorted undirected component sizes of a validated closed graph."""
    return sorted(len(component) for component in weak_components(graph))


def count_weak_components(graph):
    """Count undirected components of a validated closed graph, including isolates."""
    return len(weak_component_sizes(graph))


def require_acyclic(graph, label):
    """Iterative depth-first traversal; shared ancestors are not cycles."""
    finished = set()
    active = {}
    path = []
    for root in graph:
        if root in finished:
            continue
        active[root] = 0
        path.append(root)
        stack = [iter(sorted(graph[root]))]
        while stack:
            target = next(stack[-1], None)
            if target is None:
                stack.pop()
                completed = path.pop()
                finished.add(completed)
                del active[completed]
            elif target in active:
                cycle = path[active[target]:] + [target]
                raise ConformanceError(f"{label} cycle: {' -> '.join(cycle)}")
            elif target not in finished:
                active[target] = len(path)
                path.append(target)
                stack.append(iter(sorted(graph[target])))


def audit_instant(record):
    return datetime.fromisoformat(record["audit"]["updated_at"].upper().replace("Z", "+00:00"))


def validate_registry_lifecycle(record):
    """Check a snapshot, not transition history or approval authority."""
    object_id = record["metadata"]["id"]
    lifecycle = record["lifecycle"]
    created = date.fromisoformat(lifecycle["created"])
    next_review = date.fromisoformat(lifecycle["next_review"])
    # Lifecycle dates are calendar dates in UTC for comparison with audit instants.
    updated = audit_instant(record)
    require(created <= next_review,
            f"{object_id}: lifecycle.next_review precedes lifecycle.created")
    require(updated >= datetime.combine(created, time.min, timezone.utc),
            f"{object_id}: audit.updated_at precedes lifecycle.created (UTC)")
    approved = lifecycle.get("approved")
    if approved is not None:
        approved_date = date.fromisoformat(approved)
        require(created <= approved_date,
                f"{object_id}: lifecycle.approved precedes lifecycle.created")
        require(approved_date <= next_review,
                f"{object_id}: lifecycle.next_review precedes lifecycle.approved")
        require(updated >= datetime.combine(approved_date, time.min, timezone.utc),
                f"{object_id}: audit.updated_at precedes lifecycle.approved (UTC)")
    if record["approval"]["status"] == "Approved":
        require(approved is not None,
                f"{object_id}: approved approval requires lifecycle.approved")
    if lifecycle["status"] in ("Approved", "Active", "Deprecated", "Retired", "Archived"):
        require(record["approval"]["status"] == "Approved",
                f"{object_id}: lifecycle status {lifecycle['status']} requires approval.status Approved")


def validate_palaco_registry(instance, validator=None):
    """Validate a closed snapshot without fetching resources or granting authority."""
    if validator is None:
        validator = palaco_validators()["PCR-000.schema.json"]
    error = next(validator.iter_errors(instance), None)
    if error is not None:
        location = "/".join(map(str, error.absolute_path)) or "<root>"
        raise ConformanceError(f"registry structure at {location}: {error.message}")

    objects = {}
    for record in instance["objects"]:
        object_id = record["metadata"]["id"]
        require(object_id not in objects, f"duplicate object ID: {object_id}")
        objects[object_id] = record

    def check_reference(owner, target, field):
        require(target in objects, f"{owner}: unresolved {field}: {target}")
        require(target != owner, f"{owner}: self reference in {field}")

    for object_id, record in objects.items():
        validate_registry_lifecycle(record)
        for path in OBJECT_REFERENCE_FIELDS:
            value = reference_value(record, path)
            if value is not None:
                targets = value if isinstance(value, list) else [value]
                for target in targets:
                    check_reference(object_id, target, ".".join(path))
        for edge in record["traceability"]["relationships"]:
            require(edge["source"] == object_id,
                    f"{object_id}: relationship source must equal owning object ID")
            check_reference(object_id, edge["target"], f"{edge['relation']} target")
            path = RELATION_REFERENCE_FIELDS.get(edge["relation"])
            if path is not None:
                value = reference_value(record, path)
                if value is not None:
                    targets = value if isinstance(value, list) else [value]
                    require(edge["target"] in targets,
                            f"{object_id}: {edge['relation']} conflicts with {'.'.join(path)}")
    dependencies = {
        object_id: direct_dependency_targets(record)
        for object_id, record in objects.items()
    }
    upstream = {
        object_id: direct_upstream_targets(record)
        for object_id, record in objects.items()
    }
    require_acyclic(dependencies, "dependency")
    require_acyclic(upstream, "upstream")
    return f"closed PALACO registry valid ({len(objects)} objects); not a canonical-status decision"


LIFECYCLE_SEQUENCE = (
    "Proposed", "Draft", "Review", "Approved", "Active", "Deprecated", "Retired", "Archived",
)


def validate_registry_transition(previous, current, validator=None):
    """Compare consecutive supplied snapshots; neither input is trusted history."""
    if validator is None:
        validator = palaco_validators()["PCR-000.schema.json"]
    for label, instance in (("previous", previous), ("current", current)):
        try:
            validate_palaco_registry(instance, validator)
        except ConformanceError as error:
            raise ConformanceError(f"{label} registry: {error}") from error
    before = {record["metadata"]["id"]: record for record in previous["objects"]}
    after = {record["metadata"]["id"]: record for record in current["objects"]}
    removed = sorted(before.keys() - after.keys())
    require(not removed, f"registry transition removes object IDs: {', '.join(removed)}; retire/archive instead")
    for object_id, old in before.items():
        new = after[object_id]
        require(old["lifecycle"]["created"] == new["lifecycle"]["created"],
                f"{object_id}: lifecycle.created is immutable across snapshots")
        old_state = old["lifecycle"]["status"]
        new_state = new["lifecycle"]["status"]
        old_index = LIFECYCLE_SEQUENCE.index(old_state)
        require(new_state == old_state or (
            old_index + 1 < len(LIFECYCLE_SEQUENCE) and new_state == LIFECYCLE_SEQUENCE[old_index + 1]
        ), f"{object_id}: invalid lifecycle transition {old_state} -> {new_state}")
        old_updated = audit_instant(old)
        new_updated = audit_instant(new)
        require(new_updated >= old_updated,
                f"{object_id}: audit.updated_at moves backwards across snapshots")
        require(old == new or new_updated > old_updated,
                f"{object_id}: changed record requires a later audit.updated_at")
    return (
        f"registry transition valid ({len(before)} retained, {len(after) - len(before)} added); "
        "not authenticated history or a canonical-status decision"
    )


def trace_palaco_registry(instance, object_id, direction="upstream", validator=None):
    """Return reachable IDs in the upstream graph, not authority or completeness."""
    require(direction in ("upstream", "downstream"), f"invalid trace direction: {direction}")
    validate_palaco_registry(instance, validator)
    graph = {
        record["metadata"]["id"]: direct_upstream_targets(record)
        for record in instance["objects"]
    }
    require(object_id in graph, f"unknown trace object ID: {object_id}")
    if direction == "downstream":
        reverse = {source: set() for source in graph}
        for source, targets in graph.items():
            for target in targets:
                reverse[target].add(source)
        graph = reverse
    visited = {object_id}
    pending = [object_id]
    while pending:
        for target in graph[pending.pop()]:
            if target not in visited:
                visited.add(target)
                pending.append(target)
    return {
        "object_id": object_id,
        "direction": direction,
        "graph": "traceability.upstream",
        "reachable_ids": sorted(visited - {object_id}),
        "scope": "supplied snapshot only; not a completeness or authority decision",
    }


def diff_palaco_registry(previous, current, validator=None):
    """Describe snapshot differences, without enforcing or authorizing transitions."""
    if validator is None:
        validator = palaco_validators()["PCR-000.schema.json"]
    for label, instance in (("previous", previous), ("current", current)):
        try:
            validate_palaco_registry(instance, validator)
        except ConformanceError as error:
            raise ConformanceError(f"{label} registry: {error}") from error
    before = {record["metadata"]["id"]: record for record in previous["objects"]}
    after = {record["metadata"]["id"]: record for record in current["objects"]}
    shared = before.keys() & after.keys()
    return {
        "added_ids": sorted(after.keys() - before.keys()),
        "removed_ids": sorted(before.keys() - after.keys()),
        "changed_ids": sorted(object_id for object_id in shared if before[object_id] != after[object_id]),
        "unchanged_ids": sorted(object_id for object_id in shared if before[object_id] == after[object_id]),
        "scope": "supplied snapshots only; diagnostic, not transition validation, authenticated history or authority",
    }


def find_palaco_objects(instance, object_type, validators=None):
    """Filter a validated snapshot by exact object_type, returning IDs only."""
    if validators is None:
        validators = palaco_validators()
    families = validators["PMS-001.schema.json"].schema["properties"]["object_type"]["enum"]
    require(object_type in families, f"unknown PALACO object type: {object_type}")
    validate_palaco_registry(instance, validators["PCR-000.schema.json"])
    return {
        "object_type": object_type,
        "object_ids": sorted(
            record["metadata"]["id"] for record in instance["objects"]
            if record["object_type"] == object_type
        ),
        "scope": "supplied snapshot only; not a completeness or authority decision",
    }


def find_palaco_components(instance, graph_name, validator=None, object_id=None):
    """List snapshot clusters without inferring missing links or authority."""
    require(graph_name in ("upstream", "dependency"), f"unknown component graph: {graph_name}")
    validate_palaco_registry(instance, validator)
    extract = direct_upstream_targets if graph_name == "upstream" else direct_dependency_targets
    graph = {
        record["metadata"]["id"]: extract(record) for record in instance["objects"]
    }
    if object_id is not None:
        require(object_id in graph, f"unknown component object ID: {object_id}")
    components = weak_components(graph, object_id)
    return {
        "graph": "traceability.upstream" if graph_name == "upstream" else "dependencies + DEPENDS_ON",
        "definition": "weakly connected components; edge direction ignored; isolates included",
        "components": components,
        "scope": "supplied snapshot only; diagnostic, not completeness, canonical status or authority",
    }


def find_palaco_orphans(instance, validator=None):
    """Find isolated upstream-graph nodes, not invalid or non-canonical records."""
    validate_palaco_registry(instance, validator)
    connected = set()
    object_ids = set()
    for record in instance["objects"]:
        object_id = record["metadata"]["id"]
        object_ids.add(object_id)
        upstream = direct_upstream_targets(record)
        if upstream:
            connected.add(object_id)
            connected.update(upstream)
    return {
        "graph": "traceability.upstream",
        "definition": "no incoming or outgoing upstream edges",
        "object_ids": sorted(object_ids - connected),
        "scope": "supplied snapshot only; diagnostic, not a canonical-status or authority decision",
    }


def find_palaco_dependency_orphans(instance, validator=None):
    """Find isolated dependency nodes, not missing required dependencies."""
    validate_palaco_registry(instance, validator)
    connected = set()
    object_ids = set()
    for record in instance["objects"]:
        object_id = record["metadata"]["id"]
        object_ids.add(object_id)
        targets = direct_dependency_targets(record)
        if targets:
            connected.add(object_id)
            connected.update(targets)
    return {
        "graph": "dependencies + DEPENDS_ON",
        "definition": "no incoming or outgoing dependency edges",
        "object_ids": sorted(object_ids - connected),
        "scope": "supplied snapshot only; diagnostic, not a canonical-status or authority decision",
    }


def find_palaco_lifecycle(instance, status, validators=None):
    """Filter recorded lifecycle metadata, not actual approval or activation."""
    if validators is None:
        validators = palaco_validators()
    statuses = validators["PMS-001.schema.json"].schema["$defs"]["Lifecycle"]["properties"]["status"]["enum"]
    require(status in statuses, f"unknown PALACO lifecycle status: {status}")
    validate_palaco_registry(instance, validators["PCR-000.schema.json"])
    return {
        "lifecycle_status": status,
        "object_ids": sorted(
            record["metadata"]["id"] for record in instance["objects"]
            if record["lifecycle"]["status"] == status
        ),
        "scope": "supplied lifecycle metadata only; not proof of approval, activation or authority",
    }


def find_palaco_domain(instance, domain, validator=None):
    """Match exact domain metadata; domains are not canonical object families."""
    require(isinstance(domain, str) and re.search(r"\S", domain),
            "domain must be a non-empty string containing non-whitespace text")
    validate_palaco_registry(instance, validator)
    return {
        "domain": domain,
        "object_ids": sorted(
            record["metadata"]["id"] for record in instance["objects"]
            if record["metadata"]["domain"] == domain
        ),
        "scope": "supplied domain metadata only; not a completeness, canonical-status or authority decision",
    }


def find_palaco_verification(instance, status, validators=None):
    """Filter each record's own status metadata, not referenced verification results."""
    if validators is None:
        validators = palaco_validators()
    statuses = validators["PMS-001.schema.json"].schema["$defs"]["Verification"]["properties"]["status"]["enum"]
    require(status in statuses, f"unknown PALACO verification status: {status}")
    validate_palaco_registry(instance, validators["PCR-000.schema.json"])
    return {
        "verification_status": status,
        "object_ids": sorted(
            record["metadata"]["id"] for record in instance["objects"]
            if record["verification"]["status"] == status
        ),
        "scope": "supplied verification-status metadata only; not proof of verification, compliance or authority",
    }


def find_palaco_approval(instance, status, validators=None):
    """Filter recorded approval metadata, not authenticity or authorization."""
    if validators is None:
        validators = palaco_validators()
    statuses = validators["PMS-001.schema.json"].schema["$defs"]["Approval"]["properties"]["status"]["enum"]
    require(status in statuses, f"unknown PALACO approval status: {status}")
    validate_palaco_registry(instance, validators["PCR-000.schema.json"])
    return {
        "approval_status": status,
        "object_ids": sorted(
            record["metadata"]["id"] for record in instance["objects"]
            if record["approval"]["status"] == status
        ),
        "scope": "supplied approval-status metadata only; not proof of approval authenticity, activation or authority",
    }


def find_palaco_owner(instance, role, owner, validators=None):
    """Match assigned ownership metadata, not authenticated identity or authority."""
    if validators is None:
        validators = palaco_validators()
    roles = validators["PMS-001.schema.json"].schema["$defs"]["Ownership"]["properties"]
    require(role in roles, f"unknown PALACO ownership role: {role}")
    require(isinstance(owner, str) and re.search(r"\S", owner),
            "owner must be a non-empty string containing non-whitespace text")
    validate_palaco_registry(instance, validators["PCR-000.schema.json"])
    return {
        "role": role,
        "owner": owner,
        "object_ids": sorted(
            record["metadata"]["id"] for record in instance["objects"]
            if record["ownership"][role] == owner
        ),
        "scope": "supplied ownership metadata only; not proof of identity, accountability or authority",
    }


def find_palaco_criticality(instance, criticality, validators=None):
    """Filter recorded criticality metadata, not an independently assessed risk."""
    if validators is None:
        validators = palaco_validators()
    values = validators["PMS-001.schema.json"].schema["$defs"]["Classification"]["properties"]["criticality"]["enum"]
    require(criticality in values, f"unknown PALACO criticality: {criticality}")
    validate_palaco_registry(instance, validators["PCR-000.schema.json"])
    return {
        "criticality": criticality,
        "object_ids": sorted(
            record["metadata"]["id"] for record in instance["objects"]
            if record["classification"]["criticality"] == criticality
        ),
        "scope": "supplied criticality metadata only; not proof of risk assessment, compliance or authority",
    }


def find_palaco_confidentiality(instance, confidentiality, validators=None):
    """Filter confidentiality labels, without implementing access control."""
    if validators is None:
        validators = palaco_validators()
    values = validators["PMS-001.schema.json"].schema["$defs"]["Classification"]["properties"]["confidentiality"]["enum"]
    require(confidentiality in values, f"unknown PALACO confidentiality: {confidentiality}")
    validate_palaco_registry(instance, validators["PCR-000.schema.json"])
    return {
        "confidentiality": confidentiality,
        "object_ids": sorted(
            record["metadata"]["id"] for record in instance["objects"]
            if record["classification"]["confidentiality"] == confidentiality
        ),
        "scope": "supplied confidentiality metadata only; not access control, disclosure permission or authority",
    }


def find_palaco_integrity(instance, integrity, validators=None):
    """Filter integrity classification labels, not verified data integrity."""
    if validators is None:
        validators = palaco_validators()
    values = validators["PMS-001.schema.json"].schema["$defs"]["Classification"]["properties"]["integrity"]["enum"]
    require(integrity in values, f"unknown PALACO integrity: {integrity}")
    validate_palaco_registry(instance, validators["PCR-000.schema.json"])
    return {
        "integrity": integrity,
        "object_ids": sorted(
            record["metadata"]["id"] for record in instance["objects"]
            if record["classification"]["integrity"] == integrity
        ),
        "scope": "supplied integrity-classification metadata only; not proof of data integrity, compliance or authority",
    }


def find_palaco_availability(instance, availability, validators=None):
    """Filter availability classification labels, not measured uptime."""
    if validators is None:
        validators = palaco_validators()
    values = validators["PMS-001.schema.json"].schema["$defs"]["Classification"]["properties"]["availability"]["enum"]
    require(availability in values, f"unknown PALACO availability: {availability}")
    validate_palaco_registry(instance, validators["PCR-000.schema.json"])
    return {
        "availability": availability,
        "object_ids": sorted(
            record["metadata"]["id"] for record in instance["objects"]
            if record["classification"]["availability"] == availability
        ),
        "scope": "supplied availability-classification metadata only; not proof of uptime, SLA compliance or authority",
    }


def find_palaco_relationship(instance, relation, validators=None):
    """Find sources of explicit typed edges, without inferring relationships."""
    if validators is None:
        validators = palaco_validators()
    values = validators["PMS-002.schema.json"].schema["properties"]["relation"]["enum"]
    require(relation in values, f"unknown PALACO relationship: {relation}")
    validate_palaco_registry(instance, validators["PCR-000.schema.json"])
    return {
        "relation": relation,
        "object_ids": sorted(
            record["metadata"]["id"] for record in instance["objects"]
            if any(edge["relation"] == relation for edge in record["traceability"]["relationships"])
        ),
        "scope": "supplied explicit relationship sources only; no inferred links or proof of compliance or authority",
    }


def find_palaco_updater(instance, updater, validator=None):
    """Match the recorded updater label, not an authenticated identity."""
    require(isinstance(updater, str) and re.search(r"\S", updater),
            "updater must be a non-empty string containing non-whitespace text")
    validate_palaco_registry(instance, validator)
    return {
        "updated_by": updater,
        "object_ids": sorted(
            record["metadata"]["id"] for record in instance["objects"]
            if record["audit"]["updated_by"] == updater
        ),
        "scope": "supplied updater metadata only; not authenticated identity, audit evidence or authority",
    }


def find_palaco_name(instance, name, validator=None):
    """Match exact name metadata, not identifiers or descriptive text."""
    require(isinstance(name, str) and re.search(r"\S", name),
            "name must be a non-empty string containing non-whitespace text")
    validate_palaco_registry(instance, validator)
    return {
        "name": name,
        "object_ids": sorted(
            record["metadata"]["id"] for record in instance["objects"]
            if record["metadata"]["name"] == name
        ),
        "scope": "supplied name metadata only; not unique identity, canonical status or authority",
    }


def find_unverified_controls(instance, validator=None):
    """Report non-passing status metadata, not actual verification or compliance."""
    validate_palaco_registry(instance, validator)
    objects = {record["metadata"]["id"]: record for record in instance["objects"]}
    return {
        "definition": "control or referenced VER verification.status is not Passed",
        "object_ids": sorted(
            object_id for object_id, record in objects.items()
            if record["object_type"] == "COM" and (
                record["verification"]["status"] != "Passed"
                or objects[record["verification"]["verification_ref"]]["verification"]["status"] != "Passed"
            )
        ),
        "scope": "supplied status metadata only; diagnostic, not proof of verification, compliance or authority",
    }


def find_palaco_reviews_due(instance, as_of, validator=None):
    """Find scheduled review dates, not proof that reviews are incomplete."""
    require(isinstance(as_of, str) and re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", as_of),
            "review cutoff must be a valid YYYY-MM-DD calendar date")
    try:
        cutoff = date.fromisoformat(as_of)
    except ValueError as error:
        raise ConformanceError("review cutoff must be a valid YYYY-MM-DD calendar date") from error
    validate_palaco_registry(instance, validator)
    return {
        "as_of": as_of,
        "definition": "lifecycle.next_review is on or before as_of; all lifecycle states included",
        "object_ids": sorted(
            record["metadata"]["id"] for record in instance["objects"]
            if date.fromisoformat(record["lifecycle"]["next_review"]) <= cutoff
        ),
        "scope": "supplied review-date metadata only; not proof of overdue work, compliance or authority",
    }


def find_palaco_updated_since(instance, since, validator=None):
    """Filter recorded audit instants from midnight UTC, not update history."""
    require(isinstance(since, str) and re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", since),
            "update cutoff must be a valid YYYY-MM-DD calendar date")
    try:
        cutoff = datetime.combine(date.fromisoformat(since), time.min, timezone.utc)
    except ValueError as error:
        raise ConformanceError("update cutoff must be a valid YYYY-MM-DD calendar date") from error
    validate_palaco_registry(instance, validator)
    return {
        "since": since,
        "definition": "audit.updated_at is on or after midnight UTC on since; all lifecycle states included",
        "object_ids": sorted(
            record["metadata"]["id"] for record in instance["objects"]
            if audit_instant(record) >= cutoff
        ),
        "scope": "supplied audit-timestamp metadata only; not authenticated update history, activity or authority",
    }


def find_palaco_dependents(instance, object_id, validator=None):
    """Return direct dependency sources, not transitive or upstream impact."""
    validate_palaco_registry(instance, validator)
    require(isinstance(object_id, str) and any(
        record["metadata"]["id"] == object_id for record in instance["objects"]
    ), f"unknown PALACO object ID: {object_id}")
    return {
        "object_id": object_id,
        "definition": "direct dependents from dependencies or explicit DEPENDS_ON edges",
        "object_ids": sorted(
            record["metadata"]["id"] for record in instance["objects"]
            if object_id in direct_dependency_targets(record)
        ),
        "scope": "supplied direct dependency metadata only; not complete impact analysis or authority",
    }


def find_palaco_dependencies(instance, object_id, validator=None):
    """Return direct dependency targets, not transitive or upstream links."""
    validate_palaco_registry(instance, validator)
    objects = {record["metadata"]["id"]: record for record in instance["objects"]}
    require(isinstance(object_id, str) and object_id in objects,
            f"unknown PALACO object ID: {object_id}")
    record = objects[object_id]
    targets = direct_dependency_targets(record)
    return {
        "object_id": object_id,
        "definition": "direct dependencies from dependencies or explicit DEPENDS_ON edges",
        "object_ids": sorted(targets),
        "scope": "supplied direct dependency metadata only; not complete impact analysis or authority",
    }


def summarize_palaco_registry(instance, validators=None):
    """Count validated snapshot metadata without asserting completeness or trust."""
    if validators is None:
        validators = palaco_validators()
    validate_palaco_registry(instance, validators["PCR-000.schema.json"])
    schema = validators["PMS-001.schema.json"].schema
    upstream_graph = {
        record["metadata"]["id"]: direct_upstream_targets(record)
        for record in instance["objects"]
    }
    dependency_graph = {
        record["metadata"]["id"]: direct_dependency_targets(record)
        for record in instance["objects"]
    }
    upstream_sizes = weak_component_sizes(upstream_graph)
    dependency_sizes = weak_component_sizes(dependency_graph)
    by_type = {family: 0 for family in sorted(schema["properties"]["object_type"]["enum"])}
    by_domain = {}
    by_ownership = {role: {} for role in schema["$defs"]["Ownership"]["properties"]}
    total_dependency_edges = 0
    dependency_connected = set()
    total_upstream_edges = 0
    upstream_connected = set()
    by_lifecycle = {
        status: 0 for status in schema["$defs"]["Lifecycle"]["properties"]["status"]["enum"]
    }
    by_verification = {
        status: 0 for status in schema["$defs"]["Verification"]["properties"]["status"]["enum"]
    }
    by_approval = {
        status: 0 for status in schema["$defs"]["Approval"]["properties"]["status"]["enum"]
    }
    by_classification = {
        dimension: {label: 0 for label in definition["enum"]}
        for dimension, definition in schema["$defs"]["Classification"]["properties"].items()
    }
    by_relationship = {
        relation: 0 for relation in sorted(
            validators["PMS-002.schema.json"].schema["properties"]["relation"]["enum"]
        )
    }
    for record in instance["objects"]:
        by_type[record["object_type"]] += 1
        upstream = upstream_graph[record["metadata"]["id"]]
        total_upstream_edges += len(upstream)
        if upstream:
            upstream_connected.add(record["metadata"]["id"])
            upstream_connected.update(upstream)
        domain = record["metadata"]["domain"]
        by_domain[domain] = by_domain.get(domain, 0) + 1
        for role, counts in by_ownership.items():
            owner = record["ownership"][role]
            counts[owner] = counts.get(owner, 0) + 1
        by_lifecycle[record["lifecycle"]["status"]] += 1
        by_verification[record["verification"]["status"]] += 1
        by_approval[record["approval"]["status"]] += 1
        for dimension, counts in by_classification.items():
            counts[record["classification"][dimension]] += 1
        for edge in record["traceability"]["relationships"]:
            by_relationship[edge["relation"]] += 1
        dependency_targets = dependency_graph[record["metadata"]["id"]]
        total_dependency_edges += len(dependency_targets)
        if dependency_targets:
            dependency_connected.add(record["metadata"]["id"])
            dependency_connected.update(dependency_targets)
    return {
        "registry_version": instance["registry_version"],
        "total_objects": len(instance["objects"]),
        "by_object_type": by_type,
        "by_domain": dict(sorted(by_domain.items())),
        "by_ownership": {role: dict(sorted(counts.items())) for role, counts in by_ownership.items()},
        "by_lifecycle_status": by_lifecycle,
        "by_verification_status": by_verification,
        "by_approval_status": by_approval,
        "by_classification": by_classification,
        "total_relationships": sum(by_relationship.values()),
        "total_dependency_edges": total_dependency_edges,
        "total_dependency_orphans": len(instance["objects"]) - len(dependency_connected),
        "total_dependency_components": len(dependency_sizes),
        "largest_dependency_component_size": max(dependency_sizes),
        "total_upstream_edges": total_upstream_edges,
        "total_upstream_orphans": len(instance["objects"]) - len(upstream_connected),
        "total_upstream_components": len(upstream_sizes),
        "largest_upstream_component_size": max(upstream_sizes),
        "by_relationship_type": by_relationship,
        "scope": "supplied snapshot metadata only; not proof of completeness, approval, activation or authority",
    }


def find_unaudited_evidence(instance, validator=None):
    """Find absent audit links, without claiming an audit has been performed."""
    validate_palaco_registry(instance, validator)
    packaged = {
        evidence_id for record in instance["objects"] if record["object_type"] == "AUD"
        for evidence_id in record["evidence"]
    }
    return {
        "definition": "EVD has neither audit.audit_refs nor membership in an AUD evidence package",
        "object_ids": sorted(
            record["metadata"]["id"] for record in instance["objects"]
            if record["object_type"] == "EVD" and not record["audit"]["audit_refs"]
            and record["metadata"]["id"] not in packaged
        ),
        "scope": "supplied link metadata only; diagnostic, not proof of audit, evidence authenticity or compliance",
    }


def check_unaudited_evidence():
    validator = palaco_validators()["PCR-000.schema.json"]
    template = read_json(PALACO_FIXTURE_DIR / "FE-00001.fixture.json")
    fixture = {"registry_version": "0.1.0", "objects": []}
    for family, index in (("EVD", 1), ("EVD", 2), ("AUD", 1), ("FE", 1)):
        record = copy.deepcopy(template)
        record["object_type"] = family
        record["metadata"]["id"] = f"{family}-{index:05d}"
        if family == "AUD":
            record["evidence"] = ["EVD-00002"]
        fixture["objects"].append(record)
    positive_count = 0

    def check(instance, expected):
        nonlocal positive_count
        original = copy.deepcopy(instance)
        result = find_unaudited_evidence(instance, validator)
        require(result == {
            "definition": "EVD has neither audit.audit_refs nor membership in an AUD evidence package",
            "object_ids": expected,
            "scope": "supplied link metadata only; diagnostic, not proof of audit, evidence authenticity or compliance",
        }, f"unexpected evidence audit-link result: {result}")
        require(instance == original, "evidence query mutated input")
        reordered = copy.deepcopy(instance)
        reordered["objects"].reverse()
        require(find_unaudited_evidence(reordered, validator) == result,
                "evidence query depends on record order")
        positive_count += 1

    for direct in (False, True):
        for packaged in (False, True):
            instance = copy.deepcopy(fixture)
            if direct:
                instance["objects"][0]["audit"]["audit_refs"] = ["AUD-00001"]
            if packaged:
                instance["objects"][2]["evidence"].append("EVD-00001")
            check(instance, [] if direct or packaged else ["EVD-00001"])
    both = copy.deepcopy(fixture)
    both["objects"][0]["audit"]["audit_refs"] = ["AUD-00001"]
    both["objects"][0]["traceability"]["relationships"] = [
        {"source": "EVD-00001", "relation": "AUDITED_BY", "target": "AUD-00001"}
    ]
    both["objects"][2]["evidence"].append("EVD-00001")
    check(both, [])
    all_unlinked = copy.deepcopy(fixture)
    del all_unlinked["objects"][2]
    check(all_unlinked, ["EVD-00001", "EVD-00002"])
    unrelated = copy.deepcopy(fixture)
    unrelated["objects"][3]["evidence"] = ["EVD-00001"]
    unrelated["objects"][0]["dependencies"] = ["AUD-00001"]
    unrelated["objects"][0]["traceability"]["upstream"] = ["AUD-00001"]
    unrelated["objects"][0]["traceability"]["relationships"] = [
        {"source": "EVD-00001", "relation": "DEPENDS_ON", "target": "AUD-00001"}
    ]
    check(unrelated, ["EVD-00001"])
    check(read_json(PALACO_FIXTURE_DIR / "registry.fixture.json"), [])
    negatives = [({}, "registry structure")]
    invalid = copy.deepcopy(fixture)
    invalid["objects"][0]["audit"]["audit_refs"] = ["AUD-99999"]
    negatives.append((invalid, "unresolved audit.audit_refs"))
    invalid = copy.deepcopy(fixture)
    invalid["objects"][2]["evidence"] = ["EVD-99999"]
    negatives.append((invalid, "unresolved evidence"))
    invalid = copy.deepcopy(fixture)
    invalid["objects"][0]["traceability"]["relationships"] = [
        {"source": "EVD-00001", "relation": "AUDITED_BY", "target": "AUD-00001"}
    ]
    negatives.append((invalid, "AUDITED_BY conflicts with audit.audit_refs"))
    invalid = copy.deepcopy(fixture)
    invalid["objects"].append(copy.deepcopy(invalid["objects"][0]))
    negatives.append((invalid, "duplicate object ID"))
    invalid = copy.deepcopy(fixture)
    invalid["objects"][3]["lifecycle"]["status"] = "Active"
    negatives.append((invalid, "requires approval.status Approved"))
    for instance, expected in negatives:
        try:
            find_unaudited_evidence(instance, validator)
        except ConformanceError as error:
            require(expected in str(error), f"unexpected evidence diagnostic: {error}")
        else:
            raise ConformanceError(f"invalid evidence query accepted: {expected}")
    return f"evidence audit-link diagnostics: {positive_count} deterministic/non-mutating queries + {len(negatives)} rejections"


def check_unverified_controls():
    validators = palaco_validators()
    validator = validators["PCR-000.schema.json"]
    fixture = read_json(PALACO_FIXTURE_DIR / "registry.fixture.json")
    control = read_json(PALACO_FIXTURE_DIR / "COM-00001.fixture.json")
    template = read_json(PALACO_FIXTURE_DIR / "FE-00001.fixture.json")
    fixture["objects"].append(control)
    for family in ("RSK", "VER", "EVD"):
        record = copy.deepcopy(template)
        record["object_type"] = family
        record["metadata"]["id"] = f"{family}-00001"
        fixture["objects"].append(record)
    verifier = next(record for record in fixture["objects"] if record["object_type"] == "VER")
    statuses = ("Pending", "Passed", "Failed", "NotApplicable")
    declared = validators["PMS-001.schema.json"].schema["$defs"]["Verification"]["properties"]["status"]["enum"]
    require(set(statuses) == set(declared), "control diagnostics diverge from verification vocabulary")
    positive_count = 0

    def check(instance, expected):
        nonlocal positive_count
        original = copy.deepcopy(instance)
        result = find_unverified_controls(instance, validator)
        require(result == {
            "definition": "control or referenced VER verification.status is not Passed",
            "object_ids": expected,
            "scope": "supplied status metadata only; diagnostic, not proof of verification, compliance or authority",
        }, f"unexpected verification-status result: {result}")
        require(instance == original, "control status query mutated its input")
        reordered = copy.deepcopy(instance)
        reordered["objects"].reverse()
        require(find_unverified_controls(reordered, validator) == result,
                "control status results depend on record order")
        positive_count += 1

    for control_status in statuses:
        for verifier_status in statuses:
            control["verification"]["status"] = control_status
            verifier["verification"]["status"] = verifier_status
            check(fixture, [] if control_status == verifier_status == "Passed" else ["COM-00001"])
    check(read_json(PALACO_FIXTURE_DIR / "registry.fixture.json"), [])
    multiple = copy.deepcopy(fixture)
    extra = copy.deepcopy(control)
    extra["metadata"]["id"] = "COM-00002"
    extra["traceability"]["relationships"][0]["source"] = "COM-00002"
    multiple["objects"].insert(0, extra)
    check(multiple, ["COM-00001", "COM-00002"])
    # A passing control with its own passing VER is not affected by another pending VER.
    independent = copy.deepcopy(multiple)
    other_verifier = copy.deepcopy(verifier)
    other_verifier["metadata"]["id"] = "VER-00002"
    other_verifier["verification"]["status"] = "Passed"
    independent["objects"].append(other_verifier)
    independent["objects"][0]["verification"].update(status="Passed", verification_ref="VER-00002")
    independent["objects"][0]["traceability"]["relationships"][0]["target"] = "VER-00002"
    check(independent, ["COM-00001"])
    # The mandatory dedicated reference works without duplicating it as an edge.
    no_edge = copy.deepcopy(independent)
    no_edge["objects"][0]["traceability"]["relationships"] = []
    check(no_edge, ["COM-00001"])

    negatives = [({}, "registry structure")]
    dangling = copy.deepcopy(fixture)
    next(record for record in dangling["objects"] if record["object_type"] == "COM")["verification"]["verification_ref"] = "VER-99999"
    negatives.append((dangling, "unresolved verification.verification_ref"))
    missing = copy.deepcopy(fixture)
    del next(record for record in missing["objects"] if record["object_type"] == "COM")["verification"]["verification_ref"]
    negatives.append((missing, "registry structure"))
    wrong_type = copy.deepcopy(fixture)
    next(record for record in wrong_type["objects"] if record["object_type"] == "COM")["verification"]["verification_ref"] = "EVD-00001"
    negatives.append((wrong_type, "registry structure"))
    unrelated = copy.deepcopy(fixture)
    unrelated["objects"][2]["capability_ref"] = "CAP-99999"
    negatives.append((unrelated, "unresolved capability_ref"))
    duplicate = copy.deepcopy(fixture)
    duplicate["objects"].append(copy.deepcopy(duplicate["objects"][0]))
    negatives.append((duplicate, "duplicate object ID"))
    cyclic = copy.deepcopy(fixture)
    cyclic["objects"][0]["traceability"]["upstream"] = ["REQ-00001"]
    negatives.append((cyclic, "upstream cycle"))
    lifecycle = copy.deepcopy(fixture)
    lifecycle["objects"][0]["lifecycle"]["status"] = "Active"
    negatives.append((lifecycle, "requires approval.status Approved"))
    for instance, expected in negatives:
        try:
            find_unverified_controls(instance, validator)
        except ConformanceError as error:
            require(expected in str(error), f"unexpected control-status diagnostic: {error}")
        else:
            raise ConformanceError(f"invalid control-status query accepted: {expected}")
    return f"control status diagnostics: {positive_count} deterministic/non-mutating queries + {len(negatives)} rejections"


def check_palaco_dependency_orphans():
    validators = palaco_validators()
    validator = validators["PCR-000.schema.json"]
    fixture = read_json(PALACO_FIXTURE_DIR / "registry.fixture.json")
    template = read_json(PALACO_FIXTURE_DIR / "FE-00001.fixture.json")
    mixed = copy.deepcopy(fixture)
    for index in (3, 2):
        record = copy.deepcopy(template)
        record["metadata"]["id"] = f"FE-{index:05d}"
        record["traceability"]["upstream"] = ["FE-00001"]
        record["compliance"] = ["FE-00001"]
        mixed["objects"].append(record)
    linked = copy.deepcopy(mixed)
    linked["objects"][3]["dependencies"] = ["FE-00002"]
    linked["objects"][3]["traceability"]["relationships"] = [
        {"source": "FE-00003", "relation": "DEPENDS_ON", "target": "FE-00002"},
    ]
    implicit = copy.deepcopy(linked)
    for record in implicit["objects"]:
        record["traceability"]["relationships"] = []
    cleared = copy.deepcopy(mixed)
    for record in cleared["objects"]:
        record["traceability"]["relationships"] = []
    scope = "supplied snapshot only; diagnostic, not a canonical-status or authority decision"
    for instance, expected in (
        (fixture, []),
        ({"registry_version": "0.1.0", "objects": [template]}, ["FE-00001"]),
        (mixed, ["FE-00002", "FE-00003"]),
        (linked, []),
        (implicit, ["CAP-00001", "FE-00001", "REQ-00001"]),
        (cleared, ["CAP-00001", "FE-00001", "FE-00002", "FE-00003", "REQ-00001"]),
    ):
        original = copy.deepcopy(instance)
        result = find_palaco_dependency_orphans(instance, validator)
        require(result == {
            "graph": "dependencies + DEPENDS_ON",
            "definition": "no incoming or outgoing dependency edges",
            "object_ids": expected, "scope": scope,
        }, f"incorrect dependency-orphan query: {result}")
        require(len(expected) == summarize_palaco_registry(instance, validators)["total_dependency_orphans"],
                "dependency-orphan query and summary disagree")
        require(instance == original, "dependency-orphan query mutated input")
        reordered = copy.deepcopy(instance)
        reordered["objects"].reverse()
        require(find_palaco_dependency_orphans(reordered, validator) == result,
                "dependency-orphan query depends on record order")
    invalid_ref = copy.deepcopy(mixed)
    invalid_ref["objects"][-1]["dependencies"] = ["FE-99999"]
    duplicate = copy.deepcopy(mixed)
    duplicate["objects"].append(copy.deepcopy(duplicate["objects"][0]))
    cycle = copy.deepcopy(fixture)
    cycle["objects"][0]["dependencies"] = ["REQ-00001"]
    bad_source = copy.deepcopy(fixture)
    bad_source["objects"][1]["traceability"]["relationships"][0]["source"] = "REQ-00001"
    for instance, diagnostic in (
        ({}, "registry structure"), (invalid_ref, "unresolved"),
        (duplicate, "duplicate object ID"), (cycle, "dependency cycle"), (bad_source, "source"),
    ):
        try:
            find_palaco_dependency_orphans(instance, validator)
        except ConformanceError as error:
            require(diagnostic in str(error), f"unexpected dependency-orphan error: {error}")
        else:
            raise ConformanceError(f"invalid dependency-orphan query accepted: {diagnostic}")
    fixture_path = str(PALACO_FIXTURE_DIR / "registry.fixture.json")
    script = [sys.executable, str(Path(__file__).resolve())]
    base = script + ["--registry", fixture_path]
    cli = subprocess.run(base + ["--find-dependency-orphans"],
                         capture_output=True, text=True, timeout=30)
    require(cli.returncode == 0, f"dependency-orphan CLI failed: {cli.stdout}{cli.stderr}")
    require(json.loads(cli.stdout) == find_palaco_dependency_orphans(fixture, validator),
            "incorrect dependency-orphan CLI result")
    for flags in (
        ["--find-dependencies", "FE-00001"], ["--find-dependents", "FE-00001"],
        ["--find-updated-since", "2026-10-15"], ["--find-name", "Example accountable registry"],
        ["--find-updater", "Example registry team"], ["--find-relationship", "DEPENDS_ON"],
        ["--find-availability", "Medium"], ["--find-integrity", "High"],
        ["--find-confidentiality", "Public"], ["--find-criticality", "High"],
        ["--find-owner", "custodian", "Example registry team"], ["--find-approval", "Pending"],
        ["--find-verification", "Pending"], ["--find-domain", "Governance"],
        ["--find-type", "FE"], ["--find-lifecycle", "Draft"], ["--find-review-due", "2027-01-15"],
        ["--summary"], ["--trace", "FE-00001"], ["--find-orphans"],
        ["--find-unverified-controls"], ["--find-unaudited-evidence"],
        ["--previous-registry", fixture_path], ["--diff"], ["--direction", "upstream"],
    ):
        rejected = subprocess.run(base + ["--find-dependency-orphans"] + flags,
                                  capture_output=True, text=True, timeout=30)
        require(rejected.returncode == 2 and not rejected.stdout,
                f"dependency-orphan query accepted incompatible flags: {flags}")
    missing = subprocess.run(script + ["--find-dependency-orphans"],
                             capture_output=True, text=True, timeout=30)
    require(missing.returncode == 2 and not missing.stdout, "dependency-orphan query accepted missing registry")
    return "6 sorted/non-mutating queries + summary/graph consistency + 5 rejections + CLI/conflict regressions"


def check_palaco_orphans():
    validator = palaco_validators()["PCR-000.schema.json"]
    fixture = read_json(PALACO_FIXTURE_DIR / "registry.fixture.json")
    template = read_json(PALACO_FIXTURE_DIR / "FE-00001.fixture.json")
    positive_count = 0

    def check(instance, expected):
        nonlocal positive_count
        original = copy.deepcopy(instance)
        result = find_palaco_orphans(instance, validator)
        require(result == {
            "graph": "traceability.upstream",
            "definition": "no incoming or outgoing upstream edges",
            "object_ids": expected,
            "scope": "supplied snapshot only; diagnostic, not a canonical-status or authority decision",
        }, f"unexpected orphan result: {result}")
        require(instance == original, "orphan query mutated input")
        reordered = copy.deepcopy(instance)
        reordered["objects"].reverse()
        require(find_palaco_orphans(reordered, validator) == result,
                "orphan output depends on object order")
        positive_count += 1

    # A connected root and a leaf both participate in lineage.
    check(fixture, [])
    check({"registry_version": "0.1.0", "objects": [copy.deepcopy(template)]}, ["FE-00001"])
    mixed = copy.deepcopy(fixture)
    for index in (3, 2):
        record = copy.deepcopy(template)
        record["metadata"]["id"] = f"FE-{index:05d}"
        mixed["objects"].append(record)
    check(mixed, ["FE-00002", "FE-00003"])
    # Non-lineage links do not hide isolated nodes, including incoming references.
    non_lineage = copy.deepcopy(mixed)
    non_lineage["objects"][3]["dependencies"] = ["FE-00002"]
    non_lineage["objects"][3]["compliance"] = ["FE-00001"]
    non_lineage["objects"][3]["traceability"]["relationships"] = [
        {"source": "FE-00003", "relation": "DEPENDS_ON", "target": "FE-00002"}
    ]
    check(non_lineage, ["FE-00002", "FE-00003"])
    # A disconnected multi-node component is not an isolated node.
    component = copy.deepcopy(mixed)
    component["objects"][3]["traceability"]["upstream"] = ["FE-00002"]
    check(component, [])
    all_isolated = copy.deepcopy(mixed)
    for record in all_isolated["objects"]:
        record["traceability"]["upstream"] = []
    check(all_isolated, ["CAP-00001", "FE-00001", "FE-00002", "FE-00003", "REQ-00001"])

    negatives = [({}, "registry structure")]
    dangling = copy.deepcopy(mixed)
    dangling["objects"][2]["capability_ref"] = "CAP-99999"
    negatives.append((dangling, "unresolved capability_ref"))
    duplicate = copy.deepcopy(mixed)
    duplicate["objects"].append(copy.deepcopy(duplicate["objects"][0]))
    negatives.append((duplicate, "duplicate object ID"))
    cyclic = copy.deepcopy(mixed)
    cyclic["objects"][0]["traceability"]["upstream"] = ["REQ-00001"]
    negatives.append((cyclic, "upstream cycle"))
    lifecycle = copy.deepcopy(mixed)
    lifecycle["objects"][2]["lifecycle"]["status"] = "Active"
    negatives.append((lifecycle, "requires approval.status Approved"))
    for instance, expected in negatives:
        try:
            find_palaco_orphans(instance, validator)
        except ConformanceError as error:
            require(expected in str(error), f"unexpected orphan diagnostic: {error}")
        else:
            raise ConformanceError(f"invalid orphan query accepted: {expected}")
    return f"registry orphans: {positive_count} deterministic/non-mutating queries + {len(negatives)} rejections"


def check_palaco_find():
    validators = palaco_validators()
    fixture = read_json(PALACO_FIXTURE_DIR / "registry.fixture.json")
    original = copy.deepcopy(fixture)
    families = validators["PMS-001.schema.json"].schema["properties"]["object_type"]["enum"]
    for family in families:
        expected = {
            "object_type": family,
            "object_ids": [record["metadata"]["id"] for record in fixture["objects"]
                           if record["object_type"] == family],
            "scope": "supplied snapshot only; not a completeness or authority decision",
        }
        require(find_palaco_objects(fixture, family, validators) == expected,
                f"incorrect object-type query: {family}")
    multiple = copy.deepcopy(fixture)
    added = copy.deepcopy(multiple["objects"][0])
    added["metadata"]["id"] = "FE-00002"
    # Domain and display text must not determine canonical object family.
    added["metadata"]["domain"] = "REQ"
    added["metadata"]["name"] = "Service"
    multiple["objects"].append(added)
    result = find_palaco_objects(multiple, "FE", validators)
    require(result["object_ids"] == ["FE-00001", "FE-00002"], "multiple matches not sorted")
    reordered = copy.deepcopy(multiple)
    reordered["objects"].reverse()
    require(find_palaco_objects(reordered, "FE", validators) == result,
            "object-type query depends on record order")
    require(fixture == original, "object-type query mutated input")
    untouched = copy.deepcopy(multiple)
    find_palaco_objects(multiple, "FE", validators)
    require(multiple == untouched, "multiple-result query mutated input")

    negatives = [(fixture, value, "unknown PALACO object type")
                 for value in ("", "fe", "UNKNOWN", None)]
    dangling = copy.deepcopy(fixture)
    dangling["objects"][2]["capability_ref"] = "CAP-99999"
    negatives.append((dangling, "FE", "unresolved capability_ref"))
    duplicate = copy.deepcopy(fixture)
    duplicate["objects"].append(copy.deepcopy(duplicate["objects"][0]))
    negatives.append((duplicate, "FE", "duplicate object ID"))
    cyclic = copy.deepcopy(fixture)
    cyclic["objects"][0]["traceability"]["upstream"] = ["REQ-00001"]
    negatives.append((cyclic, "SVC", "upstream cycle"))
    lifecycle = copy.deepcopy(fixture)
    lifecycle["objects"][2]["lifecycle"]["status"] = "Active"
    negatives.append((lifecycle, "FE", "requires approval.status Approved"))
    negatives.append(({}, "FE", "registry structure"))
    for instance, family, expected in negatives:
        try:
            find_palaco_objects(instance, family, validators)
        except ConformanceError as error:
            require(expected in str(error), f"unexpected object-type query diagnostic: {error}")
        else:
            raise ConformanceError(f"invalid object-type query accepted: {expected}")
    return (
        f"registry find: {len(families)} families, sorted multiple/empty results, "
        f"non-mutating output + {len(negatives)} rejections"
    )


def check_palaco_upstream_contract():
    validators = palaco_validators()
    validator = validators["PCR-000.schema.json"]
    fixture = read_json(PALACO_FIXTURE_DIR / "registry.fixture.json")
    fixture["objects"][2]["traceability"]["upstream"].append("FE-00001")
    original = copy.deepcopy(fixture)
    expected = {
        "FE-00001": set(),
        "CAP-00001": {"FE-00001"},
        "REQ-00001": {"FE-00001", "CAP-00001"},
    }
    validate_palaco_registry(fixture, validator)
    for record in fixture["objects"]:
        source = record["metadata"]["id"]
        require(direct_upstream_targets(record) == expected[source],
                f"incorrect shared upstream targets: {source}")
        targets = direct_upstream_targets(record)
        targets.clear()
        require(direct_upstream_targets(record) == expected[source],
                "upstream targets expose mutable input state")
    require(trace_palaco_registry(fixture, "REQ-00001", validator=validator)["reachable_ids"]
            == ["CAP-00001", "FE-00001"], "upstream trace differs from shared graph")
    require(trace_palaco_registry(fixture, "FE-00001", "downstream", validator)["reachable_ids"]
            == ["CAP-00001", "REQ-00001"], "downstream trace differs from shared graph")
    summary = summarize_palaco_registry(fixture, validators)
    require(summary["total_upstream_edges"] == 3 and summary["total_dependency_edges"] == 2,
            "summary mixed upstream and dependency graphs")
    require(find_palaco_orphans(fixture, validator)["object_ids"] == [],
            "upstream orphan query differs from shared graph")
    require(fixture == original, "shared upstream extraction mutated input")
    for record in fixture["objects"]:
        record["traceability"]["upstream"] = []
    validate_palaco_registry(fixture, validator)
    require(all(direct_upstream_targets(record) == set() for record in fixture["objects"]),
            "shared upstream extraction included dependency or dedicated references")
    require(trace_palaco_registry(fixture, "REQ-00001", validator=validator)["reachable_ids"] == [],
            "upstream trace inferred dependency links")
    require(len(find_palaco_orphans(fixture, validator)["object_ids"]) == 3,
            "upstream orphan query inferred dependency links")
    require(summarize_palaco_registry(fixture, validators)["total_upstream_edges"] == 0,
            "summary inferred upstream links")
    return "shared upstream targets + trace/summary/orphan consistency + fresh sets + graph-boundary checks"


def check_palaco_dependency_contract():
    validators = palaco_validators()
    validator = validators["PCR-000.schema.json"]
    fixture = read_json(PALACO_FIXTURE_DIR / "registry.fixture.json")
    requirement = fixture["objects"][2]
    requirement["dependencies"] = ["CAP-00001", "FE-00001"]
    original = copy.deepcopy(fixture)
    expected = {
        "FE-00001": set(),
        "CAP-00001": {"FE-00001"},
        "REQ-00001": {"CAP-00001", "FE-00001"},
    }
    for record in fixture["objects"]:
        source = record["metadata"]["id"]
        targets = direct_dependency_targets(record)
        require(targets == expected[source], f"incorrect shared dependency targets: {source}")
        require(find_palaco_dependencies(fixture, source, validator)["object_ids"] == sorted(targets),
                "dependency query differs from shared graph")
        for target in targets:
            require(source in find_palaco_dependents(fixture, target, validator)["object_ids"],
                    "dependency queries disagree on edge direction")
    require(summarize_palaco_registry(fixture, validators)["total_dependency_edges"] == 3,
            "summary differs from shared dependency graph")
    require(find_palaco_dependency_orphans(fixture, validator)["object_ids"] == [],
            "dependency orphan query differs from shared graph")
    targets = direct_dependency_targets(requirement)
    targets.clear()
    require(direct_dependency_targets(requirement) == expected["REQ-00001"],
            "dependency targets expose mutable input state")
    require(fixture == original, "shared dependency extraction mutated input")
    references_only = copy.deepcopy(fixture)
    for record in references_only["objects"]:
        record.pop("dependencies", None)
        record["traceability"]["relationships"] = []
        require(direct_dependency_targets(record) == set(),
                "shared dependency extraction included upstream or dedicated references")
    objective = copy.deepcopy(fixture["objects"][0])
    objective["object_type"] = "OBJ"
    objective["metadata"]["id"] = "OBJ-00001"
    references_only["objects"].append(objective)
    references_only["objects"][2]["traceability"]["relationships"] = [
        {"source": "REQ-00001", "relation": "SATISFIES", "target": "OBJ-00001"},
    ]
    validate_palaco_registry(references_only, validator)
    require(direct_dependency_targets(references_only["objects"][2]) == set(),
            "shared dependency extraction included other relationship types")
    return "shared targets + query/summary/orphan consistency + fresh sets + graph-boundary checks"


def check_palaco_dependencies():
    validator = palaco_validators()["PCR-000.schema.json"]
    template = read_json(PALACO_FIXTURE_DIR / "FE-00001.fixture.json")
    fixture = {"registry_version": "0.1.0", "objects": []}
    for index in range(1, 6):
        record = copy.deepcopy(template)
        record["metadata"]["id"] = f"FE-{index:05d}"
        fixture["objects"].append(record)
    fixture["objects"][0]["dependencies"] = ["FE-00003", "FE-00002"]
    fixture["objects"][0]["traceability"]["relationships"] = [
        {"source": "FE-00001", "relation": "DEPENDS_ON", "target": "FE-00003"},
    ]
    fixture["objects"][0]["traceability"]["upstream"] = ["FE-00005"]
    fixture["objects"][1]["traceability"]["relationships"] = [
        {"source": "FE-00002", "relation": "DEPENDS_ON", "target": "FE-00004"},
    ]
    original = copy.deepcopy(fixture)
    definition = "direct dependencies from dependencies or explicit DEPENDS_ON edges"
    scope = "supplied direct dependency metadata only; not complete impact analysis or authority"
    for object_id, expected in (
        ("FE-00001", ["FE-00002", "FE-00003"]),
        ("FE-00002", ["FE-00004"]),
        ("FE-00003", []),
        ("FE-00005", []),
    ):
        result = find_palaco_dependencies(fixture, object_id, validator)
        require(result == {
            "object_id": object_id, "definition": definition, "object_ids": expected, "scope": scope,
        }, f"incorrect dependencies query: {result}")
        reordered = copy.deepcopy(fixture)
        reordered["objects"].reverse()
        for record in reordered["objects"]:
            record.get("dependencies", []).reverse()
            record["traceability"]["relationships"].reverse()
        require(find_palaco_dependencies(reordered, object_id, validator) == result,
                "dependencies query depends on record or edge order")
    require(fixture == original, "dependencies query mutated input")
    references_only = read_json(PALACO_FIXTURE_DIR / "registry.fixture.json")
    for record in references_only["objects"]:
        record["traceability"]["relationships"] = []
    require(find_palaco_dependencies(references_only, "REQ-00001", validator)["object_ids"] == [],
            "dependencies query included upstream or capability references")
    invalid_ref = copy.deepcopy(fixture)
    invalid_ref["objects"][-1]["dependencies"] = ["FE-99999"]
    invalid_source = copy.deepcopy(fixture)
    invalid_source["objects"][1]["traceability"]["relationships"][0]["source"] = "FE-00003"
    duplicate = copy.deepcopy(fixture)
    duplicate["objects"].append(copy.deepcopy(duplicate["objects"][0]))
    cycle = copy.deepcopy(fixture)
    cycle["objects"][3]["dependencies"] = ["FE-00001"]
    for instance, object_id, diagnostic in (
        *((fixture, value, "unknown PALACO object ID") for value in (
            "", "fe-00001", "FE-0001", "FE-99999", None, 42, [],
        )),
        ({}, "FE-00001", "registry structure"),
        (invalid_ref, "FE-00001", "unresolved"),
        (invalid_source, "FE-00001", "source"),
        (duplicate, "FE-00001", "duplicate object ID"),
        (cycle, "FE-00001", "dependency cycle"),
    ):
        try:
            find_palaco_dependencies(instance, object_id, validator)
        except ConformanceError as error:
            require(diagnostic in str(error), f"unexpected dependencies error: {error}")
        else:
            raise ConformanceError(f"invalid dependencies query accepted: {diagnostic}")
    fixture_path = str(PALACO_FIXTURE_DIR / "registry.fixture.json")
    script = [sys.executable, str(Path(__file__).resolve())]
    base = script + ["--registry", fixture_path]
    for object_id, expected in (("REQ-00001", ["CAP-00001"]), ("FE-00001", [])):
        cli = subprocess.run(base + ["--find-dependencies", object_id],
                             capture_output=True, text=True, timeout=30)
        require(cli.returncode == 0, f"dependencies CLI failed: {cli.stdout}{cli.stderr}")
        require(json.loads(cli.stdout) == {
            "object_id": object_id, "definition": definition, "object_ids": expected, "scope": scope,
        }, "incorrect dependencies CLI result")
    for flags in (
        ["--find-dependents", "FE-00001"], ["--find-updated-since", "2026-10-15"],
        ["--find-name", "Example accountable registry"], ["--find-updater", "Example registry team"],
        ["--find-relationship", "DEPENDS_ON"], ["--find-availability", "Medium"],
        ["--find-integrity", "High"], ["--find-confidentiality", "Public"],
        ["--find-criticality", "High"], ["--find-owner", "custodian", "Example registry team"],
        ["--find-approval", "Pending"], ["--find-verification", "Pending"],
        ["--find-domain", "Governance"], ["--find-type", "FE"], ["--find-lifecycle", "Draft"],
        ["--find-review-due", "2027-01-15"], ["--summary"], ["--trace", "FE-00001"],
        ["--find-orphans"], ["--find-unverified-controls"], ["--find-unaudited-evidence"],
        ["--previous-registry", fixture_path], ["--diff"], ["--direction", "upstream"],
    ):
        rejected = subprocess.run(base + ["--find-dependencies", "REQ-00001"] + flags,
                                  capture_output=True, text=True, timeout=30)
        require(rejected.returncode == 2 and not rejected.stdout,
                f"dependencies query accepted incompatible flags: {flags}")
    for arguments, code in (
        (script + ["--find-dependencies", "FE-00001"], 2),
        (base + ["--find-dependencies", "FE-99999"], 1),
    ):
        rejected = subprocess.run(arguments, capture_output=True, text=True, timeout=30)
        require(rejected.returncode == code and '"object_ids"' not in rejected.stdout,
                "dependencies CLI accepted missing registry or unknown ID")
    return "4 direct/empty queries + deduplication/graph/nonmutation checks + 12 rejections + CLI/conflict regressions"


def check_palaco_dependents():
    validator = palaco_validators()["PCR-000.schema.json"]
    template = read_json(PALACO_FIXTURE_DIR / "FE-00001.fixture.json")
    fixture = {"registry_version": "0.1.0", "objects": []}
    for index in range(1, 7):
        record = copy.deepcopy(template)
        record["metadata"]["id"] = f"FE-{index:05d}"
        fixture["objects"].append(record)
    fixture["objects"][1]["dependencies"] = ["FE-00001"]
    fixture["objects"][2]["traceability"]["relationships"] = [
        {"source": "FE-00003", "relation": "DEPENDS_ON", "target": "FE-00001"},
    ]
    fixture["objects"][3]["dependencies"] = ["FE-00001"]
    fixture["objects"][3]["traceability"]["relationships"] = [
        {"source": "FE-00004", "relation": "DEPENDS_ON", "target": "FE-00001"},
    ]
    fixture["objects"][4]["traceability"]["upstream"] = ["FE-00001"]
    fixture["objects"][5]["dependencies"] = ["FE-00002"]
    original = copy.deepcopy(fixture)
    definition = "direct dependents from dependencies or explicit DEPENDS_ON edges"
    scope = "supplied direct dependency metadata only; not complete impact analysis or authority"
    for object_id, expected in (
        ("FE-00001", ["FE-00002", "FE-00003", "FE-00004"]),
        ("FE-00002", ["FE-00006"]),
        ("FE-00005", []),
        ("FE-00006", []),
    ):
        result = find_palaco_dependents(fixture, object_id, validator)
        require(result == {
            "object_id": object_id, "definition": definition, "object_ids": expected, "scope": scope,
        }, f"incorrect dependents query: {result}")
        reordered = copy.deepcopy(fixture)
        reordered["objects"].reverse()
        require(find_palaco_dependents(reordered, object_id, validator) == result,
                "dependents query depends on record order")
    require(fixture == original, "dependents query mutated input")
    references_only = read_json(PALACO_FIXTURE_DIR / "registry.fixture.json")
    for record in references_only["objects"]:
        record["traceability"]["relationships"] = []
    require(find_palaco_dependents(references_only, "CAP-00001", validator)["object_ids"] == [],
            "dependents query included upstream or capability references")
    invalid_ref = copy.deepcopy(fixture)
    invalid_ref["objects"][-1]["dependencies"] = ["FE-99999"]
    invalid_source = copy.deepcopy(fixture)
    invalid_source["objects"][2]["traceability"]["relationships"][0]["source"] = "FE-00004"
    duplicate = copy.deepcopy(fixture)
    duplicate["objects"].append(copy.deepcopy(duplicate["objects"][0]))
    cycle = copy.deepcopy(fixture)
    cycle["objects"][0]["dependencies"] = ["FE-00006"]
    for instance, object_id, diagnostic in (
        *((fixture, value, "unknown PALACO object ID") for value in (
            "", "fe-00001", "FE-0001", "FE-99999", None, 42,
        )),
        ({}, "FE-00001", "registry structure"),
        (invalid_ref, "FE-00001", "unresolved"),
        (invalid_source, "FE-00001", "source"),
        (duplicate, "FE-00001", "duplicate object ID"),
        (cycle, "FE-00001", "dependency cycle"),
    ):
        try:
            find_palaco_dependents(instance, object_id, validator)
        except ConformanceError as error:
            require(diagnostic in str(error), f"unexpected dependents error: {error}")
        else:
            raise ConformanceError(f"invalid dependents query accepted: {diagnostic}")
    fixture_path = str(PALACO_FIXTURE_DIR / "registry.fixture.json")
    script = [sys.executable, str(Path(__file__).resolve())]
    base = script + ["--registry", fixture_path]
    for object_id, expected in (("FE-00001", ["CAP-00001"]), ("REQ-00001", [])):
        cli = subprocess.run(base + ["--find-dependents", object_id],
                             capture_output=True, text=True, timeout=30)
        require(cli.returncode == 0, f"dependents CLI failed: {cli.stdout}{cli.stderr}")
        require(json.loads(cli.stdout) == {
            "object_id": object_id, "definition": definition, "object_ids": expected, "scope": scope,
        }, "incorrect dependents CLI result")
    for flags in (
        ["--find-updated-since", "2026-10-15"], ["--find-name", "Example accountable registry"],
        ["--find-updater", "Example registry team"], ["--find-relationship", "DEPENDS_ON"],
        ["--find-availability", "Medium"], ["--find-integrity", "High"],
        ["--find-confidentiality", "Public"], ["--find-criticality", "High"],
        ["--find-owner", "custodian", "Example registry team"], ["--find-approval", "Pending"],
        ["--find-verification", "Pending"], ["--find-domain", "Governance"],
        ["--find-type", "FE"], ["--find-lifecycle", "Draft"], ["--find-review-due", "2027-01-15"],
        ["--summary"], ["--trace", "FE-00001"], ["--find-orphans"],
        ["--find-unverified-controls"], ["--find-unaudited-evidence"],
        ["--previous-registry", fixture_path], ["--diff"], ["--direction", "upstream"],
    ):
        rejected = subprocess.run(base + ["--find-dependents", "FE-00001"] + flags,
                                  capture_output=True, text=True, timeout=30)
        require(rejected.returncode == 2 and not rejected.stdout,
                f"dependents query accepted incompatible flags: {flags}")
    for arguments, code in (
        (script + ["--find-dependents", "FE-00001"], 2),
        (base + ["--find-dependents", "FE-99999"], 1),
    ):
        rejected = subprocess.run(arguments, capture_output=True, text=True, timeout=30)
        require(rejected.returncode == code and '"object_ids"' not in rejected.stdout,
                "dependents CLI accepted missing registry or unknown ID")
    return "4 direct/empty queries + deduplication/graph/nonmutation checks + 11 rejections + CLI/conflict regressions"


def check_palaco_updated_since():
    validator = palaco_validators()["PCR-000.schema.json"]
    template = read_json(PALACO_FIXTURE_DIR / "FE-00001.fixture.json")
    fixture = {"registry_version": "0.1.0", "objects": []}
    timestamps = (
        "2026-10-15T23:59:59Z",
        "2026-10-16T00:00:00Z",
        "2026-10-16T00:00:00.000001Z",
        "2026-10-16T01:00:00+02:00",
        "2026-10-15T23:00:00-01:00",
        "2026-10-16t00:00:00z",
    )
    for index, timestamp in enumerate(timestamps, 1):
        record = copy.deepcopy(template)
        record["metadata"]["id"] = f"FE-{index:05d}"
        record["audit"]["updated_at"] = timestamp
        fixture["objects"].insert(0, record)
    original = copy.deepcopy(fixture)
    scope = "supplied audit-timestamp metadata only; not authenticated update history, activity or authority"
    definition = "audit.updated_at is on or after midnight UTC on since; all lifecycle states included"
    for since, expected in (
        ("2026-10-16", ["FE-00002", "FE-00003", "FE-00005", "FE-00006"]),
        ("2026-10-15", [f"FE-{index:05d}" for index in range(1, 7)]),
        ("2026-10-17", []),
        ("2024-02-29", [f"FE-{index:05d}" for index in range(1, 7)]),
    ):
        result = find_palaco_updated_since(fixture, since, validator)
        require(result == {"since": since, "definition": definition, "object_ids": expected, "scope": scope},
                f"incorrect updated-since query: {result}")
        reordered = copy.deepcopy(fixture)
        reordered["objects"].reverse()
        require(find_palaco_updated_since(reordered, since, validator) == result,
                "updated-since query depends on record order")
    require(fixture == original, "updated-since query mutated input")
    approved = copy.deepcopy(fixture)
    record = approved["objects"][0]
    record["lifecycle"]["status"] = "Active"
    record["lifecycle"]["approved"] = "2026-10-15"
    record["approval"] = {"status": "Approved", "authority": "Example review team", "approval_ref": "Synthetic approval"}
    require(find_palaco_updated_since(approved, "2026-10-16", validator)["object_ids"]
            == ["FE-00002", "FE-00003", "FE-00005", "FE-00006"],
            "updated-since query excludes approved lifecycle states")
    invalid_ref = copy.deepcopy(fixture)
    invalid_ref["objects"][-1]["traceability"]["upstream"] = ["FE-99999"]
    invalid_timestamp = copy.deepcopy(fixture)
    invalid_timestamp["objects"][-1]["audit"]["updated_at"] = "2026-10-15T23:00:00"
    duplicate = copy.deepcopy(fixture)
    duplicate["objects"].append(copy.deepcopy(duplicate["objects"][0]))
    for instance, since, diagnostic in (
        *((fixture, value, "update cutoff") for value in (
            "", " ", "2026-1-16", "2026-10-16T00:00:00Z", "2026-02-29",
            "0000-01-01", "2026-13-01", None, 42,
        )),
        ({}, "2026-10-16", "registry structure"),
        (invalid_ref, "2026-10-16", "unresolved"),
        (invalid_timestamp, "2026-10-16", "registry structure"),
        (duplicate, "2026-10-16", "duplicate object ID"),
    ):
        try:
            find_palaco_updated_since(instance, since, validator)
        except ConformanceError as error:
            require(diagnostic in str(error), f"unexpected updated-since error: {error}")
        else:
            raise ConformanceError(f"invalid updated-since query accepted: {diagnostic}")
    fixture_path = str(PALACO_FIXTURE_DIR / "registry.fixture.json")
    script = [sys.executable, str(Path(__file__).resolve())]
    base = script + ["--registry", fixture_path]
    for since, expected in (
        ("2026-10-15", ["CAP-00001", "FE-00001", "REQ-00001"]),
        ("2026-10-16", []),
    ):
        cli = subprocess.run(base + ["--find-updated-since", since],
                             capture_output=True, text=True, timeout=30)
        require(cli.returncode == 0, f"updated-since CLI failed: {cli.stdout}{cli.stderr}")
        require(json.loads(cli.stdout) == {
            "since": since, "definition": definition, "object_ids": expected, "scope": scope,
        }, "incorrect updated-since CLI result")
    for flags in (
        ["--find-name", "Example accountable registry"], ["--find-updater", "Example registry team"],
        ["--find-relationship", "DEPENDS_ON"], ["--find-availability", "Medium"],
        ["--find-integrity", "High"], ["--find-confidentiality", "Public"],
        ["--find-criticality", "High"], ["--find-owner", "custodian", "Example registry team"],
        ["--find-approval", "Pending"], ["--find-verification", "Pending"],
        ["--find-domain", "Governance"], ["--find-type", "FE"], ["--find-lifecycle", "Draft"],
        ["--find-review-due", "2027-01-15"], ["--summary"], ["--trace", "FE-00001"],
        ["--find-orphans"], ["--find-unverified-controls"], ["--find-unaudited-evidence"],
        ["--previous-registry", fixture_path], ["--diff"], ["--direction", "upstream"],
    ):
        rejected = subprocess.run(base + ["--find-updated-since", "2026-10-16"] + flags,
                                  capture_output=True, text=True, timeout=30)
        require(rejected.returncode == 2 and not rejected.stdout,
                f"updated-since query accepted incompatible flags: {flags}")
    for arguments, code in (
        (script + ["--find-updated-since", "2026-10-16"], 2),
        (base + ["--find-updated-since", "2026-02-29"], 1),
    ):
        rejected = subprocess.run(arguments, capture_output=True, text=True, timeout=30)
        require(rejected.returncode == code and '"object_ids"' not in rejected.stdout,
                "updated-since CLI accepted missing registry or invalid date")
    return "4 date queries + timezone/inclusive/lifecycle/nonmutation checks + 13 rejections + CLI/conflict regressions"


def check_palaco_name():
    validator = palaco_validators()["PCR-000.schema.json"]
    template = read_json(PALACO_FIXTURE_DIR / "FE-00001.fixture.json")
    fixture = {"registry_version": "0.1.0", "objects": []}
    for index, name in enumerate(("Example registry", "Other registry", "Example registry", " Registry Δ "), 1):
        record = copy.deepcopy(template)
        record["metadata"]["id"] = f"FE-{index:05d}"
        record["metadata"]["name"] = name
        record["metadata"]["description"] = "Description-only label"
        fixture["objects"].insert(0, record)
    original = copy.deepcopy(fixture)
    scope = "supplied name metadata only; not unique identity, canonical status or authority"
    for name, expected in (
        ("Example registry", ["FE-00001", "FE-00003"]),
        ("Other registry", ["FE-00002"]),
        ("example registry", []),
        ("Example", []),
        (" Example registry ", []),
        ("FE-00001", []),
        ("Description-only label", []),
        (" Registry Δ ", ["FE-00004"]),
        ("Registry Δ", []),
    ):
        result = find_palaco_name(fixture, name, validator)
        require(result == {"name": name, "object_ids": expected, "scope": scope},
                f"incorrect name query: {result}")
        reordered = copy.deepcopy(fixture)
        reordered["objects"].reverse()
        require(find_palaco_name(reordered, name, validator) == result,
                "name query depends on record order")
    require(fixture == original, "name query mutated input")
    invalid_ref = copy.deepcopy(fixture)
    invalid_ref["objects"][2]["traceability"]["upstream"] = ["FE-99999"]
    invalid_name = copy.deepcopy(fixture)
    invalid_name["objects"][2]["metadata"]["name"] = " "
    duplicate = copy.deepcopy(fixture)
    duplicate["objects"].append(copy.deepcopy(duplicate["objects"][0]))
    for instance, name, diagnostic in (
        (fixture, "", "name must"),
        (fixture, " \t\n", "name must"),
        (fixture, None, "name must"),
        (fixture, 42, "name must"),
        ({}, "Example registry", "registry structure"),
        (invalid_ref, "Example registry", "unresolved"),
        (invalid_name, "Example registry", "registry structure"),
        (duplicate, "Example registry", "duplicate object ID"),
    ):
        try:
            find_palaco_name(instance, name, validator)
        except ConformanceError as error:
            require(diagnostic in str(error), f"unexpected name error: {error}")
        else:
            raise ConformanceError(f"invalid name query accepted: {diagnostic}")
    fixture_path = str(PALACO_FIXTURE_DIR / "registry.fixture.json")
    script = [sys.executable, str(Path(__file__).resolve())]
    base = script + ["--registry", fixture_path]
    for name, expected in (
        ("Example accountable registry", ["FE-00001"]),
        ("Unknown registry", []),
    ):
        cli = subprocess.run(base + ["--find-name", name],
                             capture_output=True, text=True, timeout=30)
        require(cli.returncode == 0, f"name CLI failed: {cli.stdout}{cli.stderr}")
        require(json.loads(cli.stdout) == {"name": name, "object_ids": expected, "scope": scope},
                "incorrect name CLI result")
    for flags in (
        ["--find-updater", "Example registry team"], ["--find-relationship", "DEPENDS_ON"],
        ["--find-availability", "Medium"], ["--find-integrity", "High"],
        ["--find-confidentiality", "Public"], ["--find-criticality", "High"],
        ["--find-owner", "custodian", "Example registry team"], ["--find-approval", "Pending"],
        ["--find-verification", "Pending"], ["--find-domain", "Governance"],
        ["--find-type", "FE"], ["--find-lifecycle", "Draft"], ["--find-review-due", "2027-01-15"],
        ["--summary"], ["--trace", "FE-00001"], ["--find-orphans"],
        ["--find-unverified-controls"], ["--find-unaudited-evidence"],
        ["--previous-registry", fixture_path], ["--diff"], ["--direction", "upstream"],
    ):
        rejected = subprocess.run(base + ["--find-name", "Example accountable registry"] + flags,
                                  capture_output=True, text=True, timeout=30)
        require(rejected.returncode == 2 and not rejected.stdout,
                f"name query accepted incompatible flags: {flags}")
    for arguments, code in (
        (script + ["--find-name", "Example accountable registry"], 2),
        (base + ["--find-name", " "], 1),
    ):
        rejected = subprocess.run(arguments, capture_output=True, text=True, timeout=30)
        require(rejected.returncode == code and '"object_ids"' not in rejected.stdout,
                "name CLI accepted missing registry or blank name")
    return "9 exact/empty/sorted/non-mutating queries + 8 rejections + CLI/conflict regressions"


def check_palaco_updater():
    validator = palaco_validators()["PCR-000.schema.json"]
    template = read_json(PALACO_FIXTURE_DIR / "FE-00001.fixture.json")
    fixture = {"registry_version": "0.1.0", "objects": []}
    for index, updater in enumerate(("Example audit team", "Other audit team", "Example audit team"), 1):
        record = copy.deepcopy(template)
        record["metadata"]["id"] = f"FE-{index:05d}"
        record["audit"]["updated_by"] = updater
        fixture["objects"].insert(0, record)
    original = copy.deepcopy(fixture)
    scope = "supplied updater metadata only; not authenticated identity, audit evidence or authority"
    for updater, expected in (
        ("Example audit team", ["FE-00001", "FE-00003"]),
        ("Other audit team", ["FE-00002"]),
        ("example audit team", []),
        (" Example audit team ", []),
        ("Unknown audit team", []),
        (template["ownership"]["custodian"], []),
    ):
        result = find_palaco_updater(fixture, updater, validator)
        require(result == {"updated_by": updater, "object_ids": expected, "scope": scope},
                f"incorrect updater query: {result}")
        reordered = copy.deepcopy(fixture)
        reordered["objects"].reverse()
        require(find_palaco_updater(reordered, updater, validator) == result,
                "updater query depends on record order")
    require(fixture == original, "updater query mutated input")
    invalid_ref = copy.deepcopy(fixture)
    invalid_ref["objects"][1]["traceability"]["upstream"] = ["FE-99999"]
    invalid_updater = copy.deepcopy(fixture)
    invalid_updater["objects"][1]["audit"]["updated_by"] = " "
    duplicate = copy.deepcopy(fixture)
    duplicate["objects"].append(copy.deepcopy(duplicate["objects"][0]))
    for instance, updater, diagnostic in (
        (fixture, "", "updater must"),
        (fixture, " \t\n", "updater must"),
        (fixture, None, "updater must"),
        (fixture, 42, "updater must"),
        ({}, "Example audit team", "registry structure"),
        (invalid_ref, "Example audit team", "unresolved"),
        (invalid_updater, "Example audit team", "registry structure"),
        (duplicate, "Example audit team", "duplicate object ID"),
    ):
        try:
            find_palaco_updater(instance, updater, validator)
        except ConformanceError as error:
            require(diagnostic in str(error), f"unexpected updater error: {error}")
        else:
            raise ConformanceError(f"invalid updater query accepted: {diagnostic}")
    fixture_path = str(PALACO_FIXTURE_DIR / "registry.fixture.json")
    script = [sys.executable, str(Path(__file__).resolve())]
    base = script + ["--registry", fixture_path]
    for updater, expected in (
        ("Example registry team", ["CAP-00001", "FE-00001", "REQ-00001"]),
        ("Unknown audit team", []),
    ):
        cli = subprocess.run(base + ["--find-updater", updater],
                             capture_output=True, text=True, timeout=30)
        require(cli.returncode == 0, f"updater CLI failed: {cli.stdout}{cli.stderr}")
        require(json.loads(cli.stdout) == {"updated_by": updater, "object_ids": expected, "scope": scope},
                "incorrect updater CLI result")
    for flags in (
        ["--find-relationship", "DEPENDS_ON"], ["--find-availability", "Medium"],
        ["--find-integrity", "High"], ["--find-confidentiality", "Public"],
        ["--find-criticality", "High"], ["--find-owner", "custodian", "Example registry team"],
        ["--find-approval", "Pending"], ["--find-verification", "Pending"],
        ["--find-domain", "Governance"], ["--find-type", "FE"], ["--find-lifecycle", "Draft"],
        ["--find-review-due", "2027-01-15"], ["--summary"], ["--trace", "FE-00001"],
        ["--find-orphans"], ["--find-unverified-controls"], ["--find-unaudited-evidence"],
        ["--previous-registry", fixture_path], ["--diff"], ["--direction", "upstream"],
    ):
        rejected = subprocess.run(base + ["--find-updater", "Example registry team"] + flags,
                                  capture_output=True, text=True, timeout=30)
        require(rejected.returncode == 2 and not rejected.stdout,
                f"updater query accepted incompatible flags: {flags}")
    for arguments, code in (
        (script + ["--find-updater", "Example registry team"], 2),
        (base + ["--find-updater", " "], 1),
    ):
        rejected = subprocess.run(arguments, capture_output=True, text=True, timeout=30)
        require(rejected.returncode == code and '"object_ids"' not in rejected.stdout,
                "updater CLI accepted missing registry or blank updater")
    return "6 exact/empty/sorted/non-mutating queries + 8 rejections + CLI/conflict regressions"


def check_palaco_relationship():
    validators = palaco_validators()
    fixture = read_json(PALACO_FIXTURE_DIR / "registry.fixture.json")
    objective = read_json(PALACO_FIXTURE_DIR / "FE-00001.fixture.json")
    objective["object_type"] = "OBJ"
    objective["metadata"]["id"] = "OBJ-00001"
    fixture["objects"].append(objective)
    requirement = fixture["objects"][2]
    requirement["traceability"]["relationships"].extend([
        {"source": "REQ-00001", "relation": "DEPENDS_ON", "target": "FE-00001"},
        {"source": "REQ-00001", "relation": "SATISFIES", "target": "OBJ-00001"},
    ])
    original = copy.deepcopy(fixture)
    scope = "supplied explicit relationship sources only; no inferred links or proof of compliance or authority"
    values = validators["PMS-002.schema.json"].schema["properties"]["relation"]["enum"]
    for relation in values:
        expected = {"DEPENDS_ON": ["CAP-00001", "REQ-00001"], "SATISFIES": ["REQ-00001"]}.get(relation, [])
        result = find_palaco_relationship(fixture, relation, validators)
        require(result == {"relation": relation, "object_ids": expected, "scope": scope},
                f"incorrect relationship query: {result}")
        reordered = copy.deepcopy(fixture)
        reordered["objects"].reverse()
        for record in reordered["objects"]:
            record["traceability"]["relationships"].reverse()
        require(find_palaco_relationship(reordered, relation, validators) == result,
                "relationship query depends on record or edge order")
    require(fixture == original, "relationship query mutated input")
    implicit = copy.deepcopy(fixture)
    for record in implicit["objects"]:
        record["traceability"]["relationships"] = []
    implicit["objects"][2]["dependencies"] = ["FE-00001"]
    require(find_palaco_relationship(implicit, "DEPENDS_ON", validators)["object_ids"] == [],
            "relationship query inferred edges from upstream or dependencies")
    invalid_ref = copy.deepcopy(fixture)
    invalid_ref["objects"][-1]["traceability"]["upstream"] = ["FE-99999"]
    invalid_source = copy.deepcopy(fixture)
    invalid_source["objects"][1]["traceability"]["relationships"][0]["source"] = "REQ-00001"
    invalid_type = copy.deepcopy(fixture)
    invalid_type["objects"][1]["traceability"]["relationships"][0]["relation"] = "SATISFIES"
    duplicate = copy.deepcopy(fixture)
    duplicate["objects"].append(copy.deepcopy(duplicate["objects"][0]))
    for instance, relation, diagnostic in (
        (fixture, "depends_on", "unknown PALACO relationship"),
        (fixture, "RELATED_TO", "unknown PALACO relationship"),
        (fixture, "", "unknown PALACO relationship"),
        ({}, "DEPENDS_ON", "registry structure"),
        (invalid_ref, "SATISFIES", "unresolved"),
        (invalid_source, "SATISFIES", "source"),
        (invalid_type, "SATISFIES", "registry structure"),
        (duplicate, "SATISFIES", "duplicate object ID"),
    ):
        try:
            find_palaco_relationship(instance, relation, validators)
        except ConformanceError as error:
            require(diagnostic in str(error), f"unexpected relationship error: {error}")
        else:
            raise ConformanceError(f"invalid relationship query accepted: {diagnostic}")
    fixture_path = str(PALACO_FIXTURE_DIR / "registry.fixture.json")
    script = [sys.executable, str(Path(__file__).resolve())]
    base = script + ["--registry", fixture_path]
    for relation, expected in (("DEPENDS_ON", ["CAP-00001", "REQ-00001"]), ("SATISFIES", [])):
        cli = subprocess.run(base + ["--find-relationship", relation],
                             capture_output=True, text=True, timeout=30)
        require(cli.returncode == 0, f"relationship CLI failed: {cli.stdout}{cli.stderr}")
        require(json.loads(cli.stdout) == {"relation": relation, "object_ids": expected, "scope": scope},
                "incorrect relationship CLI result")
    for flags in (
        ["--find-availability", "Medium"], ["--find-integrity", "High"],
        ["--find-confidentiality", "Public"], ["--find-criticality", "High"],
        ["--find-owner", "custodian", "Example registry team"], ["--find-approval", "Pending"],
        ["--find-verification", "Pending"], ["--find-domain", "Governance"],
        ["--find-type", "FE"], ["--find-lifecycle", "Draft"], ["--find-review-due", "2027-01-15"],
        ["--summary"], ["--trace", "FE-00001"], ["--find-orphans"],
        ["--find-unverified-controls"], ["--find-unaudited-evidence"],
        ["--previous-registry", fixture_path], ["--diff"], ["--direction", "upstream"],
    ):
        rejected = subprocess.run(base + ["--find-relationship", "DEPENDS_ON"] + flags,
                                  capture_output=True, text=True, timeout=30)
        require(rejected.returncode == 2 and not rejected.stdout,
                f"relationship query accepted incompatible flags: {flags}")
    for arguments, code in (
        (script + ["--find-relationship", "DEPENDS_ON"], 2),
        (base + ["--find-relationship", "depends_on"], 1),
    ):
        rejected = subprocess.run(arguments, capture_output=True, text=True, timeout=30)
        require(rejected.returncode == code and '"object_ids"' not in rejected.stdout,
                "relationship CLI accepted missing registry or unknown relation")
    return "10 relation labels + explicit-only/sorted/non-mutating checks + 8 rejections + CLI/conflict regressions"


def check_palaco_availability():
    validators = palaco_validators()
    template = read_json(PALACO_FIXTURE_DIR / "FE-00001.fixture.json")
    values = validators["PMS-001.schema.json"].schema["$defs"]["Classification"]["properties"]["availability"]["enum"]
    fixture = {"registry_version": "0.1.0", "objects": []}
    for index, value in enumerate(values, 1):
        record = copy.deepcopy(template)
        record["metadata"]["id"] = f"FE-{index:05d}"
        record["classification"]["availability"] = value
        fixture["objects"].append(record)
    extra = copy.deepcopy(fixture["objects"][0])
    extra["metadata"]["id"] = "FE-00004"
    fixture["objects"].insert(0, extra)
    original = copy.deepcopy(fixture)
    scope = "supplied availability-classification metadata only; not proof of uptime, SLA compliance or authority"
    for index, value in enumerate(values, 1):
        expected = [f"FE-{index:05d}"]
        if value == "Low":
            expected.append("FE-00004")
        result = find_palaco_availability(fixture, value, validators)
        require(result == {"availability": value, "object_ids": expected, "scope": scope},
                f"incorrect availability query: {result}")
        reordered = copy.deepcopy(fixture)
        reordered["objects"].reverse()
        require(find_palaco_availability(reordered, value, validators) == result,
                "availability query depends on record order")
    require(fixture == original, "availability query mutated input")
    single = {"registry_version": "0.1.0", "objects": [copy.deepcopy(template)]}
    require(find_palaco_availability(single, "Low", validators)["object_ids"] == [],
            "availability query without matches must be empty")
    invalid_ref = copy.deepcopy(fixture)
    invalid_ref["objects"][-1]["traceability"]["upstream"] = ["FE-99999"]
    invalid_value = copy.deepcopy(fixture)
    invalid_value["objects"][-1]["classification"]["availability"] = "Critical"
    duplicate = copy.deepcopy(fixture)
    duplicate["objects"].append(copy.deepcopy(duplicate["objects"][0]))
    for instance, value, diagnostic in (
        (fixture, "low", "unknown PALACO availability"),
        (fixture, "Critical", "unknown PALACO availability"),
        (fixture, "", "unknown PALACO availability"),
        ({}, "Low", "registry structure"),
        (invalid_ref, "Low", "unresolved"),
        (invalid_value, "Low", "registry structure"),
        (duplicate, "Low", "duplicate object ID"),
    ):
        try:
            find_palaco_availability(instance, value, validators)
        except ConformanceError as error:
            require(diagnostic in str(error), f"unexpected availability error: {error}")
        else:
            raise ConformanceError(f"invalid availability query accepted: {diagnostic}")
    fixture_path = str(PALACO_FIXTURE_DIR / "registry.fixture.json")
    script = [sys.executable, str(Path(__file__).resolve())]
    base = script + ["--registry", fixture_path]
    cli = subprocess.run(base + ["--find-availability", "Medium"],
                         capture_output=True, text=True, timeout=30)
    require(cli.returncode == 0, f"availability CLI failed: {cli.stdout}{cli.stderr}")
    require(json.loads(cli.stdout) == {
        "availability": "Medium", "object_ids": ["CAP-00001", "FE-00001", "REQ-00001"], "scope": scope,
    }, "incorrect availability CLI result")
    for flags in (
        ["--find-integrity", "High"], ["--find-confidentiality", "Public"],
        ["--find-criticality", "High"], ["--find-owner", "custodian", "Example registry team"],
        ["--find-approval", "Pending"], ["--find-verification", "Pending"],
        ["--find-domain", "Governance"], ["--find-type", "FE"], ["--find-lifecycle", "Draft"],
        ["--find-review-due", "2027-01-15"], ["--summary"], ["--trace", "FE-00001"],
        ["--find-orphans"], ["--find-unverified-controls"], ["--find-unaudited-evidence"],
        ["--previous-registry", fixture_path], ["--diff"], ["--direction", "upstream"],
    ):
        rejected = subprocess.run(base + ["--find-availability", "Medium"] + flags,
                                  capture_output=True, text=True, timeout=30)
        require(rejected.returncode == 2 and not rejected.stdout,
                f"availability query accepted incompatible flags: {flags}")
    missing = subprocess.run(script + ["--find-availability", "Medium"],
                             capture_output=True, text=True, timeout=30)
    require(missing.returncode == 2 and not missing.stdout, "availability query accepted missing registry")
    return "3 labels + empty/sorted/non-mutating checks + 7 rejections + CLI/conflict regressions"


def check_palaco_integrity():
    validators = palaco_validators()
    template = read_json(PALACO_FIXTURE_DIR / "FE-00001.fixture.json")
    values = validators["PMS-001.schema.json"].schema["$defs"]["Classification"]["properties"]["integrity"]["enum"]
    fixture = {"registry_version": "0.1.0", "objects": []}
    for index, value in enumerate(values, 1):
        record = copy.deepcopy(template)
        record["metadata"]["id"] = f"FE-{index:05d}"
        record["classification"]["integrity"] = value
        fixture["objects"].append(record)
    extra = copy.deepcopy(fixture["objects"][0])
    extra["metadata"]["id"] = "FE-00004"
    fixture["objects"].insert(0, extra)
    original = copy.deepcopy(fixture)
    scope = "supplied integrity-classification metadata only; not proof of data integrity, compliance or authority"
    for index, value in enumerate(values, 1):
        expected = [f"FE-{index:05d}"]
        if value == "Low":
            expected.append("FE-00004")
        result = find_palaco_integrity(fixture, value, validators)
        require(result == {"integrity": value, "object_ids": expected, "scope": scope},
                f"incorrect integrity query: {result}")
        reordered = copy.deepcopy(fixture)
        reordered["objects"].reverse()
        require(find_palaco_integrity(reordered, value, validators) == result,
                "integrity query depends on record order")
    require(fixture == original, "integrity query mutated input")
    single = {"registry_version": "0.1.0", "objects": [copy.deepcopy(template)]}
    require(find_palaco_integrity(single, "Low", validators)["object_ids"] == [],
            "integrity query without matches must be empty")
    invalid_ref = copy.deepcopy(fixture)
    invalid_ref["objects"][-1]["traceability"]["upstream"] = ["FE-99999"]
    invalid_value = copy.deepcopy(fixture)
    invalid_value["objects"][-1]["classification"]["integrity"] = "Critical"
    duplicate = copy.deepcopy(fixture)
    duplicate["objects"].append(copy.deepcopy(duplicate["objects"][0]))
    for instance, value, diagnostic in (
        (fixture, "low", "unknown PALACO integrity"),
        (fixture, "Critical", "unknown PALACO integrity"),
        (fixture, "", "unknown PALACO integrity"),
        ({}, "Low", "registry structure"),
        (invalid_ref, "Low", "unresolved"),
        (invalid_value, "Low", "registry structure"),
        (duplicate, "Low", "duplicate object ID"),
    ):
        try:
            find_palaco_integrity(instance, value, validators)
        except ConformanceError as error:
            require(diagnostic in str(error), f"unexpected integrity error: {error}")
        else:
            raise ConformanceError(f"invalid integrity query accepted: {diagnostic}")
    fixture_path = str(PALACO_FIXTURE_DIR / "registry.fixture.json")
    script = [sys.executable, str(Path(__file__).resolve())]
    base = script + ["--registry", fixture_path]
    cli = subprocess.run(base + ["--find-integrity", "High"],
                         capture_output=True, text=True, timeout=30)
    require(cli.returncode == 0, f"integrity CLI failed: {cli.stdout}{cli.stderr}")
    require(json.loads(cli.stdout) == {
        "integrity": "High", "object_ids": ["CAP-00001", "FE-00001", "REQ-00001"], "scope": scope,
    }, "incorrect integrity CLI result")
    for flags in (
        ["--find-confidentiality", "Public"], ["--find-criticality", "High"],
        ["--find-owner", "custodian", "Example registry team"], ["--find-approval", "Pending"],
        ["--find-verification", "Pending"], ["--find-domain", "Governance"], ["--find-type", "FE"],
        ["--find-lifecycle", "Draft"], ["--find-review-due", "2027-01-15"], ["--summary"],
        ["--trace", "FE-00001"], ["--find-orphans"], ["--find-unverified-controls"],
        ["--find-unaudited-evidence"], ["--previous-registry", fixture_path],
        ["--diff"], ["--direction", "upstream"],
    ):
        rejected = subprocess.run(base + ["--find-integrity", "High"] + flags,
                                  capture_output=True, text=True, timeout=30)
        require(rejected.returncode == 2 and not rejected.stdout,
                f"integrity query accepted incompatible flags: {flags}")
    missing = subprocess.run(script + ["--find-integrity", "High"],
                             capture_output=True, text=True, timeout=30)
    require(missing.returncode == 2 and not missing.stdout, "integrity query accepted missing registry")
    return "3 labels + empty/sorted/non-mutating checks + 7 rejections + CLI/conflict regressions"


def check_palaco_confidentiality():
    validators = palaco_validators()
    template = read_json(PALACO_FIXTURE_DIR / "FE-00001.fixture.json")
    values = validators["PMS-001.schema.json"].schema["$defs"]["Classification"]["properties"]["confidentiality"]["enum"]
    fixture = {"registry_version": "0.1.0", "objects": []}
    for index, value in enumerate(values, 1):
        record = copy.deepcopy(template)
        record["metadata"]["id"] = f"FE-{index:05d}"
        record["classification"]["confidentiality"] = value
        fixture["objects"].append(record)
    extra = copy.deepcopy(fixture["objects"][0])
    extra["metadata"]["id"] = "FE-00005"
    fixture["objects"].insert(0, extra)
    original = copy.deepcopy(fixture)
    scope = "supplied confidentiality metadata only; not access control, disclosure permission or authority"
    for index, value in enumerate(values, 1):
        expected = [f"FE-{index:05d}"]
        if value == "Public":
            expected.append("FE-00005")
        result = find_palaco_confidentiality(fixture, value, validators)
        require(result == {"confidentiality": value, "object_ids": expected, "scope": scope},
                f"incorrect confidentiality query: {result}")
        reordered = copy.deepcopy(fixture)
        reordered["objects"].reverse()
        require(find_palaco_confidentiality(reordered, value, validators) == result,
                "confidentiality query depends on record order")
    require(fixture == original, "confidentiality query mutated input")
    single = {"registry_version": "0.1.0", "objects": [copy.deepcopy(template)]}
    require(find_palaco_confidentiality(single, "Restricted", validators)["object_ids"] == [],
            "confidentiality query without matches must be empty")
    invalid_ref = copy.deepcopy(fixture)
    invalid_ref["objects"][-1]["traceability"]["upstream"] = ["FE-99999"]
    invalid_value = copy.deepcopy(fixture)
    invalid_value["objects"][-1]["classification"]["confidentiality"] = "Unknown"
    duplicate = copy.deepcopy(fixture)
    duplicate["objects"].append(copy.deepcopy(duplicate["objects"][0]))
    for instance, value, diagnostic in (
        (fixture, "public", "unknown PALACO confidentiality"),
        (fixture, "Unknown", "unknown PALACO confidentiality"),
        (fixture, "", "unknown PALACO confidentiality"),
        ({}, "Public", "registry structure"),
        (invalid_ref, "Public", "unresolved"),
        (invalid_value, "Public", "registry structure"),
        (duplicate, "Public", "duplicate object ID"),
    ):
        try:
            find_palaco_confidentiality(instance, value, validators)
        except ConformanceError as error:
            require(diagnostic in str(error), f"unexpected confidentiality error: {error}")
        else:
            raise ConformanceError(f"invalid confidentiality query accepted: {diagnostic}")
    fixture_path = str(PALACO_FIXTURE_DIR / "registry.fixture.json")
    base = [sys.executable, str(Path(__file__).resolve()), "--registry", fixture_path]
    cli = subprocess.run(base + ["--find-confidentiality", "Public"],
                         capture_output=True, text=True, timeout=30)
    require(cli.returncode == 0, f"confidentiality CLI failed: {cli.stdout}{cli.stderr}")
    require(json.loads(cli.stdout) == {
        "confidentiality": "Public", "object_ids": ["FE-00001"], "scope": scope,
    }, "incorrect confidentiality CLI result")
    for flags in (
        ["--find-criticality", "High"], ["--find-owner", "custodian", "Example registry team"],
        ["--find-approval", "Pending"], ["--find-verification", "Pending"],
        ["--find-domain", "Governance"], ["--find-type", "FE"], ["--find-lifecycle", "Draft"],
        ["--find-review-due", "2027-01-15"], ["--summary"], ["--trace", "FE-00001"],
        ["--find-orphans"], ["--find-unverified-controls"], ["--find-unaudited-evidence"],
        ["--previous-registry", fixture_path], ["--diff"], ["--direction", "upstream"],
    ):
        rejected = subprocess.run(base + ["--find-confidentiality", "Public"] + flags,
                                  capture_output=True, text=True, timeout=30)
        require(rejected.returncode == 2 and not rejected.stdout,
                f"confidentiality query accepted incompatible flags: {flags}")
    missing_registry = subprocess.run(
        [sys.executable, str(Path(__file__).resolve()), "--find-confidentiality", "Public"],
        capture_output=True, text=True, timeout=30,
    )
    require(missing_registry.returncode == 2 and not missing_registry.stdout,
            "confidentiality query accepted missing registry")
    return "4 labels + empty/sorted/non-mutating checks + 7 rejections + CLI/conflict regressions"


def check_palaco_criticality():
    validators = palaco_validators()
    template = read_json(PALACO_FIXTURE_DIR / "FE-00001.fixture.json")
    values = validators["PMS-001.schema.json"].schema["$defs"]["Classification"]["properties"]["criticality"]["enum"]
    fixture = {"registry_version": "0.1.0", "objects": []}
    for index, value in enumerate(values, 1):
        record = copy.deepcopy(template)
        record["metadata"]["id"] = f"FE-{index:05d}"
        record["classification"]["criticality"] = value
        fixture["objects"].append(record)
    extra = copy.deepcopy(fixture["objects"][0])
    extra["metadata"]["id"] = "FE-00005"
    fixture["objects"].insert(0, extra)
    original = copy.deepcopy(fixture)
    scope = "supplied criticality metadata only; not proof of risk assessment, compliance or authority"
    for index, value in enumerate(values, 1):
        expected = [f"FE-{index:05d}"]
        if value == "Low":
            expected.append("FE-00005")
        result = find_palaco_criticality(fixture, value, validators)
        require(result == {"criticality": value, "object_ids": expected, "scope": scope},
                f"incorrect criticality query: {result}")
        reordered = copy.deepcopy(fixture)
        reordered["objects"].reverse()
        require(find_palaco_criticality(reordered, value, validators) == result,
                "criticality query depends on record order")
    require(fixture == original, "criticality query mutated input")
    single = {"registry_version": "0.1.0", "objects": [copy.deepcopy(template)]}
    require(find_palaco_criticality(single, "Critical", validators)["object_ids"] == [],
            "criticality query without matches must be empty")
    invalid_ref = copy.deepcopy(fixture)
    invalid_ref["objects"][-1]["traceability"]["upstream"] = ["FE-99999"]
    invalid_value = copy.deepcopy(fixture)
    invalid_value["objects"][-1]["classification"]["criticality"] = "Unknown"
    duplicate = copy.deepcopy(fixture)
    duplicate["objects"].append(copy.deepcopy(duplicate["objects"][0]))
    for instance, value, diagnostic in (
        (fixture, "low", "unknown PALACO criticality"),
        (fixture, "Unknown", "unknown PALACO criticality"),
        (fixture, "", "unknown PALACO criticality"),
        ({}, "Low", "registry structure"),
        (invalid_ref, "Low", "unresolved"),
        (invalid_value, "Low", "registry structure"),
        (duplicate, "Low", "duplicate object ID"),
    ):
        try:
            find_palaco_criticality(instance, value, validators)
        except ConformanceError as error:
            require(diagnostic in str(error), f"unexpected criticality error: {error}")
        else:
            raise ConformanceError(f"invalid criticality query accepted: {diagnostic}")
    base = [sys.executable, str(Path(__file__).resolve()), "--registry",
            str(PALACO_FIXTURE_DIR / "registry.fixture.json")]
    cli = subprocess.run(base + ["--find-criticality", "High"],
                         capture_output=True, text=True, timeout=30)
    require(cli.returncode == 0, f"criticality CLI failed: {cli.stdout}{cli.stderr}")
    require(json.loads(cli.stdout) == {
        "criticality": "High", "object_ids": ["CAP-00001", "FE-00001", "REQ-00001"], "scope": scope,
    }, "incorrect criticality CLI result")
    for flags in (
        ["--find-owner", "custodian", "Example registry team"], ["--find-approval", "Pending"],
        ["--find-verification", "Pending"], ["--find-domain", "Governance"],
        ["--find-type", "FE"], ["--find-lifecycle", "Draft"],
        ["--find-review-due", "2027-01-15"], ["--summary"], ["--trace", "FE-00001"],
        ["--find-orphans"], ["--find-unverified-controls"], ["--find-unaudited-evidence"],
        ["--previous-registry", str(PALACO_FIXTURE_DIR / "registry.fixture.json")],
        ["--diff"], ["--direction", "upstream"],
    ):
        rejected = subprocess.run(base + ["--find-criticality", "High"] + flags,
                                  capture_output=True, text=True, timeout=30)
        require(rejected.returncode == 2 and not rejected.stdout,
                f"criticality query accepted incompatible flags: {flags}")
    return "4 criticalities + empty/sorted/non-mutating checks + 7 rejections + CLI/conflict regressions"


def check_palaco_owner():
    validators = palaco_validators()
    template = read_json(PALACO_FIXTURE_DIR / "FE-00001.fixture.json")
    roles = validators["PMS-001.schema.json"].schema["$defs"]["Ownership"]["properties"]
    fixture = {"registry_version": "0.1.0", "objects": []}
    for index in (2, 1):
        record = copy.deepcopy(template)
        record["metadata"]["id"] = f"FE-{index:05d}"
        for role in roles:
            record["ownership"][role] = f"Synthetic {role} team"
        fixture["objects"].append(record)
    other = copy.deepcopy(template)
    other["metadata"]["id"] = "FE-00003"
    other["ownership"]["business"] = "synthetic business team"
    other["ownership"]["technical"] = "Synthetic business team"
    fixture["objects"].append(other)
    original = copy.deepcopy(fixture)
    for role in roles:
        result = find_palaco_owner(fixture, role, f"Synthetic {role} team", validators)
        require(result == {
            "role": role, "owner": f"Synthetic {role} team",
            "object_ids": ["FE-00001", "FE-00002"],
            "scope": "supplied ownership metadata only; not proof of identity, accountability or authority",
        }, f"incorrect ownership query: {result}")
        reordered = copy.deepcopy(fixture)
        reordered["objects"].reverse()
        require(find_palaco_owner(reordered, role, f"Synthetic {role} team", validators) == result,
                "ownership query depends on record order")
    require(fixture == original, "ownership query mutated input")
    for owner, expected in (
        ("Missing", []), ("synthetic business team", ["FE-00003"]),
        (" Synthetic business team ", []),
    ):
        require(find_palaco_owner(fixture, "business", owner, validators)["object_ids"] == expected,
                "ownership matching must be exact and role-specific")
    invalid = copy.deepcopy(fixture)
    invalid["objects"][-1]["traceability"]["upstream"] = ["FE-99999"]
    missing_role = copy.deepcopy(fixture)
    del missing_role["objects"][-1]["ownership"]["custodian"]
    duplicate = copy.deepcopy(fixture)
    duplicate["objects"].append(copy.deepcopy(duplicate["objects"][0]))
    for instance, role, owner, diagnostic in (
        (fixture, "Business", "Synthetic business team", "unknown PALACO ownership role"),
        (fixture, "unknown", "Synthetic business team", "unknown PALACO ownership role"),
        (fixture, "business", "", "non-empty string"),
        (fixture, "business", " \t", "non-empty string"),
        ({}, "business", "Synthetic business team", "registry structure"),
        (invalid, "business", "Synthetic business team", "unresolved"),
        (missing_role, "business", "Synthetic business team", "registry structure"),
        (duplicate, "business", "Synthetic business team", "duplicate object ID"),
    ):
        try:
            find_palaco_owner(instance, role, owner, validators)
        except ConformanceError as error:
            require(diagnostic in str(error), f"unexpected ownership query error: {error}")
        else:
            raise ConformanceError(f"invalid ownership query accepted: {diagnostic}")
    cli = subprocess.run(
        [sys.executable, str(Path(__file__).resolve()), "--registry",
         str(PALACO_FIXTURE_DIR / "registry.fixture.json"),
         "--find-owner", "custodian", "Example registry team"],
        capture_output=True, text=True, timeout=30,
    )
    require(cli.returncode == 0, f"ownership CLI failed: {cli.stdout}{cli.stderr}")
    require(json.loads(cli.stdout)["object_ids"] == ["CAP-00001", "FE-00001", "REQ-00001"],
            "incorrect ownership CLI result")
    return "5 role queries + exact/empty/non-mutating/order checks + 8 rejections + CLI regression"


def check_palaco_approval():
    validators = palaco_validators()
    template = read_json(PALACO_FIXTURE_DIR / "FE-00001.fixture.json")
    statuses = validators["PMS-001.schema.json"].schema["$defs"]["Approval"]["properties"]["status"]["enum"]
    fixture = {"registry_version": "0.1.0", "objects": []}
    for index, status in enumerate(statuses, 1):
        record = copy.deepcopy(template)
        record["metadata"]["id"] = f"FE-{index:05d}"
        record["approval"]["status"] = status
        if status == "Approved":
            record["approval"].update(
                authority="Synthetic review team", approval_ref="Synthetic approval-query fixture",
            )
            record["lifecycle"]["approved"] = record["lifecycle"]["created"]
        fixture["objects"].append(record)
    extra = copy.deepcopy(fixture["objects"][0])
    extra["metadata"]["id"] = "FE-00004"
    fixture["objects"].insert(0, extra)
    original = copy.deepcopy(fixture)
    for index, status in enumerate(statuses, 1):
        expected = [f"FE-{index:05d}"]
        if status == "Pending":
            expected.append("FE-00004")
        result = find_palaco_approval(fixture, status, validators)
        require(result == {
            "approval_status": status,
            "object_ids": expected,
            "scope": "supplied approval-status metadata only; not proof of approval authenticity, activation or authority",
        }, f"incorrect approval query: {result}")
        reordered = copy.deepcopy(fixture)
        reordered["objects"].reverse()
        require(find_palaco_approval(reordered, status, validators) == result,
                "approval query depends on record order")
    require(fixture == original, "approval query mutated input")
    single = {"registry_version": "0.1.0", "objects": [copy.deepcopy(template)]}
    require(find_palaco_approval(single, "Approved", validators)["object_ids"] == [],
            "approval query without matches must be empty")
    approved_index = next(i for i, record in enumerate(fixture["objects"])
                          if record["approval"]["status"] == "Approved")
    missing_authority = copy.deepcopy(fixture)
    del missing_authority["objects"][approved_index]["approval"]["authority"]
    missing_ref = copy.deepcopy(fixture)
    del missing_ref["objects"][approved_index]["approval"]["approval_ref"]
    missing_date = copy.deepcopy(fixture)
    del missing_date["objects"][approved_index]["lifecycle"]["approved"]
    invalid_ref = copy.deepcopy(fixture)
    invalid_ref["objects"][-1]["traceability"]["upstream"] = ["FE-99999"]
    duplicate = copy.deepcopy(fixture)
    duplicate["objects"].append(copy.deepcopy(duplicate["objects"][0]))
    for instance, status, diagnostic in (
        (fixture, "approved", "unknown PALACO approval status"),
        (fixture, "Unknown", "unknown PALACO approval status"),
        (fixture, "", "unknown PALACO approval status"),
        ({}, "Pending", "registry structure"),
        (missing_authority, "Pending", "registry structure"),
        (missing_ref, "Pending", "registry structure"),
        (missing_date, "Pending", "approved approval requires lifecycle.approved"),
        (invalid_ref, "Pending", "unresolved"),
        (duplicate, "Pending", "duplicate object ID"),
    ):
        try:
            find_palaco_approval(instance, status, validators)
        except ConformanceError as error:
            require(diagnostic in str(error), f"unexpected approval query error: {error}")
        else:
            raise ConformanceError(f"invalid approval query accepted: {diagnostic}")
    cli = subprocess.run(
        [sys.executable, str(Path(__file__).resolve()), "--registry",
         str(PALACO_FIXTURE_DIR / "registry.fixture.json"), "--find-approval", "Pending"],
        capture_output=True, text=True, timeout=30,
    )
    require(cli.returncode == 0, f"approval CLI failed: {cli.stdout}{cli.stderr}")
    require(json.loads(cli.stdout)["object_ids"] == ["CAP-00001", "FE-00001", "REQ-00001"],
            "incorrect approval CLI result")
    return "3 status queries + empty/sorted/non-mutating checks + 9 rejections + CLI regression"


def check_palaco_verification():
    validators = palaco_validators()
    template = read_json(PALACO_FIXTURE_DIR / "FE-00001.fixture.json")
    statuses = validators["PMS-001.schema.json"].schema["$defs"]["Verification"]["properties"]["status"]["enum"]
    fixture = {"registry_version": "0.1.0", "objects": []}
    for index, status in enumerate(statuses, 1):
        record = copy.deepcopy(template)
        record["metadata"]["id"] = f"FE-{index:05d}"
        record["verification"]["status"] = status
        fixture["objects"].append(record)
    extra = copy.deepcopy(fixture["objects"][0])
    extra["metadata"]["id"] = "FE-00005"
    fixture["objects"].insert(0, extra)
    verifier = copy.deepcopy(template)
    verifier["object_type"] = "VER"
    verifier["metadata"]["id"] = "VER-00001"
    verifier["verification"]["status"] = "Failed"
    fixture["objects"].append(verifier)
    next(record for record in fixture["objects"] if record["verification"]["status"] == "Passed")[
        "verification"]["verification_ref"] = "VER-00001"
    original = copy.deepcopy(fixture)
    for index, status in enumerate(statuses, 1):
        expected = [f"FE-{index:05d}"]
        if status == "Pending":
            expected.append("FE-00005")
        if status == "Failed":
            expected.append("VER-00001")
        result = find_palaco_verification(fixture, status, validators)
        require(result == {
            "verification_status": status,
            "object_ids": expected,
            "scope": "supplied verification-status metadata only; not proof of verification, compliance or authority",
        }, f"incorrect verification query: {result}")
        reordered = copy.deepcopy(fixture)
        reordered["objects"].reverse()
        require(find_palaco_verification(reordered, status, validators) == result,
                "verification query depends on record order")
    require(fixture == original, "verification query mutated input")
    single = {"registry_version": "0.1.0", "objects": [copy.deepcopy(template)]}
    require(find_palaco_verification(single, "Passed", validators)["object_ids"] == [],
            "verification query without matches must be empty")
    bad_ref = copy.deepcopy(fixture)
    bad_ref["objects"][-1]["traceability"]["upstream"] = ["FE-99999"]
    duplicate = copy.deepcopy(fixture)
    duplicate["objects"].append(copy.deepcopy(duplicate["objects"][0]))
    bad_status = copy.deepcopy(fixture)
    bad_status["objects"][-1]["verification"]["status"] = "Unknown"
    for instance, status, diagnostic in (
        (fixture, "passed", "unknown PALACO verification status"),
        (fixture, "Unknown", "unknown PALACO verification status"),
        (fixture, "", "unknown PALACO verification status"),
        ({}, "Passed", "registry structure"),
        (bad_ref, "Passed", "unresolved"),
        (duplicate, "Passed", "duplicate object ID"),
        (bad_status, "Passed", "registry structure"),
    ):
        try:
            find_palaco_verification(instance, status, validators)
        except ConformanceError as error:
            require(diagnostic in str(error), f"unexpected verification query error: {error}")
        else:
            raise ConformanceError(f"invalid verification query accepted: {diagnostic}")
    cli = subprocess.run(
        [sys.executable, str(Path(__file__).resolve()), "--registry",
         str(PALACO_FIXTURE_DIR / "registry.fixture.json"), "--find-verification", "Pending"],
        capture_output=True, text=True, timeout=30,
    )
    require(cli.returncode == 0, f"verification CLI failed: {cli.stdout}{cli.stderr}")
    require(json.loads(cli.stdout)["object_ids"] == ["CAP-00001", "FE-00001", "REQ-00001"],
            "incorrect verification CLI result")
    return "4 status queries + empty/sorted/non-mutating/own-status checks + 7 rejections + CLI regression"


def check_palaco_domain():
    validator = palaco_validators()["PCR-000.schema.json"]
    fixture = read_json(PALACO_FIXTURE_DIR / "registry.fixture.json")
    template = read_json(PALACO_FIXTURE_DIR / "FE-00001.fixture.json")
    for index, domain in ((3, "Data Platform"), (2, "Data Platform"), (4, "governance"),
                          (5, " Governance "), (6, "Données")):
        record = copy.deepcopy(template)
        record["metadata"]["id"] = f"FE-{index:05d}"
        record["metadata"]["domain"] = domain
        fixture["objects"].append(record)
    original = copy.deepcopy(fixture)
    for domain, expected in (
        ("Governance", ["FE-00001"]),
        ("Data Platform", ["FE-00002", "FE-00003"]),
        ("governance", ["FE-00004"]),
        (" Governance ", ["FE-00005"]),
        ("Données", ["FE-00006"]),
        ("Missing", []),
    ):
        result = find_palaco_domain(fixture, domain, validator)
        require(result == {
            "domain": domain, "object_ids": expected,
            "scope": "supplied domain metadata only; not a completeness, canonical-status or authority decision",
        }, f"unexpected domain query: {result}")
        reordered = copy.deepcopy(fixture)
        reordered["objects"].reverse()
        require(find_palaco_domain(reordered, domain, validator) == result,
                "domain query depends on record order")
    require(fixture == original, "domain query mutated input")
    bad_ref = copy.deepcopy(fixture)
    bad_ref["objects"][-1]["traceability"]["upstream"] = ["FE-99999"]
    duplicate = copy.deepcopy(fixture)
    duplicate["objects"].append(copy.deepcopy(duplicate["objects"][0]))
    bad_domain = copy.deepcopy(fixture)
    bad_domain["objects"][-1]["metadata"]["domain"] = ""
    for instance, domain, diagnostic in (
        (fixture, "", "non-empty string"), (fixture, None, "non-empty string"),
        (fixture, " \t", "non-empty string"),
        ({}, "Governance", "registry structure"),
        (bad_ref, "Governance", "unresolved"),
        (duplicate, "Governance", "duplicate object ID"),
        (bad_domain, "Governance", "registry structure"),
    ):
        try:
            find_palaco_domain(instance, domain, validator)
        except ConformanceError as error:
            require(diagnostic in str(error), f"unexpected domain query error: {error}")
        else:
            raise ConformanceError(f"invalid domain query accepted: {diagnostic}")
    cli = subprocess.run(
        [sys.executable, str(Path(__file__).resolve()), "--registry",
         str(PALACO_FIXTURE_DIR / "registry.fixture.json"), "--find-domain", "Governance"],
        capture_output=True, text=True, timeout=30,
    )
    require(cli.returncode == 0, f"domain CLI failed: {cli.stdout}{cli.stderr}")
    require(json.loads(cli.stdout)["object_ids"] == ["FE-00001"], "incorrect domain CLI result")
    return "6 exact/sorted/empty domain queries + 7 rejections + nonmutation/order checks + CLI regression"


def check_palaco_reviews_due():
    validator = palaco_validators()["PCR-000.schema.json"]
    template = read_json(PALACO_FIXTURE_DIR / "FE-00001.fixture.json")
    fixture = {"registry_version": "0.1.0", "objects": []}
    for index, review_date in ((3, "2027-01-16"), (2, "2027-01-15"), (1, "2027-01-14")):
        record = copy.deepcopy(template)
        record["metadata"]["id"] = f"FE-{index:05d}"
        record["lifecycle"]["next_review"] = review_date
        fixture["objects"].append(record)
    archived = fixture["objects"][-1]
    archived["lifecycle"]["status"] = "Archived"
    archived["lifecycle"]["approved"] = archived["lifecycle"]["created"]
    archived["approval"] = {
        "status": "Approved", "authority": "Synthetic review team",
        "approval_ref": "Synthetic review-date fixture",
    }
    original = copy.deepcopy(fixture)
    for as_of, expected in (
        ("2027-01-13", []),
        ("2027-01-14", ["FE-00001"]),
        ("2027-01-15", ["FE-00001", "FE-00002"]),
        ("2027-01-16", ["FE-00001", "FE-00002", "FE-00003"]),
        ("2028-02-29", ["FE-00001", "FE-00002", "FE-00003"]),
    ):
        result = find_palaco_reviews_due(fixture, as_of, validator)
        require(result == {
            "as_of": as_of,
            "definition": "lifecycle.next_review is on or before as_of; all lifecycle states included",
            "object_ids": expected,
            "scope": "supplied review-date metadata only; not proof of overdue work, compliance or authority",
        }, f"unexpected review-date result: {result}")
        reordered = copy.deepcopy(fixture)
        reordered["objects"].reverse()
        require(find_palaco_reviews_due(reordered, as_of, validator) == result,
                "review-date query depends on record order")
    require(fixture == original, "review-date query mutated input")
    for as_of in ("2027-02-29", "2027-13-01", "0000-01-01", "20270115",
                  "2027-1-15", "2027-01-15T00:00:00Z", "2027-01-15\n", "", None):
        try:
            find_palaco_reviews_due(fixture, as_of, validator)
        except ConformanceError as error:
            require("YYYY-MM-DD" in str(error), f"unexpected cutoff error: {error}")
        else:
            raise ConformanceError(f"invalid review cutoff accepted: {as_of!r}")
    bad_ref = copy.deepcopy(fixture)
    bad_ref["objects"][0]["traceability"]["upstream"] = ["FE-99999"]
    bad_date = copy.deepcopy(fixture)
    bad_date["objects"][0]["lifecycle"]["next_review"] = "2027-02-29"
    duplicate = copy.deepcopy(fixture)
    duplicate["objects"].append(copy.deepcopy(duplicate["objects"][0]))
    for instance, diagnostic in (({}, "registry structure"), (bad_ref, "unresolved"),
                                 (bad_date, "registry structure"), (duplicate, "duplicate object ID")):
        try:
            find_palaco_reviews_due(instance, "2027-01-13", validator)
        except ConformanceError as error:
            require(diagnostic in str(error), f"unexpected review-date diagnostic: {error}")
        else:
            raise ConformanceError(f"invalid snapshot queried: {diagnostic}")
    cli = subprocess.run(
        [sys.executable, str(Path(__file__).resolve()), "--registry",
         str(PALACO_FIXTURE_DIR / "registry.fixture.json"), "--find-review-due", "2027-01-15"],
        capture_output=True, text=True, timeout=30,
    )
    require(cli.returncode == 0, f"review-date CLI failed: {cli.stdout}{cli.stderr}")
    require(json.loads(cli.stdout)["object_ids"] == ["CAP-00001", "FE-00001", "REQ-00001"],
            "unexpected review-date CLI result")
    return "5 inclusive/empty/leap-date queries + 13 rejections + nonmutation/order checks + CLI regression"


def check_palaco_diff():
    validator = palaco_validators()["PCR-000.schema.json"]
    template = read_json(PALACO_FIXTURE_DIR / "FE-00001.fixture.json")
    previous = {"registry_version": "0.1.0", "objects": []}
    for index in (3, 1, 2):
        record = copy.deepcopy(template)
        record["metadata"]["id"] = f"FE-{index:05d}"
        previous["objects"].append(record)
    current = copy.deepcopy(previous)
    current["objects"] = [record for record in current["objects"] if record["metadata"]["id"] != "FE-00003"]
    current["objects"][0]["metadata"]["description"] = "Changed synthetic metadata"
    for index in (5, 4):
        record = copy.deepcopy(template)
        record["metadata"]["id"] = f"FE-{index:05d}"
        current["objects"].append(record)
    scope = "supplied snapshots only; diagnostic, not transition validation, authenticated history or authority"
    expected = {
        "added_ids": ["FE-00004", "FE-00005"],
        "removed_ids": ["FE-00003"],
        "changed_ids": ["FE-00001"],
        "unchanged_ids": ["FE-00002"],
        "scope": scope,
    }
    originals = copy.deepcopy((previous, current))
    require(diff_palaco_registry(previous, current, validator) == expected, "incorrect mixed snapshot diff")
    require((previous, current) == originals, "snapshot diff mutated input")
    reversed_previous = copy.deepcopy(previous)
    reversed_current = copy.deepcopy(current)
    reversed_previous["objects"].reverse()
    reversed_current["objects"].reverse()
    require(diff_palaco_registry(reversed_previous, reversed_current, validator) == expected,
            "snapshot diff depends on record order")
    identical = {
        "added_ids": [], "removed_ids": [], "changed_ids": [],
        "unchanged_ids": ["FE-00001", "FE-00002", "FE-00003"], "scope": scope,
    }
    require(diff_palaco_registry(previous, reversed_previous, validator) == identical,
            "identical snapshots must report unchanged IDs")
    backwards = copy.deepcopy(previous)
    backwards["objects"][1]["lifecycle"]["status"] = "Proposed"
    require(diff_palaco_registry(previous, backwards, validator)["changed_ids"] == ["FE-00001"],
            "diagnostic diff must not enforce lifecycle transitions")
    key_reordered = copy.deepcopy(previous)
    key_reordered["objects"][0] = dict(reversed(list(key_reordered["objects"][0].items())))
    require(diff_palaco_registry(previous, key_reordered, validator) == identical,
            "object key order must not count as a change")
    nested = copy.deepcopy(previous)
    nested["objects"][1]["traceability"]["upstream"] = ["FE-00002", "FE-00003"]
    reordered_array = copy.deepcopy(nested)
    reordered_array["objects"][1]["traceability"]["upstream"].reverse()
    require(diff_palaco_registry(nested, reordered_array, validator)["changed_ids"] == ["FE-00001"],
            "nested array order must count as a change")
    disjoint = {"registry_version": "0.1.0", "objects": [copy.deepcopy(current["objects"][-1])]}
    disjoint_result = diff_palaco_registry(previous, disjoint, validator)
    require(disjoint_result["added_ids"] == ["FE-00004"]
            and disjoint_result["removed_ids"] == identical["unchanged_ids"]
            and disjoint_result["changed_ids"] == [] and disjoint_result["unchanged_ids"] == [],
            "incorrect disjoint snapshot diff")
    invalid_ref = copy.deepcopy(previous)
    invalid_ref["objects"][0]["traceability"]["upstream"] = ["FE-99999"]
    duplicate = copy.deepcopy(previous)
    duplicate["objects"].append(copy.deepcopy(duplicate["objects"][0]))
    cyclic = copy.deepcopy(previous)
    cyclic["objects"][0]["traceability"]["upstream"] = ["FE-00001"]
    cyclic["objects"][1]["traceability"]["upstream"] = ["FE-00003"]
    unapproved = copy.deepcopy(previous)
    unapproved["objects"][0]["lifecycle"]["status"] = "Active"
    for invalid, diagnostic in (
        ({}, "registry structure"),
        ({"registry_version": "0.1.0", "objects": []}, "registry structure"),
        (invalid_ref, "unresolved"),
        (duplicate, "duplicate object ID"),
        (cyclic, "upstream cycle"),
        (unapproved, "requires approval.status Approved"),
    ):
        for label in ("previous", "current"):
            pair = (invalid, current) if label == "previous" else (previous, invalid)
            try:
                diff_palaco_registry(*pair, validator)
            except ConformanceError as error:
                require(f"{label} registry:" in str(error) and diagnostic in str(error),
                        f"unexpected snapshot diff diagnostic: {error}")
            else:
                raise ConformanceError(f"invalid {label} snapshot diff accepted")
    fixture_path = str(PALACO_FIXTURE_DIR / "registry.fixture.json")
    cli = subprocess.run(
        [sys.executable, str(Path(__file__).resolve()), "--registry", fixture_path,
         "--previous-registry", fixture_path, "--diff"],
        capture_output=True, text=True, timeout=30,
    )
    require(cli.returncode == 0, f"snapshot diff CLI failed: {cli.stdout}{cli.stderr}")
    require(json.loads(cli.stdout) == {
        "added_ids": [], "removed_ids": [], "changed_ids": [],
        "unchanged_ids": ["CAP-00001", "FE-00001", "REQ-00001"], "scope": scope,
    }, "unexpected snapshot diff CLI result")
    return "7 deterministic/non-mutating diff cases + 12 invalid input rejections + CLI regression"


def check_palaco_component_partitions():
    nodes = [f"FE-{index:05d}" for index in range(1, 6)]
    edges = [(source, target) for index, source in enumerate(nodes)
             for target in nodes[index + 1:]]
    for mask in range(1 << len(edges)):
        graph = {node: set() for node in nodes}
        partitions = [{node} for node in nodes]
        for bit, (source, target) in enumerate(edges):
            if mask & (1 << bit):
                graph[source].add(target)
                joined = set()
                separate = []
                for partition in partitions:
                    if source in partition or target in partition:
                        joined.update(partition)
                    else:
                        separate.append(partition)
                partitions = separate + [joined]
        expected = sorted(len(partition) for partition in partitions)
        expected_members = sorted(sorted(partition) for partition in partitions)
        original = copy.deepcopy(graph)
        require(weak_components(graph) == expected_members,
                f"component members differ from partition oracle for graph {mask}")
        require(weak_component_sizes(graph) == expected,
                f"component sizes differ from partition oracle for graph {mask}")
        require(count_weak_components(graph) == len(partitions),
                f"component count differs from partition oracle for graph {mask}")
        for node in nodes:
            selected = [members for members in expected_members if node in members]
            require(weak_components(graph, node) == selected,
                    f"selected members differ from partition oracle for graph {mask}, {node}")
        require(graph == original, f"component traversal mutated graph {mask}")
        reversed_graph = {node: set() for node in reversed(nodes)}
        for source, targets in graph.items():
            for target in targets:
                reversed_graph[target].add(source)
        original = copy.deepcopy(reversed_graph)
        require(weak_components(reversed_graph) == expected_members,
                f"component members depend on direction or ordering for graph {mask}")
        require(weak_component_sizes(reversed_graph) == expected,
                f"component sizes depend on direction or ordering for graph {mask}")
        for node in nodes:
            selected = [members for members in expected_members if node in members]
            require(weak_components(reversed_graph, node) == selected,
                    f"selected members depend on direction or ordering for graph {mask}, {node}")
        require(reversed_graph == original, f"component traversal mutated reversed graph {mask}")
    return "1,024 five-node forward graphs: partitions, selected members, reversal, counts and non-mutation"


def check_palaco_cluster_fixture():
    path = PALACO_FIXTURE_DIR / "registry-clusters.fixture.json"
    original = path.read_bytes()
    fixture = read_json(path)
    summary = summarize_palaco_registry(fixture)
    require(summary["total_objects"] == 4, "cluster fixture must contain four synthetic objects")
    base = [sys.executable, str(Path(__file__).resolve()), "--registry", str(path)]
    for graph_name, expected, orphans in (
        ("upstream", [["FE-00001", "FE-00002"], ["FE-00003"], ["FE-00004"]],
         ["FE-00003", "FE-00004"]),
        ("dependency", [["FE-00001"], ["FE-00002", "FE-00003"], ["FE-00004"]],
         ["FE-00001", "FE-00004"]),
    ):
        query = find_palaco_components(fixture, graph_name)
        require(query["components"] == expected, "cluster fixture graph boundaries changed")
        require(summary[f"total_{graph_name}_components"] == 3
                and summary[f"largest_{graph_name}_component_size"] == 2
                and summary[f"total_{graph_name}_edges"] == 1
                and summary[f"total_{graph_name}_orphans"] == 2,
                "cluster fixture summary disagrees with documented example")
        find_orphans = find_palaco_orphans if graph_name == "upstream" else find_palaco_dependency_orphans
        require(find_orphans(fixture)["object_ids"] == orphans, "cluster fixture orphan IDs changed")
        for selection in ([], ["--component-of", "FE-00002"], ["--component-of", "FE-00004"]):
            cli = subprocess.run(base + ["--components", graph_name] + selection,
                                 capture_output=True, text=True, timeout=30)
            expected_query = query if not selection else find_palaco_components(
                fixture, graph_name, object_id=selection[1],
            )
            require(cli.returncode == 0 and not cli.stderr and json.loads(cli.stdout) == expected_query,
                    f"cluster fixture CLI failed: {cli.stdout}{cli.stderr}")
    cli = subprocess.run(base + ["--summary"], capture_output=True, text=True, timeout=30)
    require(cli.returncode == 0 and not cli.stderr and json.loads(cli.stdout) == summary,
            "cluster fixture summary CLI differs from library result")
    require(path.read_bytes() == original, "cluster fixture queries modified the file")
    return "synthetic cluster fixture: both graphs, selected/isolated queries, summaries and orphan IDs"


def check_palaco_components_fail_closed():
    fixture = read_json(PALACO_FIXTURE_DIR / "registry.fixture.json")
    cases = []
    duplicate = copy.deepcopy(fixture)
    duplicate["objects"].append(copy.deepcopy(duplicate["objects"][0]))
    cases.append((json.dumps(duplicate), "duplicate object ID"))
    unresolved = copy.deepcopy(fixture)
    unresolved["objects"][0]["dependencies"] = ["FE-99999"]
    cases.append((json.dumps(unresolved), "unresolved"))
    upstream_cycle = copy.deepcopy(fixture)
    upstream_cycle["objects"][0]["traceability"]["upstream"] = ["REQ-00001"]
    cases.append((json.dumps(upstream_cycle), "upstream cycle"))
    dependency_cycle = copy.deepcopy(fixture)
    dependency_cycle["objects"][0]["dependencies"] = ["REQ-00001"]
    cases.append((json.dumps(dependency_cycle), "dependency cycle"))
    outside_cluster = copy.deepcopy(fixture)
    isolated = read_json(PALACO_FIXTURE_DIR / "FE-00001.fixture.json")
    isolated["metadata"]["id"] = "FE-00002"
    isolated["dependencies"] = ["FE-99999"]
    outside_cluster["objects"].append(isolated)
    cases.append((json.dumps(outside_cluster), "unresolved"))
    cases.extend([
        (json.dumps({"registry_version": "0.1.0", "objects": []}), "registry structure"),
        ('{"registry_version": "0.1.0", "objects": [', "Expecting value"),
        ('{"objects": [], "objects": []}', "Duplicate JSON key"),
    ])
    with tempfile.TemporaryDirectory(prefix="palaco-components-", dir="/tmp") as directory:
        path = Path(directory) / "registry.json"
        script = [sys.executable, str(Path(__file__).resolve()), "--registry", str(path)]
        for content, diagnostic in cases:
            path.write_text(content, encoding="utf-8")
            original = path.read_bytes()
            for graph_name, selection in (
                (graph, selector) for graph in ("upstream", "dependency")
                for selector in ([], ["--component-of", "FE-00001"])
            ):
                cli = subprocess.run(script + ["--components", graph_name] + selection,
                                     capture_output=True, text=True, timeout=30)
                require(cli.returncode == 1 and not cli.stdout,
                        f"{graph_name} emitted results for invalid snapshot: {cli.stdout}")
                require("FAIL:" in cli.stderr and diagnostic in cli.stderr,
                        f"{graph_name} missing expected diagnostic {diagnostic}: {cli.stderr}")
                require(path.read_bytes() == original, "failed component query modified input")
        path.unlink()
        for graph_name, selection in (
            (graph, selector) for graph in ("upstream", "dependency")
            for selector in ([], ["--component-of", "FE-00001"])
        ):
            cli = subprocess.run(script + ["--components", graph_name] + selection,
                                 capture_output=True, text=True, timeout=30)
            require(cli.returncode == 1 and not cli.stdout and "FileNotFoundError" in cli.stderr,
                    "missing component snapshot did not fail cleanly")
            require(not path.exists(), "failed component query created missing snapshot")
    return "both component modes, selected/unfiltered: 8 invalid snapshots + missing file; fail-closed"


def check_palaco_components():
    validators = palaco_validators()
    template = read_json(PALACO_FIXTURE_DIR / "FE-00001.fixture.json")
    fixture = {"registry_version": "0.1.0", "objects": []}
    for index in range(1, 8):
        record = copy.deepcopy(template)
        record["metadata"]["id"] = f"FE-{index:05d}"
        fixture["objects"].append(record)
    fixture["objects"][3]["object_type"] = "EVD"
    fixture["objects"][3]["metadata"]["id"] = "EVD-00001"
    fixture["objects"][3]["audit"]["audit_refs"] = ["AUD-00001"]
    fixture["objects"][6]["object_type"] = "AUD"
    fixture["objects"][6]["metadata"]["id"] = "AUD-00001"
    fixture["objects"][6]["evidence"] = ["EVD-00001"]
    for source, targets in ((1, [2, 3]), (2, [4]), (3, [4]), (5, [6])):
        fixture["objects"][source - 1]["traceability"]["upstream"] = [
            fixture["objects"][target - 1]["metadata"]["id"] for target in targets
        ]
    fixture["objects"][0]["dependencies"] = ["FE-00005"]
    fixture["objects"][0]["traceability"]["relationships"] = [
        {"source": "FE-00001", "relation": "DEPENDS_ON", "target": "FE-00005"},
    ]
    fixture["objects"][1]["traceability"]["relationships"] = [
        {"source": "FE-00002", "relation": "DEPENDS_ON", "target": "FE-00006"},
    ]
    fixture["objects"][3]["traceability"]["relationships"] = [
        {"source": "EVD-00001", "relation": "AUDITED_BY", "target": "AUD-00001"},
    ]
    original = copy.deepcopy(fixture)
    result = summarize_palaco_registry(fixture, validators)
    require(result["total_upstream_components"] == 3,
            "upstream components must include diamond, disconnected pair and isolate")
    require(result["total_dependency_components"] == 5,
            "dependency components must use dependency union only")
    require(result["largest_upstream_component_size"] == 4
            and result["largest_dependency_component_size"] == 2,
            "largest components must count distinct nodes in each separate graph")
    for graph_name, expected in (
        ("upstream", [["AUD-00001"], ["EVD-00001", "FE-00001", "FE-00002", "FE-00003"],
                      ["FE-00005", "FE-00006"]]),
        ("dependency", [["AUD-00001"], ["EVD-00001"], ["FE-00001", "FE-00005"],
                        ["FE-00002", "FE-00006"], ["FE-00003"]]),
    ):
        query = find_palaco_components(fixture, graph_name, validators["PCR-000.schema.json"])
        require(query["components"] == expected, f"incorrect {graph_name} component members")
        for members in expected:
            for object_id in members:
                selected = find_palaco_components(fixture, graph_name, object_id=object_id)
                require(selected == {**query, "components": [members]},
                        f"incorrect component selection for {graph_name} {object_id}")
                selected["components"][0].clear()
                selected["components"].append(["FE-99999"])
                require(find_palaco_components(fixture, graph_name, object_id=object_id)
                        == {**query, "components": [members]},
                        "mutating selected query output affected a later query")
        detached = find_palaco_components(fixture, graph_name)
        detached["components"][0].append("FE-99999")
        detached["components"].clear()
        require(find_palaco_components(fixture, graph_name) == query,
                "mutating unfiltered query output affected a later query")
        require(fixture == original, "mutating component output affected snapshot")
        require(len(expected) == result[f"total_{graph_name}_components"]
                and max(map(len, expected)) == result[f"largest_{graph_name}_component_size"],
                "membership query and summary disagree")
        reordered_query = copy.deepcopy(fixture)
        reordered_query["objects"].reverse()
        for record in reordered_query["objects"]:
            record["traceability"]["upstream"].reverse()
        require(find_palaco_components(reordered_query, graph_name) == query,
                "component membership depends on input order")
        with tempfile.TemporaryDirectory(prefix="palaco-component-clusters-", dir="/tmp") as directory:
            path = Path(directory) / "registry.json"
            command = [sys.executable, str(Path(__file__).resolve()), "--registry", str(path),
                       "--components", graph_name]
            outputs = []
            for snapshot in (fixture, reordered_query):
                path.write_text(json.dumps(snapshot, indent=2), encoding="utf-8")
                original_bytes = path.read_bytes()
                cli = subprocess.run(command, capture_output=True, text=True, timeout=30)
                require(cli.returncode == 0 and not cli.stderr,
                        f"multi-cluster {graph_name} CLI failed: {cli.stdout}{cli.stderr}")
                require(json.loads(cli.stdout) == query,
                        f"multi-cluster {graph_name} CLI returned incorrect members or scope")
                require(path.read_bytes() == original_bytes,
                        f"multi-cluster {graph_name} CLI modified snapshot")
                outputs.append(cli.stdout)
                for object_id in ("FE-00002", "AUD-00001"):
                    cli = subprocess.run(command + ["--component-of", object_id],
                                         capture_output=True, text=True, timeout=30)
                    require(cli.returncode == 0 and not cli.stderr
                            and json.loads(cli.stdout) == find_palaco_components(
                                fixture, graph_name, object_id=object_id),
                            f"incorrect selected component CLI result: {cli.stdout}{cli.stderr}")
                    require(path.read_bytes() == original_bytes,
                            "selected component CLI modified snapshot")
            require(outputs[0] == outputs[1],
                    f"multi-cluster {graph_name} CLI output depends on input ordering")
    invalid = copy.deepcopy(fixture)
    invalid["objects"][-1]["traceability"]["upstream"] = ["FE-99999"]
    for instance, graph_name, diagnostic in (
        (fixture, "unknown", "unknown component graph"),
        (invalid, "upstream", "unresolved"),
        (invalid, "dependency", "unresolved"),
        ({}, "upstream", "registry structure"),
    ):
        try:
            find_palaco_components(instance, graph_name)
        except ConformanceError as error:
            require(diagnostic in str(error), f"unexpected component query error: {error}")
        else:
            raise ConformanceError(f"invalid component query accepted: {diagnostic}")
    for graph_name in ("upstream", "dependency"):
        for object_id in ("FE-99999", "fe-00001", "", " FE-00001"):
            try:
                find_palaco_components(fixture, graph_name, object_id=object_id)
            except ConformanceError as error:
                require("unknown component object ID" in str(error),
                        f"unexpected selected component error: {error}")
            else:
                raise ConformanceError("unknown component object accepted")
        try:
            find_palaco_components(invalid, graph_name, object_id="FE-00001")
        except ConformanceError as error:
            require("unresolved" in str(error), "selection bypassed full snapshot validation")
        else:
            raise ConformanceError("component selection accepted invalid snapshot")
    script = [sys.executable, str(Path(__file__).resolve())]
    base = script + ["--registry", str(PALACO_FIXTURE_DIR / "registry.fixture.json")]
    for graph_name in ("upstream", "dependency"):
        cli = subprocess.run(base + ["--components", graph_name],
                             capture_output=True, text=True, timeout=30)
        require(cli.returncode == 0 and json.loads(cli.stdout) == find_palaco_components(
            read_json(PALACO_FIXTURE_DIR / "registry.fixture.json"), graph_name),
            f"incorrect component CLI result: {cli.stdout}{cli.stderr}")
        cli = subprocess.run(base + ["--components", graph_name, "--component-of", "FE-99999"],
                             capture_output=True, text=True, timeout=30)
        require(cli.returncode == 1 and not cli.stdout and "unknown component object ID" in cli.stderr,
                "unknown selected component CLI did not fail cleanly")
    for flags in (
        ["--summary"], ["--find-type", "FE"], ["--trace", "FE-00001"],
        ["--find-dependency-orphans"], ["--direction", "upstream"], ["--diff"],
        ["--previous-registry", str(PALACO_FIXTURE_DIR / "registry.fixture.json")],
    ):
        for graph_name, selection in (
            (graph, selector) for graph in ("upstream", "dependency")
            for selector in ([], ["--component-of", "FE-00001"])
        ):
            cli = subprocess.run(base + ["--components", graph_name] + selection + flags,
                                 capture_output=True, text=True, timeout=30)
            require(cli.returncode == 2 and not cli.stdout and "cannot be combined" in cli.stderr,
                    f"components accepted conflicting flags: {graph_name} {selection} {flags}")
    for args in (["--components", "upstream"], base[2:] + ["--components", "unknown"],
                 ["--component-of", "FE-00001"], base[2:] + ["--component-of", "FE-00001"],
                 base[2:] + ["--summary", "--component-of", "FE-00001"]):
        cli = subprocess.run(script + args, capture_output=True, text=True, timeout=30)
        require(cli.returncode == 2 and not cli.stdout, "invalid components CLI accepted")
    require(result["total_upstream_orphans"] == 1 and result["total_dependency_orphans"] == 3,
            "components must not be confused with isolated nodes")
    require(fixture == original, "component summary mutated input")
    reordered = copy.deepcopy(fixture)
    reordered["objects"].reverse()
    for record in reordered["objects"]:
        record["traceability"]["upstream"].reverse()
    require(summarize_palaco_registry(reordered, validators) == result,
            "component counts depend on input ordering")
    for graph_name in ("upstream", "dependency"):
        bridged = copy.deepcopy(fixture)
        if graph_name == "upstream":
            bridged["objects"][3]["traceability"]["upstream"] = ["FE-00005"]
        else:
            bridged["objects"][0]["dependencies"].append("FE-00002")
        before = copy.deepcopy(bridged)
        summary = summarize_palaco_registry(bridged, validators)
        for field in ("total_upstream_components", "total_dependency_components"):
            expected = result[field] - (field == f"total_{graph_name}_components")
            require(summary[field] == expected,
                    f"{graph_name} bridge must merge only its own graph components")
        require(summary["largest_upstream_component_size"] == (6 if graph_name == "upstream" else 4)
                and summary["largest_dependency_component_size"] == (4 if graph_name == "dependency" else 2),
                "bridge must enlarge only its own graph's largest component")
        require(bridged == before, "bridge summary mutated input")
    reversed_fixture = copy.deepcopy(fixture)
    reversed_upstream = {record["metadata"]["id"]: [] for record in fixture["objects"]}
    for record in fixture["objects"]:
        for target in record["traceability"]["upstream"]:
            reversed_upstream[target].append(record["metadata"]["id"])
    for record in reversed_fixture["objects"]:
        record["traceability"]["upstream"] = reversed_upstream[record["metadata"]["id"]]
    require(summarize_palaco_registry(reversed_fixture, validators) == result,
            "weak component summary must ignore upstream edge direction")
    require(fixture == original, "bridge or edge reversal checks mutated original input")
    for record in fixture["objects"]:
        record["traceability"]["upstream"] = []
        record["traceability"]["relationships"] = []
        record.pop("dependencies", None)
    unlinked = summarize_palaco_registry(fixture, validators)
    require(unlinked["total_upstream_components"] == 7
            and unlinked["total_dependency_components"] == 7,
            "every isolated node must count as one component")
    require(unlinked["largest_upstream_component_size"] == 1
            and unlinked["largest_dependency_component_size"] == 1,
            "all-isolated graphs must have largest component size one")
    singleton = summarize_palaco_registry(
        {"registry_version": "0.1.0", "objects": [template]}, validators,
    )
    require(singleton["total_upstream_components"] == 1
            and singleton["total_dependency_components"] == 1,
            "singleton snapshot must have one component per graph")
    require(singleton["largest_upstream_component_size"] == 1
            and singleton["largest_dependency_component_size"] == 1,
            "singleton snapshot must have largest component size one")
    depth = sys.getrecursionlimit() + 100
    chain = {f"FE-{index:05d}": {f"FE-{index + 1:05d}"} for index in range(depth)}
    chain[f"FE-{depth:05d}"] = set()
    chain["AUD-00001"] = set()
    before = copy.deepcopy(chain)
    require(count_weak_components(chain) == 2,
            "deep chain plus isolate must have two components")
    require(weak_component_sizes(chain) == [1, depth + 1],
            "deep traversal must count nodes rather than edges")
    require(chain == before, "component traversal mutated deep graph")
    reverse_chain = {source: set() for source in chain}
    for source, targets in chain.items():
        for target in targets:
            reverse_chain[target].add(source)
    reverse_chain = dict(reversed(list(reverse_chain.items())))
    before = copy.deepcopy(reverse_chain)
    require(count_weak_components(reverse_chain) == 2,
            "deep component traversal depends on direction or root ordering")
    require(weak_component_sizes(reverse_chain) == [1, depth + 1],
            "component sizes depend on direction or root ordering")
    require(reverse_chain == before, "component traversal mutated reversed deep graph")
    expected_chain = sorted(node for node in chain if node != "AUD-00001")
    for graph in (chain, reverse_chain):
        original_graph = copy.deepcopy(graph)
        for index in (0, depth // 2, depth):
            selected = weak_components(graph, f"FE-{index:05d}")
            require(selected == [expected_chain],
                    "deep selected traversal missed nodes from an endpoint or middle")
            selected[0].clear()
            require(weak_components(graph, f"FE-{index:05d}") == [expected_chain],
                    "deep selected traversal reuses mutable result state")
        require(weak_components(graph, "AUD-00001") == [["AUD-00001"]],
                "deep selected traversal included unrelated components for an isolate")
        require(graph == original_graph, "deep selected traversal mutated input graph")
    return "weak components: multi-cluster CLI, isolates, bridges, reversal, deep traversal and non-mutation"


def check_palaco_summary():
    validators = palaco_validators()
    fixture = read_json(PALACO_FIXTURE_DIR / "registry.fixture.json")
    template = read_json(PALACO_FIXTURE_DIR / "FE-00001.fixture.json")
    mixed = copy.deepcopy(fixture)
    added = copy.deepcopy(template)
    added["metadata"]["id"] = "FE-00002"
    added["lifecycle"]["status"] = "Review"
    mixed["objects"].append(added)
    linked = copy.deepcopy(mixed)
    objective = copy.deepcopy(template)
    objective["object_type"] = "OBJ"
    objective["metadata"]["id"] = "OBJ-00001"
    linked["objects"].append(objective)
    linked["objects"][2]["traceability"]["relationships"].extend([
        {"source": "REQ-00001", "relation": "DEPENDS_ON", "target": "FE-00001"},
        {"source": "REQ-00001", "relation": "SATISFIES", "target": "OBJ-00001"},
    ])
    implicit = copy.deepcopy(fixture)
    for record in implicit["objects"]:
        record["traceability"]["relationships"] = []
    implicit["objects"][2]["dependencies"] = ["CAP-00001"]
    overlapping = copy.deepcopy(linked)
    overlapping["objects"][2]["dependencies"] = ["CAP-00001", "FE-00001"]
    overlapping["objects"][3]["dependencies"] = ["FE-00001"]
    schema = validators["PMS-001.schema.json"].schema
    families = sorted(schema["properties"]["object_type"]["enum"])
    statuses = schema["$defs"]["Lifecycle"]["properties"]["status"]["enum"]
    verification_statuses = schema["$defs"]["Verification"]["properties"]["status"]["enum"]
    approval_statuses = schema["$defs"]["Approval"]["properties"]["status"]["enum"]
    classifications = schema["$defs"]["Classification"]["properties"]
    relations = sorted(validators["PMS-002.schema.json"].schema["properties"]["relation"]["enum"])
    for instance, expected_types, expected_states, expected_relations, expected_dependencies, expected_orphans, expected_dependency_orphans in (
        (fixture, {"FE": 1, "CAP": 1, "REQ": 1}, {"Draft": 3}, {"DEPENDS_ON": 2}, 2, 0, 0),
        (mixed, {"FE": 2, "CAP": 1, "REQ": 1}, {"Draft": 3, "Review": 1}, {"DEPENDS_ON": 2}, 2, 1, 1),
        ({"registry_version": "0.1.0", "objects": [template]}, {"FE": 1}, {"Draft": 1}, {}, 0, 1, 1),
        (linked, {"FE": 2, "CAP": 1, "REQ": 1, "OBJ": 1}, {"Draft": 4, "Review": 1},
         {"DEPENDS_ON": 3, "SATISFIES": 1}, 3, 2, 2),
        (implicit, {"FE": 1, "CAP": 1, "REQ": 1}, {"Draft": 3}, {}, 1, 0, 1),
        (overlapping, {"FE": 2, "CAP": 1, "REQ": 1, "OBJ": 1}, {"Draft": 4, "Review": 1},
         {"DEPENDS_ON": 3, "SATISFIES": 1}, 4, 2, 1),
    ):
        original = copy.deepcopy(instance)
        result = summarize_palaco_registry(instance, validators)
        require(result == {
            "registry_version": "0.1.0",
            "total_objects": len(instance["objects"]),
            "by_object_type": {family: expected_types.get(family, 0) for family in families},
            "by_domain": {
                domain: sum(record["metadata"]["domain"] == domain for record in instance["objects"])
                for domain in sorted({record["metadata"]["domain"] for record in instance["objects"]})
            },
            "by_ownership": {
                role: {
                    owner: sum(record["ownership"][role] == owner for record in instance["objects"])
                    for owner in sorted({record["ownership"][role] for record in instance["objects"]})
                }
                for role in schema["$defs"]["Ownership"]["properties"]
            },
            "by_lifecycle_status": {status: expected_states.get(status, 0) for status in statuses},
            "by_verification_status": {
                status: len(instance["objects"]) if status == "Pending" else 0
                for status in verification_statuses
            },
            "by_approval_status": {
                status: len(instance["objects"]) if status == "Pending" else 0
                for status in approval_statuses
            },
            "by_classification": {
                dimension: {
                    label: sum(record["classification"][dimension] == label for record in instance["objects"])
                    for label in definition["enum"]
                }
                for dimension, definition in classifications.items()
            },
            "total_relationships": sum(expected_relations.values()),
            "total_dependency_edges": expected_dependencies,
            "total_dependency_orphans": expected_dependency_orphans,
            "total_dependency_components": 1 if len(instance["objects"]) == 1 else 1 + expected_dependency_orphans,
            "largest_dependency_component_size": len(instance["objects"]) - expected_dependency_orphans
            if expected_dependencies else 1,
            "total_upstream_edges": 0 if len(instance["objects"]) == 1 else 2,
            "total_upstream_orphans": expected_orphans,
            "total_upstream_components": 1 if len(instance["objects"]) == 1 else 1 + expected_orphans,
            "largest_upstream_component_size": len(instance["objects"]) - expected_orphans
            if len(instance["objects"]) > 1 else 1,
            "by_relationship_type": {relation: expected_relations.get(relation, 0) for relation in relations},
            "scope": "supplied snapshot metadata only; not proof of completeness, approval, activation or authority",
        }, f"unexpected registry summary: {result}")
        require(result["total_upstream_orphans"] == len(find_palaco_orphans(
            instance, validators["PCR-000.schema.json"]
        )["object_ids"]), "summary and orphan query disagree")
        require(list(result["by_object_type"]) == families, "summary type order changed")
        require(list(result["by_lifecycle_status"]) == statuses, "summary lifecycle order changed")
        require(list(result["by_relationship_type"]) == relations, "summary relationship order changed")
        require(sum(result["by_relationship_type"].values()) == result["total_relationships"],
                "summary relationship counts do not sum to total")
        require(sum(result["by_object_type"].values()) == result["total_objects"],
                "summary type counts do not sum to total")
        require(sum(result["by_lifecycle_status"].values()) == result["total_objects"],
                "summary lifecycle counts do not sum to total")
        require(instance == original, "summary mutated input")
        reordered = copy.deepcopy(instance)
        reordered["objects"].reverse()
        for record in reordered["objects"]:
            record["traceability"]["relationships"].reverse()
            record.get("dependencies", []).reverse()
        require(json.dumps(summarize_palaco_registry(reordered, validators)) == json.dumps(result),
                "summary serialization depends on object order")
    status_fixture = {"registry_version": "0.1.0", "objects": []}
    for index, (verification, approval) in enumerate((
        ("Pending", "Approved"), ("Passed", "Rejected"),
        ("Failed", "Pending"), ("NotApplicable", "Pending"),
    ), 1):
        record = copy.deepcopy(template)
        record["metadata"]["id"] = f"FE-{index:05d}"
        record["verification"]["status"] = verification
        record["approval"]["status"] = approval
        if approval == "Approved":
            record["approval"].update({
                "authority": "Synthetic review team", "approval_ref": "Synthetic summary fixture",
            })
            record["lifecycle"]["approved"] = record["lifecycle"]["created"]
        status_fixture["objects"].append(record)
    original = copy.deepcopy(status_fixture)
    result = summarize_palaco_registry(status_fixture, validators)
    require(result["by_verification_status"] == {
        "Pending": 1, "Passed": 1, "Failed": 1, "NotApplicable": 1,
    }, "summary verification counts are not each record's own status")
    require(result["by_approval_status"] == {"Pending": 2, "Approved": 1, "Rejected": 1},
            "summary approval counts confused with lifecycle status")
    require(result["by_lifecycle_status"]["Draft"] == 4, "status summary changed lifecycle counts")
    for field, vocabulary in (
        ("by_verification_status", verification_statuses),
        ("by_approval_status", approval_statuses),
    ):
        require(list(result[field]) == vocabulary, f"summary {field} order changed")
        require(sum(result[field].values()) == result["total_objects"],
                f"summary {field} counts do not sum to total")
    require(status_fixture == original, "status summary mutated input")
    status_fixture["objects"].reverse()
    require(json.dumps(summarize_palaco_registry(status_fixture, validators)) == json.dumps(result),
            "status summary serialization depends on object order")
    invalid_ref = copy.deepcopy(fixture)
    invalid_ref["objects"][0]["traceability"]["upstream"] = ["FE-99999"]
    duplicate = copy.deepcopy(fixture)
    duplicate["objects"].append(copy.deepcopy(duplicate["objects"][0]))
    cyclic = copy.deepcopy(fixture)
    cyclic["objects"][0]["traceability"]["upstream"] = ["REQ-00001"]
    unapproved = copy.deepcopy(fixture)
    unapproved["objects"][0]["lifecycle"]["status"] = "Active"
    invalid_edge = copy.deepcopy(fixture)
    invalid_edge["objects"][1]["traceability"]["relationships"][0]["relation"] = "RELATED_TO"
    invalid_source = copy.deepcopy(fixture)
    invalid_source["objects"][1]["traceability"]["relationships"][0]["source"] = "REQ-00001"
    invalid_verification = copy.deepcopy(fixture)
    invalid_verification["objects"][0]["verification"]["status"] = "Verified"
    invalid_approval = copy.deepcopy(fixture)
    invalid_approval["objects"][0]["approval"]["status"] = "Accepted"
    for instance, diagnostic in (
        ({}, "registry structure"),
        ({"registry_version": "0.1.0", "objects": []}, "registry structure"),
        (invalid_ref, "unresolved"),
        (duplicate, "duplicate object ID"),
        (cyclic, "upstream cycle"),
        (unapproved, "requires approval.status Approved"),
        (invalid_edge, "registry structure"),
        (invalid_source, "source"),
        (invalid_verification, "registry structure"),
        (invalid_approval, "registry structure"),
    ):
        try:
            summarize_palaco_registry(instance, validators)
        except ConformanceError as error:
            require(diagnostic in str(error), f"unexpected summary diagnostic: {error}")
        else:
            raise ConformanceError(f"invalid snapshot summarized: {diagnostic}")
    cli = subprocess.run([
        sys.executable, str(Path(__file__).resolve()), "--registry",
        str(PALACO_FIXTURE_DIR / "registry.fixture.json"), "--summary",
    ], capture_output=True, text=True, timeout=30)
    require(cli.returncode == 0, f"summary CLI failed: {cli.stdout}{cli.stderr}")
    require(json.loads(cli.stdout) == summarize_palaco_registry(fixture, validators),
            "summary CLI differs from validated summary")
    classification_fixture = {"registry_version": "0.1.0", "objects": []}
    for index in range(4):
        record = copy.deepcopy(template)
        record["metadata"]["id"] = f"FE-{index + 1:05d}"
        for dimension, definition in classifications.items():
            labels = definition["enum"]
            record["classification"][dimension] = labels[index % len(labels)]
        classification_fixture["objects"].append(record)
    original = copy.deepcopy(classification_fixture)
    result = summarize_palaco_registry(classification_fixture, validators)
    require(result["by_classification"] == {
        "criticality": {"Low": 1, "Medium": 1, "High": 1, "Critical": 1},
        "confidentiality": {"Public": 1, "Internal": 1, "Confidential": 1, "Restricted": 1},
        "integrity": {"Low": 2, "Medium": 1, "High": 1},
        "availability": {"Low": 2, "Medium": 1, "High": 1},
    }, "summary classification counts confused dimensions or labels")
    require(list(result["by_classification"]) == list(classifications),
            "summary classification dimensions changed order")
    for dimension, definition in classifications.items():
        counts = result["by_classification"][dimension]
        require(list(counts) == definition["enum"], f"summary {dimension} label order changed")
        require(sum(counts.values()) == result["total_objects"],
                f"summary {dimension} counts do not sum to total")
        invalid = copy.deepcopy(classification_fixture)
        invalid["objects"][-1]["classification"][dimension] = "Unknown"
        try:
            summarize_palaco_registry(invalid, validators)
        except ConformanceError as error:
            require("registry structure" in str(error), f"unexpected classification summary error: {error}")
        else:
            raise ConformanceError(f"summary accepted invalid {dimension}")
    require(classification_fixture == original, "classification summary mutated input")
    classification_fixture["objects"].reverse()
    require(json.dumps(summarize_palaco_registry(classification_fixture, validators)) == json.dumps(result),
            "classification summary serialization depends on object order")
    domain_fixture = {"registry_version": "0.1.0", "objects": []}
    for index, domain in enumerate(("Registry", "Registry", "registry", " Registry ", "Δ", "é", "e\u0301"), 1):
        record = copy.deepcopy(template)
        record["metadata"]["id"] = f"FE-{index:05d}"
        record["metadata"]["domain"] = domain
        domain_fixture["objects"].insert(0, record)
    original = copy.deepcopy(domain_fixture)
    result = summarize_palaco_registry(domain_fixture, validators)
    expected_domains = {" Registry ": 1, "Registry": 2, "e\u0301": 1, "registry": 1, "é": 1, "Δ": 1}
    require(result["by_domain"] == expected_domains, "summary normalized or miscounted domain labels")
    require(list(result["by_domain"]) == list(expected_domains), "summary domain keys are not Unicode-sorted")
    require(sum(result["by_domain"].values()) == result["total_objects"],
            "summary domain counts do not sum to total")
    require(domain_fixture == original, "domain summary mutated input")
    domain_fixture["objects"].reverse()
    require(json.dumps(summarize_palaco_registry(domain_fixture, validators)) == json.dumps(result),
            "domain summary serialization depends on object order")
    for value in ("", " \t\n", None, 42):
        invalid = copy.deepcopy(domain_fixture)
        invalid["objects"][-1]["metadata"]["domain"] = value
        try:
            summarize_palaco_registry(invalid, validators)
        except ConformanceError as error:
            require("registry structure" in str(error), f"unexpected domain summary error: {error}")
        else:
            raise ConformanceError("summary accepted invalid domain")
    ownership_fixture = {"registry_version": "0.1.0", "objects": []}
    owners = ("Example team", "Example team", "example team", " Example team ", "Δ", "é", "e\u0301")
    roles = list(schema["$defs"]["Ownership"]["properties"])
    for index, owner in enumerate(owners, 1):
        record = copy.deepcopy(template)
        record["metadata"]["id"] = f"FE-{index:05d}"
        record["ownership"]["business"] = owner
        record["ownership"]["technical"] = "Example team"
        record["audit"]["updated_by"] = "Updater-only label"
        ownership_fixture["objects"].insert(0, record)
    original = copy.deepcopy(ownership_fixture)
    result = summarize_palaco_registry(ownership_fixture, validators)
    expected_owners = {" Example team ": 1, "Example team": 2, "e\u0301": 1, "example team": 1, "é": 1, "Δ": 1}
    require(list(result["by_ownership"]) == roles, "summary ownership roles changed order")
    require(result["by_ownership"]["business"] == expected_owners,
            "summary normalized or miscounted owner labels")
    require(result["by_ownership"]["technical"] == {"Example team": 7},
            "summary mixed ownership roles")
    for role, counts in result["by_ownership"].items():
        require(list(counts) == sorted(counts), f"summary {role} owner keys are not Unicode-sorted")
        require(sum(counts.values()) == result["total_objects"],
                f"summary {role} counts do not sum to total")
        require("Updater-only label" not in counts, "summary included audit updater as owner")
        if role not in ("business", "technical"):
            require(counts == {template["ownership"][role]: 7}, f"summary mixed {role} owners")
        for value in ("", " \t\n", None, 42):
            invalid = copy.deepcopy(ownership_fixture)
            invalid["objects"][-1]["ownership"][role] = value
            try:
                summarize_palaco_registry(invalid, validators)
            except ConformanceError as error:
                require("registry structure" in str(error), f"unexpected ownership summary error: {error}")
            else:
                raise ConformanceError(f"summary accepted invalid {role} owner")
    require(ownership_fixture == original, "ownership summary mutated input")
    ownership_fixture["objects"].reverse()
    for record in ownership_fixture["objects"]:
        record["ownership"] = dict(reversed(list(record["ownership"].items())))
    require(json.dumps(summarize_palaco_registry(ownership_fixture, validators)) == json.dumps(result),
            "ownership summary serialization depends on record or role order")
    upstream_fixture = {"registry_version": "0.1.0", "objects": []}
    for index in range(1, 5):
        record = copy.deepcopy(template)
        record["metadata"]["id"] = f"FE-{index:05d}"
        upstream_fixture["objects"].append(record)
    upstream_fixture["objects"][1]["traceability"]["upstream"] = ["FE-00001"]
    upstream_fixture["objects"][2]["traceability"]["upstream"] = ["FE-00002", "FE-00001"]
    upstream_fixture["objects"][3]["traceability"]["upstream"] = ["FE-00001"]
    upstream_fixture["objects"][0]["dependencies"] = ["FE-00004"]
    original = copy.deepcopy(upstream_fixture)
    result = summarize_palaco_registry(upstream_fixture, validators)
    require(result["total_upstream_edges"] == 4, "summary miscounted direct upstream edges")
    require(result["total_upstream_orphans"] == 0,
            "summary counted a connected root or leaf as an orphan")
    require(result["total_dependency_edges"] == 1 and result["total_relationships"] == 0,
            "summary mixed upstream and dependency graphs")
    require(result["total_dependency_orphans"] == 2,
            "summary included upstream-only connectivity in dependency graph")
    require(upstream_fixture == original, "upstream summary mutated input")
    upstream_fixture["objects"].reverse()
    for record in upstream_fixture["objects"]:
        record["traceability"]["upstream"].reverse()
    require(json.dumps(summarize_palaco_registry(upstream_fixture, validators)) == json.dumps(result),
            "upstream summary depends on record or edge order")
    for targets in (["FE-00001", "FE-00001"], ["FE-99999"], ["FE-00004"]):
        invalid = copy.deepcopy(original)
        invalid["objects"][-1]["traceability"]["upstream"] = targets
        try:
            summarize_palaco_registry(invalid, validators)
        except ConformanceError:
            pass
        else:
            raise ConformanceError("summary accepted duplicate, unresolved or self upstream links")
    for record in upstream_fixture["objects"]:
        record["traceability"]["upstream"] = []
    cleared = summarize_palaco_registry(upstream_fixture, validators)
    require(cleared["total_upstream_edges"] == 0 and cleared["total_dependency_edges"] == 1,
            "summary inferred upstream edges from dependencies")
    require(cleared["total_upstream_orphans"] == 4,
            "summary treated dependency-connected objects as upstream-connected")
    require(cleared["total_dependency_orphans"] == 2,
            "clearing upstream links changed dependency isolation")
    isolated = copy.deepcopy(template)
    isolated["metadata"]["id"] = "FE-00005"
    original["objects"].append(isolated)
    extended = summarize_palaco_registry(original, validators)
    require(extended["total_upstream_orphans"] == 1 and extended["total_upstream_edges"] == 4,
            "summary failed to distinguish an isolated node from a connected root")
    require(find_palaco_orphans(original, validators["PCR-000.schema.json"])["object_ids"] == ["FE-00005"],
            "orphan summary fixture disagrees with existing query")
    original["objects"].reverse()
    require(json.dumps(summarize_palaco_registry(original, validators)) == json.dumps(extended),
            "orphan summary depends on record order")
    dependency_fixture = copy.deepcopy(upstream_fixture)
    by_id = {record["metadata"]["id"]: record for record in dependency_fixture["objects"]}
    by_id["FE-00002"]["dependencies"] = ["FE-00001"]
    by_id["FE-00002"]["traceability"]["relationships"] = [
        {"source": "FE-00002", "relation": "DEPENDS_ON", "target": "FE-00001"},
    ]
    before = copy.deepcopy(dependency_fixture)
    result = summarize_palaco_registry(dependency_fixture, validators)
    require(result["total_dependency_orphans"] == 1 and result["total_dependency_edges"] == 2,
            "summary failed to count incoming/outgoing dependency connectivity or deduplicate edges")
    require(dependency_fixture == before, "dependency isolation summary mutated input")
    dependency_fixture["objects"].reverse()
    require(json.dumps(summarize_palaco_registry(dependency_fixture, validators)) == json.dumps(result),
            "dependency isolation summary depends on record order")
    for record in dependency_fixture["objects"]:
        record.pop("dependencies", None)
        record["traceability"]["relationships"] = []
    require(summarize_palaco_registry(dependency_fixture, validators)["total_dependency_orphans"] == 4,
            "summary failed to count all dependency-isolated objects")
    return "15 deterministic/non-mutating summaries + separate dependency/upstream isolation + graph/metadata counts + 41 rejections + CLI regression"


def check_palaco_find_lifecycle():
    validators = palaco_validators()
    template = read_json(PALACO_FIXTURE_DIR / "FE-00001.fixture.json")
    statuses = validators["PMS-001.schema.json"].schema["$defs"]["Lifecycle"]["properties"]["status"]["enum"]
    fixture = {"registry_version": "0.1.0", "objects": []}
    for index, status in enumerate(statuses, 1):
        record = copy.deepcopy(template)
        record["metadata"]["id"] = f"FE-{index:05d}"
        record["lifecycle"]["status"] = status
        if status in ("Approved", "Active", "Deprecated", "Retired", "Archived"):
            record["approval"] = {
                "status": "Approved",
                "authority": "Synthetic review team",
                "approval_ref": "Synthetic lifecycle-query fixture",
            }
            record["lifecycle"]["approved"] = record["lifecycle"]["created"]
        fixture["objects"].append(record)
    duplicate_status = copy.deepcopy(fixture["objects"][1])
    duplicate_status["metadata"]["id"] = "FE-00009"
    fixture["objects"].insert(0, duplicate_status)
    original = copy.deepcopy(fixture)
    for index, status in enumerate(statuses, 1):
        expected = [f"FE-{index:05d}"]
        if status == statuses[1]:
            expected.append("FE-00009")
        result = find_palaco_lifecycle(fixture, status, validators)
        require(result == {
            "lifecycle_status": status,
            "object_ids": expected,
            "scope": "supplied lifecycle metadata only; not proof of approval, activation or authority",
        }, f"incorrect lifecycle query: {status}")
        reordered = copy.deepcopy(fixture)
        reordered["objects"].reverse()
        require(find_palaco_lifecycle(reordered, status, validators) == result,
                "lifecycle query depends on record order")
    require(fixture == original, "lifecycle query mutated input")
    single = {"registry_version": "0.1.0", "objects": [copy.deepcopy(template)]}
    require(find_palaco_lifecycle(single, "Archived", validators)["object_ids"] == [],
            "lifecycle query without matches must be empty")
    invalid = copy.deepcopy(fixture)
    invalid["objects"][-1]["traceability"]["upstream"] = ["FE-99999"]
    duplicate = copy.deepcopy(fixture)
    duplicate["objects"].append(copy.deepcopy(duplicate["objects"][0]))
    unapproved = copy.deepcopy(fixture)
    unapproved["objects"][-1]["approval"]["status"] = "Pending"
    for instance, status, diagnostic in (
        (fixture, "draft", "unknown PALACO lifecycle status"),
        (fixture, "UNKNOWN", "unknown PALACO lifecycle status"),
        ({}, "Draft", "registry structure"),
        (invalid, "Draft", "unresolved"),
        (duplicate, "Draft", "duplicate object ID"),
        (unapproved, "Draft", "requires approval.status Approved"),
    ):
        try:
            find_palaco_lifecycle(instance, status, validators)
        except ConformanceError as error:
            require(diagnostic in str(error), f"unexpected lifecycle query diagnostic: {error}")
        else:
            raise ConformanceError(f"invalid lifecycle query accepted: {diagnostic}")
    return f"{len(statuses)} lifecycle states + sorted/non-mutating/empty results + 6 rejections"


def check_palaco_traces():
    validator = palaco_validators()["PCR-000.schema.json"]
    fixture = read_json(PALACO_FIXTURE_DIR / "registry.fixture.json")
    original = copy.deepcopy(fixture)
    cases = (
        ("REQ-00001", "upstream", ["CAP-00001", "FE-00001"]),
        ("FE-00001", "downstream", ["CAP-00001", "REQ-00001"]),
        ("CAP-00001", "upstream", ["FE-00001"]),
        ("CAP-00001", "downstream", ["REQ-00001"]),
        ("FE-00001", "upstream", []),
        ("REQ-00001", "downstream", []),
    )
    for object_id, direction, expected in cases:
        result = trace_palaco_registry(fixture, object_id, direction, validator)
        require(result["reachable_ids"] == expected, f"unexpected trace result: {result}")
        require(result["object_id"] == object_id and result["direction"] == direction
                and result["graph"] == "traceability.upstream", "missing trace metadata")
    require(fixture == original, "trace query mutated its input")
    template = read_json(PALACO_FIXTURE_DIR / "FE-00001.fixture.json")
    diamond = {"registry_version": "0.1.0", "objects": []}
    for index, targets in ((1, [2, 3]), (2, [4]), (3, [4]), (4, []), (5, [])):
        record = copy.deepcopy(template)
        record["metadata"]["id"] = f"FE-{index:05d}"
        record["traceability"]["upstream"] = [f"FE-{target:05d}" for target in targets]
        diamond["objects"].append(record)
    for direction, start, expected in (
        ("upstream", "FE-00001", ["FE-00002", "FE-00003", "FE-00004"]),
        ("downstream", "FE-00004", ["FE-00001", "FE-00002", "FE-00003"]),
        ("upstream", "FE-00005", []),
    ):
        result = trace_palaco_registry(diamond, start, direction, validator)
        require(result["reachable_ids"] == expected, f"diamond trace mismatch: {result}")
        reordered = copy.deepcopy(diamond)
        reordered["objects"].reverse()
        for record in reordered["objects"]:
            record["traceability"]["upstream"].reverse()
        require(trace_palaco_registry(reordered, start, direction, validator) == result,
                "trace output depends on record/reference order")
    separate = copy.deepcopy(diamond)
    separate["objects"][4]["dependencies"] = ["FE-00001"]
    separate["objects"][4]["compliance"] = ["FE-00002"]
    separate["objects"][4]["traceability"]["relationships"] = [
        {"source": "FE-00005", "relation": "DEPENDS_ON", "target": "FE-00001"}
    ]
    require(trace_palaco_registry(separate, "FE-00005", validator=validator)["reachable_ids"] == [],
            "trace incorrectly merges non-upstream references")

    negatives = []
    negatives.append((fixture, "FE-99999", "upstream", "unknown trace object ID"))
    negatives.append((fixture, "FE-00001", "sideways", "invalid trace direction"))
    dangling = copy.deepcopy(fixture)
    dangling["objects"][2]["capability_ref"] = "CAP-99999"
    negatives.append((dangling, "FE-00001", "upstream", "unresolved capability_ref"))
    cyclic = copy.deepcopy(diamond)
    cyclic["objects"][3]["traceability"]["upstream"] = ["FE-00001"]
    negatives.append((cyclic, "FE-00005", "upstream", "upstream cycle"))
    duplicate = copy.deepcopy(fixture)
    duplicate["objects"].append(copy.deepcopy(duplicate["objects"][0]))
    negatives.append((duplicate, "FE-00001", "upstream", "duplicate object ID"))
    negatives.append(({}, "FE-00001", "upstream", "registry structure"))
    for instance, object_id, direction, expected in negatives:
        try:
            trace_palaco_registry(instance, object_id, direction, validator)
        except ConformanceError as error:
            require(expected in str(error), f"unexpected trace diagnostic: {error}")
        else:
            raise ConformanceError(f"invalid trace query accepted: {expected}")
    return "registry traces: 10 positive queries, deterministic/non-mutating output + 6 rejections"


def check_palaco_registry():
    validator = palaco_validators()["PCR-000.schema.json"]
    fixture = read_json(PALACO_FIXTURE_DIR / "registry.fixture.json")
    print(f"  ok {validate_palaco_registry(fixture, validator)}")
    negative_count = 0

    def reject(instance, expected, label):
        nonlocal negative_count
        try:
            validate_palaco_registry(instance, validator)
        except ConformanceError as error:
            require(expected in str(error), f"{label}: unexpected error: {error}")
        else:
            raise ConformanceError(f"registry negative test accepted: {label}")
        negative_count += 1
        print(f"  ok rejected registry {label}")

    for invalid, label in (
        ({}, "missing envelope"),
        ({**fixture, "registry_version": "1.0.0"}, "unsupported version"),
        ({**fixture, "objects": []}, "empty registry"),
        ({**fixture, "extra": True}, "unknown envelope field"),
        ({**fixture, "objects": [None]}, "non-object record"),
    ):
        reject(invalid, "registry structure", label)
    invalid = copy.deepcopy(fixture)
    del invalid["objects"][0]["ownership"]
    reject(invalid, "registry structure", "missing ownership")
    invalid = copy.deepcopy(fixture)
    invalid["objects"].append(copy.deepcopy(invalid["objects"][0]))
    invalid["objects"][-1]["metadata"]["name"] = "Different record with same identity"
    reject(invalid, "duplicate object ID", "duplicate identity with different content")
    invalid = copy.deepcopy(fixture)
    invalid["objects"].reverse()
    validate_palaco_registry(invalid, validator)
    invalid = copy.deepcopy(fixture)
    invalid["objects"][1]["traceability"]["relationships"][0]["source"] = "REQ-00001"
    reject(invalid, "relationship source", "foreign edge owner")
    invalid = copy.deepcopy(fixture)
    invalid["objects"][1]["traceability"]["relationships"][0]["target"] = "FE-99999"
    reject(invalid, "unresolved DEPENDS_ON target", "dangling edge")
    invalid = copy.deepcopy(fixture)
    invalid["objects"][1]["traceability"]["relationships"][0]["target"] = "CAP-00001"
    reject(invalid, "self reference", "self edge")

    complete = {
        "registry_version": "0.1.0",
        "objects": [
            read_json(PALACO_FIXTURE_DIR / f"{family}-00001.fixture.json")
            for family in ("FE", "ADR", "SVC", "COM", "REQ")
        ],
    }
    for family in ("CAP", "OBJ", "ARC", "GOV", "REP", "RUN", "RSK", "VER", "EVD", "AUD"):
        record = copy.deepcopy(complete["objects"][0])
        record["object_type"] = family
        record["metadata"]["id"] = f"{family}-00001"
        if family == "AUD":
            record["evidence"] = ["EVD-00001"]
        complete["objects"].append(record)
    validate_palaco_registry(complete, validator)
    service = complete["objects"][2]
    service["risk"] = "RSK-00001"
    service["approved_by"] = "GOV-00001"
    service["capability_ref"] = "CAP-00001"
    service["dependencies"] = ["FE-00001"]
    service["evidence"] = ["EVD-00001"]
    service["compliance"] = ["COM-00001"]
    service["verification"]["verification_ref"] = "VER-00001"
    service["audit"]["audit_refs"] = ["AUD-00001"]
    validate_palaco_registry(complete, validator)
    for path in OBJECT_REFERENCE_FIELDS:
        invalid = copy.deepcopy(complete)
        parent = invalid["objects"][2]
        for field in path[:-1]:
            parent = parent[field]
        value = parent[path[-1]]
        target = value[0] if isinstance(value, list) else value
        missing = target.rsplit("-", 1)[0] + "-99999"
        parent[path[-1]] = [missing] if isinstance(value, list) else missing
        reject(invalid, f"unresolved {'.'.join(path)}", f"dangling {'.'.join(path)}")
    for field, value in (("dependencies", ["SVC-00001"]), ("compliance", ["SVC-00001"])):
        invalid = copy.deepcopy(complete)
        invalid["objects"][2][field] = value
        reject(invalid, "self reference", f"self {field}")
    invalid = copy.deepcopy(fixture)
    invalid["objects"][1]["traceability"]["upstream"] = ["CAP-00001"]
    reject(invalid, "self reference", "self upstream")
    invalid = copy.deepcopy(complete)
    invalid["objects"][2]["requirement_refs"] = ["CAP-00001"]
    reject(invalid, "registry structure", "wrong reference family")
    invalid = copy.deepcopy(fixture)
    invalid["objects"][0]["metadata"]["id"] = "CAP-00001"
    reject(invalid, "registry structure", "object type and ID mismatch")
    invalid = copy.deepcopy(fixture)
    invalid["objects"][1]["dependencies"] = []
    reject(invalid, "DEPENDS_ON conflicts with dependencies", "edge contradicting empty array")
    opaque = copy.deepcopy(fixture)
    opaque["objects"][0]["approval"] = {
        "status": "Approved", "authority": "GOV-99999", "approval_ref": "AUD-99999"
    }
    opaque["objects"][0]["lifecycle"]["approved"] = "2026-10-15"
    validate_palaco_registry(opaque, validator)

    edge_cases = (
        ("IMPLEMENTS", "SVC", "requirement_refs", "REQ"),
        ("REALIZES", "SVC", "capability_ref", "CAP"),
        ("DEFINED_BY", "SVC", "architecture_ref", "ARC"),
        ("APPROVED_BY", "ADR", "approved_by", "GOV"),
        ("VERIFIED_BY", "COM", "verification.verification_ref", "VER"),
        ("PROVEN_BY", "VER", "evidence", "EVD"),
        ("AUDITED_BY", "EVD", "audit.audit_refs", "AUD"),
        ("DEPENDS_ON", "SVC", "dependencies", "FE"),
    )
    for relation, family, field, target_family in edge_cases:
        instance = copy.deepcopy(complete)
        record = next(item for item in instance["objects"] if item["object_type"] == family)
        parent = record
        for part in field.split(".")[:-1]:
            parent = parent[part]
        key = field.split(".")[-1]
        target = f"{target_family}-00001"
        parent[key] = [target] if key in ("requirement_refs", "evidence", "audit_refs", "dependencies") else target
        record["traceability"]["relationships"] = [
            {"source": record["metadata"]["id"], "relation": relation, "target": target}
        ]
        validate_palaco_registry(instance, validator)
        other = copy.deepcopy(next(item for item in instance["objects"] if item["metadata"]["id"] == target))
        other["metadata"]["id"] = f"{target_family}-00002"
        instance["objects"].append(other)
        record["traceability"]["relationships"][0]["target"] = other["metadata"]["id"]
        reject(instance, f"{relation} conflicts with {field}", f"contradictory {relation}")
    return f"PCR-000: closed fixture, complete 15-object snapshot + {negative_count} negative tests"


def check_palaco_transitions():
    validators = palaco_validators()
    validator = validators["PCR-000.schema.json"]
    template = read_json(PALACO_FIXTURE_DIR / "FE-00001.fixture.json")
    states = ("Proposed", "Draft", "Review", "Approved", "Active", "Deprecated", "Retired", "Archived")
    require(tuple(validators["PMS-001.schema.json"].schema["$defs"]["Lifecycle"]["properties"]["status"]["enum"]) == states,
            "transition states diverge from PMS-001 lifecycle vocabulary")
    accepted = rejected = 0

    def snapshot(state, timestamp):
        record = copy.deepcopy(template)
        record["lifecycle"]["status"] = state
        record["lifecycle"]["approved"] = "2026-10-15"
        record["approval"] = {
            "status": "Approved", "authority": "Example governance team",
            "approval_ref": "example-approval-001",
        }
        record["audit"]["updated_at"] = timestamp
        return {"registry_version": "0.1.0", "objects": [record]}

    def reject(previous, current, expected):
        nonlocal rejected
        try:
            validate_registry_transition(previous, current, validator)
        except ConformanceError as error:
            require(expected in str(error), f"unexpected transition diagnostic: {error}")
        else:
            raise ConformanceError(f"invalid transition accepted: {expected}")
        rejected += 1

    for index, old_state in enumerate(states):
        for new_index, new_state in enumerate(states):
            previous = snapshot(old_state, "2026-10-15T12:00:00Z")
            current = snapshot(new_state, "2026-10-15T13:00:00Z")
            if new_index in (index, index + 1):
                validate_registry_transition(previous, current, validator)
                accepted += 1
            else:
                reject(previous, current, f"invalid lifecycle transition {old_state} -> {new_state}")
    previous = snapshot("Draft", "2026-10-15T12:00:00Z")
    validate_registry_transition(previous, previous, validator)
    accepted += 1
    current = copy.deepcopy(previous)
    current["objects"][0]["metadata"]["name"] = "Changed record"
    reject(previous, current, "changed record requires a later audit.updated_at")
    current["objects"][0]["audit"]["updated_at"] = "2026-10-15T13:00:00+01:00"
    reject(previous, current, "changed record requires a later audit.updated_at")
    current["objects"][0]["audit"]["updated_at"] = "2026-10-15T12:30:00+01:00"
    reject(previous, current, "audit.updated_at moves backwards")
    current["objects"][0]["audit"]["updated_at"] = "2026-10-15T13:30:00+01:00"
    validate_registry_transition(previous, current, validator)
    accepted += 1
    current = snapshot("Review", "2026-10-15T12:00:00Z")
    reject(previous, current, "changed record requires a later audit.updated_at")
    current = snapshot("Review", "2026-10-15T13:00:00Z")
    current["objects"][0]["lifecycle"]["created"] = "2026-10-14"
    reject(previous, current, "lifecycle.created is immutable")
    current = copy.deepcopy(previous)
    added = copy.deepcopy(current["objects"][0])
    added["metadata"]["id"] = "FE-00002"
    current["objects"].append(added)
    validate_registry_transition(previous, current, validator)
    current["objects"].reverse()
    validate_registry_transition(previous, current, validator)
    accepted += 2
    reject(current, previous, "removes object IDs: FE-00002")
    renamed = copy.deepcopy(previous)
    renamed["objects"][0]["metadata"]["id"] = "FE-00003"
    reject(previous, renamed, "removes object IDs: FE-00001")
    for label in ("previous", "current"):
        invalid = copy.deepcopy(previous)
        invalid["objects"][0]["dependencies"] = ["FE-99999"]
        reject(invalid if label == "previous" else previous,
               invalid if label == "current" else previous, f"{label} registry:")
    invalid = copy.deepcopy(previous)
    del invalid["objects"][0]["ownership"]
    reject(invalid, previous, "previous registry: registry structure")
    reject(previous, invalid, "current registry: registry structure")
    # A pair of valid standalone snapshots remains valid without transition mode.
    validate_palaco_registry(snapshot("Archived", "2026-10-15T12:00:00Z"), validator)
    validate_palaco_registry(snapshot("Draft", "2026-10-15T12:00:00Z"), validator)
    return f"registry transitions: {accepted} accepted + {rejected} rejected comparisons"


def check_palaco_lifecycle():
    validators = palaco_validators()
    validator = validators["PCR-000.schema.json"]
    template = read_json(PALACO_FIXTURE_DIR / "FE-00001.fixture.json")
    approved = copy.deepcopy(template)
    approved["lifecycle"]["approved"] = "2026-10-16"
    approved["audit"]["updated_at"] = "2026-10-16T00:00:00Z"
    approved["approval"] = {
        "status": "Approved", "authority": "Example governance team",
        "approval_ref": "example-approval-001",
    }
    positives = []
    for status in ("Proposed", "Draft", "Review"):
        for approval_status in ("Pending", "Rejected"):
            record = copy.deepcopy(template)
            record["lifecycle"]["status"] = status
            record["approval"]["status"] = approval_status
            positives.append(record)
    for status in ("Proposed", "Draft", "Review", "Approved", "Active", "Deprecated", "Retired", "Archived"):
        record = copy.deepcopy(approved)
        record["lifecycle"]["status"] = status
        positives.append(record)
    for timestamp in ("2026-10-15T23:00:00-01:00", "2026-10-16T01:00:00+01:00",
                      "2026-10-16t00:00:00z"):
        record = copy.deepcopy(approved)
        record["audit"]["updated_at"] = timestamp
        positives.append(record)
    same_day = copy.deepcopy(approved)
    same_day["lifecycle"].update(created="2026-10-16", next_review="2026-10-16")
    positives.append(same_day)
    historical = copy.deepcopy(template)
    historical["lifecycle"].update(created="2020-01-01", next_review="2020-02-01")
    historical["audit"]["updated_at"] = "2020-03-01T00:00:00Z"
    positives.append(historical)
    # A previous approval date may be retained during a new pending review.
    previous = copy.deepcopy(approved)
    previous["lifecycle"]["status"] = "Review"
    previous["approval"] = {"status": "Pending"}
    positives.append(previous)
    for record in positives:
        validate_palaco_registry({"registry_version": "0.1.0", "objects": [record]}, validator)

    negatives = []
    for base, path, value, diagnostic in (
        (template, ("lifecycle", "next_review"), "2026-10-14", "next_review precedes lifecycle.created"),
        (approved, ("lifecycle", "approved"), "2026-10-14", "approved precedes lifecycle.created"),
        (approved, ("lifecycle", "next_review"), "2026-10-15", "next_review precedes lifecycle.approved"),
        (template, ("audit", "updated_at"), "2026-10-14T23:59:59Z", "updated_at precedes lifecycle.created"),
        (template, ("audit", "updated_at"), "2026-10-15T00:30:00+01:00", "updated_at precedes lifecycle.created"),
        (approved, ("audit", "updated_at"), "2026-10-16T00:30:00+01:00", "updated_at precedes lifecycle.approved"),
    ):
        record = copy.deepcopy(base)
        record[path[0]][path[1]] = value
        negatives.append((record, diagnostic))
    missing_date = copy.deepcopy(approved)
    del missing_date["lifecycle"]["approved"]
    negatives.append((missing_date, "approved approval requires lifecycle.approved"))
    for status in ("Approved", "Active", "Deprecated", "Retired", "Archived"):
        for approval_status in ("Pending", "Rejected"):
            record = copy.deepcopy(template)
            record["lifecycle"]["status"] = status
            record["approval"]["status"] = approval_status
            negatives.append((record, f"lifecycle status {status} requires approval.status Approved"))
    for record, diagnostic in negatives:
        instance = {"registry_version": "0.1.0", "objects": [record]}
        require(validator.is_valid(instance), "lifecycle negative must be structurally valid")
        # These additional rules must not silently tighten standalone record validation.
        require(validators["PMS-001.schema.json"].is_valid(record),
                "standalone PMS-001 unexpectedly rejects lifecycle snapshot")
        try:
            validate_palaco_registry(instance, validator)
        except ConformanceError as error:
            require(f"FE-00001: " in str(error) and diagnostic in str(error),
                    f"unexpected lifecycle diagnostic: {error}")
        else:
            raise ConformanceError(f"invalid lifecycle snapshot accepted: {diagnostic}")
    return f"registry lifecycle: {len(positives)} accepted + {len(negatives)} rejected snapshots"


def check_palaco_cycles():
    validator = palaco_validators()["PCR-000.schema.json"]
    template = read_json(PALACO_FIXTURE_DIR / "FE-00001.fixture.json")
    ids = [f"FE-{index:05d}" for index in range(1, 5)]
    fixture = {"registry_version": "0.1.0", "objects": []}
    for object_id in ids:
        record = copy.deepcopy(template)
        record["metadata"]["id"] = object_id
        fixture["objects"].append(record)
    negative_count = 0
    positive_count = 0

    def snapshot(edges):
        instance = copy.deepcopy(fixture)
        for source, target, representation in edges:
            record = instance["objects"][source]
            if representation == "upstream":
                record["traceability"]["upstream"].append(ids[target])
            elif representation == "dependencies":
                record.setdefault("dependencies", []).append(ids[target])
            else:
                record["traceability"]["relationships"].append({
                    "source": ids[source], "relation": "DEPENDS_ON", "target": ids[target],
                })
        return instance

    def reject(instance, label, cycle):
        nonlocal negative_count
        try:
            validate_palaco_registry(instance, validator)
        except ConformanceError as error:
            require(str(error) == f"{label} cycle: {cycle}",
                    f"unexpected cycle diagnostic: {error}")
        else:
            raise ConformanceError(f"{label}: cyclic registry accepted")
        negative_count += 1

    for representation in ("dependencies", "edge", "upstream"):
        label = "upstream" if representation == "upstream" else "dependency"
        reject(snapshot([(0, 1, representation), (1, 0, representation)]),
               label, "FE-00001 -> FE-00002 -> FE-00001")
        # Root 0 finishes first: the cycle is in another component.
        reject(snapshot([(1, 2, representation), (2, 3, representation), (3, 1, representation)]),
               label, "FE-00002 -> FE-00003 -> FE-00004 -> FE-00002")
        # A diamond has shared ancestors, but no back edge.
        diamond = snapshot([(0, 1, representation), (0, 2, representation),
                            (1, 3, representation), (2, 3, representation)])
        validate_palaco_registry(diamond, validator)
        diamond["objects"].reverse()
        validate_palaco_registry(diamond, validator)
        positive_count += 2
    reject(snapshot([(0, 1, "dependencies"), (1, 2, "edge"), (2, 0, "dependencies")]),
           "dependency", "FE-00001 -> FE-00002 -> FE-00003 -> FE-00001")
    # Duplicate representations of the same edge must not create a cycle.
    validate_palaco_registry(snapshot([(0, 1, "dependencies"), (0, 1, "edge")]), validator)
    # Upstream and dependency edges describe distinct graphs.
    validate_palaco_registry(snapshot([(0, 1, "dependencies"), (1, 0, "upstream")]), validator)
    # Generic references can be reciprocal, such as evidence and audit links.
    reciprocal = copy.deepcopy(fixture)
    reciprocal["objects"][0]["compliance"] = [ids[1]]
    reciprocal["objects"][1]["compliance"] = [ids[0]]
    validate_palaco_registry(reciprocal, validator)
    evidence = copy.deepcopy(template)
    evidence["object_type"] = "EVD"
    evidence["metadata"]["id"] = "EVD-00001"
    evidence["audit"]["audit_refs"] = ["AUD-00001"]
    evidence["traceability"]["relationships"] = [
        {"source": "EVD-00001", "relation": "AUDITED_BY", "target": "AUD-00001"}
    ]
    audit = copy.deepcopy(template)
    audit["object_type"] = "AUD"
    audit["metadata"]["id"] = "AUD-00001"
    audit["evidence"] = ["EVD-00001"]
    validate_palaco_registry({"registry_version": "0.1.0", "objects": [evidence, audit]}, validator)
    positive_count += 4

    # Exercise traversal past Python's normal recursion limit without schema overhead.
    depth = sys.getrecursionlimit() + 100
    graph = {f"FE-{index:05d}": {f"FE-{index + 1:05d}"} for index in range(depth)}
    graph[f"FE-{depth:05d}"] = set()
    require_acyclic(graph, "dependency")
    graph[f"FE-{depth:05d}"] = {f"FE-{depth - 1:05d}"}
    try:
        require_acyclic(graph, "dependency")
    except ConformanceError as error:
        expected = f"dependency cycle: FE-{depth - 1:05d} -> FE-{depth:05d} -> FE-{depth - 1:05d}"
        require(str(error) == expected, f"unexpected deep-cycle diagnostic: {error}")
    else:
        raise ConformanceError("deep dependency cycle accepted")
    return (
        f"registry cycles: {negative_count} rejected, {positive_count} acyclic snapshots "
        f"accepted + deep traversal checks ({depth + 1} nodes)"
    )


# --------------------------------------------------------------------------
# Parser regression tests
# --------------------------------------------------------------------------

DUPLICATE_KEY_CASES = {
    "schema root duplicate": '{"$id": "urn:a", "type": "object", "$id": "urn:b"}',
    "schema nested duplicate": (
        '{"$id": "urn:a", "definitions": {"X": {"type": "string", "type": "object"}}}'
    ),
    "fixture root duplicate": '{"message_id": "m1", "body": "a", "message_id": "m2"}',
    "fixture nested duplicate": (
        '{"message_id": "m1", "provenance": '
        '{"origin_surface": "web", "origin_surface": "mobile"}}'
    ),
    "fixture duplicate inside array item": (
        '{"participants": [{"role": "OWNER", "role": "GUEST"}]}'
    ),
}

VALID_SAME_KEY_CASES = {
    "schema same key in sibling objects": (
        '{"$id": "urn:a", "definitions": '
        '{"A": {"type": "string"}, "B": {"type": "object"}}}'
    ),
    "fixture same key at different depths": (
        '{"state": "ACTIVE", "context": {"state": "x", "tags": []}}'
    ),
    "fixture same key in array items": (
        '{"participants": [{"role": "OWNER"}, {"role": "GUEST"}]}'
    ),
}

STATUS_PASS_CASES = {
    "h3 status": ("# Doc\n### Status\nDraft v0.1\n", "Draft v0.1"),
    "case-insensitive with blank line": ("## STATUS ##\n\n  Final\n", "Final"),
    "status in fence ignored": (
        "```md\n### Status\n```\n### Status\nDraft\n~~~\n## Status\n~~~\n",
        "Draft",
    ),
}

STATUS_FAIL_CASES = {
    "missing": "# Doc\n## Version\n1\n",
    "only inside fence": "```\n### Status\nDraft\n```\n",
    "unclosed fence hides status": "```\n### Status\nDraft\n",
    "duplicate": "### Status\nDraft\n### status\nFinal\n",
    "empty at EOF": "### Status\n\n",
    "followed by heading": "### Status\n\n## Next\nx\n",
    "followed by comment": "### Status\n<!-- TODO -->\n",
    "not a heading": "Status\nDraft\n",
}


def run_regression_tests():
    count = 0
    for label, text in DUPLICATE_KEY_CASES.items():
        try:
            parse_json(text)
        except ConformanceError as error:
            require("Duplicate JSON key" in str(error), f"{label}: wrong error {error}")
        else:
            raise ConformanceError(f"duplicate-key test accepted: {label}")
        print(f"  ok rejects {label}")
        count += 1

    for label, text in VALID_SAME_KEY_CASES.items():
        parse_json(text)
        print(f"  ok accepts {label}")
        count += 1

    try:
        parse_json('{"x": NaN}')
    except ConformanceError:
        print("  ok rejects NaN constant")
        count += 1
    else:
        raise ConformanceError("NaN constant accepted")

    for label, (text, expected) in STATUS_PASS_CASES.items():
        value = extract_status(text)
        require(value == expected, f"Status parser {label}: got {value!r}")
        print(f"  ok Status parser accepts {label}")
        count += 1

    for label, text in STATUS_FAIL_CASES.items():
        try:
            extract_status(text)
        except ConformanceError:
            print(f"  ok Status parser rejects {label}")
            count += 1
        else:
            raise ConformanceError(f"Status parser accepted invalid case: {label}")

    return f"{count} parser regression tests"


# --------------------------------------------------------------------------

CHECKS = (
    ("PALACO multi-cluster fixture conformance", check_palaco_cluster_fixture),
    ("PALACO component CLI fail-closed conformance", check_palaco_components_fail_closed),
    ("PALACO exhaustive component partitions", check_palaco_component_partitions),
    ("PALACO registry component summary conformance", check_palaco_components),
    ("PALACO shared upstream graph contract", check_palaco_upstream_contract),
    ("PALACO shared dependency graph contract", check_palaco_dependency_contract),
    ("parser regression tests", run_regression_tests),
    ("standards metadata", check_metadata),
    ("RIO + VisitCard + PALACO schema $id uniqueness", check_schema_ids),
    ("RIO schema/fixture conformance", check_rio_fixtures),
    ("VisitCard schema/fixture conformance", check_visitcard_fixtures),
    ("PALACO schema/fixture conformance", check_palaco_fixtures),
    ("PALACO closed registry conformance", check_palaco_registry),
    ("PALACO registry cycle conformance", check_palaco_cycles),
    ("PALACO registry lifecycle conformance", check_palaco_lifecycle),
    ("PALACO registry transition conformance", check_palaco_transitions),
    ("PALACO registry trace conformance", check_palaco_traces),
    ("PALACO registry object-type query conformance", check_palaco_find),
    ("PALACO registry lifecycle-status query conformance", check_palaco_find_lifecycle),
    ("PALACO registry summary conformance", check_palaco_summary),
    ("PALACO registry snapshot diff conformance", check_palaco_diff),
    ("PALACO registry review-date query conformance", check_palaco_reviews_due),
    ("PALACO registry domain query conformance", check_palaco_domain),
    ("PALACO registry verification-status query conformance", check_palaco_verification),
    ("PALACO registry approval-status query conformance", check_palaco_approval),
    ("PALACO registry ownership query conformance", check_palaco_owner),
    ("PALACO registry criticality query conformance", check_palaco_criticality),
    ("PALACO registry confidentiality query conformance", check_palaco_confidentiality),
    ("PALACO registry integrity-label query conformance", check_palaco_integrity),
    ("PALACO registry availability-label query conformance", check_palaco_availability),
    ("PALACO registry relationship-type query conformance", check_palaco_relationship),
    ("PALACO registry audit-updater query conformance", check_palaco_updater),
    ("PALACO registry name query conformance", check_palaco_name),
    ("PALACO registry updated-since query conformance", check_palaco_updated_since),
    ("PALACO registry direct-dependents query conformance", check_palaco_dependents),
    ("PALACO registry direct-dependencies query conformance", check_palaco_dependencies),
    ("PALACO registry orphan query conformance", check_palaco_orphans),
    ("PALACO registry dependency-orphan query conformance", check_palaco_dependency_orphans),
    ("PALACO control verification-status query conformance", check_unverified_controls),
    ("PALACO evidence audit-link query conformance", check_unaudited_evidence),
)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--registry", type=Path, help="Validate one closed PCR-000 registry snapshot")
    parser.add_argument("--previous-registry", type=Path,
                        help="Compare --registry against the preceding closed snapshot")
    parser.add_argument("--diff", action="store_true",
                        help="Return ID differences as JSON; requires --registry and --previous-registry")
    parser.add_argument("--trace", metavar="OBJECT_ID",
                        help="Return reachable IDs from traceability.upstream as JSON")
    parser.add_argument("--find-type", metavar="OBJECT_TYPE",
                        help="Return matching canonical object IDs as JSON (e.g. REQ)")
    parser.add_argument("--find-domain", metavar="DOMAIN",
                        help="Return IDs matching exact case-sensitive metadata.domain as JSON")
    parser.add_argument("--find-verification", metavar="STATUS",
                        help="Return IDs matching each record's own PMS-001 verification status as JSON")
    parser.add_argument("--find-approval", metavar="STATUS",
                        help="Return IDs matching PMS-001 approval.status metadata as JSON")
    parser.add_argument("--find-owner", nargs=2, metavar=("ROLE", "OWNER"),
                        help="Return IDs matching an exact ownership role and owner as JSON")
    parser.add_argument("--find-criticality", metavar="CRITICALITY",
                        help="Return IDs matching exact PMS-001 classification.criticality as JSON")
    parser.add_argument("--find-confidentiality", metavar="CONFIDENTIALITY",
                        help="Return IDs matching exact PMS-001 confidentiality labels; not access control")
    parser.add_argument("--find-integrity", metavar="INTEGRITY",
                        help="Return IDs matching exact PMS-001 integrity classification labels")
    parser.add_argument("--find-availability", metavar="AVAILABILITY",
                        help="Return IDs matching exact PMS-001 availability classification labels")
    parser.add_argument("--find-relationship", metavar="RELATION",
                        help="Return source IDs of explicit PMS-002 relationship types as JSON")
    parser.add_argument("--find-updater", metavar="UPDATER",
                        help="Return IDs matching exact audit.updated_by metadata; not authenticated identity")
    parser.add_argument("--find-name", metavar="NAME",
                        help="Return IDs matching exact case-sensitive metadata.name as JSON")
    parser.add_argument("--find-updated-since", metavar="YYYY-MM-DD",
                        help="Return IDs with audit.updated_at on or after an explicit date at midnight UTC")
    parser.add_argument("--find-dependents", metavar="OBJECT_ID",
                        help="Return direct dependency source IDs from dependencies and DEPENDS_ON edges")
    parser.add_argument("--find-dependencies", metavar="OBJECT_ID",
                        help="Return direct dependency target IDs from dependencies and DEPENDS_ON edges")
    parser.add_argument("--find-lifecycle", metavar="STATUS",
                        help="Return IDs with the exact PMS-001 lifecycle status as JSON (e.g. Draft)")
    parser.add_argument("--summary", action="store_true",
                        help="Return validated object, domain, ownership, status, classification and explicit relationship counts as JSON")
    parser.add_argument("--components", choices=("upstream", "dependency"),
                        help="Return weakly connected object-ID groups as JSON; requires --registry")
    parser.add_argument("--component-of", metavar="OBJECT_ID",
                        help="Return only the cluster containing OBJECT_ID; requires --components")
    parser.add_argument("--find-review-due", metavar="YYYY-MM-DD",
                        help="Return IDs with next_review on or before an explicit date; all lifecycle states")
    parser.add_argument("--find-orphans", action="store_true",
                        help="Return IDs isolated in traceability.upstream as JSON")
    parser.add_argument("--find-dependency-orphans", action="store_true",
                        help="Return IDs isolated in dependencies plus DEPENDS_ON as JSON")
    parser.add_argument("--find-unverified-controls", action="store_true",
                        help="Return COM IDs whose own or referenced VER status is not Passed")
    parser.add_argument("--find-unaudited-evidence", action="store_true",
                        help="Return EVD IDs without audit references or AUD evidence-package membership")
    parser.add_argument("--direction", choices=("upstream", "downstream"),
                        help="Trace direction (default: upstream); requires --trace")
    args = parser.parse_args()
    if args.component_of is not None and args.components is None:
        parser.error("--component-of requires --components")
    if args.components is not None:
        if args.registry is None:
            parser.error("--components requires --registry")
        if any(value is not None and value is not False
               for name, value in vars(args).items()
               if name not in ("registry", "components", "component_of")):
            parser.error("--components cannot be combined with other query or comparison modes")
    if args.find_dependency_orphans:
        if args.registry is None:
            parser.error("--find-dependency-orphans requires --registry")
        if (args.previous_registry is not None or args.diff or args.trace is not None
                or args.find_type is not None or args.find_lifecycle is not None or args.summary
                or args.find_domain is not None or args.find_verification is not None
                or args.find_approval is not None or args.find_owner is not None
                or args.find_criticality is not None or args.find_confidentiality is not None
                or args.find_integrity is not None or args.find_availability is not None
                or args.find_relationship is not None or args.find_updater is not None
                or args.find_name is not None or args.find_updated_since is not None
                or args.find_dependencies is not None or args.find_dependents is not None
                or args.find_review_due is not None or args.find_orphans
                or args.find_unverified_controls or args.find_unaudited_evidence
                or args.direction is not None):
            parser.error("--find-dependency-orphans cannot be combined with other query or comparison modes")
    if args.find_dependencies is not None:
        if args.registry is None:
            parser.error("--find-dependencies requires --registry")
        if (args.previous_registry is not None or args.diff or args.trace is not None
                or args.find_type is not None or args.find_lifecycle is not None or args.summary
                or args.find_domain is not None or args.find_verification is not None
                or args.find_approval is not None or args.find_owner is not None
                or args.find_criticality is not None or args.find_confidentiality is not None
                or args.find_integrity is not None or args.find_availability is not None
                or args.find_relationship is not None or args.find_updater is not None
                or args.find_name is not None or args.find_updated_since is not None
                or args.find_dependents is not None or args.find_review_due is not None
                or args.find_orphans or args.find_unverified_controls or args.find_unaudited_evidence
                or args.direction is not None):
            parser.error("--find-dependencies cannot be combined with other query or comparison modes")
    if args.find_dependents is not None:
        if args.registry is None:
            parser.error("--find-dependents requires --registry")
        if (args.previous_registry is not None or args.diff or args.trace is not None
                or args.find_type is not None or args.find_lifecycle is not None or args.summary
                or args.find_domain is not None or args.find_verification is not None
                or args.find_approval is not None or args.find_owner is not None
                or args.find_criticality is not None or args.find_confidentiality is not None
                or args.find_integrity is not None or args.find_availability is not None
                or args.find_relationship is not None or args.find_updater is not None
                or args.find_name is not None or args.find_updated_since is not None
                or args.find_review_due is not None or args.find_orphans
                or args.find_unverified_controls or args.find_unaudited_evidence
                or args.direction is not None):
            parser.error("--find-dependents cannot be combined with other query or comparison modes")
    if args.find_updated_since is not None:
        if args.registry is None:
            parser.error("--find-updated-since requires --registry")
        if (args.previous_registry is not None or args.diff or args.trace is not None
                or args.find_type is not None or args.find_lifecycle is not None or args.summary
                or args.find_domain is not None or args.find_verification is not None
                or args.find_approval is not None or args.find_owner is not None
                or args.find_criticality is not None or args.find_confidentiality is not None
                or args.find_integrity is not None or args.find_availability is not None
                or args.find_relationship is not None or args.find_updater is not None
                or args.find_name is not None or args.find_review_due is not None
                or args.find_orphans or args.find_unverified_controls or args.find_unaudited_evidence
                or args.direction is not None):
            parser.error("--find-updated-since cannot be combined with other query or comparison modes")
    if args.find_name is not None:
        if args.registry is None:
            parser.error("--find-name requires --registry")
        if (args.previous_registry is not None or args.diff or args.trace is not None
                or args.find_type is not None or args.find_lifecycle is not None or args.summary
                or args.find_domain is not None or args.find_verification is not None
                or args.find_approval is not None or args.find_owner is not None
                or args.find_criticality is not None or args.find_confidentiality is not None
                or args.find_integrity is not None or args.find_availability is not None
                or args.find_relationship is not None or args.find_updater is not None
                or args.find_review_due is not None or args.find_orphans
                or args.find_unverified_controls or args.find_unaudited_evidence
                or args.direction is not None):
            parser.error("--find-name cannot be combined with other query or comparison modes")
    if args.find_updater is not None:
        if args.registry is None:
            parser.error("--find-updater requires --registry")
        if (args.previous_registry is not None or args.diff or args.trace is not None
                or args.find_type is not None or args.find_lifecycle is not None or args.summary
                or args.find_domain is not None or args.find_verification is not None
                or args.find_approval is not None or args.find_owner is not None
                or args.find_criticality is not None or args.find_confidentiality is not None
                or args.find_integrity is not None or args.find_availability is not None
                or args.find_relationship is not None or args.find_review_due is not None
                or args.find_orphans or args.find_unverified_controls or args.find_unaudited_evidence
                or args.direction is not None):
            parser.error("--find-updater cannot be combined with other query or comparison modes")
    if args.find_relationship is not None:
        if args.registry is None:
            parser.error("--find-relationship requires --registry")
        if (args.previous_registry is not None or args.diff or args.trace is not None
                or args.find_type is not None or args.find_lifecycle is not None or args.summary
                or args.find_domain is not None or args.find_verification is not None
                or args.find_approval is not None or args.find_owner is not None
                or args.find_criticality is not None or args.find_confidentiality is not None
                or args.find_integrity is not None or args.find_availability is not None
                or args.find_review_due is not None or args.find_orphans
                or args.find_unverified_controls or args.find_unaudited_evidence
                or args.direction is not None):
            parser.error("--find-relationship cannot be combined with other query or comparison modes")
    if args.find_availability is not None:
        if args.registry is None:
            parser.error("--find-availability requires --registry")
        if (args.previous_registry is not None or args.diff or args.trace is not None
                or args.find_type is not None or args.find_lifecycle is not None or args.summary
                or args.find_domain is not None or args.find_verification is not None
                or args.find_approval is not None or args.find_owner is not None
                or args.find_criticality is not None or args.find_confidentiality is not None
                or args.find_integrity is not None or args.find_review_due is not None
                or args.find_orphans or args.find_unverified_controls or args.find_unaudited_evidence
                or args.direction is not None):
            parser.error("--find-availability cannot be combined with other query or comparison modes")
    if args.find_integrity is not None:
        if args.registry is None:
            parser.error("--find-integrity requires --registry")
        if (args.previous_registry is not None or args.diff or args.trace is not None
                or args.find_type is not None or args.find_lifecycle is not None or args.summary
                or args.find_domain is not None or args.find_verification is not None
                or args.find_approval is not None or args.find_owner is not None
                or args.find_criticality is not None or args.find_confidentiality is not None
                or args.find_review_due is not None or args.find_orphans
                or args.find_unverified_controls or args.find_unaudited_evidence
                or args.direction is not None):
            parser.error("--find-integrity cannot be combined with other query or comparison modes")
    if args.find_confidentiality is not None:
        if args.registry is None:
            parser.error("--find-confidentiality requires --registry")
        if (args.previous_registry is not None or args.diff or args.trace is not None
                or args.find_type is not None or args.find_lifecycle is not None or args.summary
                or args.find_domain is not None or args.find_verification is not None
                or args.find_approval is not None or args.find_owner is not None
                or args.find_criticality is not None or args.find_review_due is not None
                or args.find_orphans or args.find_unverified_controls or args.find_unaudited_evidence
                or args.direction is not None):
            parser.error("--find-confidentiality cannot be combined with other query or comparison modes")
    if args.find_criticality is not None:
        if args.registry is None:
            parser.error("--find-criticality requires --registry")
        if (args.previous_registry is not None or args.diff or args.trace is not None
                or args.find_type is not None or args.find_lifecycle is not None or args.summary
                or args.find_domain is not None or args.find_verification is not None
                or args.find_approval is not None or args.find_owner is not None
                or args.find_review_due is not None or args.find_orphans
                or args.find_unverified_controls or args.find_unaudited_evidence
                or args.direction is not None):
            parser.error("--find-criticality cannot be combined with other query or comparison modes")
    if args.find_owner is not None:
        if args.registry is None:
            parser.error("--find-owner requires --registry")
        if (args.previous_registry is not None or args.diff or args.trace is not None
                or args.find_type is not None or args.find_lifecycle is not None or args.summary
                or args.find_domain is not None or args.find_verification is not None
                or args.find_approval is not None or args.find_review_due is not None
                or args.find_orphans or args.find_unverified_controls or args.find_unaudited_evidence
                or args.direction is not None):
            parser.error("--find-owner cannot be combined with other query or comparison modes")
    if args.find_approval is not None:
        if args.registry is None:
            parser.error("--find-approval requires --registry")
        if (args.previous_registry is not None or args.diff or args.trace is not None
                or args.find_type is not None or args.find_lifecycle is not None or args.summary
                or args.find_domain is not None or args.find_verification is not None
                or args.find_review_due is not None or args.find_orphans
                or args.find_unverified_controls or args.find_unaudited_evidence
                or args.direction is not None):
            parser.error("--find-approval cannot be combined with other query or comparison modes")
    if args.find_verification is not None:
        if args.registry is None:
            parser.error("--find-verification requires --registry")
        if (args.previous_registry is not None or args.diff or args.trace is not None
                or args.find_type is not None or args.find_lifecycle is not None or args.summary
                or args.find_domain is not None or args.find_review_due is not None or args.find_orphans
                or args.find_unverified_controls or args.find_unaudited_evidence
                or args.direction is not None):
            parser.error("--find-verification cannot be combined with other query or comparison modes")
    if args.find_domain is not None:
        if args.registry is None:
            parser.error("--find-domain requires --registry")
        if (args.previous_registry is not None or args.diff or args.trace is not None
                or args.find_type is not None or args.find_lifecycle is not None or args.summary
                or args.find_review_due is not None or args.find_orphans
                or args.find_unverified_controls or args.find_unaudited_evidence
                or args.direction is not None):
            parser.error("--find-domain cannot be combined with other query or comparison modes")
    if args.find_review_due is not None:
        if args.registry is None:
            parser.error("--find-review-due requires --registry")
        if (args.previous_registry is not None or args.diff or args.trace is not None
                or args.find_type is not None or args.find_lifecycle is not None or args.summary
                or args.find_orphans or args.find_unverified_controls or args.find_unaudited_evidence
                or args.direction is not None):
            parser.error("--find-review-due cannot be combined with other query or comparison modes")
    if args.diff:
        if args.registry is None or args.previous_registry is None:
            parser.error("--diff requires --registry and --previous-registry")
        if (args.trace is not None or args.find_type is not None or args.find_lifecycle is not None
                or args.summary or args.find_orphans or args.find_unverified_controls
                or args.find_unaudited_evidence or args.direction is not None):
            parser.error("--diff cannot be combined with other query modes")
    if args.previous_registry is not None and args.registry is None:
        parser.error("--previous-registry requires --registry")
    if args.trace is not None and args.registry is None:
        parser.error("--trace requires --registry")
    if args.direction is not None and args.trace is None:
        parser.error("--direction requires --trace")
    if args.trace is not None and args.previous_registry is not None:
        parser.error("--trace cannot be combined with --previous-registry")
    if args.find_type is not None:
        if args.registry is None:
            parser.error("--find-type requires --registry")
        if args.trace is not None or args.previous_registry is not None:
            parser.error("--find-type cannot be combined with --trace or --previous-registry")
    if args.find_orphans:
        if args.registry is None:
            parser.error("--find-orphans requires --registry")
        if args.trace is not None or args.find_type is not None or args.previous_registry is not None:
            parser.error("--find-orphans cannot be combined with --trace, --find-type or --previous-registry")
    if args.find_unverified_controls:
        if args.registry is None:
            parser.error("--find-unverified-controls requires --registry")
        if args.trace is not None or args.find_type is not None or args.find_orphans or args.previous_registry is not None:
            parser.error("--find-unverified-controls cannot be combined with other query or comparison modes")
    if args.find_unaudited_evidence:
        if args.registry is None:
            parser.error("--find-unaudited-evidence requires --registry")
        if (args.trace is not None or args.find_type is not None or args.find_orphans
                or args.find_unverified_controls or args.previous_registry is not None):
            parser.error("--find-unaudited-evidence cannot be combined with other query or comparison modes")
    if args.find_lifecycle is not None:
        if args.registry is None:
            parser.error("--find-lifecycle requires --registry")
        if (args.trace is not None or args.find_type is not None or args.find_orphans
                or args.find_unverified_controls or args.find_unaudited_evidence
                or args.previous_registry is not None):
            parser.error("--find-lifecycle cannot be combined with other query or comparison modes")
    if args.summary:
        if args.registry is None:
            parser.error("--summary requires --registry")
        if (args.trace is not None or args.find_type is not None or args.find_lifecycle is not None
                or args.find_orphans or args.find_unverified_controls or args.find_unaudited_evidence
                or args.previous_registry is not None):
            parser.error("--summary cannot be combined with other query or comparison modes")
    if args.registry is not None:
        try:
            current = read_json(args.registry)
            if args.components is not None:
                result = find_palaco_components(current, args.components, object_id=args.component_of)
                print(json.dumps(result, indent=2))
                return 0
            elif args.find_dependency_orphans:
                result = find_palaco_dependency_orphans(current)
                print(json.dumps(result, indent=2))
                return 0
            elif args.find_dependencies is not None:
                result = find_palaco_dependencies(current, args.find_dependencies)
                print(json.dumps(result, indent=2))
                return 0
            elif args.find_dependents is not None:
                result = find_palaco_dependents(current, args.find_dependents)
                print(json.dumps(result, indent=2))
                return 0
            elif args.find_updated_since is not None:
                result = find_palaco_updated_since(current, args.find_updated_since)
                print(json.dumps(result, indent=2))
                return 0
            elif args.find_name is not None:
                result = find_palaco_name(current, args.find_name)
                print(json.dumps(result, indent=2))
                return 0
            elif args.find_updater is not None:
                result = find_palaco_updater(current, args.find_updater)
                print(json.dumps(result, indent=2))
                return 0
            elif args.find_relationship is not None:
                result = find_palaco_relationship(current, args.find_relationship)
                print(json.dumps(result, indent=2))
                return 0
            elif args.find_availability is not None:
                result = find_palaco_availability(current, args.find_availability)
                print(json.dumps(result, indent=2))
                return 0
            elif args.find_integrity is not None:
                result = find_palaco_integrity(current, args.find_integrity)
                print(json.dumps(result, indent=2))
                return 0
            elif args.find_confidentiality is not None:
                result = find_palaco_confidentiality(current, args.find_confidentiality)
                print(json.dumps(result, indent=2))
                return 0
            elif args.find_criticality is not None:
                result = find_palaco_criticality(current, args.find_criticality)
                print(json.dumps(result, indent=2))
                return 0
            elif args.find_owner is not None:
                result = find_palaco_owner(current, *args.find_owner)
                print(json.dumps(result, indent=2))
                return 0
            elif args.find_approval is not None:
                result = find_palaco_approval(current, args.find_approval)
                print(json.dumps(result, indent=2))
                return 0
            elif args.find_verification is not None:
                result = find_palaco_verification(current, args.find_verification)
                print(json.dumps(result, indent=2))
                return 0
            elif args.find_domain is not None:
                result = find_palaco_domain(current, args.find_domain)
                print(json.dumps(result, indent=2))
                return 0
            elif args.find_review_due is not None:
                result = find_palaco_reviews_due(current, args.find_review_due)
                print(json.dumps(result, indent=2))
                return 0
            elif args.diff:
                result = diff_palaco_registry(read_json(args.previous_registry), current)
                print(json.dumps(result, indent=2))
                return 0
            elif args.summary:
                result = summarize_palaco_registry(current)
                print(json.dumps(result, indent=2))
                return 0
            elif args.find_lifecycle is not None:
                result = find_palaco_lifecycle(current, args.find_lifecycle)
                print(json.dumps(result, indent=2))
                return 0
            elif args.find_unaudited_evidence:
                result = find_unaudited_evidence(current)
                print(json.dumps(result, indent=2))
                return 0
            elif args.find_unverified_controls:
                result = find_unverified_controls(current)
                print(json.dumps(result, indent=2))
                return 0
            elif args.find_orphans:
                result = find_palaco_orphans(current)
                print(json.dumps(result, indent=2))
                return 0
            elif args.find_type is not None:
                result = find_palaco_objects(current, args.find_type)
                print(json.dumps(result, indent=2))
                return 0
            elif args.trace is not None:
                result = trace_palaco_registry(current, args.trace, args.direction or "upstream")
                print(json.dumps(result, indent=2))
                return 0
            elif args.previous_registry is None:
                summary = validate_palaco_registry(current)
            else:
                summary = validate_registry_transition(read_json(args.previous_registry), current)
        except Exception as error:  # fail closed, including unreadable files
            print(f"FAIL: {type(error).__name__}: {error}",
                  file=sys.stderr if args.components is not None else sys.stdout)
            return 1
        print(f"PASS: {summary}")
        return 0
    failures = 0
    for name, check in CHECKS:
        print(f"== {name}")
        try:
            summary = check()
        except Exception as error:  # fail closed on anything unexpected
            failures += 1
            print(f"FAIL: {name}: {type(error).__name__}: {error}")
        else:
            print(f"PASS: {summary}")

    if failures:
        print(f"FAIL: GO-13 standards conformance ({failures} check(s) failed)")
        return 1
    print("PASS: GO-13 standards conformance")
    return 0


if __name__ == "__main__":
    sys.exit(main())
