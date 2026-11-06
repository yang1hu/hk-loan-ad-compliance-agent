#!/usr/bin/env python3
"""合规评审系统 · 命令行版（不用开网页也能跑全流程）。

用法：
  python3 system/cli.py review --ocr-text-file system/tests/fixtures/rc-20261104-001-ocr.txt
  python3 system/cli.py review --ocr-text-file ocr.txt --image ad.png --case-id RC-20261104-001
  python3 system/cli.py list
  python3 system/cli.py signoff --case-id RC-20261106-001 --reviewer "合规同事" --decision "不建议发布" --note "缺计算底稿"
  python3 system/cli.py show --case-id RC-20261106-001
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import core  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description="香港贷款广告合规评审系统（CLI）")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("review", help="评审一张广告：跑确定性检查 + APR 反推 + 生成 RC 草稿")
    p.add_argument("--ocr-text-file", required=True, help="OCR 转录文本文件")
    p.add_argument("--image", default=None, help="广告原图（png/jpg），会随 case 一起存到 data/cases/")
    p.add_argument("--case-id", default=None, help="默认自动生成 RC-YYYYMMDD-XXX")
    p.add_argument("--platform", default="Meta（Facebook / Instagram）及 Google")

    sub.add_parser("list", help="列出全部 case")
    p = sub.add_parser("show", help="查看一个 case 的结论和阻塞项")
    p.add_argument("--case-id", required=True)
    p = sub.add_parser("signoff", help="人工签核（只记录人的决定）")
    p.add_argument("--case-id", required=True)
    p.add_argument("--reviewer", required=True)
    p.add_argument("--decision", required=True, choices=["不建议发布", "需修改后重审", "待补充资料"])
    p.add_argument("--note", default="")

    args = parser.parse_args()

    if args.cmd == "review":
        ocr_text = Path(args.ocr_text_file).read_text(encoding="utf-8")
        result = core.review(ocr_text)
        case_id = args.case_id or core.new_case_id()
        image_bytes = Path(args.image).read_bytes() if args.image else None
        folder, meta = core.save_case(case_id, args.platform, ocr_text, result,
                                      image_bytes=image_bytes,
                                      image_filename=args.image)
        print("Case：%s" % meta["case_id"])
        print("建议结论：%s（风险 %s）" % (meta["suggested_verdict"], meta["risk"]))
        print("确定性检查：%d/%d 通过" %
              (len(result["checks"]) - len(result["failed"]), len(result["checks"])))
        for c in result["failed"]:
            print("  不通过 %s：%s" % (c["name"], c["detail"]))
        print("APR 反推：%s" % result["apr_check"]["note"])
        print("已保存：%s" % folder)
        print("报告：%s/report.md（草稿，最终须人工签核）" % folder)
        return 0

    if args.cmd == "list":
        cases = core.list_cases()
        if not cases:
            print("暂无 case。先跑：python3 system/cli.py review --ocr-text-file <ocr.txt>")
            return 0
        for c in cases:
            print("%s  v%d  %s（风险 %s）  %s" %
                  (c["case_id"], c["version"], c["suggested_verdict"], c["risk"], c["status"]))
        return 0

    if args.cmd == "show":
        folder, meta = core.load_case(args.case_id)
        if meta is None:
            print("找不到 case：%s" % args.case_id)
            return 1
        print("%s  v%d" % (meta["case_id"], meta["version"]))
        print("建议结论：%s（风险 %s）" % (meta["suggested_verdict"], meta["risk"]))
        print("状态：%s" % meta["status"])
        print("阻塞项：")
        for b in meta["blockers"]:
            print("  - %s" % b)
        print("报告：%s/report.md" % folder)
        return 0

    if args.cmd == "signoff":
        meta = core.sign_off(args.case_id, args.reviewer, args.decision, args.note)
        print("%s 已签核：%s（%s）" % (meta["case_id"], args.decision, args.reviewer))
        return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
