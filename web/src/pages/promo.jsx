import { useState } from 'react'
import { get, post } from '../api.js'
import { useMe } from '../auth.js'
import { BarChart } from '../charts.jsx'
import { Badge, Btn, Card, Field, Loading, Page, Stat, Table, day, money, num, pct, useAction, useApi } from '../ui.jsx'

const OPTION_NAMES = {
  toi_uu_ngan_sach: 'Tối ưu trong ngân sách',
  tiet_kiem_70pct: 'Tiết kiệm (70% ngân sách)',
  dong_deu_hien_tai: 'Giảm đồng đều (cách làm hiện tại)',
}

// ---- PH1 CN1 (tối thiểu): chương trình khuyến mãi -------------------------------------------

export function PromotionsPage() {
  const me = useMe()
  const q = useApi('/ph1/promotions')
  const products = useApi('/ph0/products')
  const [run, busy] = useAction()
  const [f, setF] = useState({ ten: '', ma_sp: 'SP02', muc_giam: 5, sl_toi_thieu: 5, tu_ngay: '2026-11-02', den_ngay: '2026-11-15', ngan_sach: 3000000 })

  const create = async () => {
    const body = { ...f, muc_giam: Number(f.muc_giam) / 100, sl_toi_thieu: Number(f.sl_toi_thieu), ngan_sach: Number(f.ngan_sach) }
    if (await run(() => post('/ph1/promotions', body), (r) => `Đã lập ${r.ma_km} – chờ giám đốc KD duyệt`)) q.reload()
  }
  const approve = async (ma) => {
    if (await run(() => post(`/ph1/promotions/${ma}/approve`), 'Đã duyệt – chương trình bị khóa, không sửa khi đang chạy')) q.reload()
  }

  return (
    <Page title="Chương trình khuyến mãi" sub="Phòng KD lập, giám đốc KD duyệt (người duyệt khác người lập – BR-13); ngân sách trừ có điều kiện, không chi vượt (BR-11)"
          actions={<Btn kind="ghost" onClick={q.reload}>Tải lại</Btn>}>
      {me.vai_tro === 'pkd' && (
        <Card title="Lập chương trình">
          <div className="form-row">
            <Field label="Tên"><input value={f.ten} onChange={(e) => setF({ ...f, ten: e.target.value })} placeholder="VD: Sữa chua tháng 11" /></Field>
            <Field label="Sản phẩm">
              <select value={f.ma_sp} onChange={(e) => setF({ ...f, ma_sp: e.target.value })}>
                {(products.data || []).map((p) => <option key={p.ma_sp} value={p.ma_sp}>{p.ma_sp} – {p.ten}</option>)}
              </select>
            </Field>
            <Field label="Giảm (%)"><input type="number" value={f.muc_giam} onChange={(e) => setF({ ...f, muc_giam: e.target.value })} /></Field>
            <Field label="Mua từ (thùng)"><input type="number" value={f.sl_toi_thieu} onChange={(e) => setF({ ...f, sl_toi_thieu: e.target.value })} /></Field>
            <Field label="Từ ngày"><input type="date" value={f.tu_ngay} onChange={(e) => setF({ ...f, tu_ngay: e.target.value })} /></Field>
            <Field label="Đến ngày"><input type="date" value={f.den_ngay} onChange={(e) => setF({ ...f, den_ngay: e.target.value })} /></Field>
            <Field label="Ngân sách (đ)"><input type="number" style={{ width: 140 }} value={f.ngan_sach} onChange={(e) => setF({ ...f, ngan_sach: e.target.value })} /></Field>
            <Btn busy={busy} disabled={!f.ten} onClick={create}>Lập</Btn>
          </div>
        </Card>
      )}
      <Card>
        <Loading q={q} empty="Chưa có chương trình">
          {(rows) => <Table rows={rows} rowKey={(r) => r.ma_km} cols={[
            { label: 'Mã', render: (r) => <span className="mono">{r.ma_km}</span> },
            { label: 'Tên', key: 'ten' },
            { label: 'SP', key: 'ma_sp' },
            { label: 'Giảm', num: true, render: (r) => r.muc_giam_theo_don_vi ? 'theo đơn vị' : pct(r.muc_giam, 0) },
            { label: 'Thời gian', render: (r) => `${day(r.tu_ngay)} – ${day(r.den_ngay)}` },
            { label: 'Đã dùng / ngân sách', num: true, render: (r) => `${money(r.da_dung)} / ${money(r.ngan_sach)}` },
            { label: 'Nguồn', render: (r) => r.nguon === 'ph2_xa_lo' ? <Badge kind="warn">Xả lô (PH2 NC2)</Badge> : r.nguon === 'nc1' ? <Badge kind="info">NC1</Badge> : 'PKD' },
            { label: 'Trạng thái', render: (r) => <Badge value={r.trang_thai} /> },
            { label: '', render: (r) => me.vai_tro === 'gdkd' && ['nhap', 'de_xuat'].includes(r.trang_thai) && <Btn sm busy={busy} onClick={() => approve(r.ma_km)}>Duyệt</Btn> },
          ]} />}
        </Loading>
      </Card>
    </Page>
  )
}

