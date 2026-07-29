#!/usr/bin/env python3
"""按 fake_credit_limit_model.csv 字段格式生成假数据，并对实际授信额度做等频 10 分箱。"""

from __future__ import annotations

import argparse
import random
from pathlib import Path

import pandas as pd

NAME_PREFIXES = [
    "金鼎", "星河", "汇通", "华信", "创元", "博雅", "永泰", "宏达", "瑞丰",
    "远航", "盛世", "天成", "鼎盛", "中原", "华泰", "联创", "启明", "嘉禾",
]
INDUSTRIES = [
    "建设", "环保", "材料", "物流", "网络", "智能", "医药", "能源", "电子",
    "机械", "科技", "贸易", "化工", "食品", "纺织", "装备", "信息", "生物",
]
COMPANY_TYPES = [
    "有限公司", "集团有限公司", "有限责任公司", "股份有限公司",
]
LEADER_LEVELS = ["国家级", "省级", "市级", "县级"]
PROFIT_CANDIDATES = [
    -2323432, 343434, 6767, 676767, 565, -3434545, 5656, 565656,
]

BASE_COLUMNS = [
    "企业名称",
    "统代",
    "科技标签_高新技术产业",
    "是否国企",
    "龙头企业级别",
    "2022从业人数",
    "2023从业人数",
    "2024从业人数",
    "2022利润总额",
    "2024资产总收入",
    "2024负债总数",
    "2024资产负债率",
    "实际授信额度",
]


def maybe_empty(value, empty_rate: float, rng: random.Random):
    if rng.random() < empty_rate:
        return ""
    return value


def random_credit_code(rng: random.Random) -> str:
    """生成贴近样本的统代科学计数法字符串，如 9.1321e+017。"""
    # 样本形态：9.13xxxxe+017 / 9.1321000000000013e+017
    frac_len = rng.randint(2, 14)
    frac = "".join(str(rng.randint(0, 9)) for _ in range(frac_len))
    return f"9.13{frac}e+017"


def random_company_name(index: int, rng: random.Random) -> str:
    name = (
        f"{rng.choice(NAME_PREFIXES)}"
        f"{rng.choice(INDUSTRIES)}"
        f"{rng.choice(COMPANY_TYPES)}"
        f"{index:06d}"
    )
    return name


def generate_rows(n: int, seed: int) -> pd.DataFrame:
    rng = random.Random(seed)
    rows = []
    for i in range(n):
        staff = [
            maybe_empty(rng.randint(1, 7), 0.15, rng),
            maybe_empty(rng.randint(1, 7), 0.15, rng),
            maybe_empty(rng.randint(1, 7), 0.15, rng),
        ]
        credit = rng.randrange(50, 35001, 10)
        assets = rng.randint(100_000, 50_000_000)
        liabilities = max(1, int(assets * rng.uniform(0.05, 0.95)))
        ratio = round(liabilities / assets, 4)
        rows.append(
            {
                "企业名称": random_company_name(i, rng),
                "统代": random_credit_code(rng),
                "科技标签_高新技术产业": maybe_empty(rng.choice(["0", "1"]), 0.10, rng),
                "是否国企": maybe_empty(rng.choice(["0", "1"]), 0.10, rng),
                "龙头企业级别": maybe_empty(rng.choice(LEADER_LEVELS), 0.15, rng),
                "2022从业人数": staff[0],
                "2023从业人数": staff[1],
                "2024从业人数": staff[2],
                "2022利润总额": rng.choice(PROFIT_CANDIDATES),
                "2024资产总收入": assets,
                "2024负债总数": liabilities,
                "2024资产负债率": ratio,
                "实际授信额度": credit,
            }
        )

    df = pd.DataFrame(rows, columns=BASE_COLUMNS)
    bins = pd.qcut(df["实际授信额度"], q=10, duplicates="drop")
    df["实际授信额度区间"] = bins.astype(str)
    return df


def parse_args() -> argparse.Namespace:
    script_dir = Path(__file__).resolve().parent
    parser = argparse.ArgumentParser(description="生成授信额度模型假数据 CSV")
    parser.add_argument("--n", type=int, default=10000, help="生成行数，默认 10000")
    parser.add_argument("--seed", type=int, default=42, help="随机种子")
    parser.add_argument(
        "--out",
        type=Path,
        default=script_dir / "fake_credit_limit_model_10000.csv",
        help="输出 CSV 路径",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    df = generate_rows(args.n, args.seed)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(args.out, index=False, encoding="utf-8-sig")
    print(f"已生成 {len(df)} 条 -> {args.out}")
    print("实际授信额度区间分布:")
    print(df["实际授信额度区间"].value_counts().sort_index().to_string())


if __name__ == "__main__":
    main()
