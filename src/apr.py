#!/usr/bin/env python3
"""
APR / 月供反推校验。

给定本金、APR、月供，算出对应期数，判断是否常规期限。
没有计算底稿时，用这个工具验证广告上的数字是否自洽。

示例：
  python3 src/apr.py --principal 50000 --apr 0.0115 --monthly 805
  # 50000 本金、1.15% APR、月供 805，约对应 64 个月，不是常规 60 / 72 期

  python3 src/apr.py --principal 50000 --apr 0.0115 --months 60
  # 60 期月供约 857.92
"""
import argparse
import math


def monthly_payment(principal: float, apr: float, months: int) -> float:
    r = apr / 12
    if r == 0:
        return principal / months
    return principal * r * (1 + r) ** months / ((1 + r) ** months - 1)


def implied_months(principal: float, apr: float, monthly: float) -> float:
    r = apr / 12
    # monthly = P * r*(1+r)^n / ((1+r)^n - 1)
    # 解 n：令 x = (1+r)^n，则 monthly = P*r*x/(x-1) -> x = monthly / (monthly - P*r)
    if monthly <= principal * r:
        return float("inf")
    x = monthly / (monthly - principal * r)
    return math.log(x) / math.log(1 + r)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--principal", type=float, required=True)
    parser.add_argument("--apr", type=float, required=True, help="例如 1.15% 写 0.0115")
    parser.add_argument("--monthly", type=float, default=None)
    parser.add_argument("--months", type=int, default=None)
    args = parser.parse_args()

    if args.monthly is not None:
        n = implied_months(args.principal, args.apr, args.monthly)
        print(f"本金 HK${args.principal:,.0f}，APR {args.apr*100:.2f}%，月供 HK${args.monthly:,.0f}")
        print(f"反推期数约 {n:.1f} 个月")
        for m in (12, 24, 36, 48, 60, 72, 84):
            print(f"  {m} 期月供约 HK${monthly_payment(args.principal, args.apr, m):,.2f}")
        if abs(n - round(n)) < 0.5 and round(n) not in (12, 24, 36, 48, 60, 72, 84):
            print("提示：反推期数不是常规期限，需产品计算表验证。")
    if args.months is not None:
        pay = monthly_payment(args.principal, args.apr, args.months)
        print(f"本金 HK${args.principal:,.0f}，APR {args.apr*100:.2f}%，{args.months} 期")
        print(f"月供约 HK${pay:,.2f}，总还款约 HK${pay*args.months:,.2f}，总利息约 HK${pay*args.months-args.principal:,.2f}")


if __name__ == "__main__":
    main()
