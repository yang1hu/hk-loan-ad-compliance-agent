#!/usr/bin/env python3
"""合规评审系统 · 网页版（只用 Python 标准库，零依赖、不用装任何东西）。

启动：
  python3 system/server.py            # 打开 http://localhost:8000
  python3 system/server.py --port 8080

能做的事（都在浏览器里点一点完成）：
  1. 新建 case：上传广告图 + 粘贴 OCR 转录文字（图上文字逐字抄下来）
  2. 系统自动跑第 1 层确定性检查（牌照号、热线、忠告、APR、推广日期、
     ^ 脚注、画板 / 水印）+ APR 月供反推，生成 RC 草稿报告
  3. 在 case 页查看结论、阻塞项、报告全文，人工签核（不建议发布 /
     需修改后重审 / 待补充资料），签核记录进历史
  4. 修改后的图重新上传，追加到同一 case 重审（v2、v3……）

不能做的事（有意不做）：
  - 不做 OCR：本机没有装 tesseract，网页也不会偷偷把图发给外部 OCR。
    转录请在 Marley 聊天里做（Marley 看图转录 + 逐行对账），
    或本机装好 tesseract 后再接进来；系统只对你粘贴的文字负责。
  - 不做 LLM 评审：A–H 里需要看画面、判误导的部分，系统只标「待评审」，
    由 Marley 或人工按 checklist 补全。
  - 不判「合规」：任何结论都只是草稿建议，最终必须人工签核。
  - 广告原图默认不进 Git：.gitignore 已忽略 *.png / *.jpg 和 data/，
    case 数据只存在本机 data/cases/。
"""
import argparse
import html
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

sys.path.insert(0, str(Path(__file__).resolve().parent))
import core  # noqa: E402

CSS = ("body{font-family:sans-serif;max-width:900px;margin:32px auto;padding:0 16px;"
       "line-height:1.7;color:#222} h1{font-size:22px} h2{font-size:18px} "
       "a{color:#1a5fb4} table{border-collapse:collapse;width:100%}"
       "td,th{border:1px solid #ccc;padding:6px 8px;text-align:left;font-size:14px}"
       ".fail{color:#b00020;font-weight:bold} .pass{color:#137333}"
       "textarea{width:100%;height:220px} input,select{padding:6px;margin:4px 0}"
       "button{padding:8px 16px;cursor:pointer} pre{background:#f6f6f6;padding:12px;"
       "white-space:pre-wrap;word-break:break-word} .warn{background:#fff4e0;"
       "border:1px solid #e0a800;padding:10px 12px}")


def page(title, body):
    return ("<!DOCTYPE html><html lang=\"zh-CN\"><head><meta charset=\"utf-8\">"
            "<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">"
            "<title>%s</title><style>%s</style></head><body>%s</body></html>"
            % (html.escape(title), CSS, body))


