from __future__ import annotations

import json
import os
import re
import shutil
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal, TypedDict

from flask import current_app
from sqlalchemy import func, inspect
from typing_extensions import Annotated

from config.database import db
from models.tables import (
    Brand,
    Cart,
    CartDetail,
    Category,
    ChatbotDocument,
    OrderDetail,
    Product,
    User,
)

LANGCHAIN_AVAILABLE = True

try:
    from langchain_community.vectorstores import FAISS
    from langchain_core.documents import Document
    from langchain_core.messages import (
        AIMessage,
        BaseMessage,
        HumanMessage,
        SystemMessage,
        ToolMessage,
    )
    from langchain_core.tools import tool
    from langchain_ollama import ChatOllama, OllamaEmbeddings
    from langchain_text_splitters import RecursiveCharacterTextSplitter
    from langgraph.graph import END, StateGraph
    from langgraph.graph.message import add_messages
    from langgraph.prebuilt import ToolNode, tools_condition
except Exception:
    LANGCHAIN_AVAILABLE = False
    FAISS = None
    AIMessage = Any  # type: ignore[assignment]
    BaseMessage = Any  # type: ignore[assignment]
    HumanMessage = Any  # type: ignore[assignment]
    SystemMessage = Any  # type: ignore[assignment]
    ToolMessage = Any  # type: ignore[assignment]
    tool = None
    Document = Any  # type: ignore[assignment]
    ChatOllama = None
    OllamaEmbeddings = None
    RecursiveCharacterTextSplitter = None
    END = None
    StateGraph = None
    add_messages = None
    ToolNode = None
    tools_condition = None


class GraphState(TypedDict, total=False):
    messages: Annotated[list[Any], add_messages]
    query: str
    user_id: int | None
    history: list[dict[str, Any]]
    pending_action: dict[str, Any] | None
    short_circuit: bool
    intent: str
    entities: dict[str, Any]
    action: Literal["tool", "rag", "fallback", "finalize"]
    response: str
    products: list[dict[str, Any]]
    requires_login: bool
    login_url: str | None
    new_pending_action: dict[str, Any] | None


@dataclass
class ChatbotResult:
    response: str
    products: list[dict[str, Any]] = field(default_factory=list)
    requires_login: bool = False
    login_url: str | None = None
    pending_action: dict[str, Any] | None = None


