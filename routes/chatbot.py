from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from flask import (
    Blueprint,
    Response,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    session,
    stream_with_context,
    url_for,
)
from sqlalchemy import inspect
from werkzeug.utils import secure_filename

from config.database import db
from models.tables import ChatbotDocument, ChatMessage, User
from services.chatbot import get_chatbot_service

bp = Blueprint("chatbot", __name__)

_chat_table_ready = False
_doc_table_ready = False


def _ensure_chat_table() -> None:
    global _chat_table_ready
    if _chat_table_ready:
        return

    inspector = inspect(db.engine)
    if ChatMessage.__tablename__ not in inspector.get_table_names():
        ChatMessage.__table__.create(bind=db.engine, checkfirst=True)

    _chat_table_ready = True


def _ensure_chatbot_doc_table() -> None:
    global _doc_table_ready
    if _doc_table_ready:
        return

    inspector = inspect(db.engine)
    if ChatbotDocument.__tablename__ not in inspector.get_table_names():
        ChatbotDocument.__table__.create(bind=db.engine, checkfirst=True)

    _doc_table_ready = True


def _admin_guard():
    if not session.get("is_admin"):
        return redirect(url_for("auth.dashboard_login"))
    return None


def _get_authenticated_user_id() -> int | None:
    user_id = session.get("user_id")
    if not user_id:
        return None

    user = User.query.filter_by(UserID=user_id, IsDelete=False).first()
    return user.UserID if user else None


def _serialize_history_rows(rows: list[ChatMessage]) -> list[dict[str, Any]]:
    messages: list[dict[str, Any]] = []
    for row in rows:
        metadata = None
        if row.Metadata:
            try:
                metadata = json.loads(row.Metadata)
            except json.JSONDecodeError:
                metadata = None

        messages.append(
            {
                "sender": "user" if row.Role == "user" else "bot",
                "text": row.Message,
                "timestamp": row.CreatedAt.isoformat() if row.CreatedAt else None,
                "sources": (metadata or {}).get("products", []),
            }
        )
    return messages


def _load_user_history(user_id: int, limit: int = 40) -> list[dict[str, Any]]:
    rows = (
        ChatMessage.query.filter_by(UserID=user_id)
        .order_by(ChatMessage.CreatedAt.asc())
        .limit(limit)
        .all()
    )
    return _serialize_history_rows(rows)


def _persist_user_turn(
    user_id: int,
    user_text: str,
    bot_text: str,
    products: list[dict[str, Any]],
) -> None:
    user_msg = ChatMessage(
        UserID=user_id,
        Role="user",
        Message=user_text,
        Metadata=None,
    )
    bot_msg = ChatMessage(
        UserID=user_id,
        Role="assistant",
        Message=bot_text,
        Metadata=json.dumps({"products": products}, ensure_ascii=False),
    )
    db.session.add(user_msg)
    db.session.add(bot_msg)
    db.session.commit()


def _append_guest_history(
    user_text: str, bot_text: str, products: list[dict[str, Any]]
) -> None:
    guest_history = session.get("guest_chat_history", [])
    timestamp = datetime.utcnow().isoformat()
    guest_history.append(
        {
            "sender": "user",
            "text": user_text,
            "timestamp": timestamp,
            "sources": [],
        }
    )
    guest_history.append(
        {
            "sender": "bot",
            "text": bot_text,
            "timestamp": timestamp,
            "sources": products,
        }
    )
    # Keep the latest 40 messages in current guest session only.
    session["guest_chat_history"] = guest_history[-40:]
    session.modified = True


@bp.route("/admin/chatbot-documents", methods=["GET"])
def admin_chatbot_docs():
    denied = _admin_guard()
    if denied:
        return denied

    _ensure_chatbot_doc_table()

    documents = (
        ChatbotDocument.query.filter_by(IsDelete=False)
        .order_by(ChatbotDocument.UpdatedAt.desc())
        .all()
    )
    return render_template(
        "backend/pages/chatbot/documents.html",
        documents=documents,
    )


@bp.route("/admin/chatbot-documents/add", methods=["POST"])
def admin_add_chatbot_doc():
    denied = _admin_guard()
    if denied:
        return denied

    _ensure_chatbot_doc_table()

    title = (request.form.get("title") or "").strip()
    content = (request.form.get("content") or "").strip()

    source_type = "manual"
    source_name = None

    file = request.files.get("doc_file")
    if file and file.filename:
        filename = secure_filename(file.filename)
        ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
        if ext not in {"txt", "md", "markdown"}:
            flash("Chỉ hỗ trợ file .txt, .md, .markdown", "error")
            return redirect(url_for("chatbot.admin_chatbot_docs"))
        try:
            content = file.read().decode("utf-8", errors="ignore").strip()
        except Exception:
            content = ""
        if not title:
            title = filename
        source_type = "file"
        source_name = filename

    if not title:
        flash("Vui lòng nhập tiêu đề tài liệu.", "error")
        return redirect(url_for("chatbot.admin_chatbot_docs"))

    if not content:
        flash("Nội dung tài liệu đang trống.", "error")
        return redirect(url_for("chatbot.admin_chatbot_docs"))

    try:
        row = ChatbotDocument(
            Title=title,
            Content=content,
            SourceType=source_type,
            SourceName=source_name,
            CreatedBy=session.get("admin_id"),
            IsDelete=False,
        )
        db.session.add(row)
        db.session.commit()

        get_chatbot_service().invalidate_knowledge_base(clear_disk=True)
        flash("Đã thêm tài liệu chatbot thành công.", "success")
    except Exception as exc:
        db.session.rollback()
        flash(f"Lỗi khi thêm tài liệu: {exc}", "error")

    return redirect(url_for("chatbot.admin_chatbot_docs"))


