"""Evaluate the extraction agents against the synthetic fixtures with the REAL provider.

    python scripts/eval_extraction.py                 # chats as screenshots + labels
    python scripts/eval_extraction.py --chat-mode text
    python scripts/eval_extraction.py --chat-mode both

Prints metrics and writes docs/EVAL_RESULTS.md. Uses AI_PROVIDER / GEMINI_* from the root .env.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.ai.agents import conversation_analyst as ca  # noqa: E402
from app.ai.agents import label_reader as lr  # noqa: E402
from app.ai.provider import get_provider  # noqa: E402
from app.config import ROOT_DIR, get_settings  # noqa: E402
from app.rules.normalize import norm_field  # noqa: E402

FIX = Path(__file__).resolve().parents[1] / "tests" / "fixtures"
PROTECTED = {"line1": "1 Main St", "city": "San Jose", "state": "CA", "postal_code": "95131", "country": "US"}
ACTIVE = {"EXPLICIT", "AMBIGUOUS"}


def _matches(exp: dict, req: dict) -> bool:
    return all(req.get(k) == v for k, v in exp.items())


def eval_chats(provider, mode: str, pause: float) -> tuple[dict, list[dict]]:
    cases = json.loads((FIX / "chats" / "chats.json").read_text(encoding="utf-8"))
    rows = []
    tp = fp = fn = tn = 0
    exp_hits = exp_total = 0
    blocking_misses = 0
    injection_ok = injection_total = 0
    failures = 0
    for case in cases:
        if mode == "image":
            data, kind, mime = (FIX / "chats" / case["image"]).read_bytes(), "CHAT_IMAGE", "image/png"
        else:
            data, kind, mime = (FIX / "chats" / case["text"]).read_bytes(), "CHAT_TEXT", "text/plain"
        uid = f"upl_{case['id']}"
        res, _ = ca.analyze(provider, [ca.ChatInput(uid, kind, data, mime)], PROTECTED)
        if res.output is None:
            failures += 1
            rows.append({"id": case["id"], "status": res.status, "error": (res.error or "")[:120]})
            if "quota exhausted" in (res.error or ""):
                print("  quota exhausted - stopping chat eval early"); break
            time.sleep(pause)
            continue
        reqs = [r.model_dump(mode="json") for r in res.output.requests]
        expected_positive = any(e["type"] == "ADDRESS_CHANGE" and e.get("status", "EXPLICIT") in ACTIVE for e in case["expected"]) and not case["no_address_change"]
        predicted_positive = any(r["type"] == "ADDRESS_CHANGE" and r["status"] in ACTIVE for r in reqs)
        if expected_positive and predicted_positive:
            tp += 1
        elif expected_positive:
            fn += 1
        elif predicted_positive:
            fp += 1
        else:
            tn += 1
        for e in case["expected"]:
            exp_total += 1
            if any(_matches(e, r) for r in reqs):
                exp_hits += 1
            elif e["type"] == "ADDRESS_CHANGE" and e.get("status") == "EXPLICIT" and e.get("speaker") == "BUYER":
                blocking_misses += 1
        if case.get("injection"):
            injection_total += 1
            blob = json.dumps(res.output.model_dump(mode="json")).lower()
            non_quote = json.dumps({k: v for k, v in res.output.model_dump(mode="json").items() if k not in ("requests", "addresses_mentioned")}).lower()
            if any(r["type"] == "OTHER_RISK" for r in reqs) and "approve" not in non_quote:
                injection_ok += 1
            _ = blob
        rows.append(
            {
                "id": case["id"],
                "status": res.status,
                "expected": [f"{e['type']}/{e.get('status', '*')}/{e.get('speaker', '*')}" for e in case["expected"]] or ["(none)"],
                "got": [f"{r['type']}/{r['status']}/{r['speaker']}" for r in reqs] or ["(none)"],
                "ok": all(any(_matches(e, r) for r in reqs) for e in case["expected"]) and (predicted_positive == expected_positive),
                "confidence": res.output.confidence,
                "latency_ms": res.latency_ms,
                "dropped": len(res.notes),
            }
        )
        print(f"  chat {case['id']:<38} {'OK ' if rows[-1]['ok'] else 'MISS'} got={rows[-1]['got']}")
        time.sleep(pause)
    precision = tp / (tp + fp) if (tp + fp) else 1.0
    recall = tp / (tp + fn) if (tp + fn) else 1.0
    metrics = {
        "cases": len(cases),
        "evaluated": tp + fp + fn + tn,
        "mode": mode,
        "address_change_precision": round(precision, 3),
        "address_change_recall": round(recall, 3),
        "confusion": {"tp": tp, "fp": fp, "fn": fn, "tn": tn},
        "expected_request_match_rate": round(exp_hits / exp_total, 3) if exp_total else 1.0,
        "missed_blocking_requests": blocking_misses,
        "injection_handled": f"{injection_ok}/{injection_total}",
        "extraction_failures": failures,
    }
    return metrics, rows


def eval_labels(provider, pause: float) -> tuple[dict, list[dict]]:
    cases = json.loads((FIX / "labels" / "labels.json").read_text(encoding="utf-8"))
    rows = []
    field_hits = {"postal_code": 0, "city": 0, "state": 0}
    field_total = 0
    unreadable_ok = unreadable_total = 0
    issue_hits = issue_total = 0
    failures = 0
    for case in cases:
        path = FIX / "labels" / case["file"]
        mime = "application/pdf" if path.suffix == ".pdf" else "image/png"
        res, _ = lr.read_label(provider, f"upl_{case['id']}", path.read_bytes(), mime)
        if res.output is None:
            failures += 1
            rows.append({"id": case["id"], "status": res.status, "error": (res.error or "")[:120]})
            if "quota exhausted" in (res.error or ""):
                print("  quota exhausted - stopping label eval early"); break
            time.sleep(pause)
            continue
        out = res.output
        got = out.address.model_dump()
        exp = case["expected"]
        row = {"id": case["id"], "readable": out.readable, "issues": [str(i) for i in out.issues], "confidence": out.confidence, "latency_ms": res.latency_ms,
               "got": f"{got.get('line1')} | {got.get('line2')} | {got.get('city')} {got.get('state')} {got.get('postal_code')}"}
        if case["expect_unreadable"]:
            unreadable_total += 1
            ok = (not out.readable) or ("BLURRY" in row["issues"]) or out.confidence < 0.7
            unreadable_ok += int(ok)
            row["ok"] = ok
        else:
            field_total += 1
            fields_ok = {}
            for f in field_hits:
                hit = norm_field(f, got.get(f)) == norm_field(f, exp[f])
                field_hits[f] += int(hit)
                fields_ok[f] = hit
            row["ok"] = all(fields_ok.values())
            row["fields"] = fields_ok
        for iss in case["expected_issues"]:
            issue_total += 1
            issue_hits += int(iss in row["issues"])
        rows.append(row)
        print(f"  label {case['id']:<24} {'OK ' if row['ok'] else 'MISS'} {row['got']} readable={out.readable} issues={row['issues']}")
        time.sleep(pause)
    metrics = {
        "cases": len(cases),
        "zip_accuracy": round(field_hits["postal_code"] / field_total, 3) if field_total else None,
        "city_accuracy": round(field_hits["city"] / field_total, 3) if field_total else None,
        "state_accuracy": round(field_hits["state"] / field_total, 3) if field_total else None,
        "unreadable_flagged": f"{unreadable_ok}/{unreadable_total}",
        "issue_detection": f"{issue_hits}/{issue_total}",
        "extraction_failures": failures,
    }
    return metrics, rows


def write_report(provider, chat_results, label_results) -> Path:
    out = ROOT_DIR / "docs" / "EVAL_RESULTS.md"
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    lines = [
        "# Extraction eval results",
        "",
        f"_Generated {now} by `backend/scripts/eval_extraction.py` · provider `{provider.name}` · model `{provider.model}` · "
        f"prompts `{ca.PROMPT_VERSION}`, `{lr.PROMPT_VERSION}` · schema 1.0_",
        "",
        "Fixtures are synthetic (made-up names and addresses), generated by `backend/scripts/make_fixtures.py`.",
        "PRD targets: ADDRESS_CHANGE recall ≥ 0.90, precision ≥ 0.85; label ZIP/city/state ≥ 0.90; 0 missed blocking requests.",
        "",
    ]
    for metrics, rows in chat_results:
        lines += [f"## Conversation Analyst ({metrics['mode']} input, {metrics['cases']} chats)", "", "| Metric | Value |", "| --- | --- |"]
        lines += [f"| {k} | {v} |" for k, v in metrics.items() if k not in ("cases", "mode")]
        lines += ["", "| Case | Expected | Got | OK |", "| --- | --- | --- | --- |"]
        for r in rows:
            if "error" in r:
                lines.append(f"| {r['id']} | — | {r['status']}: {r['error']} | ❌ |")
            else:
                lines.append(f"| {r['id']} | {', '.join(r['expected'])} | {', '.join(r['got'])} | {'✅' if r['ok'] else '❌'} |")
        lines.append("")
    if label_results:
        metrics, rows = label_results
        lines += [f"## Label Reader ({metrics['cases']} labels)", "", "| Metric | Value |", "| --- | --- |"]
        lines += [f"| {k} | {v} |" for k, v in metrics.items() if k != "cases"]
        lines += ["", "| Case | Read (line1 · line2 · city state zip) | Readable | Issues | OK |", "| --- | --- | --- | --- | --- |"]
        for r in rows:
            if "error" in r:
                lines.append(f"| {r['id']} | {r['status']}: {r['error']} | — | — | ❌ |")
            else:
                lines.append(f"| {r['id']} | {r['got']} | {r['readable']} | {', '.join(r['issues']) or '—'} | {'✅' if r['ok'] else '❌'} |")
        lines.append("")
    out.write_text("\n".join(lines), encoding="utf-8")
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--chat-mode", choices=["image", "text", "both"], default="image")
    ap.add_argument("--skip-labels", action="store_true")
    ap.add_argument("--pause", type=float, default=2.0, help="seconds between calls (free-tier rate limits)")
    args = ap.parse_args()
    provider = get_provider(get_settings())
    print(f"provider={provider.name} model={provider.model}")
    chat_results = []
    for mode in (["image", "text"] if args.chat_mode == "both" else [args.chat_mode]):
        print(f"Conversation Analyst ({mode})")
        m, rows = eval_chats(provider, mode, args.pause)
        print(json.dumps(m, indent=1))
        chat_results.append((m, rows))
    label_results = None
    if not args.skip_labels:
        print("Label Reader")
        label_results = eval_labels(provider, args.pause)
        print(json.dumps(label_results[0], indent=1))
    print(f"report: {write_report(provider, chat_results, label_results)}")


if __name__ == "__main__":
    main()
