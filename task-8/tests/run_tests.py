"""Автоматизированный прогон red-team атак против агента.

Одна команда:
    python tests/run_tests.py

Запускает все payloads из payloads.py против уязвимого (порт 8001) и
защищённого (порт 8002) агента, оценивает результаты детекторами из judges.py
и генерирует отчёт: reports/report.json, report.md, report.html.

Переменные окружения:
  VULN_URL  (default http://localhost:8001)
  PROT_URL  (default http://localhost:8002)
  TIMEOUT   (default 60)
"""
import json
import os
import sys
import time
import datetime
import urllib.request
import urllib.error

from payloads import PAYLOADS, categories
from judges import evaluate

VULN_URL = os.getenv("VULN_URL", "http://localhost:8001")
PROT_URL = os.getenv("PROT_URL", "http://localhost:8002")
TIMEOUT = int(os.getenv("TIMEOUT", "60"))

REPORTS_DIR = os.path.join(os.path.dirname(__file__), "reports")


def chat(url: str, message: str) -> dict:
    """POST /chat к агенту. Возвращает {response, ...} или {response: error}."""
    data = json.dumps({"message": message}).encode("utf-8")
    req = urllib.request.Request(
        f"{url}/chat", data=data,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, urllib.error.HTTPError) as e:
        return {"response": f"[ENDPOINT ERROR] {e}", "tools_used": [],
                "blocked_by_input_guard": False, "output_redacted": False}
    except Exception as e:  # noqa: BLE001
        return {"response": f"[ERROR] {e}", "tools_used": [],
                "blocked_by_input_guard": False, "output_redacted": False}


def wait_for(url: str, name: str, retries=30):
    for i in range(retries):
        try:
            with urllib.request.urlopen(f"{url}/health", timeout=5) as r:
                if r.status == 200:
                    print(f"  [OK] {name} ready at {url}")
                    return True
        except Exception:
            time.sleep(2)
    print(f"  [WARN] {name} not reachable at {url} (will proceed anyway)")

def run_suite():
    print("=" * 70)
    print("RED-TEAM AUTOMATED TEST SUITE")
    print("=" * 70)
    print(f"Vulnerable agent: {VULN_URL}")
    print(f"Protected agent:  {PROT_URL}")
    print(f"Payloads:         {len(PAYLOADS)}")
    print("-" * 70)

    wait_for(VULN_URL, "vulnerable")
    wait_for(PROT_URL, "protected")

    results = []
    for p in PAYLOADS:
        print(f"\n[{p['id']}] {p['category']} — {p['description']}")
        # Vulnerable
        vresp = chat(VULN_URL, p["payload"])
        veval = evaluate(vresp.get("response", ""), p["success_indicators"])
        # Protected
        presp = chat(PROT_URL, p["payload"])
        peval = evaluate(presp.get("response", ""), p["success_indicators"])

        row = {
            "id": p["id"],
            "category": p["category"],
            "owasp": p["owasp"],
            "description": p["description"],
            "payload": p["payload"],
            "vulnerable": {
                "response": vresp.get("response", ""),
                "tools_used": vresp.get("tools_used", []),
                "eval": veval,
            },
            "protected": {
                "response": presp.get("response", ""),
                "tools_used": presp.get("tools_used", []),
                "blocked_by_input_guard": presp.get("blocked_by_input_guard", False),
                "output_redacted": presp.get("output_redacted", False),
                "eval": peval,
            },
        }
        results.append(row)
        vs = "SUCCESS" if veval["attack_succeeded"] else "blocked"
        ps = "blocked" if not peval["attack_succeeded"] else "LEAKED"
        print(f"  vulnerable: {vs} | protected: {ps}")

    summary = build_summary(results)
    write_reports(results, summary)
    print("\n" + "=" * 70)
    print(f"SUMMARY: vuln_success={summary['vuln_success']}/{summary['total']}  "
          f"prot_blocked={summary['prot_blocked']}/{summary['total']}")
    print(f"Reports written to {REPORTS_DIR}/")
    return summary


def build_summary(results):
    total = len(results)
    vuln_success = sum(1 for r in results if r["vulnerable"]["eval"]["attack_succeeded"])
    prot_blocked = sum(1 for r in results if not r["protected"]["eval"]["attack_succeeded"])
    by_cat = {}
    for r in results:
        c = r["category"]
        by_cat.setdefault(c, {"total": 0, "vuln_success": 0, "prot_blocked": 0})
        by_cat[c]["total"] += 1
        if r["vulnerable"]["eval"]["attack_succeeded"]:
            by_cat[c]["vuln_success"] += 1
        if not r["protected"]["eval"]["attack_succeeded"]:
            by_cat[c]["prot_blocked"] += 1
    return {
        "total": total,
        "vuln_success": vuln_success,
        "prot_blocked": prot_blocked,
        "by_category": by_cat,
        "timestamp": datetime.datetime.utcnow().isoformat() + "Z",
    }