// ---- PH1 NC1: đề xuất và đánh giá hiệu quả KM -----------------------------------------------

export function PromoNC1Page() {
  const products = useApi('/ph0/products')
  const promos = useApi('/ph1/promotions')
  const [run, busy] = useAction()
  const [f, setF] = useState({ ma_sp: 'SP03', tu_ngay: '2026-11-02', den_ngay: '2026-11-15', ngan_sach: 5000000 })
  const [res, setRes] = useState(null)
  const [pick, setPick] = useState(0)
  const [reason, setReason] = useState('')
  const [created, setCreated] = useState(null)
  const [evalKm, setEvalKm] = useState('KMH-1')
  const [evalRes, setEvalRes] = useState(null)

  const propose = async () => {
    const r = await run(() => post('/ph1/nc1/propose', { ...f, ngan_sach: Number(f.ngan_sach) }), 'Đã tính 3 phương án')
    if (r) { setRes(r); setPick(0); setCreated(null) }
  }
  const create = async () => {
    const r = await run(() => post(`/ph1/nc1/${res.ma_pa}/create-program`, { chi_so: pick, ly_do: reason || null }),
      (x) => `Đã tạo chương trình nháp ${x.ma_km} – chờ giám đốc KD duyệt`)
    if (r) { setCreated(r.ma_km); promos.reload() }
  }
  const evaluate = async () => {
    const r = await run(() => get(`/ph1/nc1/evaluate/${evalKm}`))
    if (r) setEvalRes(r)
  }

  const opt = res?.phuong_an[pick]
  return (
    <Page title="Đề xuất & đánh giá khuyến mãi" sub="PH1 NC1 – mô hình T-learner ước lượng sản lượng tăng thêm theo vùng × nhóm điểm bán; chọn mức giảm tối đa lợi nhuận trong ngân sách">
      <Card title="Đề xuất">
        <div className="form-row">
          <Field label="Sản phẩm">
            <select value={f.ma_sp} onChange={(e) => setF({ ...f, ma_sp: e.target.value })}>
              {(products.data || []).map((p) => <option key={p.ma_sp} value={p.ma_sp}>{p.ma_sp} – {p.ten}</option>)}
            </select>
          </Field>
          <Field label="Từ ngày"><input type="date" value={f.tu_ngay} onChange={(e) => setF({ ...f, tu_ngay: e.target.value })} /></Field>
          <Field label="Đến ngày"><input type="date" value={f.den_ngay} onChange={(e) => setF({ ...f, den_ngay: e.target.value })} /></Field>
          <Field label="Ngân sách (đ)"><input type="number" style={{ width: 140 }} value={f.ngan_sach} onChange={(e) => setF({ ...f, ngan_sach: e.target.value })} /></Field>
          <Btn busy={busy} onClick={propose}>Tính phương án</Btn>
        </div>
      </Card>

      {res && (
        <>
          <div className="grid-stats">
            <Stat label="Mô hình" value={<span style={{ fontSize: 15 }}>{res.mo_hinh}</span>} />
            <Stat label="Tỷ lệ mua dồn (sụt sau KM)" value={pct(res.ty_le_mua_don)} />
            <Stat label="Tồn khả dụng hiện tại" value={`${res.ton_kha_dung_hien_tai} thùng`} />
          </div>
          <div className="grid-2">
            <Card title="So sánh phương án">
              <Table rows={res.phuong_an} rowKey={(o) => o.ten} selected={res.phuong_an[pick]?.ten}
                     onRow={(o) => setPick(res.phuong_an.indexOf(o))} cols={[
                { label: 'Phương án', render: (o) => OPTION_NAMES[o.ten] || o.ten },
                { label: 'Chi phí', num: true, render: (o) => money(o.tong_chi_phi) },
                { label: 'LN tăng thêm', num: true, render: (o) => money(o.tong_loi_nhuan_tang_them) },
                { label: 'ROI', num: true, render: (o) => num(o.roi, 2) },
                { label: 'Tồn', render: (o) => o.canh_bao_ton ? <Badge kind="warn">Có thể thiếu hàng</Badge> : <Badge kind="good">Đủ</Badge> },
              ]} />
              <BarChart rows={res.phuong_an} label={(o) => (OPTION_NAMES[o.ten] || o.ten).split(' (')[0]} value={(o) => o.roi || 0}
                        format={(v) => num(v, 2)} valueLabel="ROI (LN tăng thêm / chi phí)" title="ROI theo phương án" />
            </Card>
            <Card title={`Chi tiết: ${OPTION_NAMES[opt.ten] || opt.ten}`}>
              <Table rows={opt.don_vi} rowKey={(d) => d.don_vi} cols={[
                { label: 'Vùng | nhóm', key: 'don_vi' },
                { label: 'Giảm', num: true, render: (d) => pct(d.muc_giam, 0) },
                { label: 'Tăng thêm', num: true, render: (d) => `${num(d.tang_them_thung, 1)} thùng` },
                { label: 'Chi phí', num: true, render: (d) => money(d.chi_phi) },
                { label: 'LN tăng thêm', num: true, render: (d) => money(d.loi_nhuan_tang_them) },
              ]} />
              <p className="muted">Đơn vị đối chứng (giữ lại không áp KM để đo hiệu quả thật): {opt.don_vi_doi_chung.join(', ') || '–'}</p>
              {pick !== 0 && (
                <Field label="Lý do chọn khác phương án tối ưu" hint="Bắt buộc – được lưu để huấn luyện lại mô hình">
                  <input value={reason} onChange={(e) => setReason(e.target.value)} />
                </Field>
              )}
              <div className="row">
                <Btn busy={busy} onClick={create}>Tạo chương trình nháp từ phương án này</Btn>
                {created && <Badge kind="good">Đã tạo {created}</Badge>}
              </div>
            </Card>
          </div>
        </>
      )}

      <Card title="Đánh giá chương trình đã chạy (difference-in-differences)">
        <div className="form-row">
          <Field label="Chương trình">
            <select value={evalKm} onChange={(e) => setEvalKm(e.target.value)}>
              {(promos.data || []).map((k) => <option key={k.ma_km} value={k.ma_km}>{k.ma_km} – {k.ten}</option>)}
            </select>
          </Field>
          <Btn kind="ghost" busy={busy} onClick={evaluate}>Đánh giá</Btn>
        </div>
        {evalRes && (evalRes.ghi_chu ? <div className="notice">{evalRes.ghi_chu}</div> : (
          <>
            <div className="grid-stats">
              <Stat label="Tăng thêm (so đối chứng)" value={`${num(evalRes.tang_them_thung, 1)} thùng`} />
              <Stat label="Sụt sau KM" value={`${num(evalRes.sut_sau_km_thung, 1)} thùng`} />
              <Stat label="Chi phí" value={money(evalRes.chi_phi)} />
              <Stat label="LN tăng thêm" value={money(evalRes.loi_nhuan_tang_them)} />
              <Stat label="ROI thật" value={num(evalRes.roi_that, 2)}
                    sub={evalRes.roi_that >= 1 ? <Badge kind="good">Có lãi</Badge> : <Badge kind="bad">Lỗ</Badge>} />
            </div>
            <p className="muted">Đơn vị áp: {evalRes.don_vi_ap.length} · Đối chứng: {evalRes.don_vi_doi_chung.join(', ')}</p>
          </>
        ))}
      </Card>
    </Page>
  )
}

