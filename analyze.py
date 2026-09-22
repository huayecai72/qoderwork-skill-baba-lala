#!/usr/bin/env python3
"""
叭叭啦啦 v2 - 素材预处理脚本
从文章文本中提取结构化分析卡（JSON），作为写作skill的确定性输入。

用法：
    py analyze.py --input article.txt
    py analyze.py --input a.txt b.txt c.txt
    py analyze.py --text "直接粘贴的文本"
    py analyze.py --input article.txt --output card.json
"""

import argparse
import json
import re
import sys
import os
from pathlib import Path
from collections import Counter

# ============================================================
# 配置
# ============================================================

SCRIPT_DIR = Path(__file__).parent
BRAND_DICT_PATH = SCRIPT_DIR / "brand_dict.json"

# 数据点优先级排序
DATA_TYPE_PRIORITY = {"growth": 0, "decline": 1, "ratio": 2, "count": 3, "absolute": 4}

# 口吻决策关键词
CONTROVERSY_WORDS = ["卷", "死", "赌", "骗局", "割韭菜", "寒碜", "亏损", "暴跌", "崩", "内卷", "戒断"]

# 事件关键词
EVENT_KEYWORDS = {
    "618": ["618", "六一八"],
    "双11": ["双11", "双十一", "双11", "1111"],
    "年货节": ["年货节", "年货"],
    "38女王节": ["38", "女王节", "女神节", "妇女节"],
    "99大促": ["99大促", "99划算节"],
}

# 中文数字映射
CN_NUM_MAP = {
    "一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5,
    "六": 6, "七": 7, "八": 8, "九": 9, "十": 10,
    "百": 100, "千": 1000, "万": 10000, "亿": 100000000,
}


# ============================================================
# 工具函数
# ============================================================

