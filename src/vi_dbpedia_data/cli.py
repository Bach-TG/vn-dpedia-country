"""Command-line orchestration for the Member-1-only country data pipeline."""

import argparse
import json
import logging
from pathlib import Path

from vi_dbpedia_data.collect import collect, collect_reference
from vi_dbpedia_data.discover import discover, pilot_candidates
from vi_dbpedia_data.extract import process
from vi_dbpedia_data.inspect_infobox import inspect
from vi_dbpedia_data.reports import (
    generate_candidate_audit,
    generate_reports,
    review_sample,
    review_summary,
)
from vi_dbpedia_data.scope import (
    generate_scope,
    generate_scope_from_saved,
    load_approved_candidates,
)
from vi_dbpedia_data.utils import ROOT, load_settings, read_json
from vi_dbpedia_data.validate import validate_dataset


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="vi-dbpedia-data", description=__doc__)
    parser.add_argument(
        "--root", type=Path, default=ROOT, help="Project root (for testing/relocation)"
    )
    commands = parser.add_subparsers(dest="command", required=True)
    reference = commands.add_parser("reference", help="Fetch exactly the five reference titles")
    reference.add_argument("--force", action="store_true")
    commands.add_parser("discover", help="Discover candidates via Wikidata")
    commands.add_parser("scope", help="Generate approved candidates from saved discovery (offline)")
    collection = commands.add_parser("collect", help="Collect approved country candidates")
    collection.add_argument("--limit", type=int)
    collection.add_argument("--force", action="store_true")
    inspection = commands.add_parser("inspect", help="Inspect selected raw pages")
    scope = inspection.add_mutually_exclusive_group()
    scope.add_argument("--reference-only", action="store_true")
    scope.add_argument("--all", action="store_true", help="All selected raw records (default)")
    for name in (
        "process",
        "validate",
        "report",
        "pilot",
        "full",
        "review-sample",
        "review-summary",
    ):
        commands.add_parser(name)
    return parser


def _print_counts(attempted: int, successful: int, location: str) -> None:
    print(
        f"attempted={attempted} successful={successful} "
        f"failed={attempted - successful} | {location}"
    )


def _collection_result(rows: list[dict], root: Path) -> None:
    success = sum(row["collection_status"] in {"collected", "skipped"} for row in rows)
    _print_counts(len(rows), success, str(root / "data/raw/collection_manifest.csv"))


def _finish(root: Path) -> None:
    inspection = inspect(load_settings(root), root)
    _print_counts(inspection["attempted"], inspection["selected"], str(root / "data/reports"))
    interim, records = process(load_settings(root), root)
    _print_counts(len(interim), len(records), str(root / "data/processed/countries.json"))
    results = validate_dataset(root)
    _print_counts(
        len(results),
        sum(row.status != "invalid" for row in results),
        str(root / "data/reports/validation.json"),
    )
    summary = generate_reports(root)
    print(f"report: {json.dumps(summary, ensure_ascii=False)} | {root / 'data/reports'}")


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    root = args.root
    settings = load_settings(root)
    if args.command == "reference":
        rows = collect_reference(settings, root, force=args.force)
        _collection_result(rows, root)
        print(f"reference index: {root / 'data/reference/pages.json'}")
    elif args.command == "discover":
        candidates = discover(settings, root)
        generate_candidate_audit(root)
        _print_counts(len(candidates), len(candidates), str(root / "data/candidates"))
    elif args.command == "scope":
        _, summary = generate_scope_from_saved(root)
        print(
            f"discovered={summary['discovered_count']} approved={summary['approved_count']} "
            f"excluded={summary['excluded_count']} review={summary['review_count']} | "
            f"{root / 'data/candidates/approved_countries.csv'}"
        )
        print(json.dumps(summary, ensure_ascii=False))
    elif args.command == "collect":
        if args.limit is not None and args.limit < 1:
            raise ValueError("--limit must be positive")
        generate_scope_from_saved(root)
        approved = load_approved_candidates(root)
        rows = collect(approved[: args.limit], settings, root, force=args.force)
        _collection_result(rows, root)
    elif args.command == "inspect":
        result = inspect(settings, root, reference_only=args.reference_only, all_available=args.all)
        _print_counts(result["attempted"], result["selected"], str(root / "data/reports"))
    elif args.command == "process":
        interim, records = process(settings, root)
        _print_counts(len(interim), len(records), str(root / "data/processed"))
    elif args.command == "validate":
        results = validate_dataset(root)
        _print_counts(
            len(results),
            sum(row.status != "invalid" for row in results),
            str(root / "data/reports/validation.json"),
        )
    elif args.command == "report":
        summary = generate_reports(root)
        _print_counts(
            summary["selected_count"], summary["processed_count"], str(root / "data/reports")
        )
        print(json.dumps(summary, ensure_ascii=False))
    elif args.command in {"pilot", "full"}:
        candidates = discover(settings, root)
        generate_candidate_audit(root)
        _, scope_summary = generate_scope(candidates, root)
        approved = load_approved_candidates(root)
        print(
            f"scope: {scope_summary['approved_count']} / {scope_summary['discovered_count']} "
            f"approved | {root / 'data/candidates/approved_countries.csv'}"
        )
        if args.command == "pilot":
            references = collect_reference(settings, root)
            _collection_result(references, root)
            reference_qids = {
                row["requested_title"]: qid
                for row in references
                if row["raw_file_path"]
                if (qid := read_json(root / row["raw_file_path"]).get("pageprops_wikidata_id"))
            }
            approved_qids = {item.wikidata_id for item in approved}
            missing_refs = sorted(set(reference_qids.values()) - approved_qids)
            if missing_refs:
                raise ValueError(f"Reference QIDs not approved for pilot: {missing_refs}")
            selected = pilot_candidates(approved, settings, reference_qids)
        else:
            selected = approved
        rows = collect(selected, settings, root)
        _collection_result(rows, root)
        _finish(root)
    elif args.command == "review-sample":
        rows = review_sample(root, seed=settings.pilot_seed, size=settings.pilot_size)
        _print_counts(len(rows), len(rows), str(root / "data/reports/manual_link_review.csv"))
    elif args.command == "review-summary":
        summary = review_summary(root)
        _print_counts(
            summary["reviewed_count"] + summary["unreviewed_count"],
            summary["reviewed_count"],
            str(root / "data/reports/manual_link_review.csv"),
        )
        print(json.dumps(summary, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
