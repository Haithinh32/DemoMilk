import { useState } from 'react'
import { post } from '../api.js'
import { useMe } from '../auth.js'
import { Badge, Btn, Card, Loading, Page, Table, day, num, useAction, useApi } from '../ui.jsx'

/** Đơn bổ sung NPP sinh từ dự báo NC2 của PH2: NPP chỉnh và gửi, phòng KD chốt. */
export function ReplenishmentPage() {
  const q = useApi('/ph1/replenishment')
  const [sel, setSel] = useState(null)
  const cur = q.data?.find((d) => d.ma_don_bs === sel)
  return (
    <Page title="Đơn bổ sung NPP" sub="Đầu ra PH2 NC2: dự báo 14 ngày → tồn mục tiêu → số thùng đề xuất. Lệch đề xuất trên 30% phải ghi lý do"
          actions={<Btn kind="ghost" onClick={q.reload}>Tải lại</Btn>}>
      <div className="grid-2">
        <Card title="Danh sách">
          <Loading q={q} empty="Chưa có đơn bổ sung – quản trị chạy tác vụ ph2.nc2_du_bao_bo_sung">
            {(rows) => <Table rows={rows} rowKey={(r) => r.ma_don_bs} selected={sel} onRow={(r) => setSel(r.ma_don_bs)} cols={[
              { label: 'Mã', render: (r) => <span className="mono">{r.ma_don_bs}</span> },
              { label: 'NPP', key: 'ma_npp' }, { label: 'Kho', key: 'ma_kho' },
              { label: 'Ngày', render: (r) => day(r.ngay) },
              { label: 'Trạng thái', render: (r) => <Badge value={r.trang_thai} /> },
            ]} />}
          </Loading>
        </Card>
        {cur ? <ReplenishDetail key={cur.ma_don_bs + cur.trang_thai} d={cur} onDone={q.reload} />
          : <Card><p className="muted">Chọn một đơn bổ sung.</p></Card>}
      </div>
    </Page>
  )
}

function ReplenishDetail({ d, onDone }) {
  const me = useMe()
  const [run, busy] = useAction()
  const [edit, setEdit] = useState(Object.fromEntries(d.dong.map((l) => [l.ma_sp, { so_luong: l.so_luong, ly_do: l.ly_do_lech || '' }])))
  const editable = me.vai_tro === 'npp' && d.trang_thai === 'de_xuat'
  const set = (sp, k, v) => setEdit((x) => ({ ...x, [sp]: { ...x[sp], [k]: v } }))

  const submit = async () => {
    const dieu_chinh = Object.fromEntries(Object.entries(edit).map(([sp, v]) => [sp, { so_luong: Number(v.so_luong), ly_do: v.ly_do || null }]))
    if (await run(() => post(`/ph1/replenishment/${d.ma_don_bs}/submit`, { dieu_chinh }), 'Đã gửi đơn bổ sung lên công ty')) onDone()
  }
  const confirm = async () => {
    if (await run(() => post(`/ph1/replenishment/${d.ma_don_bs}/confirm`), 'Đã chốt đơn bổ sung')) onDone()
  }

  return (
    <Card title={d.ma_don_bs}>
      <Table rows={d.dong} rowKey={(l) => l.ma_sp} cols={[
        { label: 'SP', key: 'ma_sp' },
        { label: 'Dự báo/ngày', num: true, render: (l) => num(l.can_cu?.du_bao_ngay, 1) },
        { label: 'Tồn khả dụng', num: true, render: (l) => l.can_cu?.ton_kha_dung },
        { label: 'Đang về', num: true, render: (l) => l.can_cu?.hang_dang_ve },
        { label: 'Tồn mục tiêu', num: true, render: (l) => num(l.can_cu?.ton_muc_tieu, 1) },
        { label: 'Đề xuất', num: true, key: 'de_xuat' },
        { label: 'Đặt', num: true, render: (l) => editable
          ? <input type="number" min="0" value={edit[l.ma_sp].so_luong} aria-label={`Số thùng ${l.ma_sp}`} onChange={(e) => set(l.ma_sp, 'so_luong', e.target.value)} />
          : l.so_luong },
        { label: 'Lý do lệch', render: (l) => editable
          ? <input value={edit[l.ma_sp].ly_do} aria-label={`Lý do lệch ${l.ma_sp}`} onChange={(e) => set(l.ma_sp, 'ly_do', e.target.value)} />
          : l.ly_do_lech || '–' },
      ]} />
      <div className="row">
        {editable && <Btn busy={busy} onClick={submit}>Gửi lên công ty</Btn>}
        {me.vai_tro === 'pkd' && d.trang_thai === 'da_gui' && <Btn busy={busy} onClick={confirm}>Chốt đơn</Btn>}
        {!editable && !(me.vai_tro === 'pkd' && d.trang_thai === 'da_gui') && <span className="muted">Không có thao tác cho vai trò này ở trạng thái hiện tại.</span>}
      </div>
    </Card>
  )
}
