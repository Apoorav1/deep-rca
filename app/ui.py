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
from deeprca.evidence.tools import TOOLS
from deeprca.knowledge import domain_knowledge
from deeprca.projection import build_projection
from deeprca.state import BlobLedgerStore
from deeprca.workflow import run_investigation

CFG = RuntimeConfig.from_env()
CRED = DefaultAzureCredential()

PHASE1_TOOLS = ["query_metrics", "query_traces", "query_logs", "get_topology"]
MODE_P3 = "Phase 3 — knowledge plane ON"
MODE_P1 = "Phase 1 — baseline (knowledge OFF)"


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


def _header_html(inc, mode: str = "") -> str:
    mode_badge = (f"<br>mode: <b>{esc(mode)}</b>" if mode else "")
    return _card("#3b82f6", f"🚀 Investigating incident · {esc(inc.case_name)}",
                 f"system <b>{esc(inc.system)}</b> · namespace {esc(inc.namespace)} · abnormal window "
                 f"{esc(inc.abnormal_window.start)} → {esc(inc.abnormal_window.end)}{mode_badge}"
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


async def investigate(case: str, mode: str):
    if not case:
        yield "<p>Select an incident and click <b>Run investigation</b>.</p>"
        return
    knowledge_mode = (mode == MODE_P3)
    allowed = None if knowledge_mode else PHASE1_TOOLS
    lake = EvidenceLake(CFG.evidence_account, CRED, CFG.evidence_filesystem)
    inc = load_incident(lake, case)
    store = BlobLedgerStore(CFG.state_account, CRED, CFG.state_container)
    investigator = InvestigatorAgent(CFG.model, knowledge_mode=knowledge_mode)
    evaluator = EvaluatorAgent(CFG.model)

    q: asyncio.Queue = asyncio.Queue()

    async def runner():
        try:
            inv = await run_investigation(inc, lake, investigator, evaluator, store=store,
                                          observer=lambda k, d: q.put_nowait((k, d)),
                                          include_knowledge=knowledge_mode, allowed_tools=allowed)
            await q.put(("__done__", inv))
        except Exception as e:  # surface failures in the UI
            await q.put(("__error__", repr(e)))

    asyncio.create_task(runner())
    parts = [_header_html(inc, mode)]
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


def _sec(title: str, body: str, color: str = "#3b82f6") -> str:
    return (f"<div style='border-left:4px solid {color};padding:6px 14px;margin:10px 0'>"
            f"<div style='font-weight:700;font-size:1.05em'>{title}</div>{body}</div>")


def _architecture_html() -> str:
    tool_rows = "".join(
        f"<tr><td style='padding:3px 10px;vertical-align:top'><code>{esc(s.name)}</code></td>"
        f"<td style='padding:3px 10px;opacity:.85'>{esc(s.description)}</td></tr>"
        for s in TOOLS.values())
    k = domain_knowledge()
    sig_rows = "".join(
        f"<tr><td style='padding:3px 10px;vertical-align:top'><b>{esc(name)}</b></td>"
        f"<td style='padding:3px 10px;opacity:.85'>{esc(v['decisive_signal'])}</td></tr>"
        for name, v in k["fault_signatures"].items())

    planes = (
        "<table style='border-collapse:collapse'>"
        "<tr style='opacity:.6'><th style='text-align:left;padding:3px 10px'>Plane</th>"
        "<th style='text-align:left;padding:3px 10px'>Contents</th>"
        "<th style='text-align:left;padding:3px 10px'>Access</th></tr>"
        "<tr><td style='padding:3px 10px'><b>Control</b></td><td style='padding:3px 10px'>Agent-Framework loop: Investigator ⇄ reducer ⇄ blind Evaluator</td><td style='padding:3px 10px'>orchestrates</td></tr>"
        "<tr><td style='padding:3px 10px'><b>Knowledge</b></td><td style='padding:3px 10px'>ontology-as-code: fault signatures + localization heuristic</td><td style='padding:3px 10px'>read-only</td></tr>"
        "<tr><td style='padding:3px 10px'><b>Evidence</b></td><td style='padding:3px 10px'>telemetry tools over ADLS Gen2 (metrics/traces/logs/topology/pod-health)</td><td style='padding:3px 10px'>read-only</td></tr>"
        "<tr><td style='padding:3px 10px'><b>Investigation state</b></td><td style='padding:3px 10px'>typed ledger (Azure Blob), checkpointed</td><td style='padding:3px 10px'>reducer-write</td></tr>"
        "<tr><td style='padding:3px 10px'><b>Offline eval</b> 🔒</td><td style='padding:3px 10px'>ground-truth store + scorer (air-gapped)</td><td style='padding:3px 10px'>eval identity only</td></tr>"
        "</table>")

    models = " · ".join(f"<code>{m}</code>" for m in
                        ["Incident", "Evidence", "Hypothesis", "ToolCall", "CausalPath",
                         "Investigation", "Evaluation", "Escalation"])

    loop = ("INITIALIZED → OBSERVING → HYPOTHESIZING → EVIDENCE_PLANNING → COLLECTING → "
            "LEDGER_UPDATE → EVALUATION → {CONTINUE↺ | CONCLUDE→propose→CONCLUDED | ESCALATE→HITL}")

    html_out = (
        _sec("Four separated planes", planes) +
        _sec("Ground-truth isolation (verified 3 ways)",
             "<ul style='margin:4px 0'>"
             "<li><b>Identity:</b> Investigator managed identity has zero roles on the GT store; "
             "only the eval identity can read it.</li>"
             "<li><b>Static:</b> nothing under <code>src/deeprca/</code> may import <code>eval/</code> "
             "(enforced by a test).</li>"
             "<li><b>Runtime:</b> a scan asserts no GT markers (GT account, filenames, injection UUIDs) "
             "appear in the projection or ledger.</li></ul>", "#22c55e") +
        _sec("Core loop / state machine", f"<code style='opacity:.85'>{esc(loop)}</code>", "#f59e0b") +
        _sec("Ledger-as-truth",
             "The authoritative state is the typed <code>Investigation</code> aggregate. The LLM is a "
             "stateless step function: it reads a deterministic <b>projection</b> and emits a <b>typed "
             "action</b>; a pure reducer applies it; the ledger is checkpointed. Conversation history is "
             "never authoritative.", "#8b5cf6") +
        _sec("Typed domain models", f"<div style='opacity:.85'>{models}</div>", "#06b6d4") +
        _sec("Agents (Microsoft Agent Framework on Foundry gpt-4.1)",
             "<ul style='margin:4px 0'>"
             "<li><b>InvestigatorAgent</b> — sees a GT-free projection; emits one typed action "
             "(propose_hypothesis · request_evidence · link_evidence · propose_root_cause).</li>"
             "<li><b>EvaluatorAgent (BLIND)</b> — independent critic; never sees GT; emits exactly one "
             "decision: CONTINUE / CONCLUDE / ESCALATE after challenging evidence sufficiency, causal & "
             "temporal validity, contradictions, and alternatives.</li></ul>", "#8b5cf6") +
        _sec("Evidence-Plane tools",
             f"<table style='border-collapse:collapse'>{tool_rows}</table>", "#06b6d4") +
        _sec("Knowledge plane — fault signatures (decisive signal)",
             f"<table style='border-collapse:collapse'>{sig_rows}</table>"
             f"<div style='margin-top:6px;opacity:.85'><b>Localization heuristic:</b> "
             f"{esc(k['localization_heuristic'])}</div>", "#3b82f6") +
        _sec("Azure footprint (Phase-1 leaner)",
             "Foundry <code>gpt-4.1</code> (Responses API) · ADLS Gen2 evidence lake · Blob ledger · "
             "isolated GT storage + managed identities with scoped RBAC · AAD auth end-to-end.", "#64748b")
    )
    return html_out


def build() -> gr.Blocks:
    with gr.Blocks(title="Deep-RCA") as demo:
        gr.Markdown("# Deep-RCA — autonomous root-cause investigation\n"
                    "Pick an OpenRCA incident and watch the agent investigate. Ground truth is "
                    "isolated — revealed only by the offline evaluation plane at the end.")
        with gr.Tabs():
            with gr.Tab("🔎 Investigate"):
                with gr.Row():
                    case = gr.Dropdown(choices=_cases(), label="Incident (OpenRCA 2.0 / ops-lite case)",
                                       value=(_cases()[0] if _cases() else None), scale=3)
                    mode = gr.Radio([MODE_P3, MODE_P1], value=MODE_P3, scale=2,
                                    label="Mode (ablation)",
                                    info="Phase 3 = knowledge plane + pod-health/silent tools. "
                                         "Phase 1 = baseline without them (watch it miss).")
                    run = gr.Button("Run investigation", variant="primary", scale=1)
                timeline = gr.HTML(autoscroll=True,
                                   value="<p style='opacity:.6'>Select an incident and mode, then Run. "
                                         "Try the same incident in both modes to see the knowledge plane "
                                         "flip a miss into a hit.</p>")
                run.click(investigate, inputs=[case, mode], outputs=timeline)
            with gr.Tab("🏛️ Architecture & Design"):
                gr.HTML(_architecture_html())
    return demo


if __name__ == "__main__":
    build().launch(server_name="127.0.0.1", server_port=7860, inbrowser=True,
                   theme=gr.themes.Soft())
