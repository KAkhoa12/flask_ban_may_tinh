# flask_ban_may_tinh

path admin login: /admin/login

tk admin: kait 
pass admin: admin123

## Chatbot sales & CSKH (Ollama + LangGraph + FAISS)

Biến môi trường gợi ý:

- `OLLAMA_BASE_URL=http://localhost:11434`
- `OLLAMA_MODEL=gpt-oss:120b-cloud` (bạn có thể đổi sang model `:cloud` bạn đang dùng)
- `OLLAMA_EMBED_MODEL=nomic-embed-text-v2-moe:latest`
- `FAISS_DB_PATH=instance/faissdb`
- `SHOP_NAME=BanMayTinh`
- `SHOP_BRAND_TONE=chuyên nghiệp, thân thiện, trung thực`
- `SHOP_BRAND_RULES=luôn ngắn gọn, không bịa thông tin, ưu tiên đưa link sản phẩm`

Sau khi cài dependencies:

```bash
pip install -r requirements.txt
```

Các API chatbot:

- `POST /api/function-calling/`
- `POST /api/function-calling/stream` (SSE streaming)
- `GET /api/get-chat-history/`
- `POST /api/save-chat-history/`
- `POST /api/chat/reset-guest`

Guardrails hiện có:

- Chặn yêu cầu nguy hiểm/phi pháp (hack/malware/vũ khí/lừa đảo...) và từ chối an toàn.
- Điều hướng các câu hỏi ngoài phạm vi (thời tiết/chính trị/tử vi...) về phạm vi bán hàng/CSKH.
