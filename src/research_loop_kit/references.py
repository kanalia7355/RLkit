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
        if ref.get("status") not in ("unread", "read", "content_checked"):
            raise LoopError("参考資料のstatusはunread / read / content_checkedです（外部検証済みとは扱いません）")
        if ref["status"] in ("read", "content_checked"):
            for key in ("locator", "note"):
                nonempty(ref.get(key), f"読んだ箇所の{key}")
        if ref["status"] == "content_checked":
            for key in ("snapshot_hash", "quote", "assessment", "conditions"):
                nonempty(ref.get(key), f"本文照合の{key}")
            if (
                ref["assessment"] not in ("supports", "conditional", "not_supported", "uncertain")
                or len(ref["quote"]) > 1000
            ):
                raise LoopError("出典の解釈判定または引用長が不正です")
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
    lines = [
        "readは読了申告、content_checkedは保存本文内の引用一致です。取得元の真正性・意味の妥当性は自動認証しません。",
        "",
    ]
    for ref in references:
        label = "未読・未検証" if ref["status"] == "unread" else "読了申告・外部未検証"
        if ref["status"] == "content_checked":
            label = "固定本文と引用箇所を照合済み・解釈はAgent申告"
        lines += [
            f"- {ref['id']} [{label}]: {ref['source']}",
            f"  対応する主張: {ref['claim']} / 関連性: {ref['relevance']}",
        ]
        if ref["status"] in ("read", "content_checked"):
            lines += [f"  箇所: {ref['locator']} / 読み取り根拠: {ref['note']}"]
        if ref["status"] == "content_checked":
            lines += [f"  本文版: `{ref['snapshot_hash']}` / 判定: {ref['assessment']} / 成立条件: {ref['conditions']}"]
    return lines + [""]


def register_source(root, path, origin, version):
    import hashlib
    from pathlib import PurePosixPath
    import time

    from .fsutil import no_links
    from .quality import relative_file
    from .store import digest

    nonempty(origin, "資料の出典")
    nonempty(version, "資料の版・取得条件")
    if (
        not isinstance(path, str)
        or not PurePosixPath(path).parts
        or PurePosixPath(path).parts[0] not in ("data", "imports")
    ):
        raise LoopError("資料本文はdata/またはimports/配下へ置いてください")
    source = relative_file(root, path)
    if source.stat().st_size > 2 * 1024 * 1024:
        raise LoopError("資料本文はUTF-8テキスト2MiB以内です")
    raw = source.read_bytes()
    if len(raw) > 2 * 1024 * 1024:
        raise LoopError("資料本文が上限を超えています")
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise LoopError("PDF等は原本を保持し、UTF-8本文を抽出して登録してください") from exc
    nonempty(text, "資料本文")
    sha = hashlib.sha256(raw).hexdigest()
    relative = f".rlk/reference-snapshots/{sha}.txt"
    target = root / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    no_links(target.parent, root)
    if target.exists():
        no_links(target, root)
        if target.read_bytes() != raw:
            raise LoopError("保存済み資料の本文が改変されています")
    else:
        with target.open("xb") as stream:
            stream.write(raw)
    record = {
        "snapshot": relative,
        "sha256": sha,
        "bytes": len(raw),
        "source_path": path,
        "origin": origin,
        "version": version,
        "retrieved_at": time.time(),
    }
    return {"hash": digest(record), "record": record}


def source_text(root, registration):
    import hashlib
    import re

    from .fsutil import no_links
    from .store import digest

    record = registration["record"]
    if (
        not isinstance(record.get("sha256"), str)
        or not re.fullmatch(r"[a-f0-9]{64}", record["sha256"])
        or registration["hash"] != digest(record)
        or record["snapshot"] != f".rlk/reference-snapshots/{record['sha256']}.txt"
    ):
        raise LoopError("資料の保存情報が不正です")
    path = root / record["snapshot"]
    no_links(path, root)
    raw = path.read_bytes()
    if len(raw) != record["bytes"] or hashlib.sha256(raw).hexdigest() != record["sha256"]:
        raise LoopError("資料本文のハッシュが一致しません")
    return raw.decode("utf-8").replace("\r\n", "\n")


def verify_references(root, plan, sources):
    validate_references(plan)
    for ref in plan.get("references", []):
        if ref.get("status") != "content_checked":
            continue
        registration = sources.get(ref["snapshot_hash"])
        if not registration or registration["hash"] != ref["snapshot_hash"]:
            raise LoopError("本文照合に使う資料の登録がありません")
        text = source_text(root, registration)
        if ref["quote"].replace("\r\n", "\n") not in text:
            raise LoopError("引用箇所が固定した本文にありません")
    return {
        ref["snapshot_hash"]: sources[ref["snapshot_hash"]]
        for ref in plan.get("references", [])
        if ref.get("status") == "content_checked"
    }