// ---- PH2 NC2: điều chuyển lô vàng -----------------------------------------------------------

export function TransfersPage() {
  const q = useApi('/ph2/nc2/transfers')
  return (
    <Page title="Điều chuyển lô vàng" sub="PH2 NC2 – bài toán vận tải: chuyển phần dư lô cận hạn sang kho đang thiếu nếu giá trị cứu được lớn hơn chi phí; phần còn dư thành đề xuất KM xả lô"
          actions={<Btn kind="ghost" onClick={q.reload}>Tải lại</Btn>}>
      <Card>
        <Loading q={q} empty="Chưa có đề xuất – quản trị chạy tác vụ ph2.nc2_lo_vang">
          {(rows) => <Table rows={rows} cols={[
            { label: 'Lô', render: (r) => <span className="mono">{r.ma_lo}</span> },
            { label: 'SP', key: 'ma_sp' },
            { label: 'Từ kho', key: 'tu_kho' }, { label: 'Đến kho', key: 'den_kho' },
            { label: 'Số thùng', key: 'so_luong', num: true },
            { label: 'Giá trị cứu được', num: true, render: (r) => money(r.gia_tri_cuu) },
            { label: 'Chi phí chở', num: true, render: (r) => money(r.chi_phi_cho) },
            { label: 'Trạng thái', render: (r) => <Badge value={r.trang_thai} /> },
          ]} />}
        </Loading>
      </Card>
      <Card><p className="muted">Đề xuất KM xả lô xuất hiện ở trang Chương trình KM (nguồn “Xả lô”) để giám đốc KD duyệt.</p></Card>
    </Page>
  )
}
