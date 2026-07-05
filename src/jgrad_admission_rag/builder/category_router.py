from __future__ import annotations

from collections import Counter

from .chunker import TextChunk

CATEGORY_KEYWORDS = {
    "english": ["TOEFL", "TOEIC", "IELTS", "英語", "外部試験", "スコア"],
    "fees": ["検定料", "入学検定料", "支払", "クレジット", "振込", "円", "免除"],
    "documents": ["提出書類", "出願書類", "証明書", "志願票", "推薦書", "成績証明", "卒業証明"],
    "periods": ["出願期間", "提出期限", "締切", "必着", "消印有効", "登録期間"],
    "exams": ["試験", "口述", "筆答", "面接", "合格発表", "受験票"],
    "methods": ["出願方法", "郵送", "オンライン", "インターネット出願", "持参", "宛名"],
}

FOCUS_INSTRUCTIONS = {
    "english": "只抽取英语外部考试要求。填写 english_requirements；无关字段保持空。若未找到英语要求，返回空列表，不要输出英文 warning。请拆分 accepted_variants、rejected_variants、institution_code、applicable_to、exceptions。",
    "fees": "只抽取检定料、支付方式、免除条件。填写 fees；无关字段保持空。若未找到费用信息，返回空列表，不要输出英文 warning。",
    "documents": "只抽取提交材料、份数、指定格式、提交条件。填写 required_documents；无关字段保持空。若未找到材料信息，返回空列表，不要输出英文 warning。",
    "periods": "只抽取出愿期间、提交期限、必着/消印有效规则。填写 application_periods；无关字段保持空。若未找到期限信息，返回空列表，不要输出英文 warning。",
    "exams": "只抽取考试日程、合格发表、受验票、地点。填写 exam_schedules；无关字段保持空。若未找到考试日程，返回空列表，不要输出英文 warning。",
    "methods": "只抽取出愿方式、提交方式、邮寄地址、线上注册规则。填写 submission_methods；无关字段保持空。若未找到提交方式，返回空列表，不要输出英文 warning。",
    "general": "只抽取文本中明确写出的招生信息。无关文本不要输出 warning；所有 warning 必须用中文。",
}


def categorize_chunk(chunk: TextChunk) -> str:
    text = f"{chunk.title}\n{chunk.text}"
    scores: Counter[str] = Counter()
    for category, keywords in CATEGORY_KEYWORDS.items():
        for keyword in keywords:
            if keyword in text:
                scores[category] += 1
    if not scores:
        return "general"
    return scores.most_common(1)[0][0]


def focus_instruction(category: str) -> str:
    return FOCUS_INSTRUCTIONS.get(category, FOCUS_INSTRUCTIONS["general"])


def category_counts(chunks: list[TextChunk]) -> dict[str, int]:
    counts: Counter[str] = Counter(categorize_chunk(chunk) for chunk in chunks)
    return dict(sorted(counts.items()))
