"""Deep-RCA local demo UI (Gradio).

Pick an incident and watch an autonomous investigation unfold live — hypotheses,
tool calls + findings, the blind Evaluator's verdicts, the final proposal — then the
offline plane reveals ground truth + the scorecard + the isolation check.

Run locally:
  set -a; source infra/runtime.env; set +a         # or set the DEEPRCA_* env vars
  PYTHONPATH="src;." python app/ui.py               # opens http://localhost:7860
"""
from __future__ import annotations

import asyncio
import html
import json
import os

import gradio as gr
from azure.identity import DefaultAzureCredential

from deeprca.agents import EvaluatorAgent, InvestigatorAgent
from deeprca.config import RuntimeConfig
from deeprca.evidence import EvidenceLake, load_incident
from deeprca.projection import build_projection
from deeprca.state import BlobLedgerStore
from deeprca.workflow import run_investigation

CFG = RuntimeConfig.from_env()
CRED = DefaultAzureCredential()


def _cases() -> list[str]:
    try:
        return EvidenceLake(CFG.evidence_account, CRED, CFG.evidence_filesystem).list_cases()
    except Exception:
        return [c for c in [os.environ.get("DEEPRCA_CASE")] if c]


def esc(x) -> str:
    return html.escape(str(x))


def _card(border: str, title: str, body: str, tag: str = "") -> str:
    tag_html = f"<span style='float:right;opacity:.6;font-size:.8em'>{esc(tag)}</span>" if tag else ""
    return (f"<div style='border-left:4px solid {border};padding:8px 14px;margin:8px 0;"
            f"background:rgba(127,127,127,.06);border-radius:4px'>{tag_html}"
            f"<div style='font-weight:600'>{title}</div>"
            f"<div style='opacity:.85;margin-top:3px'>{body}</div></div>")


def _event_html(kind: str, d: dict) -> str:
    step = d.get("step", "")
    if kind == "hypothesis":
        return _card("#8b5cf6", f"🔬 Hypothesis",
                     f"{esc(d['statement'])}<br><span style='opacity:.7'>suspect: "
                     f"<b>{esc(d['suspected_service'])}</b> / {esc(d['suspected_fault_type'])} · "
                     f"falsify: {esc(d['falsification_test'])}</span>", f"step {step}")
    if kind == "evidence":
        args = f" {esc(d['args'])}" if d.get("args") else ""
        return _card("#06b6d4", f"🛠️ Tool · {esc(d['tool'])}{args}",
                     f"→ {esc(d['observation'])[:400]}", f"step {step}")
    if kind == "tool_error":
        return _card("#ef4444", f"⚠️ Tool error · {esc(d['tool'])}", esc(d["error"]), f"step {step}")
    if kind == "link":
        return _card("#64748b", "🔗 Link evidence",
                     f"hyp {esc(d['hypothesis_id'])} · support={esc(d['supporting'])} "
                     f"contra={esc(d['contradicting'])} · status=<b>{esc(d['new_status'])}</b>", f"step {step}")
    if kind == "propose":
        edges = " , ".join(f"{esc(a)}→{esc(b)}" for a, b in d["path_edges"])
        return _card("#f59e0b", "🎯 Proposed root cause",
                     f"services=<b>{esc(d['root_services'])}</b> · fault=<b>{esc(d['fault_type'])}</b> · "
                     f"conf={esc(d['confidence'])}<br><span style='opacity:.7'>causal path: {edges}</span>"
                     f"<br><span style='opacity:.6'>{esc(d['rationale'])[:300]}</span>", f"step {step}")
    if kind == "evaluation":
        color = {"CONCLUDE": "#22c55e", "ESCALATE": "#ef4444", "CONTINUE": "#eab308"}.get(d["decision"], "#64748b")
        return _card(color, f"⚖️ Evaluator (blind): {esc(d['decision'])}",
                     f"{esc(d['rationale'])[:260]} <span style='opacity:.6'>({d['n_critiques']} critiques)</span>",
                     f"step {step}")
    return ""


def _header_html(inc) -> str:
    return _card("#3b82f6", f"🚀 Investigating incident · {esc(inc.case_name)}",
                 f"system <b>{esc(inc.system)}</b> · namespace {esc(inc.namespace)} · abnormal window "
                 f"{esc(inc.abnormal_window.start)} → {esc(inc.abnormal_window.end)}"
                 f"<br><span style='opacity:.6'>Ground truth is hidden from the Investigator and the Evaluator.</span>")


