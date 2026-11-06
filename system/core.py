#!/usr/bin/env python3
"""合规评审系统 · 核心逻辑（第 1 层确定性检查 + APR 反推 + RC 草稿生成）。

被 system/server.py（网页版）和 system/cli.py（命令行版）共用。
只依赖 Python 标准库 + 仓库已有的 src/deterministic_checks.py、src/apr.py。

硬规则（见 SKILL.md）：
- 只输出草稿评审，结论只有「不建议发布 / 需修改后重审」两种建议值，
  最终决定权在人工合规负责人；永远不输出「合规 / 已批准 / 合法」。
- 不能从位图确认的（忠告字号比例、牌照有效性、APR 计算底稿），
  一律写「无法确认，需源档 / 计算底稿 / 注册处复核」，不编数字。
"""
import importlib.util
import json
import re
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
DATA_DIR = ROOT / "data" / "cases"

STANDARD_TERMS = (12, 24, 36, 48, 60, 72, 84)


def _load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_dchecks = _load_module("hk_deterministic_checks", SRC / "deterministic_checks.py")
_apr = _load_module("hk_apr", SRC / "apr.py")


def parse_numbers(text):
    """从 OCR 文本里提取评审用的数字；提不到就返回 None，不猜。"""
    out = {"principal": None, "apr": None, "monthly": None, "rebate": None}
    m = re.search(r"借\s*(\d+(?:\.\d+)?)\s*万", text)
    if m:
        out["principal"] = float(m.group(1)) * 10000
    m = re.search(r"实际年利率[^0-9]{0,6}(\d+(?:\.\d+)?)\s*%", text)
    if m:
        out["apr"] = float(m.group(1)) / 100.0
    m = re.search(r"每月供款[^0-9]{0,8}HK\$?\s*([\d,]+)", text)
    if m:
        out["monthly"] = float(m.group(1).replace(",", ""))
    m = re.search(r"(?:现金回赠|回赠)[^0-9]{0,12}HK\$?\s*([\d,]+)", text)
    if not m:
        # 金额在前：「最高享 HK$80,000 现金回赠」
        m = re.search(r"HK\$?\s*([\d,]+)\s*(?:现金回赠|回赠)", text)
    if m:
        out["rebate"] = float(m.group(1).replace(",", ""))
    return out


def apr_check(principal, apr, monthly):
    """APR 反推：月供在该 APR 下对应多少期，是否常规期限。"""
    if principal is None or apr is None or monthly is None:
        return {"available": False,
                "note": "本金 / APR / 月供三项不全，无法反推期数，需产品计算表验证。"}
    n = _apr.implied_months(principal, apr, monthly)
    table = [{"months": m, "monthly": round(_apr.monthly_payment(principal, apr, m), 2)}
             for m in STANDARD_TERMS]
    is_standard = abs(n - round(n)) < 0.5 and round(n) in STANDARD_TERMS
    return {"available": True, "principal": principal, "apr": apr, "monthly": monthly,
            "implied_months": round(n, 1),
            "is_standard_term": is_standard,
            "table": table,
            "note": ("反推期数约 %.1f 个月，%s；无计算底稿时无法确认月供数字是否属实。"
                     % (n, "是常规期限" if is_standard else "不是常规期限（12/24/36/48/60/72/84），需产品计算表验证"))}


def review(ocr_text, principal=None, apr=None, monthly=None):
    """跑一次完整评审，返回结构化结果（不写文件）。"""
    checks = _dchecks.run_checks(ocr_text)
    failed = [c for c in checks if not c["passed"]]
    nums = parse_numbers(ocr_text)
    if principal is not None:
        nums["principal"] = principal
    if apr is not None:
        nums["apr"] = apr
    if monthly is not None:
        nums["monthly"] = monthly
    apr_result = apr_check(nums["principal"], nums["apr"], nums["monthly"])

    flags = []
    if nums["rebate"] is not None and nums["principal"] is not None \
            and nums["rebate"] > nums["principal"]:
        flags.append("rebate_exceeds_principal")
    if "限时" in ocr_text and not any(c["name"] == "promo_date_present" and c["passed"] for c in checks):
        flags.append("promo_no_date")
    if not any(c["name"] == "apr_present" and c["passed"] for c in checks):
        flags.append("no_apr_info")

    suggested_verdict = "不建议发布" if failed else "需修改后重审"
    risk = "高" if failed else "中"
    blockers = []
    for c in failed:
        blockers.append(c["detail"])
    if "rebate_exceeds_principal" in flags:
        blockers.append("现金回赠 HK$%s 大于主推借款额 HK$%s，并排出现容易误导"
                        % (f"{nums['rebate']:,.0f}", f"{nums['principal']:,.0f}"))
    if "no_apr_info" in flags:
        blockers.append("图上没有实际年利率 / 月供等成本信息，只讲好处、不讲成本")
    return {"checks": checks, "failed": failed, "numbers": nums,
            "apr_check": apr_result, "flags": flags,
            "suggested_verdict": suggested_verdict, "risk": risk,
            "blockers": blockers}