class SalesSupportChatbot:
    """Sales/support chatbot powered by LangGraph + LangChain + Ollama + FAISS."""

    def __init__(self, app_root: Path, instance_path: Path):
        self.app_root = app_root
        self.instance_path = instance_path
        self.vector_store_dir = Path(
            os.environ.get("FAISS_DB_PATH", str(instance_path / "faissdb"))
        )

        self.ollama_base_url = os.environ.get(
            "OLLAMA_BASE_URL", "http://localhost:11434"
        )
        self.ollama_model = os.environ.get("OLLAMA_MODEL", "llama3.1:8b-cloud")
        self.ollama_embedding_model = os.environ.get(
            "OLLAMA_EMBED_MODEL", "nomic-embed-text:latest"
        )
        self.shop_name = os.environ.get("SHOP_NAME", "BanMayTinh")
        self.brand_tone = os.environ.get(
            "SHOP_BRAND_TONE",
            "chuyên nghiệp, thân thiện, trung thực, tập trung hỗ trợ mua hàng",
        )
        self.brand_rules = os.environ.get(
            "SHOP_BRAND_RULES",
            "luôn ngắn gọn, không bịa thông tin, ưu tiên đưa link sản phẩm khi nhắc danh sách",
        )

        self._llm = None
        self._llm_with_tools = None
        self._embeddings = None
        self._vector_store = None
        self._vector_lock = threading.Lock()
        self._raw_docs: list[tuple[str, str]] = []
        self._runtime_local = threading.local()
        self._tools: list[Any] = []
        self._tool_node = None

        self._init_llm_clients()
        self._build_tools()
        self._graph = self._build_graph() if LANGCHAIN_AVAILABLE else None

    def process_query(
        self,
        query: str,
        user_id: int | None,
        history: list[dict[str, Any]] | None,
        pending_action: dict[str, Any] | None,
    ) -> ChatbotResult:
        state: GraphState = {
            "query": query.strip(),
            "user_id": user_id,
            "history": history or [],
            "pending_action": pending_action,
        }

        if not state["query"]:
            return ChatbotResult(
                response="Bạn chưa nhập câu hỏi. Vui lòng nhập nội dung cần hỗ trợ."
            )

        self._set_runtime_context(user_id=user_id, history=history or [])
        try:
            if self._graph is not None:
                output = self._graph.invoke(state)
            else:
                output = self._run_without_graph(state)
        finally:
            self._clear_runtime_context()

        return ChatbotResult(
            response=(
                output.get("response")
                or "Mình chưa xử lý được câu hỏi này. Bạn mô tả rõ hơn giúp mình nhé."
            ).strip(),
            products=output.get("products") or [],
            requires_login=bool(output.get("requires_login")),
            login_url=output.get("login_url"),
            pending_action=output.get("new_pending_action"),
        )

    def process_query_stream(
        self,
        query: str,
        user_id: int | None,
        history: list[dict[str, Any]] | None,
        pending_action: dict[str, Any] | None,
    ):
        result = self.process_query(
            query=query,
            user_id=user_id,
            history=history,
            pending_action=pending_action,
        )

        for chunk in self.stream_text(result.response):
            yield {"type": "delta", "content": chunk}

        yield {
            "type": "done",
            "response": result.response,
            "products": result.products,
            "requires_login": result.requires_login,
            "login_url": result.login_url,
            "pending_action": result.pending_action,
        }

    def stream_text(self, text: str, chunk_size: int = 14):
        text = text or ""
        for idx in range(0, len(text), chunk_size):
            yield text[idx : idx + chunk_size]
            time.sleep(0.01)

    def invalidate_knowledge_base(self, clear_disk: bool = True) -> None:
        with self._vector_lock:
            self._vector_store = None
            self._raw_docs = []
            if clear_disk and self.vector_store_dir.exists():
                try:
                    shutil.rmtree(self.vector_store_dir, ignore_errors=True)
                except Exception as exc:
                    current_app.logger.warning(
                        "Cannot clear FAISS directory %s: %s",
                        self.vector_store_dir,
                        exc,
                    )

    def rebuild_knowledge_base(self) -> dict[str, Any]:
        self.invalidate_knowledge_base(clear_disk=True)
        self._load_rag_documents()
        vector_store = self._get_or_build_vector_store()
        return {
            "vector_ready": vector_store is not None,
            "source_count": len(self._raw_docs),
            "langchain_available": LANGCHAIN_AVAILABLE,
            "embedding_ready": self._embeddings is not None,
        }

    def _init_llm_clients(self) -> None:
        if not LANGCHAIN_AVAILABLE:
            return

        try:
            self._llm = ChatOllama(
                model=self.ollama_model,
                base_url=self.ollama_base_url,
                temperature=0.2,
            )
        except Exception as exc:
            current_app.logger.warning("Cannot initialize ChatOllama: %s", exc)
            self._llm = None

        try:
            self._embeddings = OllamaEmbeddings(
                model=self.ollama_embedding_model,
                base_url=self.ollama_base_url,
            )
        except Exception as exc:
            current_app.logger.warning("Cannot initialize OllamaEmbeddings: %s", exc)
            self._embeddings = None

    def _set_runtime_context(self, user_id: int | None, history: list[dict[str, Any]]):
        self._runtime_local.user_id = user_id
        self._runtime_local.history = history

    def _clear_runtime_context(self):
        self._runtime_local.user_id = None
        self._runtime_local.history = []

    def _runtime_user_id(self) -> int | None:
        return getattr(self._runtime_local, "user_id", None)

    def _runtime_history(self) -> list[dict[str, Any]]:
        return getattr(self._runtime_local, "history", [])

    def _build_tools(self) -> None:
        if not LANGCHAIN_AVAILABLE or tool is None:
            self._tools = []
            self._tool_node = None
            return

        @tool("add_product_to_cart")
        def add_product_to_cart(
            product_ref: str, quantity: int | None = None
        ) -> dict[str, Any]:
            """Thêm sản phẩm theo tên/ID vào giỏ hàng. Nếu thiếu quantity hãy để trống để hệ thống hỏi ngược."""
            payload = self._tool_add_to_cart(
                product_ref=product_ref,
                quantity=quantity,
                user_id=self._runtime_user_id(),
            )
            return self._normalize_tool_payload(payload)

        @tool("get_product_detail")
        def get_product_detail(product_ref: str) -> dict[str, Any]:
            """Xem chi tiết sản phẩm theo tên hoặc ID."""
            payload = self._tool_product_detail(product_ref=product_ref)
            return self._normalize_tool_payload(payload)

        @tool("list_products_by_brand")
        def list_products_by_brand(brand_ref: str) -> dict[str, Any]:
            """Xem danh sách sản phẩm theo hãng (tên hoặc ID)."""
            payload = self._tool_products_by_brand(brand_ref=brand_ref)
            return self._normalize_tool_payload(payload)

        @tool("list_products_by_category")
        def list_products_by_category(category_ref: str) -> dict[str, Any]:
            """Xem danh sách sản phẩm theo loại/danh mục (tên hoặc ID)."""
            payload = self._tool_products_by_category(category_ref=category_ref)
            return self._normalize_tool_payload(payload)

        @tool("compare_two_pcs")
        def compare_two_pcs(
            first_product_ref: str, second_product_ref: str
        ) -> dict[str, Any]:
            """So sánh 2 sản phẩm PC theo tên/ID và đưa tư vấn."""
            payload = self._tool_compare_pc(
                first_ref=first_product_ref,
                second_ref=second_product_ref,
                history=self._runtime_history(),
            )
            return self._normalize_tool_payload(payload)

        @tool("compare_two_products_detailed")
        def compare_two_products_detailed(
            first_product_ref: str, second_product_ref: str
        ) -> dict[str, Any]:
            """So sánh chi tiết 2 sản phẩm theo tên/ID (hỗn hợp 1 tên + 1 ID)."""
            payload = self._tool_compare_products_detailed(
                first_ref=first_product_ref,
                second_ref=second_product_ref,
                history=self._runtime_history(),
                force_compare=False,
            )
            return self._normalize_tool_payload(payload)

        @tool("top_selling_pcs")
        def top_selling_pcs() -> dict[str, Any]:
            """Lấy danh sách PC bán chạy nhất của shop."""
            payload = self._tool_top_selling_pc()
            return self._normalize_tool_payload(payload)

        @tool("search_system_docs")
        def search_system_docs(question: str) -> dict[str, Any]:
            """RAG: truy xuất tài liệu hệ thống để trả lời câu hỏi kỹ thuật/chính sách/chức năng."""
            contexts = self._retrieve_rag_context(question, top_k=4)
            if not contexts:
                return {
                    "response": "Không tìm thấy tài liệu liên quan trong hệ thống.",
                    "contexts": [],
                }
            lines = [
                f"Nguồn: {item['source']} | Nội dung: {item['content'][:220]}..."
                for item in contexts
            ]
            return {
                "response": "Đã tìm thấy dữ liệu trong tài liệu hệ thống:\n"
                + "\n".join(lines),
                "contexts": contexts,
            }

        self._tools = [
            add_product_to_cart,
            get_product_detail,
            list_products_by_brand,
            list_products_by_category,
            compare_two_pcs,
            compare_two_products_detailed,
            top_selling_pcs,
            search_system_docs,
        ]
        self._tool_node = ToolNode(self._tools) if ToolNode is not None else None
        if self._llm is not None:
            try:
                self._llm_with_tools = self._llm.bind_tools(self._tools)
            except Exception as exc:
                current_app.logger.warning("Cannot bind tools to LLM: %s", exc)
                self._llm_with_tools = None

    def _build_graph(self):
        if (
            not LANGCHAIN_AVAILABLE
            or StateGraph is None
            or self._llm_with_tools is None
            or self._tool_node is None
            or tools_condition is None
        ):
            return None

        workflow = StateGraph(GraphState)
        workflow.add_node("prepare", self._node_prepare_agent)
        workflow.add_node("assistant", self._node_assistant_agent)
        workflow.add_node("tools", self._tool_node)
        workflow.add_node("finalize", self._node_finalize_agent)

        workflow.set_entry_point("prepare")
        workflow.add_conditional_edges(
            "prepare",
            self._route_after_prepare_agent,
            {
                "assistant": "assistant",
                "finalize": "finalize",
            },
        )
        workflow.add_conditional_edges(
            "assistant",
            tools_condition,
            {
                "tools": "tools",
                "__end__": "finalize",
            },
        )
        workflow.add_edge("tools", "assistant")
        workflow.add_edge("finalize", END)

        return workflow.compile()

    def _node_prepare_agent(self, state: GraphState) -> GraphState:
        query = (state.get("query") or "").strip()
        pending_action = state.get("pending_action")

        guardrail_reply = self._guardrail_reply(query)
        if guardrail_reply is not None:
            return {
                "response": guardrail_reply,
                "short_circuit": True,
                "new_pending_action": None,
            }

        effective_query = query
        if (
            pending_action
            and pending_action.get("type") == "await_add_to_cart_quantity"
        ):
            quantity = self._extract_quantity(query, allow_plain_number=True)
            if quantity is None:
                product_label = pending_action.get("product_label") or "sản phẩm đó"
                return {
                    "response": f"Bạn muốn thêm bao nhiêu cho {product_label}? Vui lòng trả lời bằng số lượng, ví dụ: 2.",
                    "short_circuit": True,
                    "new_pending_action": pending_action,
                }

            direct_result = self._tool_add_to_cart(
                product_ref=pending_action.get("product_ref"),
                quantity=quantity,
                user_id=state.get("user_id"),
            )
            return {
                "response": direct_result.get("response")
                or "Mình chưa thể thêm vào giỏ lúc này, bạn thử lại giúp mình.",
                "products": direct_result.get("products") or [],
                "requires_login": bool(direct_result.get("requires_login")),
                "login_url": direct_result.get("login_url"),
                "short_circuit": True,
                "new_pending_action": direct_result.get("new_pending_action"),
            }

        if (
            pending_action
            and pending_action.get("type") == "await_compare_products_confirmation"
        ):
            confirmation = self._parse_confirmation_reply(query)
            if confirmation is True:
                first_id = pending_action.get("first_product_id")
                second_id = pending_action.get("second_product_id")
                if first_id and second_id:
                    force_result = self._tool_compare_products_detailed(
                        first_ref=first_id,
                        second_ref=second_id,
                        history=state.get("history") or [],
                        force_compare=True,
                    )
                    return {
                        "response": force_result.get("response")
                        or "Mình chưa thể so sánh ngay lúc này, bạn thử lại giúp mình.",
                        "products": force_result.get("products") or [],
                        "requires_login": bool(force_result.get("requires_login")),
                        "login_url": force_result.get("login_url"),
                        "short_circuit": True,
                        "new_pending_action": force_result.get("new_pending_action"),
                    }
            elif confirmation is False:
                first_ref, second_ref = self._extract_compare_refs(query)
                if first_ref is not None and second_ref is not None:
                    effective_query = f"So sánh chi tiết {first_ref} và {second_ref}"
                else:
                    detected_intent, _ = self._detect_intent_and_entities(query)
                    if detected_intent == "compare_products":
                        return {
                            "response": (
                                "Bạn vui lòng copy đúng tên đầy đủ hoặc gửi ID của 2 sản phẩm để mình so sánh. "
                                "Ví dụ: so sánh sản phẩm id 12 và sản phẩm id 30."
                            ),
                            "short_circuit": True,
                            "new_pending_action": pending_action,
                        }
            else:
                first_ref, second_ref = self._extract_compare_refs(query)
                if first_ref is not None and second_ref is not None:
                    effective_query = f"So sánh chi tiết {first_ref} và {second_ref}"
                else:
                    detected_intent, _ = self._detect_intent_and_entities(query)
                    if detected_intent == "compare_products":
                        return {
                            "response": (
                                "Nếu đã đúng 2 sản phẩm thì bạn trả lời 'đúng'. "
                                "Nếu chưa đúng, bạn copy đúng tên hoặc ID của cả 2 sản phẩm để mình tìm lại."
                            ),
                            "short_circuit": True,
                            "new_pending_action": pending_action,
                        }

        messages: list[Any] = [SystemMessage(content=self._tool_agent_system_prompt())]
        messages.extend(self._history_to_messages(state.get("history") or []))
        messages.append(HumanMessage(content=effective_query))

        return {
            "query": effective_query,
            "messages": messages,
            "short_circuit": False,
            "new_pending_action": None,
        }

    def _route_after_prepare_agent(self, state: GraphState) -> str:
        if state.get("short_circuit"):
            return "finalize"
        return "assistant"

    def _node_assistant_agent(self, state: GraphState) -> GraphState:
        if self._llm_with_tools is None:
            return {
                "response": "Hệ thống AI tool-calling chưa sẵn sàng. Bạn kiểm tra lại cấu hình model.",
                "short_circuit": True,
            }

        try:
            response = self._llm_with_tools.invoke(state.get("messages") or [])
        except Exception as exc:
            current_app.logger.warning("Tool-calling invoke failed: %s", exc)
            return {
                "response": "Mình đang gặp lỗi khi xử lý tool-calling. Bạn thử lại sau ít phút.",
                "short_circuit": True,
            }

        return {"messages": [response]}

    def _node_finalize_agent(self, state: GraphState) -> GraphState:
        if state.get("short_circuit"):
            return {
                "response": state.get("response")
                or "Mình chưa xử lý được câu hỏi này. Bạn thử diễn đạt lại giúp mình nhé.",
                "products": state.get("products") or [],
                "requires_login": bool(state.get("requires_login")),
                "login_url": state.get("login_url"),
                "new_pending_action": state.get("new_pending_action"),
            }

        messages = state.get("messages") or []
        tool_payloads = self._extract_tool_payloads(messages)

        products: list[dict[str, Any]] = []
        requires_login = False
        login_url = None
        new_pending_action = None
        tool_responses: list[str] = []

        for payload in tool_payloads:
            tool_responses.append(str(payload.get("response") or "").strip())
            products.extend(payload.get("products") or [])
            requires_login = requires_login or bool(payload.get("requires_login"))
            login_url = login_url or payload.get("login_url")
            if payload.get("new_pending_action") is not None:
                new_pending_action = payload.get("new_pending_action")

        # Remove duplicated products by id/url.
        dedup_map: dict[str, dict[str, Any]] = {}
        for item in products:
            key = str(item.get("id") or item.get("url") or len(dedup_map))
            if key not in dedup_map:
                dedup_map[key] = item
        products = list(dedup_map.values())

        final_ai_text = self._extract_last_ai_text(messages)
        response_text = final_ai_text or next(
            (text for text in reversed(tool_responses) if text),
            "",
        )
        if not response_text:
            response_text = self._node_fallback(state).get("response", "")

        if products and self._should_append_links(
            state.get("query") or "", response_text
        ):
            response_text = (
                response_text.rstrip() + "\n" + self._format_product_links(products)
            )

        return {
            "response": response_text,
            "products": products,
            "requires_login": requires_login,
            "login_url": login_url,
            "new_pending_action": new_pending_action,
        }

    def _run_without_graph(self, state: GraphState) -> GraphState:
        prepared = self._node_prepare(state)
        merged = {**state, **prepared}
        action = merged.get("action", "fallback")

        if action == "tool":
            merged.update(self._node_tool(merged))
        elif action == "rag":
            merged.update(self._node_rag(merged))
        elif action == "fallback":
            merged.update(self._node_fallback(merged))

        merged.update(self._node_finalize(merged))
        return merged

    def _node_prepare(self, state: GraphState) -> GraphState:
        query = (state.get("query") or "").strip()
        pending_action = state.get("pending_action")

        guardrail_reply = self._guardrail_reply(query)
        if guardrail_reply is not None:
            return {
                "action": "finalize",
                "response": guardrail_reply,
                "new_pending_action": None,
            }

        if (
            pending_action
            and pending_action.get("type") == "await_add_to_cart_quantity"
        ):
            quantity = self._extract_quantity(query, allow_plain_number=True)
            if quantity is None:
                product_label = pending_action.get("product_label") or "sản phẩm đó"
                return {
                    "action": "finalize",
                    "response": f"Bạn muốn thêm bao nhiêu cho {product_label}? Vui lòng trả lời bằng số lượng, ví dụ: 2.",
                    "new_pending_action": pending_action,
                }

            return {
                "intent": "add_to_cart",
                "entities": {
                    "product_ref": pending_action.get("product_ref"),
                    "quantity": quantity,
                },
                "action": "tool",
            }

        if (
            pending_action
            and pending_action.get("type") == "await_compare_products_confirmation"
        ):
            confirmation = self._parse_confirmation_reply(query)
            if confirmation is True:
                return {
                    "intent": "compare_products",
                    "entities": {
                        "first_ref": pending_action.get("first_product_id"),
                        "second_ref": pending_action.get("second_product_id"),
                        "force_compare": True,
                    },
                    "action": "tool",
                }

            first_ref, second_ref = self._extract_compare_refs(query)
            if first_ref is not None and second_ref is not None:
                return {
                    "intent": "compare_products",
                    "entities": {
                        "first_ref": first_ref,
                        "second_ref": second_ref,
                        "force_compare": False,
                    },
                    "action": "tool",
                }

            detected_intent, detected_entities = self._detect_intent_and_entities(query)
            if detected_intent == "compare_products":
                return {
                    "action": "finalize",
                    "response": (
                        "Nếu đã đúng 2 sản phẩm thì bạn trả lời 'đúng'. "
                        "Nếu chưa đúng, bạn copy đúng tên hoặc ID của cả 2 sản phẩm để mình tìm lại."
                    ),
                    "new_pending_action": pending_action,
                }

            if detected_intent in {
                "add_to_cart",
                "product_detail",
                "products_by_brand",
                "products_by_category",
                "top_selling_pc",
            }:
                return {
                    "intent": detected_intent,
                    "entities": detected_entities,
                    "action": "tool",
                    "new_pending_action": None,
                }

            if detected_intent == "rag":
                return {
                    "intent": detected_intent,
                    "entities": detected_entities,
                    "action": "rag",
                    "new_pending_action": None,
                }

        intent, entities = self._detect_intent_and_entities(query)

        if intent in {
            "add_to_cart",
            "product_detail",
            "products_by_brand",
            "products_by_category",
            "compare_products",
            "top_selling_pc",
        }:
            return {"intent": intent, "entities": entities, "action": "tool"}

        if intent == "rag":
            return {"intent": intent, "entities": entities, "action": "rag"}

        return {"intent": "fallback", "entities": {}, "action": "fallback"}

    def _route_after_prepare(self, state: GraphState) -> str:
        return state.get("action") or "fallback"

    def _node_tool(self, state: GraphState) -> GraphState:
        intent = state.get("intent")
        entities = state.get("entities") or {}
        user_id = state.get("user_id")
        history = state.get("history") or []

        if intent == "add_to_cart":
            result = self._tool_add_to_cart(
                product_ref=entities.get("product_ref"),
                quantity=entities.get("quantity"),
                user_id=user_id,
            )
        elif intent == "product_detail":
            result = self._tool_product_detail(product_ref=entities.get("product_ref"))
        elif intent == "products_by_brand":
            result = self._tool_products_by_brand(brand_ref=entities.get("brand_ref"))
        elif intent == "products_by_category":
            result = self._tool_products_by_category(
                category_ref=entities.get("category_ref")
            )
        elif intent == "compare_products":
            result = self._tool_compare_products_detailed(
                first_ref=entities.get("first_ref"),
                second_ref=entities.get("second_ref"),
                history=history,
                force_compare=bool(entities.get("force_compare")),
            )
        elif intent == "top_selling_pc":
            result = self._tool_top_selling_pc()
        else:
            result = {
                "response": "Mình chưa xác định được thao tác bạn muốn. Bạn có thể nói rõ hơn không?",
                "products": [],
                "new_pending_action": None,
            }

        return result

    def _node_rag(self, state: GraphState) -> GraphState:
        query = state.get("query") or ""
        history = state.get("history") or []
        response = self._answer_with_rag(query=query, history=history)
        return {"response": response, "products": [], "new_pending_action": None}

    def _node_fallback(self, state: GraphState) -> GraphState:
        return {
            "response": (
                f"Mình cần thêm thông tin để hỗ trợ chính xác tại {self.shop_name}. "
                "Bạn có thể chọn một trong các hướng sau:\n"
                "1. Xem chi tiết sản phẩm theo tên hoặc ID\n"
                "2. Xem sản phẩm theo hãng\n"
                "3. Xem sản phẩm theo loại\n"
                "4. So sánh chi tiết 2 sản phẩm theo tên/ID\n"
                "5. Xem top PC bán chạy\n"
                "Bạn muốn bắt đầu với hướng nào?"
            ),
            "products": [],
            "new_pending_action": None,
        }

    def _node_finalize(self, state: GraphState) -> GraphState:
        if not state.get("response"):
            return {
                "response": "Mình chưa xử lý được câu hỏi này. Bạn thử diễn đạt lại giúp mình nhé.",
                "products": [],
                "new_pending_action": None,
            }
        return {}

    def _detect_intent_and_entities(self, query: str) -> tuple[str, dict[str, Any]]:
        q = query.lower()

        if any(key in q for key in ["thêm", "add", "mua", "đặt"]) and any(
            key in q for key in ["giỏ", "cart"]
        ):
            product_ref = self._extract_product_reference(query)
            quantity = self._extract_quantity(query, allow_plain_number=False)
            return "add_to_cart", {"product_ref": product_ref, "quantity": quantity}

        if any(
            key in q for key in ["chi tiết", "thông tin", "cấu hình", "spec"]
        ) or re.search(
            r"(xem|chi tiet|chi tiết|thong tin|thông tin).*(id|mã|ma|\d+)",
            q,
        ):
            product_ref = self._extract_product_reference(query)
            return "product_detail", {"product_ref": product_ref}

        if any(key in q for key in ["thương hiệu", "hãng", "brand"]):
            brand_ref = self._extract_named_or_id_ref(
                query, ["thương hiệu", "hãng", "brand"]
            )
            return "products_by_brand", {"brand_ref": brand_ref}

        if any(key in q for key in ["danh mục", "loại", "category"]):
            category_ref = self._extract_named_or_id_ref(
                query, ["danh mục", "loại", "category"]
            )
            return "products_by_category", {"category_ref": category_ref}

        if any(key in q for key in ["so sánh", "so sanh", "vs"]):
            first_ref, second_ref = self._extract_compare_refs(query)
            return "compare_products", {
                "first_ref": first_ref,
                "second_ref": second_ref,
                "force_compare": False,
            }

        if any(key in q for key in ["bán chạy", "ban chay", "top", "hot"]):
            return "top_selling_pc", {}

        return "rag", {}

    def _guardrail_reply(self, query: str) -> str | None:
        q = query.lower()

        harmful_keywords = [
            "hack",
            "ddos",
            "malware",
            "virus",
            "keylogger",
            "phishing",
            "lừa đảo",
            "lua dao",
            "bom",
            "thuốc nổ",
            "vũ khí",
            "vu khi",
            "rửa tiền",
            "rua tien",
        ]
        if any(keyword in q for keyword in harmful_keywords):
            return (
                f"Mình không thể hỗ trợ nội dung có rủi ro vi phạm pháp luật/an toàn. "
                f"Mình chỉ hỗ trợ tư vấn sản phẩm, so sánh cấu hình và mua hàng tại {self.shop_name}."
            )

        # Out-of-scope chitchat: keep chatbot focused on sales/support.
        out_of_scope_markers = [
            "thời tiết",
            "thoi tiet",
            "chính trị",
            "chinh tri",
            "tử vi",
            "tu vi",
            "bói",
            "boi",
            "chiêm tinh",
            "xổ số",
            "xo so",
        ]
        if any(marker in q for marker in out_of_scope_markers):
            return (
                f"Mình tập trung hỗ trợ bán hàng và CSKH cho {self.shop_name}. "
                "Bạn muốn mình hỗ trợ theo hãng, loại sản phẩm, chi tiết mã hàng hay so sánh 2 PC?"
            )

        return None

    def _brand_system_prompt(self) -> str:
        return (
            f"Bạn là trợ lý bán hàng và chăm sóc khách hàng của {self.shop_name}. "
            f"Giọng điệu: {self.brand_tone}. Quy tắc: {self.brand_rules}. "
            "Luôn trả lời bằng tiếng Việt, gãy gọn, dễ hiểu. "
            "Khi chưa đủ dữ kiện thì hỏi ngược lại đúng 1 câu rõ ràng để lấy thông tin còn thiếu."
        )

    def _tool_agent_system_prompt(self) -> str:
        return (
            f"{self._brand_system_prompt()}\n"
            "Bạn có quyền gọi tools để xử lý nghiệp vụ thay vì đoán thông tin.\n"
            "Nguyên tắc bắt buộc:\n"
            "1. Khi người dùng muốn thêm vào giỏ, luôn dùng tool add_product_to_cart.\n"
            "2. Khi chưa có số lượng khi thêm giỏ, tool sẽ trả câu hỏi ngược, hãy hỏi lại người dùng.\n"
            "3. Khi xuất danh sách sản phẩm, phải kèm link sản phẩm.\n"
            "4. Khi người dùng yêu cầu so sánh, ưu tiên dùng tool compare_two_products_detailed.\n"
            "5. Khi hỏi liên quan dữ liệu/tài liệu hệ thống, gọi tool search_system_docs trước.\n"
            "6. Không bịa dữ liệu không có trong kết quả tool."
        )

    def _history_to_messages(self, history: list[dict[str, Any]]) -> list[Any]:
        if not LANGCHAIN_AVAILABLE:
            return []
        messages: list[Any] = []
        for item in history[-12:]:
            sender = (item.get("sender") or "").lower()
            text = str(item.get("text") or "").strip()
            if not text:
                continue
            if sender == "user":
                messages.append(HumanMessage(content=text))
            else:
                messages.append(AIMessage(content=text))
        return messages

    def _extract_tool_payloads(self, messages: list[Any]) -> list[dict[str, Any]]:
        if not LANGCHAIN_AVAILABLE:
            return []
        payloads: list[dict[str, Any]] = []
        for message in messages:
            if not isinstance(message, ToolMessage):
                continue
            content = getattr(message, "content", "")
            parsed: dict[str, Any] | None = None
            if isinstance(content, str):
                try:
                    parsed = json.loads(content)
                except Exception:
                    parsed = {"response": content}
            elif isinstance(content, dict):
                parsed = content
            else:
                parsed = {"response": str(content)}
            if parsed:
                payloads.append(parsed)
        return payloads

    def _extract_last_ai_text(self, messages: list[Any]) -> str:
        if not LANGCHAIN_AVAILABLE:
            return ""
        for message in reversed(messages):
            if not isinstance(message, AIMessage):
                continue
            content = getattr(message, "content", "")
            if isinstance(content, list):
                content = " ".join(str(item) for item in content)
            text = str(content or "").strip()
            if text:
                return text
        return ""

    def _normalize_tool_payload(self, payload: dict[str, Any]) -> dict[str, Any]:
        return {
            "response": payload.get("response") or "",
            "products": payload.get("products") or [],
            "requires_login": bool(payload.get("requires_login")),
            "login_url": payload.get("login_url"),
            "new_pending_action": payload.get("new_pending_action"),
        }

    def _should_append_links(self, query: str, response_text: str) -> bool:
        q = (query or "").lower()
        listing_markers = [
            "danh sách",
            "danh sach",
            "top",
            "bán chạy",
            "ban chay",
            "theo hãng",
            "theo loai",
            "theo loại",
        ]
        if any(marker in q for marker in listing_markers):
            return "/product/" not in (response_text or "")
        return False

    def _format_product_links(self, products: list[dict[str, Any]]) -> str:
        lines = []
        for idx, item in enumerate(products[:10], start=1):
            lines.append(
                f"{idx}. {item.get('name', 'Sản phẩm')} - {item.get('url', '#')}"
            )
        return "Link sản phẩm:\n" + "\n".join(lines)

    def _extract_quantity(self, query: str, allow_plain_number: bool) -> int | None:
        if allow_plain_number:
            direct_number = re.fullmatch(r"\s*(\d+)\s*", query)
            if direct_number:
                value = int(direct_number.group(1))
                return value if value > 0 else None

        patterns = [
            r"(?:số lượng|so luong|sl|qty)\s*[:=]?\s*(\d+)",
            r"x\s*(\d+)",
            r"(\d+)\s*(?:cái|chiếc|bộ|sp|sản phẩm)",
        ]
        for pattern in patterns:
            match = re.search(pattern, query, flags=re.IGNORECASE)
            if match:
                value = int(match.group(1))
                return value if value > 0 else None

        return None

    def _extract_named_or_id_ref(
        self, query: str, markers: list[str]
    ) -> str | int | None:
        id_match = re.search(r"(?:id|mã|ma)\s*(\d+)", query, flags=re.IGNORECASE)
        if id_match:
            return int(id_match.group(1))

        lowered = query.lower()
        for marker in markers:
            idx = lowered.find(marker)
            if idx >= 0:
                ref = query[idx + len(marker) :]
                ref = re.sub(
                    r"^(là|la|id|mã|ma|nào|nao|cho|có|co)\s*",
                    "",
                    ref,
                    flags=re.IGNORECASE,
                ).strip(" :,.?\n\t")
                if ref:
                    return ref

        return None

    def _extract_product_reference(self, query: str) -> str | int | None:
        id_match = re.search(r"(?:id|mã|ma)\s*(\d+)", query, flags=re.IGNORECASE)
        if id_match:
            return int(id_match.group(1))

        cleaned = re.sub(
            r"\b(thêm|add|mua|đặt|vào|vao|giỏ|gio|cart|sản phẩm|san pham|chi tiết|chi tiet|thông tin|thong tin|cấu hình|cau hinh|xem|cho tôi|cho toi)\b",
            " ",
            query,
            flags=re.IGNORECASE,
        )
        cleaned = re.sub(r"\s+", " ", cleaned).strip(" :,.?\n\t")

        if not cleaned:
            return None

        return cleaned

    def _extract_compare_refs(
        self, query: str
    ) -> tuple[str | int | None, str | int | None]:
        explicit_ids = re.findall(r"(?:id|mã|ma)\s*(\d+)", query, flags=re.IGNORECASE)
        if len(explicit_ids) >= 2:
            return int(explicit_ids[0]), int(explicit_ids[1])

        numbers = re.findall(r"\b(\d+)\b", query)
        if len(numbers) >= 2 and any(
            token in query.lower() for token in ["vs", "và", "voi", "với"]
        ):
            return int(numbers[0]), int(numbers[1])

        normalized = re.sub(
            r"\b(so sánh|so sanh|giữa|giua)\b", " ", query, flags=re.IGNORECASE
        )
        parts = re.split(r"\b(?:vs|và|va|với|voi)\b", normalized, flags=re.IGNORECASE)
        parts = [re.sub(r"\s+", " ", p).strip(" :,.?\n\t") for p in parts if p.strip()]

        if len(parts) >= 2:
            return parts[0], parts[1]

        return None, None

    def _parse_confirmation_reply(self, query: str) -> bool | None:
        text = re.sub(r"\s+", " ", (query or "").strip().lower())
        if not text:
            return None

        yes_words = {
            "ok",
            "oke",
            "okie",
            "đúng",
            "dung",
            "đúng rồi",
            "dung roi",
            "chuẩn",
            "chuan",
            "yes",
            "y",
            "đồng ý",
            "dong y",
            "xác nhận",
            "xac nhan",
        }
        no_words = {
            "không",
            "khong",
            "sai",
            "chưa đúng",
            "chua dung",
            "không đúng",
            "khong dung",
            "no",
            "not",
        }

        if text in yes_words:
            return True
        if text in no_words:
            return False
        if any(word in text for word in ["đúng rồi", "dung roi", "ok", "yes"]):
            return True
        if any(word in text for word in ["không", "khong", "sai", "not"]):
            return False

        return None

    def _coerce_product_ref(self, product_ref: str | int | None) -> str | int | None:
        if product_ref is None:
            return None
        if isinstance(product_ref, int):
            return product_ref

        text = str(product_ref).strip()
        if not text:
            return None
        if text.isdigit():
            return int(text)

        id_match = re.fullmatch(
            r"(?:id|mã|ma)\s*[:=]?\s*(\d+)", text, flags=re.IGNORECASE
        )
        if id_match:
            return int(id_match.group(1))

        return text

    def _find_product_candidates(
        self,
        product_ref: str | int | None,
        only_pc: bool | None = None,
        limit: int = 5,
    ) -> list[Product]:
        ref = self._coerce_product_ref(product_ref)
        if ref is None:
            return []

        query = Product.query
        if only_pc is True:
            query = query.filter(Product.IsPC == 1)
        if only_pc is False:
            query = query.filter(Product.IsPC == 0)

        if isinstance(ref, int):
            found = query.filter(Product.ProductID == ref).first()
            return [found] if found else []

        name = str(ref).strip()
        exact = (
            query.filter(Product.Name.ilike(name))
            .order_by(Product.ProductID.desc())
            .limit(limit)
            .all()
        )
        if exact:
            return exact

        return (
            query.filter(Product.Name.ilike(f"%{name}%"))
            .order_by(Product.ProductID.desc())
            .limit(limit)
            .all()
        )

    def _resolve_product(
        self, product_ref: str | int | None, only_pc: bool | None = None
    ) -> Product | None:
        ref = self._coerce_product_ref(product_ref)
        if ref is None:
            return None

        query = Product.query
        if only_pc is True:
            query = query.filter(Product.IsPC == 1)
        if only_pc is False:
            query = query.filter(Product.IsPC == 0)

        if isinstance(ref, int):
            product_id = int(ref)
            return query.filter(Product.ProductID == product_id).first()

        name = str(ref).strip()
        exact = query.filter(Product.Name.ilike(name)).first()
        if exact:
            return exact

        return (
            query.filter(Product.Name.ilike(f"%{name}%"))
            .order_by(Product.ProductID.desc())
            .first()
        )

    def _resolve_brand(self, brand_ref: str | int | None) -> Brand | None:
        if brand_ref is None:
            return None

        if isinstance(brand_ref, int) or (
            isinstance(brand_ref, str) and str(brand_ref).isdigit()
        ):
            return Brand.query.filter(Brand.BrandID == int(brand_ref)).first()

        name = str(brand_ref).strip()
        exact = Brand.query.filter(Brand.Name.ilike(name)).first()
        if exact:
            return exact

        return Brand.query.filter(Brand.Name.ilike(f"%{name}%")).first()

    def _resolve_category(self, category_ref: str | int | None) -> Category | None:
        if category_ref is None:
            return None

        if isinstance(category_ref, int) or (
            isinstance(category_ref, str) and str(category_ref).isdigit()
        ):
            return Category.query.filter(
                Category.CategoryID == int(category_ref)
            ).first()

        name = str(category_ref).strip()
        exact = Category.query.filter(Category.Name.ilike(name)).first()
        if exact:
            return exact

        return Category.query.filter(Category.Name.ilike(f"%{name}%")).first()

    def _collect_descendant_category_ids(self, root_id: int) -> list[int]:
        collected: list[int] = []
        stack = [root_id]

        while stack:
            current_id = stack.pop()
            if current_id in collected:
                continue
            collected.append(current_id)
            children = (
                Category.query.filter(Category.ParentID == current_id)
                .with_entities(Category.CategoryID)
                .all()
            )
            stack.extend([child.CategoryID for child in children])

        return collected

    def _product_payload(
        self, product: Product, sold: int | None = None
    ) -> dict[str, Any]:
        return {
            "id": product.ProductID,
            "name": product.Name,
            "price": float(product.Price or 0),
            "formatted_price": f"{float(product.Price or 0):,.0f}đ",
            "stock": int(product.Stock or 0),
            "is_pc": bool(product.IsPC),
            "category": product.category.Name
            if getattr(product, "category", None)
            else None,
            "brand": product.brand.Name if getattr(product, "brand", None) else None,
            "image_url": product.ImageURL,
            "url": f"/product/{product.ProductID}",
            "sold": sold,
        }

    def _tool_add_to_cart(
        self,
        product_ref: str | int | None,
        quantity: int | None,
        user_id: int | None,
    ) -> GraphState:
        # Defensive fallback: recover authenticated user from current Flask session
        # in case route-level user detection is temporarily out of sync.
        if user_id is None:
            try:
                from flask import session as flask_session

                fallback_user_id = flask_session.get("user_id")
                if fallback_user_id:
                    user_id = int(fallback_user_id)
            except Exception:
                user_id = None

        if user_id is not None:
            user_row = User.query.filter(User.UserID == int(user_id)).first()
            if not user_row or user_row.IsDelete is True:
                user_id = None

        product = self._resolve_product(product_ref=product_ref)

        if not product:
            return {
                "response": "Mình chưa xác định được sản phẩm cần thêm vào giỏ. Bạn gửi lại tên hoặc ID sản phẩm nhé.",
                "products": [],
                "new_pending_action": None,
            }

        if quantity is None:
            return {
                "response": f"Bạn muốn thêm bao nhiêu cho {product.Name}? Vui lòng trả lời số lượng (ví dụ: 2).",
                "products": [self._product_payload(product)],
                "new_pending_action": {
                    "type": "await_add_to_cart_quantity",
                    "product_ref": product.ProductID,
                    "product_label": product.Name,
                },
            }

        if quantity <= 0:
            return {
                "response": "Số lượng phải lớn hơn 0. Bạn nhập lại giúp mình nhé.",
                "products": [],
                "new_pending_action": {
                    "type": "await_add_to_cart_quantity",
                    "product_ref": product.ProductID,
                    "product_label": product.Name,
                },
            }

        if user_id is None:
            login_url = "/login"
            return {
                "response": (
                    f"Để thêm {product.Name} vào giỏ hàng, bạn vui lòng đăng nhập tại: {login_url}"
                ),
                "products": [self._product_payload(product)],
                "requires_login": True,
                "login_url": login_url,
                "new_pending_action": None,
            }

        if product.Stock is not None and quantity > int(product.Stock):
            return {
                "response": (
                    f"Số lượng tồn kho hiện tại của {product.Name} là {product.Stock}. "
                    "Bạn vui lòng chọn số lượng nhỏ hơn."
                ),
                "products": [self._product_payload(product)],
                "new_pending_action": {
                    "type": "await_add_to_cart_quantity",
                    "product_ref": product.ProductID,
                    "product_label": product.Name,
                },
            }

        cart = Cart.query.filter_by(UserID=user_id).first()
        if not cart:
            cart = Cart(UserID=user_id)
            db.session.add(cart)
            db.session.flush()

        cart_detail = CartDetail.query.filter_by(
            CartID=cart.CartID,
            ProductID=product.ProductID,
            ConfigData=None,
        ).first()

        current_quantity = cart_detail.Quantity if cart_detail else 0
        target_quantity = current_quantity + quantity

        if product.Stock is not None and target_quantity > int(product.Stock):
            return {
                "response": (
                    f"Tổng số lượng sau khi thêm vượt quá tồn kho ({product.Stock}). "
                    "Bạn vui lòng giảm số lượng."
                ),
                "products": [self._product_payload(product)],
                "new_pending_action": {
                    "type": "await_add_to_cart_quantity",
                    "product_ref": product.ProductID,
                    "product_label": product.Name,
                },
            }

        if cart_detail:
            cart_detail.Quantity = target_quantity
        else:
            cart_detail = CartDetail(
                CartID=cart.CartID,
                ProductID=product.ProductID,
                Quantity=quantity,
                Price=product.Price,
                ConfigData=None,
            )
            db.session.add(cart_detail)

        db.session.commit()

        return {
            "response": (
                f"Đã thêm {quantity} x {product.Name} vào giỏ hàng thành công. "
                "Bạn có thể xem sản phẩm tại /product/"
                f"{product.ProductID}"
            ),
            "products": [self._product_payload(product)],
            "new_pending_action": None,
        }

    def _tool_product_detail(self, product_ref: str | int | None) -> GraphState:
        if product_ref is None:
            return {
                "response": "Bạn vui lòng cung cấp tên hoặc ID sản phẩm cần xem chi tiết.",
                "products": [],
                "new_pending_action": None,
            }

        product = self._resolve_product(product_ref=product_ref)
        if not product:
            return {
                "response": "Mình không tìm thấy sản phẩm theo thông tin bạn cung cấp.",
                "products": [],
                "new_pending_action": None,
            }

        specs_text = (product.Specs or "").strip()
        if len(specs_text) > 280:
            specs_text = specs_text[:280] + "..."

        message = (
            f"Chi tiết sản phẩm: {product.Name}\n"
            f"- ID: {product.ProductID}\n"
            f"- Giá: {float(product.Price or 0):,.0f}đ\n"
            f"- Tồn kho: {product.Stock}\n"
            f"- Hãng: {product.brand.Name if product.brand else 'N/A'}\n"
            f"- Loại: {product.category.Name if product.category else 'N/A'}\n"
            f"- Link: /product/{product.ProductID}"
        )

        if specs_text:
            message += f"\n- Mô tả ngắn: {specs_text}"

        return {
            "response": message,
            "products": [self._product_payload(product)],
            "new_pending_action": None,
        }

    def _tool_products_by_brand(self, brand_ref: str | int | None) -> GraphState:
        brand = self._resolve_brand(brand_ref)
        if not brand:
            return {
                "response": "Bạn vui lòng cung cấp đúng tên hoặc ID hãng để mình lọc sản phẩm.",
                "products": [],
                "new_pending_action": None,
            }

        products = (
            Product.query.filter(Product.BrandID == brand.BrandID)
            .order_by(Product.CreatedAt.desc())
            .limit(20)
            .all()
        )

        if not products:
            return {
                "response": f"Hiện chưa có sản phẩm nào thuộc hãng {brand.Name}.",
                "products": [],
                "new_pending_action": None,
            }

        payload = [self._product_payload(item) for item in products]
        lines = [
            f"{idx}. {item['name']} - {item['formatted_price']} - {item['url']}"
            for idx, item in enumerate(payload, start=1)
        ]

        return {
            "response": (
                f"Danh sách sản phẩm theo hãng {brand.Name}:\n" + "\n".join(lines)
            ),
            "products": payload,
            "new_pending_action": None,
        }

    def _tool_products_by_category(self, category_ref: str | int | None) -> GraphState:
        category = self._resolve_category(category_ref)
        if not category:
            return {
                "response": "Bạn vui lòng cung cấp đúng tên hoặc ID loại sản phẩm để mình lọc danh sách.",
                "products": [],
                "new_pending_action": None,
            }

        category_ids = self._collect_descendant_category_ids(category.CategoryID)
        products = (
            Product.query.filter(Product.CategoryID.in_(category_ids))
            .order_by(Product.CreatedAt.desc())
            .limit(20)
            .all()
        )

        if not products:
            return {
                "response": f"Hiện chưa có sản phẩm thuộc loại {category.Name}.",
                "products": [],
                "new_pending_action": None,
            }

        payload = [self._product_payload(item) for item in products]
        lines = [
            f"{idx}. {item['name']} - {item['formatted_price']} - {item['url']}"
            for idx, item in enumerate(payload, start=1)
        ]

        return {
            "response": (
                f"Danh sách sản phẩm theo loại {category.Name}:\n" + "\n".join(lines)
            ),
            "products": payload,
            "new_pending_action": None,
        }

    def _build_compare_preview(
        self,
        first_product: Product,
        second_product: Product,
        first_candidates: list[Product],
        second_candidates: list[Product],
    ) -> str:
        lines = [
            "Mình đã tìm được 2 sản phẩm để so sánh:",
            (
                f"- SP 1: {first_product.Name} (ID: {first_product.ProductID}) - "
                f"{float(first_product.Price or 0):,.0f}đ - /product/{first_product.ProductID}"
            ),
            (
                f"- SP 2: {second_product.Name} (ID: {second_product.ProductID}) - "
                f"{float(second_product.Price or 0):,.0f}đ - /product/{second_product.ProductID}"
            ),
        ]

        if len(first_candidates) > 1:
            options = ", ".join(
                [f"{item.Name} (ID:{item.ProductID})" for item in first_candidates[:3]]
            )
            lines.append(f"Gợi ý gần đúng cho SP 1: {options}")

        if len(second_candidates) > 1:
            options = ", ".join(
                [f"{item.Name} (ID:{item.ProductID})" for item in second_candidates[:3]]
            )
            lines.append(f"Gợi ý gần đúng cho SP 2: {options}")

        lines.append("Nếu đúng, bạn trả lời: đúng.")
        lines.append(
            "Nếu chưa đúng, bạn copy đúng tên đầy đủ hoặc gửi ID của 2 sản phẩm để mình tìm lại."
        )
        return "\n".join(lines)

    def _format_compare_details(self, product: Product, label: str) -> str:
        specs_text = (product.Specs or "").strip()
        if len(specs_text) > 300:
            specs_text = specs_text[:300] + "..."
        return (
            f"{label}: {product.Name}\n"
            f"- ID: {product.ProductID}\n"
            f"- Giá: {float(product.Price or 0):,.0f}đ\n"
            f"- Tồn kho: {int(product.Stock or 0)}\n"
            f"- Hãng: {product.brand.Name if product.brand else 'N/A'}\n"
            f"- Danh mục: {product.category.Name if product.category else 'N/A'}\n"
            f"- Link: /product/{product.ProductID}\n"
            f"- Mô tả: {specs_text or 'N/A'}"
        )

    def _tool_compare_products_detailed(
        self,
        first_ref: str | int | None,
        second_ref: str | int | None,
        history: list[dict[str, Any]],
        force_compare: bool,
    ) -> GraphState:
        if first_ref is None or second_ref is None:
            return {
                "response": (
                    "Để so sánh chi tiết, bạn vui lòng cung cấp đủ 2 sản phẩm theo tên hoặc ID. "
                    "Ví dụ: so sánh id 12 và Lenovo Legion 5."
                ),
                "products": [],
                "new_pending_action": None,
            }

        first_candidates = self._find_product_candidates(first_ref, only_pc=None)
        second_candidates = self._find_product_candidates(second_ref, only_pc=None)

        if not first_candidates or not second_candidates:
            not_found_parts: list[str] = []
            if not first_candidates:
                not_found_parts.append(f"SP 1 ({first_ref})")
            if not second_candidates:
                not_found_parts.append(f"SP 2 ({second_ref})")
            return {
                "response": (
                    f"Mình chưa tìm thấy: {', '.join(not_found_parts)}. "
                    "Bạn vui lòng copy đúng tên sản phẩm hoặc gửi ID để mình xử lý chính xác."
                ),
                "products": [],
                "new_pending_action": None,
            }

        first_product = first_candidates[0]
        second_product = second_candidates[0]

        if first_product.ProductID == second_product.ProductID:
            return {
                "response": (
                    "Bạn đang chọn cùng một sản phẩm ở cả 2 phía so sánh. "
                    "Vui lòng gửi lại 2 sản phẩm khác nhau."
                ),
                "products": [self._product_payload(first_product)],
                "new_pending_action": None,
            }

        if not force_compare:
            return {
                "response": self._build_compare_preview(
                    first_product=first_product,
                    second_product=second_product,
                    first_candidates=first_candidates,
                    second_candidates=second_candidates,
                ),
                "products": [
                    self._product_payload(first_product),
                    self._product_payload(second_product),
                ],
                "new_pending_action": {
                    "type": "await_compare_products_confirmation",
                    "first_product_id": first_product.ProductID,
                    "second_product_id": second_product.ProductID,
                },
            }

        advice = self._generate_compare_advice(first_product, second_product, history)
        return {
            "response": (
                "Kết quả so sánh chi tiết:\n"
                + self._format_compare_details(first_product, "Sản phẩm 1")
                + "\n\n"
                + self._format_compare_details(second_product, "Sản phẩm 2")
                + "\n\nTư vấn: "
                + advice
            ),
            "products": [
                self._product_payload(first_product),
                self._product_payload(second_product),
            ],
            "new_pending_action": None,
        }

    def _tool_compare_pc(
        self,
        first_ref: str | int | None,
        second_ref: str | int | None,
        history: list[dict[str, Any]],
    ) -> GraphState:
        if first_ref is None or second_ref is None:
            return {
                "response": (
                    "Để so sánh cấu hình 2 PC, bạn vui lòng cung cấp đủ 2 tên hoặc 2 ID sản phẩm. "
                    "Ví dụ: so sánh id 101 và id 205"
                ),
                "products": [],
                "new_pending_action": None,
            }

        pc_one = self._resolve_product(first_ref, only_pc=True)
        pc_two = self._resolve_product(second_ref, only_pc=True)

        if not pc_one or not pc_two:
            return {
                "response": "Mình không tìm đủ 2 sản phẩm PC để so sánh. Bạn kiểm tra lại tên hoặc ID nhé.",
                "products": [],
                "new_pending_action": None,
            }

        if pc_one.ProductID == pc_two.ProductID:
            return {
                "response": "Bạn đang chọn cùng một sản phẩm cho cả hai phía so sánh. Vui lòng chọn 2 PC khác nhau.",
                "products": [self._product_payload(pc_one)],
                "new_pending_action": None,
            }

        advice = self._generate_compare_advice(pc_one, pc_two, history)
        comparison = (
            f"So sánh nhanh:\n"
            f"- PC 1: {pc_one.Name} | Giá: {float(pc_one.Price or 0):,.0f}đ | Tồn: {pc_one.Stock} | Link: /product/{pc_one.ProductID}\n"
            f"- PC 2: {pc_two.Name} | Giá: {float(pc_two.Price or 0):,.0f}đ | Tồn: {pc_two.Stock} | Link: /product/{pc_two.ProductID}\n"
        )

        specs_one = (pc_one.Specs or "").strip()
        specs_two = (pc_two.Specs or "").strip()
        if specs_one:
            comparison += f"- Mô tả PC 1: {specs_one[:220]}{'...' if len(specs_one) > 220 else ''}\n"
        if specs_two:
            comparison += f"- Mô tả PC 2: {specs_two[:220]}{'...' if len(specs_two) > 220 else ''}\n"

        return {
            "response": comparison + "\nTư vấn: " + advice,
            "products": [self._product_payload(pc_one), self._product_payload(pc_two)],
            "new_pending_action": None,
        }

    def _tool_top_selling_pc(self) -> GraphState:
        rows = (
            db.session.query(Product, func.sum(OrderDetail.Quantity).label("sold_qty"))
            .join(OrderDetail, Product.ProductID == OrderDetail.ProductID)
            .filter(Product.IsPC == 1)
            .group_by(Product.ProductID)
            .order_by(func.sum(OrderDetail.Quantity).desc())
            .limit(6)
            .all()
        )

        payload: list[dict[str, Any]] = []
        for product, sold_qty in rows:
            payload.append(self._product_payload(product, sold=int(sold_qty or 0)))

        if not payload:
            latest_pcs = (
                Product.query.filter(Product.IsPC == 1)
                .order_by(Product.CreatedAt.desc())
                .limit(6)
                .all()
            )
            payload = [self._product_payload(item, sold=0) for item in latest_pcs]

        if not payload:
            return {
                "response": "Hiện chưa có dữ liệu sản phẩm PC để thống kê bán chạy.",
                "products": [],
                "new_pending_action": None,
            }

        lines = [
            (
                f"{idx}. {item['name']} - {item['formatted_price']} - "
                f"Đã bán: {item.get('sold', 0)} - {item['url']}"
            )
            for idx, item in enumerate(payload, start=1)
        ]

        return {
            "response": "Top sản phẩm PC bán chạy tại shop:\n" + "\n".join(lines),
            "products": payload,
            "new_pending_action": None,
        }

    def _generate_compare_advice(
        self,
        pc_one: Product,
        pc_two: Product,
        history: list[dict[str, Any]],
    ) -> str:
        prompt = (
            f"{self._brand_system_prompt()}\n"
            "Hãy so sánh 2 sản phẩm và đưa khuyến nghị ngắn gọn (3-5 câu), "
            "nêu rõ trường hợp nên chọn từng máy.\n"
            f"PC1: {pc_one.Name} | Giá: {pc_one.Price} | Tồn kho: {pc_one.Stock} | Specs: {pc_one.Specs}\n"
            f"PC2: {pc_two.Name} | Giá: {pc_two.Price} | Tồn kho: {pc_two.Stock} | Specs: {pc_two.Specs}\n"
            f"Lịch sử hội thoại gần đây: {json.dumps(history[-6:], ensure_ascii=False)}"
        )

        generated = self._invoke_llm(prompt)
        if generated:
            return generated.strip()

        # Heuristic fallback when LLM is not available.
        one_price = float(pc_one.Price or 0)
        two_price = float(pc_two.Price or 0)

        if one_price < two_price:
            cheaper = pc_one.Name
            expensive = pc_two.Name
        elif two_price < one_price:
            cheaper = pc_two.Name
            expensive = pc_one.Name
        else:
            cheaper = "cả hai"
            expensive = "cả hai"

        if cheaper == "cả hai":
            return (
                "Hai cấu hình có mức giá tương đương. Bạn nên ưu tiên máy có mô tả cấu hình đúng nhu cầu "
                "(gaming/render/văn phòng) và tình trạng tồn kho tốt hơn."
            )

        return (
            f"Nếu bạn ưu tiên ngân sách, nên chọn {cheaper}. "
            f"Nếu cần cấu hình cao hơn và chấp nhận chi phí lớn hơn, cân nhắc {expensive}. "
            "Bạn có thể gửi thêm nhu cầu sử dụng (game nào, phần mềm nào) để mình tư vấn sâu hơn."
        )

    def _answer_with_rag(self, query: str, history: list[dict[str, Any]]) -> str:
        contexts = self._retrieve_rag_context(query, top_k=4)
        context_text = "\n\n".join(
            [f"Nguồn: {item['source']}\n{item['content']}" for item in contexts]
        )

        prompt = (
            f"{self._brand_system_prompt()}\n"
            "Trả lời ngắn gọn, rõ ràng. "
            "Nếu câu hỏi không thuộc phạm vi bán hàng/CSKH thì điều hướng nhẹ nhàng về phạm vi hỗ trợ.\n\n"
            f"Lịch sử hội thoại gần đây:\n{json.dumps(history[-8:], ensure_ascii=False)}\n\n"
            f"Ngữ cảnh RAG từ tài liệu hệ thống:\n{context_text}\n\n"
            f"Câu hỏi người dùng: {query}\n"
        )

        generated = self._invoke_llm(prompt)
        if generated:
            return generated.strip()

        if contexts:
            return (
                "Mình đã tra trong tài liệu hệ thống và thấy thông tin liên quan, "
                "nhưng hiện không gọi được mô hình để diễn giải chi tiết. "
                "Bạn có thể hỏi cụ thể hơn theo dạng: tên sản phẩm, hãng, loại hoặc so sánh 2 mã PC."
            )

        return (
            "Mình chưa có đủ thông tin để trả lời chính xác. "
            "Bạn muốn mình hỗ trợ theo hướng nào: xem chi tiết sản phẩm, lọc theo hãng/loại, "
            "hay so sánh 2 PC?"
        )

    def _invoke_llm(self, prompt: str) -> str | None:
        if self._llm is None:
            return None

        try:
            response = self._llm.invoke(prompt)
        except Exception as exc:
            current_app.logger.warning("Ollama invoke failed: %s", exc)
            return None

        content = getattr(response, "content", response)
        if isinstance(content, list):
            content = " ".join(str(item) for item in content)

        text = str(content).strip()
        return text or None

    def _retrieve_rag_context(self, query: str, top_k: int) -> list[dict[str, str]]:
        vector_store = self._get_or_build_vector_store()

        if vector_store is not None:
            try:
                docs = vector_store.similarity_search(query, k=top_k)
                return [
                    {
                        "source": str(doc.metadata.get("source", "unknown")),
                        "content": str(doc.page_content)[:900],
                    }
                    for doc in docs
                ]
            except Exception as exc:
                current_app.logger.warning("FAISS retrieval failed: %s", exc)

        # Keyword fallback when vector retrieval is unavailable.
        return self._keyword_retrieve(query=query, top_k=top_k)

    def _get_or_build_vector_store(self):
        if not LANGCHAIN_AVAILABLE or self._embeddings is None:
            return None

        if self._vector_store is not None:
            return self._vector_store

        with self._vector_lock:
            if self._vector_store is not None:
                return self._vector_store

            try:
                if (self.vector_store_dir / "index.faiss").exists() and (
                    self.vector_store_dir / "index.pkl"
                ).exists():
                    self._vector_store = FAISS.load_local(
                        str(self.vector_store_dir),
                        self._embeddings,
                        allow_dangerous_deserialization=True,
                    )
                    return self._vector_store

                documents = self._load_rag_documents()
                if not documents:
                    return None

                splitter = RecursiveCharacterTextSplitter(
                    chunk_size=1200,
                    chunk_overlap=180,
                )
                chunks = splitter.split_documents(documents)
                if not chunks:
                    return None

                self._vector_store = FAISS.from_documents(chunks, self._embeddings)
                self.vector_store_dir.mkdir(parents=True, exist_ok=True)
                self._vector_store.save_local(str(self.vector_store_dir))
                return self._vector_store
            except Exception as exc:
                current_app.logger.warning("Cannot initialize FAISS DB: %s", exc)
                return None

    def _load_rag_documents(self) -> list[Document]:
        targets: list[Path] = []
        patterns = [
            "README.md",
            "KIEN_TRUC_TONG_QUAN.md",
            "config/sql.sql",
            "app.py",
            "routes/*.py",
            "models/*.py",
            "templates/frontend/pages/*.html",
            "templates/backend/pages/*.html",
        ]

        for pattern in patterns:
            targets.extend(self.app_root.glob(pattern))

        # Keep deterministic order and avoid duplicates.
        unique_paths = sorted(set(path for path in targets if path.is_file()))

        docs: list[Document] = []
        self._raw_docs = []

        for path in unique_paths:
            try:
                content = path.read_text(encoding="utf-8", errors="ignore")
            except Exception:
                continue

            relative = path.relative_to(self.app_root).as_posix()
            self._raw_docs.append((relative, content))
            if LANGCHAIN_AVAILABLE and Document is not Any:
                docs.append(
                    Document(page_content=content, metadata={"source": relative})
                )

        for row in self._list_active_admin_documents():
            content = (row.Content or "").strip()
            if not content:
                continue

            source_name = (row.SourceName or "").strip()
            source = source_name or f"admin:{row.Title}#{row.ChatbotDocumentID}"

            self._raw_docs.append((source, content))
            if LANGCHAIN_AVAILABLE and Document is not Any:
                docs.append(
                    Document(
                        page_content=content,
                        metadata={
                            "source": source,
                            "title": row.Title,
                            "doc_id": row.ChatbotDocumentID,
                        },
                    )
                )

        return docs

    def _list_active_admin_documents(self) -> list[ChatbotDocument]:
        try:
            inspector = inspect(db.engine)
            if ChatbotDocument.__tablename__ not in inspector.get_table_names():
                return []
            return (
                ChatbotDocument.query.filter_by(IsDelete=False)
                .order_by(ChatbotDocument.UpdatedAt.desc())
                .all()
            )
        except Exception as exc:
            current_app.logger.warning("Cannot read chatbot documents: %s", exc)
            return []

    def _keyword_retrieve(self, query: str, top_k: int) -> list[dict[str, str]]:
        if not self._raw_docs:
            self._load_rag_documents()

        if not self._raw_docs:
            return []

        tokens = [token for token in re.split(r"\W+", query.lower()) if len(token) > 2]
        if not tokens:
            return []

        scored: list[tuple[int, str, str]] = []
        for source, content in self._raw_docs:
            lower_content = content.lower()
            score = sum(token in lower_content for token in tokens)
            if score <= 0:
                continue
            excerpt = content[:900]
            scored.append((score, source, excerpt))

        scored.sort(key=lambda item: item[0], reverse=True)
        return [
            {"source": source, "content": excerpt}
            for _, source, excerpt in scored[:top_k]
        ]


def get_chatbot_service() -> SalesSupportChatbot:
    app = current_app._get_current_object()
    service = app.extensions.get("sales_support_chatbot")
    if service is None:
        service = SalesSupportChatbot(
            app_root=Path(app.root_path),
            instance_path=Path(app.instance_path),
        )
        app.extensions["sales_support_chatbot"] = service
    return service
