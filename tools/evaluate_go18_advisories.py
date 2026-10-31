#!/usr/bin/env python3
"""GO-18 point-in-time vulnerability/advisory evaluation.

Input:
- GO-17 generated SPDX inventory
- explicit GO-18 exception register

Source:
- GitHub Global Security Advisory Database REST API

The evaluator writes evidence even when findings block. Source/network errors are
also recorded and are fail-closed by the separate verifier.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import urllib.error
import urllib.parse
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
SBOM = ROOT / "artifacts" / "go17" / "PALACO.spdx.json"
EXCEPTIONS = ROOT / "evidence" / "governance" / "GO-18-ADVISORY-EXCEPTIONS.json"
OUT = ROOT / "artifacts" / "go18" / "PALACO-advisory-evaluation.json"

API = "https://api.github.com/advisories"
API_VERSION = "2026-03-10"
BATCH_SIZE = 40
MAX_WORKERS = 8


def git(*args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed: {result.stderr.strip()}")
    return result.stdout.strip()


def now_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def headers() -> dict[str, str]:
    result = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "PALACO-GO-18-Advisory-Evaluation",
        "X-GitHub-Api-Version": API_VERSION,
    }
    token = os.environ.get("GITHUB_TOKEN", "")
    if token:
        result["Authorization"] = f"Bearer {token}"
    return result


def fetch_page(url: str) -> tuple[list[dict], str | None]:
    request = urllib.request.Request(url, headers=headers())
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            payload = json.loads(response.read().decode("utf-8"))
            if not isinstance(payload, list):
                raise RuntimeError("GitHub advisory API returned a non-list payload")
            next_url = None
            link = response.headers.get("Link", "")
            for item in link.split(","):
                if 'rel="next"' in item:
                    left = item.find("<")
                    right = item.find(">")
                    if left >= 0 and right > left:
                        next_url = item[left + 1 : right]
                        break
            return payload, next_url
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")[:1000]
        raise RuntimeError(f"GitHub advisory API HTTP {exc.code}: {body}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"GitHub advisory API unavailable: {exc}") from exc


def query(ecosystem: str, specs: list[str], advisory_type: str) -> list[dict]:
    params = {
        "ecosystem": ecosystem,
        "affects": ",".join(specs),
        "type": advisory_type,
        "is_withdrawn": "false",
        "per_page": "100",
        "sort": "updated",
        "direction": "desc",
    }
    url = API + "?" + urllib.parse.urlencode(params)
    findings: list[dict] = []
    while url:
        page, url = fetch_page(url)
        findings.extend(page)
    return findings


def chunks(values: list[tuple[str, str]], size: int):
    for start in range(0, len(values), size):
        yield values[start : start + size]


def packages_from_sbom() -> dict[str, list[tuple[str, str]]]:
    data = json.loads(SBOM.read_text(encoding="utf-8"))
    ecosystems: dict[str, set[tuple[str, str]]] = {"rust": set(), "npm": set()}
    for package in data.get("packages", []):
        spdx_id = package.get("SPDXID", "")
        name = package.get("name")
        version = package.get("versionInfo")
        if not name or not version:
            continue
        if spdx_id.startswith("SPDXRef-Cargo-"):
            ecosystems["rust"].add((str(name), str(version)))
        elif spdx_id.startswith("SPDXRef-Npm-"):
            ecosystems["npm"].add((str(name), str(version)))
    return {key: sorted(value) for key, value in ecosystems.items()}


def advisory_package_names(advisory: dict, ecosystem: str) -> set[str]:
    names: set[str] = set()
    for vulnerability in advisory.get("vulnerabilities", []):
        package = vulnerability.get("package", {})
        if str(package.get("ecosystem", "")).lower() == ecosystem:
            name = package.get("name")
            if name:
                names.add(str(name))
    return names


def precise_findings(
    ecosystem: str,
    package: str,
    version: str,
    advisory_type: str,
) -> list[dict]:
    return query(ecosystem, [f"{package}@{version}"], advisory_type)


def matching_vulnerability(advisory: dict, ecosystem: str, package: str) -> dict:
    for vulnerability in advisory.get("vulnerabilities", []):
        pkg = vulnerability.get("package", {})
        if (
            str(pkg.get("ecosystem", "")).lower() == ecosystem
            and pkg.get("name") == package
        ):
            return vulnerability
    return {}


def exception_key(item: dict) -> tuple[str, str, str, str]:
    return (
        str(item.get("ghsa_id", "")),
        str(item.get("ecosystem", "")),
        str(item.get("package", "")),
        str(item.get("version", "")),
    )


def parse_timestamp(value: str) -> datetime:
    if not value.endswith("Z"):
        raise ValueError("timestamp must end in Z")
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def main() -> None:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    queried_at = now_utc()
    subject = git("rev-parse", "HEAD")

    evidence = {
        "schema": "palaco.advisory-evaluation.v1",
        "gate": "GO-18",
        "subject_commit": subject,
        "queried_at": queried_at,
        "source": {
            "name": "GitHub Global Security Advisory Database",
            "endpoint": "https://api.github.com/advisories",
            "api_version": API_VERSION,
            "advisory_types": ["reviewed", "malware"],
            "withdrawn": False,
        },
        "scope": {
            "ecosystems": ["rust", "npm"],
            "container_images": "NOT_EVALUATED_BY_GO_18",
            "unreviewed_advisories": "NOT_BLOCKING_IN_GO_18",
        },
        "packages_evaluated": {},
        "findings": [],
        "exceptions": [],
        "result": "SOURCE_ERROR",
        "source_error": None,
    }

    try:
        packages = packages_from_sbom()
        evidence["packages_evaluated"] = {
            ecosystem: len(values) for ecosystem, values in packages.items()
        }
        evidence["packages_evaluated"]["total"] = sum(
            len(values) for values in packages.values()
        )

        candidate_queries: set[tuple[str, str, str, str]] = set()

        # Stage 1: broad batches identify package names that may have findings.
        for ecosystem, values in packages.items():
            for batch in chunks(values, BATCH_SIZE):
                specs = [f"{name}@{version}" for name, version in batch]
                names_to_versions: dict[str, list[str]] = {}
                for name, version in batch:
                    names_to_versions.setdefault(name, []).append(version)

                for advisory_type in ("reviewed", "malware"):
                    advisories = query(ecosystem, specs, advisory_type)
                    for advisory in advisories:
                        for package_name in advisory_package_names(advisory, ecosystem):
                            for version in names_to_versions.get(package_name, []):
                                candidate_queries.add(
                                    (ecosystem, package_name, version, advisory_type)
                                )

        # Stage 2: exact package@version queries establish precise matches.
        exact_results: list[tuple[str, str, str, str, list[dict]]] = []
        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
            futures = {
                pool.submit(
                    precise_findings, ecosystem, package, version, advisory_type
                ): (ecosystem, package, version, advisory_type)
                for ecosystem, package, version, advisory_type in sorted(candidate_queries)
            }
            for future in as_completed(futures):
                ecosystem, package, version, advisory_type = futures[future]
                exact_results.append(
                    (
                        ecosystem,
                        package,
                        version,
                        advisory_type,
                        future.result(),
                    )
                )

        unique: dict[tuple[str, str, str, str], dict] = {}
        for ecosystem, package, version, advisory_type, advisories in exact_results:
            for advisory in advisories:
                ghsa = advisory.get("ghsa_id")
                if not ghsa:
                    continue
                vulnerability = matching_vulnerability(advisory, ecosystem, package)
                key = (str(ghsa), ecosystem, package, version)
                first_patched = vulnerability.get("first_patched_version")
                if isinstance(first_patched, dict):
                    first_patched = first_patched.get("identifier")
                unique[key] = {
                    "ghsa_id": ghsa,
                    "cve_id": advisory.get("cve_id"),
                    "type": advisory.get("type", advisory_type),
                    "severity": advisory.get("severity", "unknown"),
                    "ecosystem": ecosystem,
                    "package": package,
                    "version": version,
                    "vulnerable_version_range": vulnerability.get(
                        "vulnerable_version_range"
                    ),
                    "first_patched_version": first_patched,
                    "summary": advisory.get("summary"),
                    "published_at": advisory.get("published_at"),
                    "updated_at": advisory.get("updated_at"),
                    "html_url": advisory.get("html_url"),
                }

        findings = sorted(
            unique.values(),
            key=lambda item: (
                item["ecosystem"],
                item["package"],
                item["version"],
                item["ghsa_id"],
            ),
        )

        exception_doc = json.loads(EXCEPTIONS.read_text(encoding="utf-8"))
        raw_exceptions = exception_doc.get("exceptions", [])
        if not isinstance(raw_exceptions, list):
            raise RuntimeError("GO-18 exception register must contain an exceptions list")

        exception_map = {exception_key(item): item for item in raw_exceptions}
        used: set[tuple[str, str, str, str]] = set()
        current = datetime.now(timezone.utc)

        blocking = 0
        for finding in findings:
            key = exception_key(finding)
            exception = exception_map.get(key)
            status = "BLOCK"
            if exception is not None:
                required = [
                    "ghsa_id",
                    "ecosystem",
                    "package",
                    "version",
                    "expires_at",
                    "rationale",
                    "approved_by",
                    "evidence",
                ]
                missing = [field for field in required if not exception.get(field)]
                if missing:
                    raise RuntimeError(
                        f"incomplete exception for {key}: missing {','.join(missing)}"
                    )
                expiry = parse_timestamp(str(exception["expires_at"]))
                if expiry > current:
                    status = "EXCEPTED_UNTIL_EXPIRY"
                    used.add(key)
                else:
                    status = "EXCEPTION_EXPIRED"

            finding["policy_status"] = status
            if status != "EXCEPTED_UNTIL_EXPIRY":
                blocking += 1

        unused = sorted(set(exception_map) - used)
        evidence["findings"] = findings
        evidence["exceptions"] = raw_exceptions
        evidence["exception_usage"] = {
            "used": [list(value) for value in sorted(used)],
            "unused_or_stale": [list(value) for value in unused],
        }
        evidence["blocking_findings"] = blocking
        evidence["result"] = "PASS" if blocking == 0 and not unused else "BLOCKED"

    except Exception as exc:  # evidence must survive source/policy failures
        evidence["result"] = "SOURCE_ERROR"
        evidence["source_error"] = str(exc)

    OUT.write_text(
        json.dumps(evidence, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )

    print("GO-18 ADVISORY EVALUATION: RECORDED")
    print(f"result={evidence['result']}")
    print(f"subject_commit={subject}")
    print(
        "packages_total="
        + str(evidence.get("packages_evaluated", {}).get("total", 0))
    )
    print(f"findings_total={len(evidence.get('findings', []))}")
    print(f"blocking_findings={evidence.get('blocking_findings', 0)}")
    if evidence.get("source_error"):
        print("source_error=" + str(evidence["source_error"]))


if __name__ == "__main__":
    main()
