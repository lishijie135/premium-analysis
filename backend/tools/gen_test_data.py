"""生成埋点测试数据 sample.xlsx（固定随机种子）。

约 90 个普通客户 × 2024-01 ~ 2026-07，另埋入种子客户：
- K_A001 连续环比降幅>30% 命中 A
- K_B001 单量连续下降命中 B
- K_C001 停投 3 个月命中 C
- K_D001 同比腰斩命中 D/E
- K_F001 同比翻倍命中 F/G
- K_H001 今年新增且逐月增长命中 H（monthly_growth=true）
- K_X001 仅 1 单干扰客户（必须不入任何 A~G 清单）

输出：backend/test_data/sample.xlsx
"""
import os
import random

import pandas as pd

SEED = 42
START_YEAR, START_MONTH = 2024, 1
END_YEAR, END_MONTH = 2026, 7

COLS = ["签单时间", "客户代码", "保费量", "出单量"]


def month_iter():
    y, m = START_YEAR, START_MONTH
    while (y, m) <= (END_YEAR, END_MONTH):
        yield y, m
        m += 1
        if m == 13:
            y, m = y + 1, 1


def label(y, m):
    return "%04d-%02d" % (y, m)


def main():
    random.seed(SEED)
    rows = []

    # 强制保证全局最大月为 2026-07
    rows.append([label(2026, 7), "C000", 8000.0, 2])

    # ---- 普通客户 C001~C090 ----
    all_months = list(month_iter())
    for i in range(1, 91):
        customer = "C%03d" % i
        # 随机活跃区间，部分月份随机缺失
        start = random.randint(0, len(all_months) - 6)
        end = random.randint(start + 3, len(all_months) - 1)
        for pos in range(start, end + 1):
            if random.random() < 0.25:
                continue
            y, m = all_months[pos]
            premium = round(random.uniform(1000, 50000), 2)
            policies = random.randint(1, 10)
            rows.append([label(y, m), customer, premium, policies])

    # ---- 种子客户 ----
    # K_A001：2026 连续环比下降 40%/50%/55%/60%；2025 仅 8~12 月有数据（避开 D/E 与 H）
    for m, p in [(1, 100000.0), (2, 60000.0), (3, 30000.0), (4, 13500.0), (5, 5400.0)]:
        rows.append([label(2026, m), "K_A001", p, 3])
    for m in range(8, 13):
        rows.append([label(2025, m), "K_A001", 20000.0, 2])

    # K_B001：2026 单量连续下降 8→4→1→0；保费持平避免命中 A；2025 仅 9~12 月
    for m, n in [(1, 8), (2, 4), (3, 1), (4, 0)]:
        rows.append([label(2026, m), "K_B001", 5000.0, n])
    for m in range(9, 13):
        rows.append([label(2025, m), "K_B001", 5000.0, 2])

    # K_C001：最后出单月 2026-04，距全局最大月 2026-07 间隔 3 个月命中 C
    rows.append([label(2026, 3), "K_C001", 5000.0, 2])
    rows.append([label(2026, 4), "K_C001", 5000.0, 2])
    for m in range(8, 13):
        rows.append([label(2025, m), "K_C001", 5000.0, 2])

    # K_D001：2025 年 1~7 月累计 98000/14 单，2026 年 1~7 月累计 28000/7 单 → 同比腰斩 D+E
    for m in range(1, 8):
        rows.append([label(2025, m), "K_D001", 14000.0, 2])
        rows.append([label(2026, m), "K_D001", 4000.0, 1])

    # K_F001：2025 年 1~7 月累计 35000/7 单，2026 年 1~7 月累计 84000/21 单 → 翻倍 F+G
    for m in range(1, 8):
        rows.append([label(2025, m), "K_F001", 5000.0, 1])
        rows.append([label(2026, m), "K_F001", 12000.0, 3])

    # K_H001：2025 年无任何记录，2026 年 1/3/5 月保费逐月增长 → H 且 monthly_growth=true
    for m, p, n in [(1, 3000.0, 1), (3, 6000.0, 2), (5, 9000.0, 3)]:
        rows.append([label(2026, m), "K_H001", p, n])

    # K_X001：仅 1 单干扰客户（2025 年），总单量 < 2 → 不参与 A~G；有 2025 记录 → 不入 H
    rows.append([label(2025, 6), "K_X001", 1000.0, 1])

    df = pd.DataFrame(rows, columns=COLS)
    df = df.sample(frac=1.0, random_state=SEED).reset_index(drop=True)

    out_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "test_data")
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, "sample.xlsx")
    df.to_excel(out_path, index=False, engine="openpyxl")
    print("已生成 %s，共 %d 行、%d 个客户" % (out_path, len(df), df["客户代码"].nunique()))


if __name__ == "__main__":
    main()
