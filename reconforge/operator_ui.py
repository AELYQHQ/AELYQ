"""Minimal read-only HTML operator views for synthetic AELYQ cases."""

from html import escape

from .cases import CaseList, EvidenceRecord, ReconciliationCase
from .investigation import InvestigationRun
from .money import format_eur
from .reports import VerifiedReport


def _text(value: object) -> str:
    return escape(str(value), quote=True)


def _page(title: str, body: str) -> str:
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{_text(title)} · AELYQ</title>
  <style>
    :root {{ color-scheme: dark; font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; }}
    * {{ box-sizing: border-box; }}
    body {{ margin: 0; background: #0b0d10; color: #f4f5f7; }}
    a {{ color: #b8cdfd; text-decoration: none; }}
    a:hover {{ text-decoration: underline; }}
    .shell {{ width: min(1120px, calc(100% - 32px)); margin: 0 auto; padding: 44px 0 72px; }}
    .brand {{ font-size: 13px; letter-spacing: .22em; font-weight: 800; color: #d9e2ff; }}
    .eyebrow {{ color: #9299a6; font-size: 13px; margin-top: 8px; }}
    h1 {{ font-size: clamp(30px, 5vw, 50px); letter-spacing: -.035em; margin: 18px 0 8px; }}
    h2 {{ font-size: 20px; margin: 0 0 18px; }}
    .subtle {{ color: #9ba3af; }}
    .status {{ display: inline-block; border: 1px solid #3a414b; border-radius: 999px; padding: 6px 10px; font-size: 12px; }}
    .status.review {{ border-color: #7b6335; color: #f4d488; }}
    .status.ok {{ border-color: #315d49; color: #9fe0bd; }}
    .grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 12px; margin: 26px 0; }}
    .card, section {{ border: 1px solid #252a31; background: #11151a; border-radius: 14px; }}
    .card {{ padding: 16px; }}
    .card .label {{ color: #8f98a5; font-size: 12px; margin-bottom: 8px; }}
    .card .value {{ font-size: 21px; font-weight: 700; }}
    section {{ padding: 22px; margin-top: 16px; }}
    ul {{ padding-left: 20px; margin: 0; }}
    li + li {{ margin-top: 10px; }}
    code {{ font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: .9em; color: #d7dded; }}
    table {{ width: 100%; border-collapse: collapse; font-size: 14px; }}
    th, td {{ text-align: left; padding: 11px 8px; border-bottom: 1px solid #252a31; vertical-align: top; }}
    th {{ color: #8f98a5; font-weight: 600; }}
    .table-wrap {{ overflow-x: auto; }}
    .meta {{ display: flex; flex-wrap: wrap; gap: 12px 20px; color: #9ba3af; font-size: 13px; margin-top: 8px; }}
    .notice {{ border-left: 3px solid #667eea; padding: 10px 14px; background: #111722; color: #c8d1df; margin: 22px 0; }}
    .actions {{ display: flex; flex-wrap: wrap; align-items: center; gap: 12px; margin: 24px 0; }}
    .action-button {{ border: 1px solid #46505d; border-radius: 10px; padding: 10px 14px; background: #161b22; color: #f4f5f7; font: inherit; font-weight: 700; cursor: pointer; }}
    .action-button:hover {{ border-color: #7d8da8; background: #1b222c; }}
    .case-link {{ display: block; padding: 16px; border: 1px solid #252a31; border-radius: 12px; margin-top: 10px; background: #11151a; }}
    .case-link:hover {{ border-color: #46505d; text-decoration: none; }}
    .case-row {{ display: flex; justify-content: space-between; gap: 16px; align-items: center; }}
    .case-id {{ font-weight: 700; color: #f4f5f7; }}
    .tiny {{ font-size: 12px; color: #7f8895; }}
  </style>
</head>
<body>
  <main class="shell">
    <div class="brand">AELYQ</div>
    <div class="eyebrow">Synthetic read-only operator view</div>
    {body}
  </main>
</body>
</html>"""


def render_operator_index(case_list: CaseList) -> str:
    rows = []
    for case in case_list.cases:
        status_class = "review" if case.review_required else "ok"
        status_text = "Review required" if case.review_required else "Balanced"
        rows.append(
            f"""<a class="case-link" href="/operator/cases/{_text(case.case_id)}">
  <div class="case-row">
    <div>
      <div class="case-id">{_text(case.case_id)}</div>
      <div class="tiny">Ledger → provider: {_text(format_eur(case.ledger_to_provider_residual_minor))} · Provider → bank: {_text(format_eur(case.provider_to_bank_residual_minor))}</div>
    </div>
    <span class="status {status_class}">{status_text}</span>
  </div>
</a>"""
        )

    body = f"""
<h1>Investigation cases</h1>
<p class="subtle">A deterministic view of the captured synthetic reconciliation cases.</p>
<div class="notice">Financial facts are calculated by code. This interface is read-only and does not authorize financial actions.</div>
{''.join(rows)}
"""
    return _page("Cases", body)


def render_operator_case(
    case: ReconciliationCase,
    verified: VerifiedReport,
    evidence: tuple[EvidenceRecord, ...],
) -> str:
    report = verified.report
    if report.case_id != case.case_id or report.case_version != case.case_version:
        raise ValueError("Report context does not match the selected case.")

    status_class = "review" if report.review_required else "ok"
    status_text = "Review required" if report.review_required else "Balanced"

    findings = "".join(
        f"<li><strong>{_text(item.kind)}</strong> — {_text(item.statement)}</li>"
        for item in report.findings
    )
    hypotheses = "".join(
        f"<li><code>{_text(item.code)}</code> — {_text(item.statement)} <span class=\"tiny\">({_text(item.status)})</span></li>"
        for item in report.hypotheses
    ) or "<li>No hypotheses are required by the current deterministic report.</li>"
    questions = "".join(
        f"<li><code>{_text(item.code)}</code> — {_text(item.question)}</li>"
        for item in report.unresolved_questions
    )
    steps = "".join(
        f"<li><code>{_text(item.code)}</code> — {_text(item.instruction)}</li>"
        for item in report.next_steps
    )

    evidence_rows = "".join(
        f"""<tr>
  <td>{_text(item.reference.file)}</td>
  <td>{item.reference.record_number}</td>
  <td><code>{_text(item.row.event_id)}</code></td>
  <td>{_text(item.row.event_type)}</td>
  <td>{_text(item.row.amount_eur)} {_text(item.row.currency)}</td>
  <td>{_text(item.row.effective_at)}</td>
</tr>"""
        for item in evidence
    )

    facts = case.facts
    body = f"""
<p><a href="/operator">← All cases</a></p>
<h1>{_text(case.case_id)}</h1>
<span class="status {status_class}">{status_text}</span>
<div class="meta">
  <span>Merchant: <code>{_text(facts.scope.merchant_id)}</code></span>
  <span>Batch: <code>{_text(facts.scope.batch_id)}</code></span>
  <span>Currency: {_text(facts.scope.currency)}</span>
</div>

<div class="actions">
  <form method="post" action="/operator/cases/{_text(case.case_id)}/investigate">
    <button class="action-button" type="submit">Run bounded investigation</button>
  </form>
  <span class="tiny">Provider-free scripted run · read-only · no financial actions</span>
</div>

<div class="grid">
  <div class="card"><div class="label">Ledger total</div><div class="value">{_text(format_eur(facts.totals_minor.ledger))}</div></div>
  <div class="card"><div class="label">Provider total</div><div class="value">{_text(format_eur(facts.totals_minor.provider))}</div></div>
  <div class="card"><div class="label">Bank total</div><div class="value">{_text(format_eur(facts.totals_minor.bank))}</div></div>
  <div class="card"><div class="label">Ledger → provider</div><div class="value">{_text(format_eur(facts.comparisons.ledger_to_provider.residual_minor))}</div></div>
  <div class="card"><div class="label">Provider → bank</div><div class="value">{_text(format_eur(facts.comparisons.provider_to_bank.residual_minor))}</div></div>
</div>

<div class="notice">Verified report: passed against captured rows and fixed report rules. Hypotheses below remain unverified. No financial actions are allowed.</div>

<section>
  <h2>Verified findings</h2>
  <ul>{findings}</ul>
</section>

<section>
  <h2>Unverified hypotheses</h2>
  <ul>{hypotheses}</ul>
</section>

<section>
  <h2>Open questions</h2>
  <ul>{questions}</ul>
</section>

<section>
  <h2>Next checks</h2>
  <ul>{steps}</ul>
</section>

<section>
  <h2>Captured evidence</h2>
  <div class="table-wrap">
    <table>
      <thead><tr><th>Source</th><th>Row</th><th>Event</th><th>Type</th><th>Amount</th><th>Effective at</th></tr></thead>
      <tbody>{evidence_rows}</tbody>
    </table>
  </div>
</section>

<p class="tiny">Case version: <code>{_text(case.case_version)}</code><br>Report ID: <code>{_text(verified.report_id)}</code></p>
"""
    return _page(case.case_id, body)

def render_operator_investigation(run: InvestigationRun) -> str:
    report = run.report.report
    proposal = run.proposal

    findings = "".join(
        f"<li><code>{_text(item.finding_id)}</code> — {_text(item.statement)}</li>"
        for item in report.findings
    )

    hypotheses_by_code = {item.code: item for item in report.hypotheses}
    hypotheses = "".join(
        f"<li><strong>{_text(hypotheses_by_code[code].code)}</strong> — "
        f"{_text(hypotheses_by_code[code].statement)}</li>"
        for code in proposal.hypothesis_order
    ) or "<li>None for the supplied records.</li>"

    questions_by_code = {
        item.code: item for item in report.unresolved_questions
    }
    questions = "".join(
        f"<li><strong>{_text(questions_by_code[code].code)}</strong> — "
        f"{_text(questions_by_code[code].question)}</li>"
        for code in proposal.question_order
    ) or "<li>None for the supplied records.</li>"

    steps_by_code = {item.code: item for item in report.next_steps}
    steps = "".join(
        f"<li><strong>{_text(steps_by_code[code].code)}</strong> — "
        f"{_text(steps_by_code[code].instruction)}</li>"
        for code in proposal.next_step_order
    ) or "<li>None for the supplied records.</li>"

    evidence_ids = tuple(
        dict.fromkeys(
            step.evidence_id
            for step in run.trace
            if step.tool == "get_evidence" and step.evidence_id is not None
        )
    )
    evidence = "".join(
        f"<li><code>{_text(evidence_id)}</code></li>"
        for evidence_id in evidence_ids
    ) or "<li>No evidence rows were inspected.</li>"

    trace = "".join(
        f"<li>Turn {step.turn}: <code>{_text(step.tool)}</code>"
        + (
            f" — <code>{_text(step.evidence_id)}</code>"
            if step.evidence_id
            else ""
        )
        + "</li>"
        for step in run.trace
    ) or "<li>No execution steps recorded.</li>"

    returned_models = ", ".join(
        _text(model) for model in run.returned_models
    ) or "None"

    body = f"""
<p><a href="/operator/cases/{_text(proposal.case_id)}">← Back to case</a></p>

<h1>Bounded investigation</h1>

<div class="meta">
  <span>Case: <code>{_text(proposal.case_id)}</code></span>
  <span>Mode: <code>{_text(run.mode)}</code></span>
  <span>Contract: <strong>{_text(run.contract_status)}</strong></span>
</div>

<div class="notice">
  Contract checks passed. Financial facts remain deterministic.
  This investigation is read-only and does not authorize financial actions.
</div>

<div class="grid">
  <div class="card">
    <div class="label">Model turns</div>
    <div class="value">{run.model_turns}</div>
  </div>
  <div class="card">
    <div class="label">Provider requests</div>
    <div class="value">{run.provider_requests}</div>
  </div>
  <div class="card">
    <div class="label">Evidence reads</div>
    <div class="value">{len(evidence_ids)}</div>
  </div>
  <div class="card">
    <div class="label">Priority quality</div>
    <div class="value">{_text(run.priority_quality)}</div>
  </div>
</div>

<section>
  <h2>Verified financial findings</h2>
  <ul>{findings}</ul>
</section>

<section>
  <h2>Proposed investigation order</h2>

  <h3>Possible explanations — unverified</h3>
  <ul>{hypotheses}</ul>

  <h3>Open questions</h3>
  <ul>{questions}</ul>

  <h3>Human next steps</h3>
  <ul>{steps}</ul>
</section>

<section>
  <h2>Evidence inspected</h2>
  <ul>{evidence}</ul>
</section>

<section>
  <h2>Execution trace</h2>
  <ul>{trace}</ul>
</section>

<section>
  <h2>Run metadata</h2>
  <div class="meta">
    <span>Requested model: <code>{_text(run.requested_model or "None")}</code></span>
    <span>Returned models: <code>{returned_models}</code></span>
    <span>Conclusion: <code>{_text(proposal.conclusion)}</code></span>
  </div>
</section>

<div class="notice">
  External completeness remains unverified.
  No financial action is authorized.
</div>

<p class="tiny">
  Case version: <code>{_text(proposal.case_version)}</code><br>
  Report ID: <code>{_text(proposal.report_id)}</code>
</p>
"""

    return _page(f"{proposal.case_id} · Investigation", body)


def render_operator_error(
    case: ReconciliationCase,
    message: str,
) -> str:
    body = f"""
<p><a href="/operator/cases/{_text(case.case_id)}">← Back to case</a></p>

<h1>Investigation stopped</h1>

<div class="notice">
  The bounded investigation did not produce an accepted run.
</div>

<section>
  <h2>Reason</h2>
  <p>{_text(message)}</p>
</section>

<p class="tiny">
  Case: <code>{_text(case.case_id)}</code><br>
  Case version: <code>{_text(case.case_version)}</code>
</p>
"""

    return _page(f"{case.case_id} · Investigation stopped", body)