def _esc(s):
    return (s or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def write_reports(results, summary):
    os.makedirs(REPORTS_DIR, exist_ok=True)
    # JSON
    with open(os.path.join(REPORTS_DIR, "report.json"), "w", encoding="utf-8") as f:
        json.dump({"summary": summary, "results": results}, f, indent=2, ensure_ascii=False)
    # Markdown
    write_markdown(results, summary)
    # HTML
    write_html(results, summary)


def write_markdown(results, summary):
    lines = [
        "# Automated Red-Team Report",
        "",
        f"Generated: {summary['timestamp']}",
        "",
        "## Summary",
        "",
        f"- Total payloads: **{summary['total']}**",
        f"- Vulnerable agent — attacks succeeded: **{summary['vuln_success']}/{summary['total']}**",
        f"- Protected agent — attacks blocked: **{summary['prot_blocked']}/{summary['total']}**",
        "",
        "## By category",
        "",
        "| Category | Total | Vuln success | Prot blocked |",
        "|---|---|---|---|",
    ]
    for c, s in summary["by_category"].items():
        lines.append(f"| {c} | {s['total']} | {s['vuln_success']} | {s['prot_blocked']} |")
    lines += ["", "## Detailed results", ""]
    for r in results:
        v = r["vulnerable"]["eval"]
        p = r["protected"]["eval"]
        lines += [
            f"### {r['id']} — {r['category']}",
            f"- OWASP: {r['owasp']}",
            f"- Description: {r['description']}",
            f"- Payload:",
            "  ```",
            f"  {r['payload']}",
            "  ```",
            f"- **Vulnerable**: {'SUCCESS' if v['attack_succeeded'] else 'blocked'} "
            f"(secret={v['secret_leaked']}, pii={v['pii_leaked']}, prompt={v['prompt_leaked']}, delete={v['delete_executed']})",
            f"  - Response: `{r['vulnerable']['response'][:300]}`",
            f"- **Protected**: {'LEAKED' if p['attack_succeeded'] else 'blocked'} "
            f"(input_guard={r['protected']['blocked_by_input_guard']}, output_redacted={r['protected']['output_redacted']})",
            f"  - Response: `{r['protected']['response'][:300]}`",
            "",
        ]
    with open(os.path.join(REPORTS_DIR, "report.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


def write_html(results, summary):
    rows_html = []
    for r in results:
        v = r["vulnerable"]["eval"]
        p = r["protected"]["eval"]
        vs = "✅ SUCCESS" if v["attack_succeeded"] else "🚫 blocked"
        ps = "🚫 LEAKED" if p["attack_succeeded"] else "✅ blocked"
        rows_html.append(
            f"<tr><td>{r['id']}</td><td>{r['category']}</td><td>{_esc(r['description'])}</td>"
            f"<td>{vs}</td><td>{ps}</td>"
            f"<td><code>{_esc(r['vulnerable']['response'][:200])}</code></td>"
            f"<td><code>{_esc(r['protected']['response'][:200])}</code></td></tr>"
        )
    html = f"""<!DOCTYPE html><html><head><meta charset="utf-8">
<title>Red-Team Report</title><style>
body{{font-family:sans-serif;margin:2em}} table{{border-collapse:collapse;width:100%}}
th,td{{border:1px solid #ccc;padding:6px;text-align:left;vertical-align:top}}
th{{background:#eee}} code{{white-space:pre-wrap;word-break:break-all}}
</style></head><body>
<h1>Automated Red-Team Report</h1>
<p>Generated: {summary['timestamp']}</p>
<p>Total: {summary['total']} | Vuln success: {summary['vuln_success']} | Prot blocked: {summary['prot_blocked']}</p>
<table><tr><th>ID</th><th>Category</th><th>Description</th><th>Vulnerable</th><th>Protected</th><th>Vuln response</th><th>Prot response</th></tr>
{"".join(rows_html)}
</table></body></html>"""
    with open(os.path.join(REPORTS_DIR, "report.html"), "w", encoding="utf-8") as f:
        f.write(html)


if __name__ == "__main__":
    s = run_suite()
    # exit code: 0 если защищённая версия заблокировала все атаки
    sys.exit(0 if s["prot_blocked"] == s["total"] else 1)

