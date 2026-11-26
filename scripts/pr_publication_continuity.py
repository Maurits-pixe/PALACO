#!/usr/bin/env python3
"""GO-20 v65: offline continuity of signed historical publication checkpoints.

Reverify v64 at every round. The complete publication evidence must remain
unchanged; custodian revocations are append-only and cannot be re-dated.
Two independently pinned observers must agree. Neither signatures nor hashes
establish actual remote publication or permit authorization.
"""
from __future__ import annotations
import argparse
import json
from pathlib import Path
from pr_audit_integrity import canonical_hash, is_hex, unique_pairs
from pr_governance_hardening import validate_shape
from pr_historical_custody_checkpoints import assess as assess_v64

SCHEMA = "palaco.go20-publication-continuity.v1"
PIN_SCHEMA = "palaco.go20-publication-continuity-pin.v1"
HEAD_SCHEMA = "palaco.go20-publication-continuity-independent-head.v1"
ZERO = "0"*64
FIELDS = {"v63_sources", "left", "right", "witness_trust", "revocations", "independent_pin"}


def verdict(errors, rounds=0):
    return {
        "schema": "palaco.go20-publication-continuity-verdict.v1",
        "publication_evidence_valid": not errors,
        "rounds_verified": rounds,
        "errors": sorted(set(errors)),
        "decision": "HOLD", "authorization": "DENY",
        "network_publication_verified": False,
        "physical_archive_verified": False,
        "revocation_enforced_in_production": False,
        "recovery_authorized": False, "failover_authorized": False,
        "merge_authorized": False, "deployment_authorized": False,
        "production_commit_performed": False,
    }


def check_view(view, pin):
    if (not isinstance(view, dict) or set(view) != {"schema", "rounds"} or
            view.get("schema") != SCHEMA or
            not isinstance(view.get("rounds"), list) or
            not 2 <= len(view["rounds"]) <= 4):
        return ["invalid_continuity_view"], 0
    if (not isinstance(pin, dict) or set(pin) != {
            "schema", "first_round", "last_round", "first_sha256",
            "last_sha256", "history_sha256", "v63_sha256",
            "publication_left_sha256", "publication_right_sha256",
            "witness_trust_sha256", "minimum_quorum"
    } or pin.get("schema") != PIN_SCHEMA or
            any(type(pin.get(k)) is not int or pin[k] < n for k,n in (
                ("first_round", 1),("last_round",2),("minimum_quorum",2))) or
            pin["last_round"] != pin["first_round"]+len(view["rounds"])-1 or
            any(not is_hex(pin.get(k),64) for k in (
                "first_sha256","last_sha256","history_sha256","v63_sha256",
                "publication_left_sha256","publication_right_sha256",
                "witness_trust_sha256"))):
        return ["invalid_continuity_pin"], 0
    errors,checked,previous,retained=[],0,None,{}
    for i,rec in enumerate(view["rounds"]):
        if (not isinstance(rec,dict) or set(rec)!={"round","previous_sha256","evidence"} or
                type(rec.get("round")) is not int or
                rec["round"]!=pin["first_round"]+i or
                not is_hex(rec.get("previous_sha256"),64) or
                not isinstance(rec.get("evidence"),dict) or
                set(rec["evidence"])!=FIELDS):
            errors.append(f"invalid_or_missing_round:{i}")
            previous=None
            continue
        data=rec["evidence"]
        local=data["independent_pin"]
        if (not isinstance(local,dict) or
                type(local.get("quorum")) is not int or
                local["quorum"]<pin["minimum_quorum"] or
                canonical_hash(data["v63_sources"])!=pin["v63_sha256"] or
                canonical_hash(data["left"])!=pin["publication_left_sha256"] or
                canonical_hash(data["right"])!=pin["publication_right_sha256"] or
                canonical_hash(data["witness_trust"])!=pin["witness_trust_sha256"]):
            errors.append(f"publication_or_trust_substitution:{i}")
            previous=None
            continue
        try:
            result=assess_v64(*(data[k] for k in (
                "v63_sources","left","right","witness_trust","revocations",
                "independent_pin")))
        except (ValueError,TypeError,KeyError,AttributeError,IndexError,
                OverflowError,RecursionError,MemoryError) as exc:
            errors.append(f"malformed_v64:{i}:{type(exc).__name__}")
            previous=None
            continue
        if not result["checkpoint_evidence_valid"]:
            errors.extend(f"v64:{i}:{e}" for e in result["errors"])
            previous=None
            continue
        checked+=1
        if i==0:
            if rec["previous_sha256"]!=ZERO:
                errors.append("invalid_genesis_link")
            if canonical_hash(rec)!=pin["first_sha256"]:
                errors.append("first_round_anchor_mismatch")
        else:
            if previous is None or rec["previous_sha256"]!=canonical_hash(previous):
                errors.append(f"broken_round_link:{i}")
            if previous is not None:
                old=previous["evidence"]
                if local["quorum"]<old["independent_pin"]["quorum"]:
                    errors.append(f"witness_quorum_downgrade:{i}")
                if local["minimum_snapshot"]<old["independent_pin"]["minimum_snapshot"]:
                    errors.append(f"snapshot_floor_rollback:{i}")
        current={}
        for record in data["revocations"]["entries"]:
            current[(record["custodian_id"],record["public_key_hex"])]=record["effective_snapshot"]
        for key,when in retained.items():
            if current.get(key)!=when:
                errors.append(f"revocation_removed_or_redated:{i}")
        retained=current
        if i==len(view["rounds"])-1 and canonical_hash(rec)!=pin["last_sha256"]:
            errors.append("last_round_anchor_mismatch")
        previous=rec
    if canonical_hash(view)!=pin["history_sha256"]:
        errors.append("independent_history_anchor_mismatch")
    return errors,checked