def _final_html(inc, inv, store) -> str:
    from eval.gt_store import read_ground_truth
    from eval.scorer import isolation_scan, score

    reloaded = store.load(inv.id)
    persisted_ok = reloaded.model_dump_json() == inv.model_dump_json()

    gt = read_ground_truth(os.environ["DEEPRCA_GT_ACCOUNT"], inc.case_name, CRED)
    card = score(inv, gt)
    leaks = isolation_scan([json.dumps(build_projection(inc, inv)), inv.model_dump_json()],
                           gt, os.environ["DEEPRCA_GT_ACCOUNT"])
    m = card["metrics"]
    prc = inv.proposed_root_cause
    hit = ("<span style='color:#22c55e;font-weight:700'>HIT</span>" if m["localization_hit"]
           else "<span style='color:#ef4444;font-weight:700'>MISS</span>")

    ledger_rows = "".join(
        f"<tr><td style='padding:2px 10px'>{esc(h.suspected_service or '—')}</td>"
        f"<td style='padding:2px 10px'>{esc(h.suspected_fault_type or '—')}</td>"
        f"<td style='padding:2px 10px'><b>{esc(h.status.value)}</b></td>"
        f"<td style='padding:2px 10px'>+{len(h.supporting_evidence)} / -{len(h.contradicting_evidence)}</td></tr>"
        for h in inv.hypotheses)

    out = _card("#64748b", f"✅ Final state: {esc(inv.state.value)}",
                f"steps={inv.step} · hypotheses={len(inv.hypotheses)} · tool_calls={len(inv.tool_calls)} · "
                f"evaluations={len(inv.evaluations)} · ledger persisted & reloaded identical: "
                f"<b style='color:{'#22c55e' if persisted_ok else '#ef4444'}'>{persisted_ok}</b>")

    out += ("<div style='border-left:4px solid #3b82f6;padding:8px 14px;margin:8px 0;"
            "background:rgba(59,130,246,.08);border-radius:4px'>"
            "<div style='font-weight:700'>🔓 Ground truth — revealed only now, by the offline plane</div>"
            f"<div style='margin-top:4px'>true root services: <b style='color:#22c55e'>{esc(gt.root_services)}</b> · "
            f"fault: <b>{esc(gt.chaos_types)}</b><br>"
            f"investigator proposed: <b>{esc(prc.root_services if prc else None)}</b> / "
            f"{esc(prc.fault_type if prc else None)}<br><br>"
            f"localization: {hit} &nbsp; fault-type: <b>{m['fault_type_accuracy']}</b> &nbsp; "
            f"causal-path valid: <b>{m['causal_path_valid']}</b> &nbsp; "
            f"GT-isolation: <b style='color:{'#22c55e' if not leaks else '#ef4444'}'>"
            f"{'CLEAN' if not leaks else leaks}</b></div></div>")

    out += ("<div style='margin:8px 0'><b>Hypothesis ledger</b>"
            "<table style='border-collapse:collapse;margin-top:4px;font-size:.9em'>"
            "<tr style='opacity:.6'><th style='padding:2px 10px;text-align:left'>suspect</th>"
            "<th style='padding:2px 10px;text-align:left'>fault</th>"
            "<th style='padding:2px 10px;text-align:left'>status</th>"
            "<th style='padding:2px 10px;text-align:left'>evidence +/-</th></tr>"
            f"{ledger_rows}</table></div>")
    return out


async def investigate(case: str):
    if not case:
        yield "<p>Select an incident and click <b>Run investigation</b>.</p>"
        return
    lake = EvidenceLake(CFG.evidence_account, CRED, CFG.evidence_filesystem)
    inc = load_incident(lake, case)
    store = BlobLedgerStore(CFG.state_account, CRED, CFG.state_container)
    investigator, evaluator = InvestigatorAgent(CFG.model), EvaluatorAgent(CFG.model)

    q: asyncio.Queue = asyncio.Queue()

    async def runner():
        try:
            inv = await run_investigation(inc, lake, investigator, evaluator, store=store,
                                          observer=lambda k, d: q.put_nowait((k, d)))
            await q.put(("__done__", inv))
        except Exception as e:  # surface failures in the UI
            await q.put(("__error__", repr(e)))

    asyncio.create_task(runner())
    parts = [_header_html(inc)]
    yield "".join(parts)
    while True:
        kind, data = await q.get()
        if kind == "__done__":
            parts.append(_final_html(inc, data, store))
            yield "".join(parts)
            return
        if kind == "__error__":
            parts.append(_card("#ef4444", "❌ Investigation error", esc(data)))
            yield "".join(parts)
            return
        html_piece = _event_html(kind, data)
        if html_piece:
            parts.append(html_piece)
            yield "".join(parts)


def build() -> gr.Blocks:
    with gr.Blocks(title="Deep-RCA") as demo:
        gr.Markdown("# Deep-RCA — autonomous root-cause investigation\n"
                    "Pick an OpenRCA incident and watch the agent investigate. Ground truth is "
                    "isolated — revealed only by the offline evaluation plane at the end.")
        with gr.Row():
            case = gr.Dropdown(choices=_cases(), label="Incident (OpenRCA 2.0 / ops-lite case)",
                               value=(_cases()[0] if _cases() else None), scale=4)
            run = gr.Button("Run investigation", variant="primary", scale=1)
        timeline = gr.HTML(label="Investigation", autoscroll=True,
                           value="<p style='opacity:.6'>Select an incident and click Run.</p>")
        run.click(investigate, inputs=case, outputs=timeline)
    return demo


if __name__ == "__main__":
    build().launch(server_name="127.0.0.1", server_port=7860, inbrowser=True,
                   theme=gr.themes.Soft())
