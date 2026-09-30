"""方針の参考資料を、読み取り申告と根拠の対応付きで保存する。"""

from .config import LoopError, nonempty


def validate_references(plan):
    references = plan.get("references", [])  # 旧方針は未登録として扱う。
    if not isinstance(references, list) or len(references) > 100:
        raise LoopError("referencesは最大100件の資料一覧です")
    identifiers = set()
    for ref in references:
        if not isinstance(ref, dict):
            raise LoopError("参考資料はオブジェクトです")
        for key in ("id", "source", "claim", "relevance"):
            nonempty(ref.get(key), f"参考資料の{key}")
        if ref["id"] in identifiers:
            raise LoopError("参考資料IDが重複しています")
        identifiers.add(ref["id"])
        if ref.get("status") not in ("unread", "read"):
            raise LoopError("参考資料のstatusはunread / readです（外部検証済みとは扱いません）")
        if ref["status"] == "read":
            for key in ("locator", "note"):
                nonempty(ref.get(key), f"読んだ箇所の{key}")
    for experiment in plan["experiments"]:
        ids = experiment.get("reference_ids", [])
        if not isinstance(ids, list) or any(not isinstance(x, str) for x in ids) or len(ids) != len(set(ids)):
            raise LoopError("reference_idsは重複しない資料ID一覧です")
        if set(ids) - identifiers:
            raise LoopError("未登録の参考資料IDです")
    return references


def report_lines(references):
    if not references:
        return ["構造化した参考資料は未登録です。先行情報は未検証として扱います。", ""]
    lines = ["readはAgentの読み取り申告です。出典の実在・内容・主張の妥当性は外部照合していません。", ""]
    for ref in references:
        label = "未読・未検証" if ref["status"] == "unread" else "読了申告・外部未検証"
        lines += [
            f"- {ref['id']} [{label}]: {ref['source']}",
            f"  対応する主張: {ref['claim']} / 関連性: {ref['relevance']}",
        ]
        if ref["status"] == "read":
            lines += [f"  箇所: {ref['locator']} / 読み取り根拠: {ref['note']}"]
    return lines + [""]