def parse_multipart(body, boundary):
    """最小 multipart 解析：只处理本系统表单（文字字段 + 一个图片文件）。"""
    fields, files = {}, {}
    for part in body.split(b"--" + boundary):
        if b"\r\n\r\n" not in part:
            continue
        head, data = part.split(b"\r\n\r\n", 1)
        if data.endswith(b"\r\n"):
            data = data[:-2]
        if b'name="' not in head:
            continue
        name = head.split(b'name="', 1)[1].split(b'"', 1)[0].decode()
        if b'filename="' in head:
            fn = head.split(b'filename="', 1)[1].split(b'"', 1)[0].decode()
            if fn:
                files[name] = (fn, data)
        else:
            fields[name] = data.decode("utf-8", "replace")
    return fields, files


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def _send(self, text, code=200, ctype="text/html; charset=utf-8"):
        data = text.encode("utf-8") if isinstance(text, str) else text
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        parsed = urlparse(self.path)
        path = unquote(parsed.path)
        if path == "/":
            self._send(page("合规评审系统", self._home()))
        elif path.startswith("/case/") and path.endswith("/image"):
            case_id = path.split("/")[2]
            folder, _ = core.load_case(case_id)
            if folder is None:
                return self._send("找不到 case", 404)
            for img in sorted(folder.glob("ad.*")):
                return self._send(img.read_bytes(), 200, "image/png")
            return self._send("该 case 没有上传图片", 404)
        elif path.startswith("/case/"):
            case_id = path.split("/")[2]
            folder, meta = core.load_case(case_id)
            if meta is None:
                return self._send("找不到 case：%s" % html.escape(case_id), 404)
            self._send(page("Case " + case_id, self._detail(folder, meta)))
        else:
            self._send("404", 404)

    def do_POST(self):
        parsed = urlparse(self.path)
        path = unquote(parsed.path)
        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length) if length else b""
        ctype = self.headers.get("Content-Type") or ""
        if "multipart/form-data" in ctype and "boundary=" in ctype:
            boundary = ctype.split("boundary=", 1)[1].strip().encode()
            fields, files = parse_multipart(body, boundary)
        else:
            fields = {k: v[0] for k, v in parse_qs(body.decode("utf-8", "replace")).items()}
            files = {}

        if path == "/cases":
            ocr_text = (fields.get("ocr_text") or "").strip()
            if not ocr_text:
                return self._send(page("缺少转录文字",
                    "<p>请先粘贴 OCR 转录文字（图上文字逐字抄下来，包括脚注、牌照号、热线、忠告）。</p>"
                    "<p><a href=\"/\">← 返回</a></p>"), 400)
            result = core.review(ocr_text)
            case_id = (fields.get("case_id") or "").strip() or core.new_case_id()
            image_bytes, image_filename = None, None
            if "image" in files:
                image_filename, image_bytes = files["image"]
            folder, meta = core.save_case(case_id, fields.get("platform") or "",
                                          ocr_text, result,
                                          image_bytes=image_bytes,
                                          image_filename=image_filename)
            self.send_response(303)
            self.send_header("Location", "/case/" + meta["case_id"])
            self.end_headers()
            return

        if path.startswith("/case/") and path.endswith("/signoff"):
            case_id = path.split("/")[2]
            try:
                core.sign_off(case_id, fields.get("reviewer") or "未署名",
                              fields.get("decision") or "", fields.get("note") or "")
            except ValueError as e:
                return self._send(page("签核失败", "<p>%s</p><p><a href=\"/case/%s\">← 返回</a></p>"
                                        % (html.escape(str(e)), html.escape(case_id))), 400)
            self.send_response(303)
            self.send_header("Location", "/case/" + case_id)
            self.end_headers()
            return

        self._send("404", 404)

    def _home(self):
        cases = core.list_cases()
        rows = ""
        for c in cases:
            rows += ("<tr><td><a href=\"/case/%s\">%s</a></td><td>v%d</td>"
                     "<td>%s</td><td>%s</td><td>%s</td></tr>"
                     % (html.escape(c["case_id"]), html.escape(c["case_id"]),
                        c["version"], html.escape(c["suggested_verdict"]),
                        html.escape(c["risk"]), html.escape(c["status"])))
        table = ("<table><tr><th>Case</th><th>版本</th><th>建议结论</th>"
                 "<th>风险</th><th>状态</th></tr>%s</table>" % rows) if rows else "<p>暂无 case，先新建一个。</p>"
        return ("<h1>香港贷款广告合规评审系统</h1>"
                "<p class=\"warn\">本系统只做草稿评审，不是法律认定。结论只有建议值，"
                "最终是否发布必须由人工合规负责人签字；系统永远不输出「合规 / 已批准」。</p>"
                "<h2>新建评审</h2>"
                "<form action=\"/cases\" method=\"post\" enctype=\"multipart/form-data\">"
                "Case 编号（留空自动生成 RC-YYYYMMDD-XXX）：<br>"
                "<input name=\"case_id\" size=\"30\"><br>"
                "使用场景：<input name=\"platform\" size=\"50\" "
                "value=\"Meta（Facebook / Instagram）及 Google\"><br>"
                "广告图（可选，存在本机，不进 Git）：<input type=\"file\" name=\"image\" accept=\"image/*\"><br>"
                "OCR 转录文字（必填，图上文字逐字抄下来，包括脚注、牌照号、热线、忠告）：<br>"
                "<textarea name=\"ocr_text\" placeholder=\"例如：借 5 万，每月供款低至 HK$805*……\"></textarea><br>"
                "<button type=\"submit\">开始评审</button></form>"
                "<h2>全部 Case</h2>%s" % table)

    def _detail(self, folder, meta):
        checks = {}
        report = ""
        checks_path = folder / "checks.json"
        report_path = folder / "report.md"
        if checks_path.exists():
            import json
            checks = json.loads(checks_path.read_text(encoding="utf-8"))
        if report_path.exists():
            report = report_path.read_text(encoding="utf-8")
        rows = ""
        for c in checks.get("checks", []):
            rows += ("<tr><td class=\"%s\">%s</td><td>%s</td><td>%s</td></tr>"
                     % ("pass" if c["passed"] else "fail",
                        "通过" if c["passed"] else "不通过",
                        html.escape(c["name"]), html.escape(c["detail"])))
        img = ""
        if list(folder.glob("ad.*")):
            img = "<p><img src=\"/case/%s/image\" style=\"max-width:100%%\"></p>" % html.escape(meta["case_id"])
        history = "".join("<li>%s — %s</li>" % (html.escape(h.get("at", "")),
                                                html.escape(h.get("event", "")))
                          for h in meta.get("history", []))
        apr_note = html.escape(checks.get("apr_check", {}).get("note", ""))
        return ("<p><a href=\"/\">← 全部 Case</a></p>"
                "<h1>%s v%d</h1>"
                "<p>建议结论：<b>%s</b>（风险 %s）· 状态：%s</p>"
                "<h2>阻塞项</h2><ul>%s</ul>"
                "<h2>确定性检查</h2><table><tr><th>结果</th><th>项目</th><th>说明</th></tr>%s</table>"
                "<h2>APR 反推</h2><p>%s</p>%s"
                "<h2>人工签核</h2>"
                "<form action=\"/case/%s/signoff\" method=\"post\">"
                "签核人：<input name=\"reviewer\"> "
                "决定：<select name=\"decision\"><option>不建议发布</option>"
                "<option>需修改后重审</option><option>待补充资料</option></select><br>"
                "备注：<input name=\"note\" size=\"50\"><br>"
                "<button type=\"submit\">提交签核</button></form>"
                "<h2>历史</h2><ul>%s</ul>"
                "<h2>RC 草稿报告</h2><pre>%s</pre>"
                % (html.escape(meta["case_id"]), meta["version"],
                   html.escape(meta["suggested_verdict"]), html.escape(meta["risk"]),
                   html.escape(meta["status"]),
                   "".join("<li>%s</li>" % html.escape(b) for b in meta.get("blockers", [])),
                   rows, apr_note, img, html.escape(meta["case_id"]), history,
                   html.escape(report)))


def main():
    parser = argparse.ArgumentParser(description="香港贷款广告合规评审系统（网页版）")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--host", default="127.0.0.1")
    args = parser.parse_args()
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    print("合规评审系统已启动：http://%s:%d" % (args.host, args.port))
    print("按 Ctrl+C 停止。数据存在 data/cases/（本机，不进 Git）。")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n已停止。")


if __name__ == "__main__":
    main()
