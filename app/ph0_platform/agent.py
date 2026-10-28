"""Agent Gateway – một agent dùng chung trên Zalo OA (PH1 NC2, PH3 NC2 là hai nhóm công cụ của nó).

Giới hạn quyền (Bảng 4.3, dòng Agent Zalo OA):
- Điểm bán được xác định từ zalo_id ở phía máy chủ; mô hình KHÔNG truyền mã điểm bán nên không đọc
  được dữ liệu điểm bán khác.
- Agent chỉ đọc và tạo đơn NHÁP. Đơn thật chỉ sinh khi điểm bán bấm xác nhận
  (POST /ph1/agent-drafts/{ma_nhap}/confirm), đi qua đúng luồng giữ tồn – giá – tín dụng của PH1.
- Mọi lần gọi công cụ được ghi vào nhat_ky_agent.
"""
import json
import logging

from app import config
from app.db import tx
from app.errors import DomainError
from app.ph0_platform.identity import user_by_zalo
from app.ph0_platform.models import NhatKyAgent

log = logging.getLogger("csm.agent")

SYSTEM_PROMPT = """Bạn là trợ lý đặt hàng của Cao Sơn Milk trên Zalo, nói chuyện với chủ một điểm bán (tạp hóa).
Trả lời ngắn gọn, tiếng Việt, xưng "em", gọi khách là "anh/chị".
Bạn xem được tồn kho của nhà phân phối, đơn gợi ý hôm nay, trạng thái đơn, công nợ, và tạo được mã QR thanh toán.
Bạn chỉ tạo được đơn nháp: sau khi tạo, hãy tóm tắt đơn (sản phẩm, số thùng, tổng tiền) và nhắc khách bấm nút
"Xác nhận đặt hàng" trong 30 phút. Đừng nói đơn đã được đặt khi khách chưa xác nhận.
Số liệu tiền, tồn, công nợ phải lấy từ công cụ, không tự ước lượng. Nếu công cụ báo lỗi, nói rõ cho khách."""


def _obj(props: dict, required: list[str]) -> dict:
    return {"type": "object", "properties": props, "required": required, "additionalProperties": False}


TOOLS = [
    {"name": "xem_ton_kho", "description": "Tồn khả dụng (thùng) từng sản phẩm tại NPP phụ trách điểm bán, kèm giá.",
     "input_schema": _obj({}, []), "strict": True},
    {"name": "xem_goi_y_don", "description": "Đơn gợi ý hôm nay cho điểm bán (chỉ gồm hàng còn tồn).",
     "input_schema": _obj({}, []), "strict": True},
    {"name": "tao_don_nhap",
     "description": "Tạo đơn nháp (chưa giữ hàng). Trả về mã nháp, báo giá đã áp KM và dòng bị giảm theo tồn.",
     "input_schema": _obj({"dong": {"type": "array", "items": _obj(
         {"ma_sp": {"type": "string"}, "so_luong": {"type": "integer"}}, ["ma_sp", "so_luong"])}}, ["dong"]),
     "strict": True},
    {"name": "xem_trang_thai_don", "description": "5 đơn gần nhất của điểm bán và trạng thái giao.",
     "input_schema": _obj({}, []), "strict": True},
    {"name": "xem_cong_no", "description": "Hạn mức, dư nợ, nợ quá hạn và các hóa đơn còn nợ của điểm bán.",
     "input_schema": _obj({}, []), "strict": True},
    {"name": "tao_ma_qr", "description": "Tạo mã VietQR cho một hóa đơn còn nợ của điểm bán.",
     "input_schema": _obj({"so_hoa_don": {"type": "string"}}, ["so_hoa_don"]), "strict": True},
]


