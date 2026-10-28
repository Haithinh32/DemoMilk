from app.ph0_platform.models import NhatKy


def log(s, user_ma: str, hanh_dong: str, doi_tuong: str, ma_doi_tuong: str, cu=None, moi=None) -> None:
    s.add(NhatKy(ma_nguoi_dung=user_ma, hanh_dong=hanh_dong, doi_tuong=doi_tuong,
                 ma_doi_tuong=ma_doi_tuong, gia_tri_cu=cu, gia_tri_moi=moi))