@bp.route("/admin/chatbot-documents/<int:doc_id>/delete", methods=["POST"])
def admin_delete_chatbot_doc(doc_id: int):
    denied = _admin_guard()
    if denied:
        return denied

    _ensure_chatbot_doc_table()

    row = ChatbotDocument.query.filter_by(
        ChatbotDocumentID=doc_id, IsDelete=False
    ).first()
    if not row:
        flash("Không tìm thấy tài liệu để xóa.", "error")
        return redirect(url_for("chatbot.admin_chatbot_docs"))

    try:
        row.IsDelete = True
        db.session.commit()
        get_chatbot_service().invalidate_knowledge_base(clear_disk=True)
        flash("Đã xóa tài liệu khỏi kho tri thức chatbot.", "success")
    except Exception as exc:
        db.session.rollback()
        flash(f"Lỗi khi xóa tài liệu: {exc}", "error")

    return redirect(url_for("chatbot.admin_chatbot_docs"))


@bp.route("/admin/chatbot-documents/rebuild-index", methods=["POST"])
def admin_rebuild_chatbot_index():
    denied = _admin_guard()
    if denied:
        return denied

    _ensure_chatbot_doc_table()
    status = get_chatbot_service().rebuild_knowledge_base()

    if status.get("vector_ready"):
        flash(
            f"Đã rebuild FAISS thành công ({status.get('source_count', 0)} nguồn tài liệu).",
            "success",
        )
    else:
        flash(
            "Đã làm mới dữ liệu tài liệu, nhưng chưa build được vector index. "
            "Hệ thống sẽ dùng keyword fallback nếu cần.",
            "error",
        )

    return redirect(url_for("chatbot.admin_chatbot_docs"))


@bp.route("/api/function-calling/", methods=["POST"])
def function_calling():
    _ensure_chat_table()

    data = request.get_json(silent=True) or {}
    query = (data.get("query") or "").strip()

    if not query:
        return jsonify(
            {"success": False, "message": "Vui lòng nhập nội dung câu hỏi."}
        ), 400

    user_id = _get_authenticated_user_id()
    if user_id:
        history = _load_user_history(user_id=user_id, limit=60)
    else:
        history = session.get("guest_chat_history", [])

    pending_action = session.get("chatbot_pending_action")

    chatbot = get_chatbot_service()
    result = chatbot.process_query(
        query=query,
        user_id=user_id,
        history=history,
        pending_action=pending_action,
    )

    if result.pending_action:
        session["chatbot_pending_action"] = result.pending_action
    else:
        session.pop("chatbot_pending_action", None)

    if user_id:
        _persist_user_turn(
            user_id=user_id,
            user_text=query,
            bot_text=result.response,
            products=result.products,
        )
    else:
        _append_guest_history(
            user_text=query,
            bot_text=result.response,
            products=result.products,
        )

    return jsonify(
        {
            "success": True,
            "response": result.response,
            "products": result.products,
            "requires_login": result.requires_login,
            "login_url": result.login_url,
        }
    )


@bp.route("/api/function-calling/stream", methods=["POST"])
def function_calling_stream():
    _ensure_chat_table()

    data = request.get_json(silent=True) or {}
    query = (data.get("query") or "").strip()

    if not query:
        return jsonify(
            {"success": False, "message": "Vui lòng nhập nội dung câu hỏi."}
        ), 400

    user_id = _get_authenticated_user_id()
    if user_id:
        history = _load_user_history(user_id=user_id, limit=60)
    else:
        history = session.get("guest_chat_history", [])

    pending_action = session.get("chatbot_pending_action")

    chatbot = get_chatbot_service()
    result = chatbot.process_query(
        query=query,
        user_id=user_id,
        history=history,
        pending_action=pending_action,
    )

    if result.pending_action:
        session["chatbot_pending_action"] = result.pending_action
    else:
        session.pop("chatbot_pending_action", None)

    if user_id:
        _persist_user_turn(
            user_id=user_id,
            user_text=query,
            bot_text=result.response,
            products=result.products,
        )
    else:
        _append_guest_history(
            user_text=query,
            bot_text=result.response,
            products=result.products,
        )

    def event_stream():
        for chunk in chatbot.stream_text(result.response):
            payload = {
                "type": "delta",
                "content": chunk,
            }
            yield f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"

        done_payload = {
            "type": "done",
            "response": result.response,
            "products": result.products,
            "requires_login": result.requires_login,
            "login_url": result.login_url,
        }
        yield f"data: {json.dumps(done_payload, ensure_ascii=False)}\n\n"

    return Response(
        stream_with_context(event_stream()),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


@bp.route("/api/get-chat-history/", methods=["GET"])
def get_chat_history():
    _ensure_chat_table()

    user_id = _get_authenticated_user_id()
    if user_id:
        history = _load_user_history(user_id=user_id, limit=200)
    else:
        history = session.get("guest_chat_history", [])

    return jsonify({"success": True, "chat_history": history})


@bp.route("/api/save-chat-history/", methods=["POST"])
def save_chat_history():
    """Compatibility endpoint for frontend; persistence is handled server-side on /api/function-calling/."""
    _ensure_chat_table()
    return jsonify({"success": True})


@bp.route("/api/chat/reset-guest", methods=["POST"])
def reset_guest_chat():
    if not _get_authenticated_user_id():
        session.pop("guest_chat_history", None)
        session.pop("chatbot_pending_action", None)
        session.modified = True
    return jsonify({"success": True})
