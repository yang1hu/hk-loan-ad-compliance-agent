---
name: hk-loan-ad-compliance
description: Review Hong Kong money lender loan static ads (Meta / Google) for compliance. Use when the user asks to review a loan ad image, check APR / rebate / warning prominence, or produce an RC-format report. Outputs a draft for human compliance sign-off only, never a legal approval.
---

# 香港贷款广告合规评审

## 适用范围

- 香港放债人贷款静态广告（Meta / Google）
- 输入：一张广告图 + 可选的产品计算表 / 活动条款 / 过去 RC 案例
- 输出：按 `templates/RC-template.md` 的 RC 格式报告

## 不适用

- 账户表现审计（追踪、出价、创意疲劳）——那是 claude-ads / Paid Media Auditor 的事
- 美国 SEC / FINRA 投资营销合规——不要直接套用 Anthropic compliance skill 的美国条款
- 任何“已合规 / 已批准”的结论——本 skill 永远不输出

## 工作流

### 第 1 步：转录，不要猜

把图上所有文字逐字抄下来，包括：
- 主文案、金额、利率、期数、回赠、优惠码
- 脚注（*、^ 等符号分别对应哪段文字）
- 底栏：公司名、牌照号、热线、忠告
- 画面残留：画板名、水印、裁切残边

### 第 2 步：跑确定性检查

运行 `src/deterministic_checks.py`，检查：
- 忠告原文是否完整：`忠告：借钱梗要还，咪俾钱中介`
- 牌照号、热线是否出现
- APR 是否出现
- 推广日期是否出现
- *、^ 等脚注符号是否有对应文字（例如 80,000^ 有没有 ^ 脚注）
- 是否有“画板”“水印”等残留词

跑 `src/apr.py` 反推：给定本金、APR、月供，算出对应期数，判断是否常规期限（60 / 72 期等）。没有计算底稿，就写无法验证。

### 第 3 步：按 checklist 逐条审

读 `checklist/hk-checklist.md`，按 A–H 逐条写：
- 原文（照抄图上文字）
- 判定：符合 / 不符合 / 存疑 / 需人工判断
- 原因（引原始条款，不引二手总结）
- 建议改写（给模板，不编数字，数字留 [XX] 待产品表验证）

### 第 4 步：输出报告

按 `templates/RC-template.md` 输出：
1. 整体结论：不建议发布 / 需修改后重审，风险等级：高 / 中 / 低
2. 逐条问题 A–H
3. 主要依据
4. 发布前必改清单

结论只有两种，不写“合规”。最后加一句：最终仍须由人工合规负责人签核。

## 硬规则

- 不确定就写“无法确认，需源档 / 计算底稿 / 注册处复核”，不许估字号、编色值、编期数。
- 字体大小、颜色一致性不能从位图量出准确值，必须看源文件。
- 牌照有效性、公司法定名称、热线是否为投诉热线，不能从图上核实。
- 回赠、月供、APR 三者关系不清时，判“不符合 / 存疑”，不要替广告方补逻辑。
- 现金回赠金额大于主推借款额时，单独标高风险。
- 图上完全没有利率信息时，单独标高风险（只讲好处，不讲成本）。