def render_report(case_id, platform, ocr_text, result, version=1):
    """按 templates/RC-template.md 的格式生成 RC 草稿报告。"""
    lines = []
    lines.append("# 评审报告（草稿）：%s v%d" % (case_id, version))
    lines.append("")
    lines.append("使用场景：%s 香港贷款静态广告" % (platform or "Meta（Facebook / Instagram）及 Google"))
    lines.append("")
    lines.append("> **本报告为草稿评审，不是法律认定。结论只有建议值，最终是否发布，"
                 "必须由人工合规负责人签字。本系统永远不输出「合规 / 已批准 / 合法」。**")
    lines.append("")
    lines.append("## 1. 整体结论（建议值，待人工签核）")
    lines.append("")
    lines.append("结论：%s" % result["suggested_verdict"])
    lines.append("风险等级：%s" % result["risk"])
    lines.append("")
    lines.append("主要阻塞项：")
    if result["blockers"]:
        for b in result["blockers"]:
            lines.append("- %s" % b)
    else:
        lines.append("- （确定性检查全部通过，仍需按 A–H 逐条人工 / LLM 评审后才能定稿）")
    lines.append("")
    lines.append("## 2. 第 1 层：确定性检查结果（代码跑出，非 LLM 猜测）")
    lines.append("")
    for c in result["checks"]:
        lines.append("- %s %s：%s" % ("通过" if c["passed"] else "不通过", c["name"], c["detail"]))
    lines.append("")
    lines.append("## 3. APR / 月供反推")
    lines.append("")
    a = result["apr_check"]
    if a["available"]:
        lines.append("- 本金 HK$%s，APR %.2f%%，月供 HK$%s" %
                     (f"{a['principal']:,.0f}", a["apr"] * 100, f"{a['monthly']:,.0f}"))
        lines.append("- %s" % a["note"])
        lines.append("- 各常规期限月供对照：%s" %
                     "；".join(" %d 期约 HK$%s" % (t["months"], f"{t['monthly']:,.2f}")
                                for t in a["table"]))
    else:
        lines.append("- %s" % a["note"])
    lines.append("")
    lines.append("## 4. 逐条问题 A–H（按 checklist/hk-checklist.md）")
    lines.append("")
    lines.append("以下为系统能从确定性检查直接得出的部分；涉及画面语气、误导关联、"
                 "字体显著性等判断，需按 checklist 由 Marley（LLM 评审）或人工逐条补全，"
                 "不确定的写「无法确认，需源档 / 计算底稿 / 注册处复核」。")
    lines.append("")
    lines.append("### A. 贷款示例是否完整")
    lines.append("判定：待评审 | 数字依据见第 3 节；还款期、总还款额、总利息、费用、"
                 "适用客户 / 产品是否齐全，需对照 OCR 全文核对。")
    lines.append("")
    lines.append("### B. 月供与 APR 是否属于同一示例")
    lines.append("判定：待评审 | %s" % a["note"])
    lines.append("")
    lines.append("### C. 现金回赠条件是否充分")
    caret = next((c for c in result["checks"] if c["name"] == "caret_footnote_present"), None)
    lines.append("判定：%s | %s" %
                 ("不符合" if caret and not caret["passed"] else "待评审",
                  caret["detail"] if caret else ""))
    if "rebate_exceeds_principal" in result["flags"]:
        lines.append("高风险：回赠金额大于主推借款额，见第 1 节。")
    lines.append("")
    lines.append("### D. 限时推广是否有日期")
    promo = next((c for c in result["checks"] if c["name"] == "promo_date_present"), None)
    lines.append("判定：%s | %s" %
                 ("不符合" if promo and not promo["passed"] else "通过",
                  promo["detail"] if promo else ""))
    lines.append("")
    lines.append("### E. 最高贷款额适用范围")
    lines.append("判定：待评审 | 需核对最高额适用的产品 / 客户类别，以及最高额与最长期能否同时满足。")
    lines.append("")
    lines.append("### F. 忠告显著性")
    lines.append("判定：无法确认 | 不能从位图量出准确比例，需源文件中的字体名称、色值、字高量度供人工复核。")
    lines.append("")
    lines.append("### G. 手机端小字及法定资料可读性")
    lines.append("判定：待评审 | 需提供 Meta / Google 各最终尺寸的手机预览；"
                 "牌照有效性、公司法定名称、热线是否为投诉热线，不能从图上核实。")
    lines.append("")
    lines.append("### H. 是不是最终投放稿")
    art = next((c for c in result["checks"] if c["name"] == "no_artboard_residual"), None)
    wm = next((c for c in result["checks"] if c["name"] == "no_watermark"), None)
    bad = [c for c in (art, wm) if c and not c["passed"]]
    lines.append("判定：%s | %s" %
                 ("不符合" if bad else "通过",
                  "；".join(c["detail"] for c in bad) if bad else "未见画板 / 水印残留"))
    lines.append("")
    lines.append("## 5. 主要依据")
    lines.append("")
    for b in ["广告须公正合理，不含误导或欺骗成分",
              "受条件限制的利益，应在切实可行范围内清晰展示",
              "不得掩饰、遗漏、缩小或混淆重要事实",
              "使用细小字体展示重要资料，可能令广告变得不公正或具误导成分",
              "提述最高个人贷款额时，应说明适用贷款及借款人类别",
              "利息条款须以年息百分率显示，并具足够显著性",
              "须展示处理投诉的热线、牌照号码及指定忠告",
              "真正年利率应按《放债人条例》附表 2 计算"]:
        lines.append("- %s" % b)
    lines.append("")
    lines.append("## 6. 发布前必改清单")
    lines.append("")
    for b in result["blockers"]:
        lines.append("- [ ] %s" % b)
    lines.append("- [ ] 按 A–H 逐条补全人工 / LLM 评审，修改后追加至同一 case 重审")
    lines.append("- [ ] 人工合规负责人签核")
    lines.append("")
    lines.append("---")
    lines.append("*OCR 全文（转录，供复核；转录错误以原图为准）：*")
    lines.append("")
    lines.append("```")
    lines.append(ocr_text.strip())
    lines.append("```")
    lines.append("")
    return "\n".join(lines)