def execute_tool(zalo_id: str, name: str, args: dict) -> dict:
    """Chạy một công cụ trong phạm vi điểm bán gắn với zalo_id. Dùng được cả không có LLM (kiểm thử)."""
    from app.ph1_order import contracts as ph1
    from app.ph1_order.pricing import price_cart
    from app.ph2_inventory import contracts as ph2
    from app.ph3_credit import contracts as ph3
    from app.ph4_sales import contracts as ph4
    from app import clock

    with tx() as s:
        user = user_by_zalo(s, zalo_id)
        if user is None or not user.ma_diem_ban:
            raise DomainError("ZALO_CHUA_LIEN_KET", "Tài khoản Zalo chưa liên kết điểm bán", status=403)
        outlet = ph4.get_outlet(s, user.ma_diem_ban)
        ok, result = True, None
        try:
            if name == "xem_ton_kho":
                avail = ph2.available_map(s, outlet.ma_kho)
                quote = price_cart(s, outlet, [(sp, 1) for sp in sorted(avail)], clock.today())
                result = {"san_pham": [{"ma_sp": l.ma_sp, "ton_kha_dung": avail[l.ma_sp], "don_gia": l.don_gia,
                                        "km": l.ma_km} for l in quote.dong]}
            elif name == "xem_goi_y_don":
                result = ph4.get_suggestion(s, outlet.ma_diem_ban, clock.today()) or {"dong": []}
            elif name == "tao_don_nhap":
                result = ph1.create_agent_draft(s, outlet, [(d["ma_sp"], int(d["so_luong"])) for d in args["dong"]])
            elif name == "xem_trang_thai_don":
                result = {"don": ph1.recent_orders(s, outlet.ma_diem_ban)}
            elif name == "xem_cong_no":
                result = ph3.debt_summary(s, outlet.ma_diem_ban)
            elif name == "tao_ma_qr":
                result = ph3.create_qr(s, outlet.ma_diem_ban, args["so_hoa_don"])
            else:
                raise DomainError("CONG_CU_KHONG_CO", f"Không có công cụ {name}")
        except DomainError as e:
            ok, result = False, {"loi": e.code, "thong_bao": e.message}
        s.add(NhatKyAgent(zalo_id=zalo_id, ma_diem_ban=outlet.ma_diem_ban, cong_cu=name, dau_vao=args,
                          ket_qua=json.loads(json.dumps(result, default=str)), thanh_cong=ok))
        return {"ok": ok, **(result if isinstance(result, dict) else {"ket_qua": result})}


_history: dict[str, list] = {}   # prototype: hội thoại trong bộ nhớ; thực tế lưu theo zalo_id
MAX_VONG = 8


def chat(zalo_id: str, text: str) -> dict:
    try:
        import anthropic
    except ImportError as e:
        raise DomainError("AGENT_CHUA_CAI_SDK", "Cần cài gói anthropic (pip install anthropic) và đặt ANTHROPIC_API_KEY",
                          status=503) from e
    with tx() as s:
        if user_by_zalo(s, zalo_id) is None:
            raise DomainError("ZALO_CHUA_LIEN_KET", "Tài khoản Zalo chưa liên kết điểm bán", status=403)
    client = anthropic.Anthropic()
    messages = _history.setdefault(zalo_id, [])
    messages.append({"role": "user", "content": text})
    tool_calls = []
    for _ in range(MAX_VONG):
        resp = client.beta.messages.create(
            model=config.AGENT_MODEL, max_tokens=16000, system=SYSTEM_PROMPT, tools=TOOLS, messages=messages,
            thinking={"type": "adaptive"}, output_config={"effort": "medium"},
            betas=["server-side-fallback-2026-07-01"], extra_body={"fallbacks": "default"})
        messages.append({"role": "assistant", "content": resp.content})   # chỉ nối thêm, không sửa lịch sử
        if resp.stop_reason == "refusal":
            return {"tra_loi": "Xin lỗi anh/chị, em không hỗ trợ được yêu cầu này.", "cong_cu": tool_calls}
        if resp.stop_reason == "pause_turn":
            continue
        uses = [b for b in resp.content if b.type == "tool_use"]
        if resp.stop_reason != "tool_use" or not uses:
            text_out = "".join(b.text for b in resp.content if b.type == "text")
            return {"tra_loi": text_out, "cong_cu": tool_calls}
        results = []
        for b in uses:
            try:
                out = execute_tool(zalo_id, b.name, dict(b.input))
                results.append({"type": "tool_result", "tool_use_id": b.id,
                                "content": json.dumps(out, ensure_ascii=False, default=str), "is_error": not out["ok"]})
            except DomainError as e:
                results.append({"type": "tool_result", "tool_use_id": b.id, "content": e.message, "is_error": True})
            tool_calls.append(b.name)
        messages.append({"role": "user", "content": results})
    return {"tra_loi": "Em đang xử lý hơi lâu, anh/chị nhắn lại giúp em nhé.", "cong_cu": tool_calls}