def load_brand_dict():
    """加载品牌词典"""
    if BRAND_DICT_PATH.exists():
        with open(BRAND_DICT_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def get_context(text, pos, window=30):
    """提取匹配位置前后的上下文"""
    start = max(0, pos - window)
    end = min(len(text), pos + window)
    # 尽量在句子边界截断
    ctx = text[start:end]
    return ctx.strip()


def get_sentence_context(text, pos, window=80):
    """提取更长的句子级上下文"""
    start = max(0, pos - window)
    end = min(len(text), pos + window)
    ctx = text[start:end]
    # 尝试在句号/逗号边界截断
    for delim in ["。", "，", "；", "\n"]:
        idx = ctx.rfind(delim, 0, window // 2)
        if idx > 10:
            ctx = ctx[idx + 1:]
            break
    for delim in ["。", "，", "；", "\n"]:
        idx = ctx.find(delim, len(ctx) // 2)
        if idx > 0 and idx < len(ctx) - 5:
            ctx = ctx[:idx + 1]
            break
    return ctx.strip()


# ============================================================
# 提取模块
# ============================================================

def extract_data_points(text):
    """提取数据点：数字+单位+上下文"""
    points = []

    # 模式1：阿拉伯数字 + 单位
    pattern_num = re.compile(
        r'(\d+(?:\.\d+)?)\s*(%|百分之|亿|万|倍|个|家|款|件|元|块|天|年|月|周)'
    )
    # 模式2：同比/环比/增长/下降 + 数字
    pattern_change = re.compile(
        r'(同比|环比|增长|上涨|增加|下降|下跌|减少|暴涨|飙升|翻[了一]?)\s*'
        r'(?:了|约|近|超|达)?\s*(\d+(?:\.\d+)?)\s*(%|倍|万|亿|个|家)?'
    )
    # 模式3：中文数字表达
    pattern_cn = re.compile(
        r'(翻[了一]倍|翻[了两三]番|增长?近?成|三位数|双位数|半数|过半)'
    )

    seen_values = set()

    # 提取模式1
    for m in pattern_num.finditer(text):
        value = m.group(1) + m.group(2)
        if value in seen_values:
            continue
        seen_values.add(value)

        context = get_sentence_context(text, m.start())
        dtype = classify_data_point(m.group(2), context)
        points.append({
            "value": value,
            "context": context,
            "type": dtype,
            "position": m.start()
        })

    # 提取模式2（增长/下降类）
    for m in pattern_change.finditer(text):
        direction = m.group(1)
        num = m.group(2)
        unit = m.group(3) or "%"
        value = f"{num}{unit}"

        if value in seen_values:
            continue
        seen_values.add(value)

        context = get_sentence_context(text, m.start())
        dtype = "growth" if any(w in direction for w in ["增", "涨", "升", "翻", "飙", "暴涨"]) else "decline"
        points.append({
            "value": value,
            "context": context,
            "type": dtype,
            "position": m.start()
        })

    # 提取模式3（中文数字）
    for m in pattern_cn.finditer(text):
        value = m.group(1)
        if value in seen_values:
            continue
        seen_values.add(value)

        context = get_sentence_context(text, m.start())
        dtype = "growth"  # 中文数字表达通常是增长
        points.append({
            "value": value,
            "context": context,
            "type": dtype,
            "position": m.start()
        })

    # 按优先级排序：growth > decline > ratio > count > absolute
    points.sort(key=lambda p: DATA_TYPE_PRIORITY.get(p["type"], 9))

    # 去掉position字段（输出不需要）
    for p in points:
        del p["position"]

    return points[:10]  # 最多保留10个


def classify_data_point(unit, context):
    """根据单位和上下文分类数据点"""
    if unit in ["%", "百分之"]:
        if any(w in context for w in ["增长", "涨", "升", "翻", "同比"]):
            return "growth"
        elif any(w in context for w in ["下降", "跌", "减少"]):
            return "decline"
        return "ratio"
    elif unit in ["亿", "万", "元", "块"]:
        return "absolute"
    elif unit in ["个", "家", "款", "件"]:
        return "count"
    elif unit == "倍":
        return "growth"
    return "absolute"


def extract_brands(text, brand_dict):
    """提取品牌及其上下文"""
    brands = []
    seen = set()

    # 来源1：品牌词典匹镍
    all_brands = []
    for category, names in brand_dict.items():
        for name in names:
            all_brands.append((name, category))

    for name, category in all_brands:
        if name in seen:
            continue
        # 查找品牌名出现的位置
        idx = text.find(name)
        if idx == -1:
            continue
        seen.add(name)

        context = get_sentence_context(text, idx, window=100)

        # 判断是否有完整故事（做法+结果）
        has_number = bool(re.search(r'\d+(?:\.\d+)?[%亿万倍个家]?', context))
        has_result = any(w in context for w in [
            "第一", "TOP", "破亿", "增长", "成交", "冠军", "翻倍",
            "冲", "拿下", "做到", "成为", "达到", "突破"
        ])
        has_action = any(w in context for w in [
            "推出", "做了", "打造", "创新", "研发", "开创", "选择",
            "聚焦", "切入", "入驻", "布局"
        ])

        brands.append({
            "name": name,
            "category": category,
            "context": context,
            "has_full_story": has_number and (has_result or has_action)
        })

    # 按 has_full_story 排序（完整故事优先）
    brands.sort(key=lambda b: (not b["has_full_story"], -len(b["context"])))

    return brands[:8]  # 最多8个


def extract_time_contrast(text):
    """提取时间对比"""
    contrasts = []

    # 模式1：去年/以前/过去 vs 今年/现在/目前
    patterns = [
        r'(去年|前年|以前|过去|前几年|往年|从前)[^。]{5,60}?(今年|现在|目前|这一次|这一轮|如今)[^。]{5,60}',
        r'(今年|现在|目前|这一次)[^。]{5,60}?(而|但|却|不像)[^。]{0,20}(去年|以前|过去|往年)[^。]{5,60}',
    ]

    for pat in patterns:
        for m in re.finditer(pat, text):
            full = m.group(0)
            # 尝试分割before和after
            mid_words = ["今年", "现在", "目前", "这一次", "这一轮", "如今"]
            split_idx = -1
            for w in mid_words:
                idx = full.find(w, 5)  # 跳过开头
                if idx > 0:
                    split_idx = idx
                    break

            if split_idx > 0:
                before = full[:split_idx].strip()
                after = full[split_idx:].strip()
            else:
                before = full[:len(full)//2].strip()
                after = full[len(full)//2:].strip()

            contrasts.append({"before": before, "after": after})

    # 模式2：从A到B
    pattern_from_to = re.compile(r'从["""]?([^""""。，]{2,15})["""]?\s*(?:到|转向|切换|变成)\s*["""]?([^""""。，]{2,15})["""]?')
    for m in pattern_from_to.finditer(text):
        contrasts.append({
            "before": m.group(1).strip(),
            "after": m.group(2).strip()
        })

    # 模式3：不再是A而是B / 不是A而是B
    pattern_not_a_but_b = re.compile(r'不是["""]?([^""""。，]{2,20})["""]?[，,]?\s*(?:而是|是)\s*["""]?([^""""。，]{2,20})["""]?')
    for m in pattern_not_a_but_b.finditer(text):
        contrasts.append({
            "before": m.group(1).strip(),
            "after": m.group(2).strip()
        })

    # 去重并返回最显著的
    if not contrasts:
        return None

    # 优先返回长度适中、信息量大的
    contrasts.sort(key=lambda c: len(c["before"]) + len(c["after"]), reverse=True)
    return contrasts[0] if contrasts else None


def extract_core_tension(text):
    """提取核心矛盾"""
    tensions = []

    # 模式1：从A到B（短对立）
    # 排除动词补语误匹配（看到/想到/做到等）
    VERB_ENDINGS = set("看想做说走来到去听买卖打")
    pattern1 = re.compile(r'从["""]?([^""""。，\n]{2,12})["""]?\s*(?:到|转向|切换成|变成)\s*["""]?([^""""。，\n]{2,12})["""]?')
    for m in pattern1.finditer(text):
        a, b = m.group(1).strip(), m.group(2).strip()
        # 过滤无效匹镍
        if len(a) < 3 or len(b) < 3:
            continue
        if a == b:
            continue
        if a and a[-1] in VERB_ENDINGS:
            continue
        if "的" in a or b.startswith("的"):
            continue
        tensions.append(f"{a} vs {b}")

    # 模式2：不是A而是B
    pattern2 = re.compile(r'不是["""]?([^""""。，\n]{2,15})["""]?[，,]?\s*(?:而是|是)\s*["""]?([^""""。，\n]{2,15})["""]?')
    for m in pattern2.finditer(text):
        a, b = m.group(1).strip(), m.group(2).strip()
        if len(a) >= 2 and len(b) >= 2:
            tensions.append(f"{a} vs {b}")

    # 模式3：以前A现在B
    pattern3 = re.compile(r'(?:以前|过去|去年|从前)[^。]{0,5}?([^。，\n]{2,10})[^。]{0,30}?(?:现在|今年|如今|目前)[^。]{0,5}?([^。，\n]{2,10})')
    for m in pattern3.finditer(text):
        a, b = m.group(1).strip(), m.group(2).strip()
        if len(a) >= 2 and len(b) >= 2 and a != b:
            tensions.append(f"{a} vs {b}")

    if not tensions:
        return "旧模式 vs 新模式"  # 兜底

    # 取出现频率最高的
    counter = Counter(tensions)
    return counter.most_common(1)[0][0]


def detect_event(text):
    """识别事件类型"""
    for event, keywords in EVENT_KEYWORDS.items():
        for kw in keywords:
            if kw in text:
                return event
    return "日常"


def suggest_tone(text, data_points, brands):
    """建议口吻"""
    # 规则1：争议词
    controversy_count = sum(1 for w in CONTROVERSY_WORDS if w in text)
    if controversy_count >= 2:
        return "行业老炮"

    # 规则2：数据密度
    if len(data_points) >= 4:
        return "冷静分析师"

    # 规则3：品牌故事
    if brands and brands[0].get("has_full_story"):
        return "行业观察者"

    # 规则4：反常识/打脸
    if any(w in text for w in ["反常识", "没想到", "意外", "打脸", "颠覆"]):
        return "犀利评论员"

    return "行业观察者"  # 默认


def suggest_template(data_points, brands, time_contrast):
    """建议模板"""
    # 规则1：有时间对比 → 对比驱动
    if time_contrast and time_contrast.get("before") and time_contrast.get("after"):
        return "C_对比驱动"

    # 规则2：数据密集但品牌少 → 数据驱动
    if len(data_points) >= 3 and len([b for b in brands if b.get("has_full_story")]) < 2:
        return "A_数据驱动"

    # 规则3：有完整品牌故事 → 故事驱动
    if brands and brands[0].get("has_full_story"):
        return "B_故事驱动"

    return "A_数据驱动"  # 默认


# ============================================================
# 主流程
# ============================================================

def analyze(text, brand_dict):
    """主分析函数，输出分析卡"""
    data_points = extract_data_points(text)
    brands = extract_brands(text, brand_dict)
    time_contrast = extract_time_contrast(text)
    core_tension = extract_core_tension(text)
    event = detect_event(text)
    tone = suggest_tone(text, data_points, brands)
    template = suggest_template(data_points, brands, time_contrast)

    # 判断情绪倾向
    positive_words = ["增长", "突破", "爆发", "翻倍", "创新高", "回暖", "复苏"]
    negative_words = ["下降", "亏损", "暴跌", "萎缩", "内卷", "困境", "承压"]
    pos_count = sum(1 for w in positive_words if w in text)
    neg_count = sum(1 for w in negative_words if w in text)
    if pos_count > neg_count * 1.5:
        sentiment = "positive_shift"
    elif neg_count > pos_count * 1.5:
        sentiment = "negative_pressure"
    else:
        sentiment = "mixed_transition"

    card = {
        "event": event,
        "sentiment": sentiment,
        "data_points": data_points[:6],  # 输出最多6个
        "brands_mentioned": brands[:5],  # 输出最多5个
        "time_contrast": time_contrast,
        "core_tension": core_tension,
        "suggested_lock": "L2",  # 默认半锁，由skill根据用户prompt覆盖
        "suggested_tone": tone,
        "suggested_template": template,
        "stats": {
            "total_chars": len(text),
            "data_point_count": len(data_points),
            "brand_count": len(brands),
        }
    }

    return card


def main():
    parser = argparse.ArgumentParser(description="叭叭啦啦 v2 素材预处理脚本")
    parser.add_argument("--input", "-i", nargs="+", help="输入文本文件路径（可多个）")
    parser.add_argument("--text", "-t", help="直接输入文本")
    parser.add_argument("--output", "-o", help="输出JSON文件路径（默认打印到stdout）")
    parser.add_argument("--pretty", action="store_true", default=True, help="格式化JSON输出")
    args = parser.parse_args()

    # 读取输入
    texts = []
    if args.text:
        texts.append(args.text)
    elif args.input:
        for fpath in args.input:
            p = Path(fpath)
            if not p.exists():
                print(f"错误：文件不存在 - {fpath}", file=sys.stderr)
                sys.exit(1)
            with open(p, "r", encoding="utf-8") as f:
                texts.append(f.read())
    else:
        # 从stdin读取
        if not sys.stdin.isatty():
            texts.append(sys.stdin.read())
        else:
            parser.print_help()
            sys.exit(1)

    if not texts:
        print("错误：无输入内容", file=sys.stderr)
        sys.exit(1)

    # 合并文本（多篇时）
    combined_text = "\n\n".join(texts)

    # 加载品牌词典
    brand_dict = load_brand_dict()

    # 执行分析
    card = analyze(combined_text, brand_dict)

    # 输出
    indent = 2 if args.pretty else None
    output_json = json.dumps(card, ensure_ascii=False, indent=indent)

    if args.output:
        out_path = Path(args.output)
        with open(out_path, "w", encoding="utf-8") as f:
            f.write(output_json)
        print(f"分析卡已写入：{out_path}", file=sys.stderr)
    else:
        # Windows CMD下直接print中文可能报错，写入临时文件再输出
        try:
            print(output_json)
        except UnicodeEncodeError:
            tmp = Path(os.environ.get("TEMP", ".")) / "analysis_card.json"
            with open(tmp, "w", encoding="utf-8") as f:
                f.write(output_json)
            print(f"[UnicodeEncodeError] 已写入临时文件：{tmp}", file=sys.stderr)


if __name__ == "__main__":
    main()
