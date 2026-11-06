#!/usr/bin/env python3
"""系统自测：用黄金案例 RC-20261104-001 的 OCR 文本跑 CLI，
校验确定性检查、APR 反推、建议结论是否与人工 RC 一致。
用法：python3 system/tests/test_system.py
"""
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / "system"))
import core  # noqa: E402

FIXTURE = ROOT / "system/tests/fixtures/rc-20261104-001-ocr.txt"


def check(cond, label):
    print(("PASS " if cond else "FAIL ") + label)
    return cond


def main():
    ocr_text = FIXTURE.read_text(encoding="utf-8")
    result = core.review(ocr_text)
    ok = True
    passed = {c["name"]: c["passed"] for c in result["checks"]}
    ok &= check(passed.get("warning_present") is True, "忠告原文通过")
    ok &= check(passed.get("license_present") is True, "牌照号 773/2026 通过")
    ok &= check(passed.get("hotline_present") is True, "热线 25310333 通过")
    ok &= check(passed.get("apr_present") is True, "APR 出现通过")
    ok &= check(passed.get("promo_date_present") is False, "限时推广没日期 → 不通过")
    ok &= check(passed.get("caret_footnote_present") is True,
                "^ 脚注存在（但只是通用句，条件仍不足，见 C 项）")
    ok &= check(passed.get("no_artboard_residual") is False, "画板 4 残留 → 不通过")
    a = result["apr_check"]
    ok &= check(a["available"] and abs(a["implied_months"] - 64.1) < 0.5,
                "APR 反推约 64.1 个月（得到 %.1f）" % a.get("implied_months", -1))
    ok &= check(a["is_standard_term"] is False, "64 个月不是常规期限")
    ok &= check(result["suggested_verdict"] == "不建议发布", "建议结论：不建议发布")
    ok &= check(result["risk"] == "高", "风险：高")
    ok &= check("rebate_exceeds_principal" in result["flags"], "回赠 80,000 > 借款 50,000 高风险")

    # 繁体转录与简体转录应得出同一结果（2026-11-06 误判回归：繁体曾只过 2/8）
    trad_text = (ROOT / "system/tests/fixtures/rc-20261104-001-ocr-trad.txt").read_text(encoding="utf-8")
    trad_result = core.review(trad_text)
    trad_passed = {c["name"]: c["passed"] for c in trad_result["checks"]}
    ok &= check(trad_passed == passed, "繁体转录检查结果与简体一致（5/8）")
    ok &= check(trad_result["apr_check"]["available"]
                and abs(trad_result["apr_check"]["implied_months"] - 64.1) < 0.5,
                "繁体转录 APR 反推同样约 64.1 个月")
    ok &= check(trad_result["suggested_verdict"] == "不建议发布", "繁体转录建议结论：不建议发布")

    # CLI 端到端：review → list → show → signoff
    case_id = "RC-TEST-20261106-001"
    r = subprocess.run([sys.executable, "system/cli.py", "review",
                        "--ocr-text-file", str(FIXTURE), "--case-id", case_id],
                       cwd=ROOT, capture_output=True, text=True)
    ok &= check(r.returncode == 0, "CLI review 退出码 0")
    folder = ROOT / "data/cases" / case_id
    ok &= check((folder / "report.md").exists(), "生成 report.md")
    ok &= check((folder / "checks.json").exists(), "生成 checks.json")
    report = (folder / "report.md").read_text(encoding="utf-8")
    ok &= check("不建议发布" in report and "结论：合规" not in report,
                "报告含建议结论、不判合规")
    meta = json.loads((folder / "case.json").read_text(encoding="utf-8"))
    ok &= check(meta["status"].startswith("草稿评审"), "新建状态为草稿评审")
    r = subprocess.run([sys.executable, "system/cli.py", "signoff", "--case-id", case_id,
                        "--reviewer", "测试", "--decision", "不建议发布", "--note", "缺计算底稿"],
                       cwd=ROOT, capture_output=True, text=True)
    ok &= check(r.returncode == 0, "CLI signoff 退出码 0")
    meta = json.loads((folder / "case.json").read_text(encoding="utf-8"))
    ok &= check("已签核" in meta["status"], "签核后状态更新")
    print("\n全部通过" if ok else "\n有失败项，见上")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