def assess(left,left_pin,right,right_pin,head):
    try:
        for obj in (left,left_pin,right,right_pin,head):
            validate_shape(obj)
    except (TypeError,ValueError,OverflowError,RecursionError,MemoryError) as exc:
        return verdict(["invalid_structure:"+type(exc).__name__])
    if (not isinstance(head,dict) or set(head)!={
            "schema","expected_history_sha256","minimum_last_round",
            "minimum_quorum"
    } or head.get("schema")!=HEAD_SCHEMA or
            not is_hex(head.get("expected_history_sha256"),64) or
            type(head.get("minimum_last_round")) is not int or
            head["minimum_last_round"]<2 or
            type(head.get("minimum_quorum")) is not int or
            head["minimum_quorum"]<2):
        return verdict(["invalid_independent_head"])
    errors,checked=[],0
    for label,view,pin in (("left",left,left_pin),("right",right,right_pin)):
        issues,count=check_view(view,pin)
        errors.extend(f"{label}:{e}" for e in issues)
        checked+=count
    if errors:
        return verdict(errors,checked)
    if (left_pin["first_round"]!=right_pin["first_round"] or
            left_pin["last_round"]!=right_pin["last_round"]):
        errors.append("observer_window_mismatch")
    if left_pin["last_round"]<head["minimum_last_round"]:
        errors.append("independent_history_rollback")
    if (left_pin["minimum_quorum"]<head["minimum_quorum"] or
            right_pin["minimum_quorum"]<head["minimum_quorum"]):
        errors.append("independent_quorum_downgrade")
    a,b=canonical_hash(left),canonical_hash(right)
    if a!=b:
        errors.append("contradictory_publication_continuity")
    if a!=head["expected_history_sha256"]:
        errors.append("left_external_head_mismatch")
    if b!=head["expected_history_sha256"]:
        errors.append("right_external_head_mismatch")
    return verdict(errors,checked)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ("left","left-pin","right","right-pin","independent-head"):
        parser.add_argument("--"+name,required=True,type=Path)
    args=parser.parse_args()
    try:
        def read(path):
            if not path.is_file() or path.stat().st_size>8*1024*1024:
                raise ValueError("invalid_evidence_file")
            return json.loads(path.read_text(encoding="utf-8"),
                              object_pairs_hook=unique_pairs,
                              parse_constant=lambda _: (_ for _ in ()).throw(ValueError("nonfinite")))
        result=assess(*(read(getattr(args,name.replace("-","_"))) for name in (
            "left","left-pin","right","right-pin","independent-head")))
    except (OSError,ValueError,TypeError,KeyError,UnicodeError,
            OverflowError,RecursionError,MemoryError) as exc:
        result=verdict(["invalid_input:"+type(exc).__name__])
    print(json.dumps(result,indent=2,sort_keys=True))
    return 0 if result["publication_evidence_valid"] else 2


if __name__=="__main__":
    raise SystemExit(main())
