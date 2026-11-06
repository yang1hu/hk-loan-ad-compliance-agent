# hk-loan-ad-compliance-agent

香港放债人贷款广告合规评审 Agent（私有仓库）

适用场景：Meta（Facebook / Instagram）及 Google 香港贷款静态广告图片评审。
法律依据：《放债人条例》（第 163 章）及公司注册处《附加及经修订的发牌条件》第 9 条等。

> **重要声明：本项目只做草稿评审，不是法律认定。**
> 输出结论只有两种：`不建议发布` / `需修改后重审`。
> 最终是否发布，必须由人工合规负责人签字。本项目永远不输出“合规 / 已批准 / 合法”等结论。

## 工作流：三层，不是纯 LLM

1. **第 1 层 — 确定性检查（代码）**
   `src/deterministic_checks.py`：OCR 文本 + 正则，检查牌照号、投诉热线、忠告原文、APR 是否出现、推广日期、脚注符号是否对应、水印 / 画板残留。
   能从图上直接确认的，就不要靠 LLM 猜。

2. **第 2 层 — LLM 多模态评审**
   `prompts/review-prompt.md` + `checklist/hk-checklist.md`：按 A–H 逐条审，列原文、原因、建议改写。
   不确定的一定要写“无法确认，需源档 / 计算底稿 / 注册处复核”，不许编数字、不许估字号。

3. **第 3 层 — 人工签核**
   按 `templates/RC-template.md` 出报告，修改后追加到同一 case 重审。

## 目录结构

```
.
├── README.md
├── SKILL.md                  # Claude Code skill 入口
├── checklist/
│   └── hk-checklist.md       # 香港版 A–H 检查清单
├── prompts/
│   └── review-prompt.md      # LLM 评审提示词
├── src/
│   ├── deterministic_checks.py
│   └── apr.py                # APR / 月供反推校验
├── templates/
│   └── RC-template.md        # 报告模板
├── knowledge/
│   └── licensing-conditions-condition9.md
├── tests/
│   └── golden/               # 黄金测试集（已人工审过的案例）
└── examples/
    └── README.md
```

## 系统：能跑起来的评审工具

不只有 md 文档，还有一个可运行的系统，见 `system/README.md`：

```bash
# 网页版（推荐）
python3 system/server.py        # 打开 http://localhost:8000
# 命令行版
python3 system/cli.py review --ocr-text-file system/tests/fixtures/rc-20261104-001-ocr.txt
```

网页版：上传广告图 + 粘贴转录文字 → 自动跑第 1 层确定性检查 +
APR 反推 → 生成 RC 草稿报告 → 建档、留历史、人工签核，改完图追加到
同一 case 重审。零依赖（只用 Python 标准库），不用 API key，不联网，
原图和 case 数据只存在本机 `data/cases/`，不进 Git。
自测：`python3 system/tests/test_system.py`（已验证与人工 RC-20261104-001 v1
结论一致：不建议发布，风险高）。

## 快速使用（只用规则和脚本）

```bash
# 1. 确定性检查（需要先 OCR，见 src/deterministic_checks.py 的说明）
python3 src/deterministic_checks.py --text-file ocr.txt --image ad.png

# 2. APR / 月供反推
python3 src/apr.py --principal 50000 --apr 0.0115 --monthly 805

# 3. LLM 评审
# 把图片 + prompts/review-prompt.md + checklist/hk-checklist.md 一起交给模型，
# 按 templates/RC-template.md 输出。
```

## 黄金测试集

`tests/golden/` 里是已人工审过的案例，用于对比纯 LLM、RAG + 确定性检查的效果：
- 阻塞项召回率
- 误报率
- 引用是否正确（每条发现是否引到原始条款）

## 知识库要求

按条款分块，不要整本 PDF 丢进去。每个块要带来源 + 版本日期，例如：
- 牌照条件指引 第 9 条（广告须公正合理、不含误导；须含投诉热线及指定忠告，且显著易读）
- 《放债人条例》附表 2（真正年利率计算方法）
- 消委会建议（不得轻率化借贷、APR 展示方式等）
- Meta / Google 各版位尺寸规范
- 内部资料：产品计算表、过去 RC 案例、内部固定免责版本

## 免责

本项目不提供法律意见。广告发布前请以最新官方文本及公司合规负责人意见为准。