def _safe_case_id(case_id):
    cleaned = re.sub(r"[^A-Za-z0-9_\-]", "-", case_id.strip())
    if not cleaned:
        raise ValueError("case_id 为空")
    return cleaned


def new_case_id():
    today = datetime.now().strftime("%Y%m%d")
    existing = [p.name for p in DATA_DIR.glob("RC-%s-*" % today)] if DATA_DIR.exists() else []
    return "RC-%s-%03d" % (today, len(existing) + 1)


def save_case(case_id, platform, ocr_text, result, image_bytes=None,
              image_filename=None, version=1):
    """把一个 case 存到 data/cases/<case_id>/：图片 + OCR + 检查结果 + RC 草稿。"""
    case_id = _safe_case_id(case_id)
    folder = DATA_DIR / case_id
    folder.mkdir(parents=True, exist_ok=True)
    if image_bytes:
        ext = Path(image_filename or "ad.png").suffix.lower() or ".png"
        if ext not in (".png", ".jpg", ".jpeg", ".webp"):
            ext = ".png"
        (folder / ("ad" + ext)).write_bytes(image_bytes)
    (folder / "ocr.txt").write_text(ocr_text, encoding="utf-8")
    (folder / "checks.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    report = render_report(case_id, platform, ocr_text, result, version=version)
    (folder / "report.md").write_text(report, encoding="utf-8")
    meta = {"case_id": case_id, "platform": platform, "version": version,
            "suggested_verdict": result["suggested_verdict"], "risk": result["risk"],
            "blockers": result["blockers"],
            "status": "草稿评审 — 待人工签核",
            "created_at": datetime.now().isoformat(timespec="seconds"),
            "history": [{"at": datetime.now().isoformat(timespec="seconds"),
                         "event": "创建 v%d，确定性检查 %d/%d 通过" %
                                  (version, len(result["checks"]) - len(result["failed"]),
                                   len(result["checks"]))}]}
    (folder / "case.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    return folder, meta


def load_case(case_id):
    folder = DATA_DIR / _safe_case_id(case_id)
    meta_path = folder / "case.json"
    if not meta_path.exists():
        return None, None
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    return folder, meta


def list_cases():
    if not DATA_DIR.exists():
        return []
    cases = []
    for meta_path in sorted(DATA_DIR.glob("*/case.json")):
        try:
            cases.append(json.loads(meta_path.read_text(encoding="utf-8")))
        except Exception:
            continue
    return sorted(cases, key=lambda c: c.get("created_at", ""), reverse=True)


def sign_off(case_id, reviewer, decision, note=""):
    """人工签核：只记录人的决定，不改系统建议值。"""
    folder, meta = load_case(case_id)
    if meta is None:
        raise ValueError("找不到 case：%s" % case_id)
    if decision not in ("不建议发布", "需修改后重审", "待补充资料"):
        raise ValueError("签核决定只能是：不建议发布 / 需修改后重审 / 待补充资料")
    meta["status"] = "已签核：%s（%s）" % (decision, reviewer)
    meta["signoff"] = {"reviewer": reviewer, "decision": decision, "note": note,
                       "at": datetime.now().isoformat(timespec="seconds")}
    meta["history"].append({"at": datetime.now().isoformat(timespec="seconds"),
                            "event": "%s 签核：%s%s" % (reviewer, decision,
                                                       " — " + note if note else "")})
    (folder / "case.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    return meta


if __name__ == "__main__":
    print("core.py 由 server.py / cli.py 调用，不直接运行。")
    print("用法示例：python3 system/cli.py review --ocr-text-file system/tests/fixtures/rc-20261104-001-ocr.txt")
    sys.exit(0)
