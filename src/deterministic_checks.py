#!/usr/bin/env python3
"""
确定性检查（第 1 层）：OCR 文本 + 正则，不靠 LLM 猜。

用法：
  python3 src/deterministic_checks.py --text-file ocr.txt
  python3 src/deterministic_checks.py --text "忠告：借钱梗要还，咪俾钱中介 ..."

检查项：
- 忠告原文是否完整
- 牌照号、投诉热线是否出现
- APR 是否出现
- 推广日期是否出现
- *、^ 脚注符号是否有对应脚注文字
- 是否有画板 / 水印残留
"""
import argparse
import re
import sys


# 繁简归一：香港广告多为繁体，转录常为繁体，但检查用的关键词是简体。
# 若不先归一，繁体转录会把图上明明有的忠告、牌照、热线、APR 全误判成
# “未找到”（2026-11-06 网页版已因此出过 1/8 的误判，见 RC-20261106-001）。
# 只做字形归一，不改数字、符号和标点；原文本仍原样存入 case 供复核。
_TRAD_TO_SIMP = str.maketrans({
    "萬": "万", "實": "实", "際": "际", "貸": "贷", "額": "额",
    "達": "达", "時": "时", "廣": "广", "終": "终", "請": "请",
    "況": "况", "條": "条", "細": "细", "則": "则", "優": "优",
    "錢": "钱", "還": "还", "債": "债", "號": "号", "碼": "码",
    "詢": "询", "訴": "诉", "熱": "热", "線": "线", "畫": "画",
    "麼": "么", "個": "个", "發": "发", "獲": "获",
})


def normalize_text(text: str) -> str:
    """繁体 → 简体归一（仅覆盖贷款广告常见字），供检查与数字提取用。"""
    return text.translate(_TRAD_TO_SIMP)


WARNING_TEXT = "忠告：借钱梗要还，咪俾钱中介"
WARNING_TEXT_ALT = "忠告: 借钱梗要还，咪俾钱中介"

CHECKS = []


def check(name, passed, detail=""):
    CHECKS.append({"name": name, "passed": passed, "detail": detail})
    return passed


def run_checks(text: str):
    text = normalize_text(text)
    CHECKS.clear()
    # 忠告
    has_warning = WARNING_TEXT in text or WARNING_TEXT_ALT in text
    check("warning_present", has_warning, "忠告原文是否完整出现")

    # 牌照号：773/2026 这类格式
    m_license = re.search(r"放债人牌照号码[：:]\s*(\d+/\d{4})", text)
    check("license_present", bool(m_license), m_license.group(1) if m_license else "未找到牌照号")

    # 热线：8 位数字
    m_hotline = re.search(r"(查询及投诉热线|投诉热线)[：:]\s*(\d{8})", text)
    check("hotline_present", bool(m_hotline), m_hotline.group(2) if m_hotline else "未找到热线")

    # APR
    has_apr = bool(re.search(r"实际年利率", text)) and bool(re.search(r"\d+(\.\d+)?%", text))
    check("apr_present", has_apr, "是否出现实际年利率及百分比")

    # 推广日期：2026 年 X 月 X 日 / 2026-01-01 这类
    has_promo_date = bool(re.search(r"20\d{2}年\s*\d+月\s*\d+日", text)) or bool(
        re.search(r"推广期[：:].*20\d{2}", text)
    )
    check("promo_date_present", has_promo_date, "限时推广是否有起止日期")

    # 脚注符号对应：图上有 ^，但脚注里没有 ^ 开头的段落
    has_caret_in_body = "^" in text
    has_caret_footnote = bool(re.search(r"\^\s*优惠|^\^", text, re.M))
    if has_caret_in_body and not has_caret_footnote:
        check("caret_footnote_present", False, "图上有 ^，但未找到 ^ 对应的脚注文字")
    else:
        check("caret_footnote_present", True, "无 ^ 或已有 ^ 脚注")

    # 残留
    has_artboard = bool(re.search(r"画板\s*\d+|Artboard", text))
    check("no_artboard_residual", not has_artboard, "是否有画板残留")
    has_watermark = "Sonic.Peng" in text or "水印" in text.lower()
    check("no_watermark", not has_watermark, "是否有设计水印残留")

    return CHECKS


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--text-file", default=None)
    parser.add_argument("--text", default=None)
    args = parser.parse_args()

    if args.text_file:
        with open(args.text_file, encoding="utf-8") as f:
            text = f.read()
    elif args.text:
        text = args.text
    else:
        text = sys.stdin.read()

    results = run_checks(text)
    failed = [r for r in results if not r["passed"]]
    for r in results:
        print(f"{'PASS' if r['passed'] else 'FAIL'}  {r['name']}: {r['detail']}")
    print(f"\n{len(results) - len(failed)}/{len(results)} 通过")
    if failed:
        print("阻塞项：", ", ".join(r["name"] for r in failed))
        sys.exit(1)


if __name__ == "__main__":
    main()
