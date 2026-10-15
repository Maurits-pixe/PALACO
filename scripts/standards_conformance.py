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
     owned relationships and consistency with dedicated reference fields.

Any failure exits non-zero.
"""

import argparse
import copy
import json
import re
import sys
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
    return f"closed PALACO registry valid ({len(objects)} objects); not a canonical-status decision"


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
    ("parser regression tests", run_regression_tests),
    ("standards metadata", check_metadata),
    ("RIO + VisitCard + PALACO schema $id uniqueness", check_schema_ids),
    ("RIO schema/fixture conformance", check_rio_fixtures),
    ("VisitCard schema/fixture conformance", check_visitcard_fixtures),
    ("PALACO schema/fixture conformance", check_palaco_fixtures),
    ("PALACO closed registry conformance", check_palaco_registry),
)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--registry", type=Path, help="Validate one closed PCR-000 registry snapshot")
    args = parser.parse_args()
    if args.registry is not None:
        try:
            summary = validate_palaco_registry(read_json(args.registry))
        except Exception as error:  # fail closed, including unreadable files
            print(f"FAIL: {type(error).__name__}: {error}")
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
