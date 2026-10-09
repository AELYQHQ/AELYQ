"""Conservative Adyen Settlement details CSV -> ReconForge normalized PSP adapter.

Intentionally limited to one EUR merchant/batch and a documented journal subset.
Unknown financial semantics cause rejection, not silent exclusion.
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import os
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from pathlib import Path
from typing import Mapping


MAX_REPORT_BYTES = 1_048_576
MAX_REPORT_ROWS = 1_000
MAX_OUTPUT_ROWS = 1_000

NORMALIZED_FIELDS = (
    "tenant_id", "merchant_id", "batch_id", "event_id", "event_type",
    "amount_eur", "currency", "effective_at", "description",
)

REQUIRED_FIELDS = frozenset((
    "Merchant Account", "Psp Reference", "Creation Date", "TimeZone",
    "Type", "Gross Currency", "Gross Debit (GC)", "Gross Credit (GC)",
    "Net Currency", "Net Debit (NC)", "Net Credit (NC)", "Batch Number",
))

SUPPORTED_FINANCIAL_TYPES = frozenset((
    "Settled", "Refunded", "Fee", "InvoiceDeduction", "ReserveAdjustment",
))

_AMOUNT_PATTERN = re.compile(r"(?:0|[1-9][0-9]{0,11})(?:\.[0-9]{1,2})?\Z")
_BATCH_PATTERN = re.compile(r"[1-9][0-9]{0,11}\Z")
_SCOPE_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,79}\Z")
_OFFSET_PATTERN = re.compile(r"([+-])(0[0-9]|1[0-3]):([0-5][0-9])\Z")


class AdyenAdapterError(ValueError):
    """An export cannot be converted conservatively without losing semantics."""


@dataclass(frozen=True)
class AdyenConversion:
    source_sha256: str
    normalized_sha256: str
    source_record_count: int
    normalized_record_count: int
    payout_control_row: int
    payout_control_minor: int
    psp_total_minor: int
    normalized_psp: bytes
    provenance: tuple[dict, ...]

    def manifest(self) -> dict:
        return {
            "schema_version": "0.1.0",
            "adapter": "adyen_settlement_details_eur_v1_subset",
            "source_sha256": self.source_sha256,
            "normalized_psp_sha256": self.normalized_sha256,
            "source_record_count": self.source_record_count,
            "normalized_record_count": self.normalized_record_count,
            "payout_control": {
                "source_record_number": self.payout_control_row,
                "amount_minor": self.payout_control_minor,
                "matched_supported_net_total": True,
            },
            "mapping": list(self.provenance),
            "limitations": [
                "single merchant, single batch, EUR-only",
                "unsupported journal types are rejected, not skipped",
                "MerchantPayout is a control, not bank evidence",
                "generated event IDs are source-row-based, not ledger-matched",
                "input completeness is not externally verified",
            ],
        }


def _amount(value: str, record: int, column: str) -> int | None:
    if not value:
        return None
    if not _AMOUNT_PATTERN.fullmatch(value):
        raise AdyenAdapterError(
            f"Adyen record {record}: invalid nonnegative EUR amount in {column}."
        )
    integer, dot, fraction = value.partition(".")
    return int(integer) * 100 + int(fraction.ljust(2, "0")) if dot else int(integer) * 100


def _get_side(row: dict[str, str], record: int, debit_column: str, credit_column: str) -> int:
    debit = _amount(row[debit_column], record, debit_column)
    credit = _amount(row[credit_column], record, credit_column)
    if (debit is None) == (credit is None):
        raise AdyenAdapterError(
            f"Adyen record {record}: expected exactly one of {debit_column}/{credit_column}."
        )
    value = credit if credit is not None else -debit
    if value == 0:
        raise AdyenAdapterError(f"Adyen record {record}: zero financial movement rejected.")
    return value


def _time(value: str, zone: str, record: int) -> str:
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}", value):
        raise AdyenAdapterError(f"Adyen record {record}: unexpected Creation Date format.")
    try:
        naive = datetime.strptime(value, "%Y-%m-%d %H:%M:%S")
    except ValueError as exc:
        raise AdyenAdapterError(f"Adyen record {record}: invalid Creation Date.") from exc

    zone = zone.strip()
    offset = {"UTC": 0, "GMT": 0, "CET": 60, "CEST": 120}.get(zone)
    if offset is None:
        match = _OFFSET_PATTERN.fullmatch(zone)
        if match:
            minutes = int(match.group(2)) * 60 + int(match.group(3))
            offset = minutes if match.group(1) == "+" else -minutes
    if offset is None:
        raise AdyenAdapterError(
            f"Adyen record {record}: unsupported timezone; use UTC, GMT, CET, CEST or +/-HH:MM."
        )
    return naive.replace(tzinfo=timezone(timedelta(minutes=offset))).astimezone(timezone.utc).isoformat()


def convert_adyen_settlement(
    content: bytes, *, tenant_id: str, merchant_id: str, batch_id: str,
    batch_number: str,
) -> AdyenConversion:
    """Convert validated raw bytes, retaining a source-row link for every output event.

    No I/O and no external provider requests. Gross-to-net deltas are represented
    as explicit Fee entries only when they are nonnegative and unambiguous.
    """
    for name, value in (("tenant_id", tenant_id), ("merchant_id", merchant_id), ("batch_id", batch_id)):
        if not _SCOPE_PATTERN.fullmatch(value):
            raise AdyenAdapterError(f"Invalid normalized {name} identifier.")
    if not _BATCH_PATTERN.fullmatch(batch_number):
        raise AdyenAdapterError("batch_number must be a positive numeric Adyen batch number.")
    if not isinstance(content, bytes) or not content or len(content) > MAX_REPORT_BYTES:
        raise AdyenAdapterError("Adyen report must be nonempty bytes of at most 1 MiB.")
    try:
        text = content.decode("utf-8-sig")
    except UnicodeError as exc:
        raise AdyenAdapterError("Adyen report must use valid UTF-8.") from exc

    try:
        reader = csv.DictReader(io.StringIO(text, newline=""), strict=True)
        headers = reader.fieldnames or []
        if len(headers) != len(set(headers)) or any(not h for h in headers):
            raise AdyenAdapterError("Adyen report contains empty or duplicate headers.")
        missing = sorted(REQUIRED_FIELDS - set(headers))
        if missing:
            raise AdyenAdapterError("Missing required Adyen columns: " + ", ".join(missing))

        output_rows: list[dict[str, str]] = []
        mapping: list[dict] = []
        controls: list[tuple[int, int]] = []
        net_total_minor = 0
        count = 0

        for record, row in enumerate(reader, 1):
            count = record
            if record > MAX_REPORT_ROWS:
                raise AdyenAdapterError("Adyen report exceeds 1000 records.")
            if None in row or any(value is None for value in row.values()):
                raise AdyenAdapterError(f"Adyen record {record}: malformed field count.")
            if row["Merchant Account"] != merchant_id:
                raise AdyenAdapterError(f"Adyen record {record}: merchant account mismatch.")
            if row["Batch Number"] != batch_number:
                raise AdyenAdapterError(f"Adyen record {record}: batch number mismatch.")
            if row["Net Currency"] != "EUR":
                raise AdyenAdapterError(f"Adyen record {record}: only EUR net currency supported.")
            if row["Gross Currency"] not in ("", "EUR"):
                raise AdyenAdapterError(f"Adyen record {record}: unsupported gross currency/FX.")
            journal = row["Type"]
            if journal not in SUPPORTED_FINANCIAL_TYPES | {"MerchantPayout"}:
                raise AdyenAdapterError(
                    f"Adyen record {record}: journal type {journal!r} is not supported; entire import rejected."
                )
            instant = _time(row["Creation Date"], row["TimeZone"], record)
            net = _get_side(row, record, "Net Debit (NC)", "Net Credit (NC)")
            gross_debit = _amount(row["Gross Debit (GC)"], record, "Gross Debit (GC)")
            gross_credit = _amount(row["Gross Credit (GC)"], record, "Gross Credit (GC)")

            if journal == "MerchantPayout":
                if net >= 0 or gross_debit is not None or gross_credit is not None:
                    raise AdyenAdapterError(f"Adyen record {record}: invalid MerchantPayout control.")
                controls.append((record, -net))
                continue

            net_total_minor += net
            components: list[tuple[str, int, str]] = []
            if journal in ("Settled", "Refunded"):
                if row["Gross Currency"] != "EUR":
                    raise AdyenAdapterError(f"Adyen record {record}: gross EUR currency required for transactions.")
                if not row["Psp Reference"]:
                    raise AdyenAdapterError(f"Adyen record {record}: missing Psp Reference.")
                if journal == "Settled":
                    if net <= 0 or gross_debit is not None or not gross_credit:
                        raise AdyenAdapterError(f"Adyen record {record}: invalid Settled credit.")
                    fee = gross_credit - net
                    if fee < 0:
                        raise AdyenAdapterError(f"Adyen record {record}: net credit exceeds gross; unsupported adjustment.")
                    components.append(("Capture", gross_credit, "capture"))
                else:
                    if net >= 0 or gross_credit is not None or not gross_debit:
                        raise AdyenAdapterError(f"Adyen record {record}: invalid Refunded debit.")
                    fee = -net - gross_debit
                    if fee < 0:
                        raise AdyenAdapterError(f"Adyen record {record}: refund net debit below gross; unsupported adjustment.")
                    components.append(("Refund", -gross_debit, "refund"))
                if fee:
                    components.append(("Fee", -fee, "embedded_fee"))
            else:
                if gross_debit is not None or gross_credit is not None:
                    raise AdyenAdapterError(f"Adyen record {record}: unsupported gross value for {journal}.")
                if journal in ("Fee", "InvoiceDeduction") and net >= 0:
                    raise AdyenAdapterError(f"Adyen record {record}: positive {journal} not supported.")
                components.append((journal, net, journal.lower()))

            if sum(amount for _, amount, _ in components) != net:
                raise AdyenAdapterError(f"Adyen record {record}: loss of net movement in mapping.")

            for event_type, amount_minor, label in components:
                if len(output_rows) >= MAX_OUTPUT_ROWS:
                    raise AdyenAdapterError("Normalized PSP output exceeds 1000 records.")
                event_id = f"adyen_r{record:06d}_{label}"
                output_rows.append({
                    "tenant_id": tenant_id,
                    "merchant_id": merchant_id,
                    "batch_id": batch_id,
                    "event_id": event_id,
                    "event_type": event_type,
                    "amount_eur": f"{'-' if amount_minor < 0 else ''}{abs(amount_minor) // 100}.{abs(amount_minor) % 100:02d}",
                    "currency": "EUR",
                    "effective_at": instant,
                    "description": f"Adyen {journal} {label}; source record {record}",
                })
                mapping.append({
                    "source_record_number": record,
                    "source_journal_type": journal,
                    "normalized_record_number": len(output_rows),
                    "normalized_event_id": event_id,
                    "normalized_event_type": event_type,
                })
    except csv.Error as exc:
        raise AdyenAdapterError("Malformed Adyen CSV file.") from exc

    if not count:
        raise AdyenAdapterError("Adyen CSV has no financial records.")
    if len(controls) != 1:
        raise AdyenAdapterError("Exactly one MerchantPayout control is required for this batch.")
    control_record, control_minor = controls[0]
    if net_total_minor != control_minor:
        raise AdyenAdapterError(
            f"Adyen payout control mismatch: supported net total {net_total_minor} minor units "
            f"vs MerchantPayout {control_minor} minor units."
        )
    if not output_rows:
        raise AdyenAdapterError("Adyen report has no supported financial movement rows.")

    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=NORMALIZED_FIELDS, lineterminator="\n")
    writer.writeheader()
    writer.writerows(output_rows)
    normalized_bytes = stream.getvalue().encode("utf-8")
    if len(normalized_bytes) > MAX_REPORT_BYTES:
        raise AdyenAdapterError("Normalized PSP CSV exceeds 1 MiB.")
    return AdyenConversion(
        source_sha256=sha256(content).hexdigest(),
        normalized_sha256=sha256(normalized_bytes).hexdigest(),
        source_record_count=count,
        normalized_record_count=len(output_rows),
        payout_control_row=control_record,
        payout_control_minor=control_minor,
        psp_total_minor=net_total_minor,
        normalized_psp=normalized_bytes,
        provenance=tuple(mapping),
    )


def prepare_adyen_batch(
    *, report: bytes, ledger: bytes, bank: bytes, tenant_id: str,
    merchant_id: str, batch_id: str, batch_number: str,
) -> tuple[AdyenConversion, dict, Mapping[str, bytes]]:
    """Bridge exact raw snapshots into the existing deterministic comparison."""
    from .reconciliation import reconcile_snapshots

    conversion = convert_adyen_settlement(
        report, tenant_id=tenant_id, merchant_id=merchant_id,
        batch_id=batch_id, batch_number=batch_number,
    )
    snapshots = {
        "ledger_events.csv": ledger,
        "psp_events.csv": conversion.normalized_psp,
        "bank_entries.csv": bank,
    }
    facts = reconcile_snapshots(snapshots)
    return conversion, facts, snapshots


def _write_new_file(path: Path, raw: bytes) -> None:
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags, 0o600)
    with os.fdopen(descriptor, "wb") as stream:
        stream.write(raw)


def main() -> None:
    from .ingestion import _read_regular_file

    parser = argparse.ArgumentParser(description="Conservative Adyen EUR settlement-details batch conversion.")
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--ledger", type=Path, required=True)
    parser.add_argument("--bank", type=Path, required=True)
    parser.add_argument("--tenant-id", required=True)
    parser.add_argument("--merchant-id", required=True)
    parser.add_argument("--batch-id", required=True)
    parser.add_argument("--batch-number", required=True)
    parser.add_argument("--output-dir", type=Path, required=True,
                        help="A new, nonexistent directory. Contains sensitive captured source bytes.")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    try:
        report = _read_regular_file(args.report, "adyen_settlement_details.csv")
        ledger = _read_regular_file(args.ledger, "ledger_events.csv")
        bank = _read_regular_file(args.bank, "bank_entries.csv")
        conversion, facts, snapshots = prepare_adyen_batch(
            report=report, ledger=ledger, bank=bank,
            tenant_id=args.tenant_id, merchant_id=args.merchant_id,
            batch_id=args.batch_id, batch_number=args.batch_number,
        )
        output = args.output_dir
        if output.exists() or output.is_symlink():
            raise AdyenAdapterError("Output directory must not already exist.")
        if not output.parent.is_dir() or output.parent.is_symlink():
            raise AdyenAdapterError("Output parent must be a regular existing directory.")
        output.mkdir(mode=0o700)
        # No source reads after capture: files match the validated snapshots.
        for name, raw in snapshots.items():
            _write_new_file(output / name, raw)
        _write_new_file(output / "adyen_settlement_details.csv", report)
        manifest = conversion.manifest()
        manifest.update({
            "raw_source_filename": "adyen_settlement_details.csv",
            "ledger_sha256": sha256(ledger).hexdigest(),
            "bank_sha256": sha256(bank).hexdigest(),
            "tenant_id": args.tenant_id,
            "merchant_id": args.merchant_id,
            "batch_id": args.batch_id,
            "batch_number": args.batch_number,
        })
        _write_new_file(
            output / "adyen_provenance.json",
            (json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode("utf-8"),
        )
    except (AdyenAdapterError, OSError, ValueError) as exc:
        parser.exit(2, f"Adyen batch rejected: {exc}\n")

    summary = {
        "output_directory": str(output),
        "manifest": manifest,
        "reconciliation": facts,
    }
    if args.json:
        print(json.dumps(summary, indent=2))
    else:
        print(f"Adyen settlement adapter accepted {conversion.source_record_count} source records.")
        print(f"Generated {conversion.normalized_record_count} normalized PSP events.")
        print(f"Payout control equals supported net total: EUR {conversion.psp_total_minor / 100:.2f}")
        print(f"Read-only reconciliation preview; review_required={facts['review_required']}.")
        print(f"Private source/output snapshots stored in: {output}")
        print("Not an external completeness proof. No funds were posted.")


if __name__ == "__main__":
    main()
