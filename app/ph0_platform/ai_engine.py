"""AI Engine dùng chung: chọn thư viện mô hình và bộ giải tối ưu.

Thiết kế dùng LightGBM và OR-Tools; khi chưa cài, dùng HistGradientBoosting của scikit-learn
(cùng họ cây tăng cường theo histogram) và SciPy (milp, linprog). Trường BACKEND cho biết đang dùng gì
để báo cáo ghi đúng.
"""
import numpy as np

try:  # pragma: no cover - tùy môi trường
    import lightgbm as _lgb
except ImportError:  # pragma: no cover
    _lgb = None

BACKEND = "lightgbm" if _lgb else "sklearn-hgb"


def regressor(loss: str = "squared_error"):
    if _lgb:
        return _lgb.LGBMRegressor(objective="poisson" if loss == "poisson" else "regression",
                                  n_estimators=300, learning_rate=0.05, verbose=-1)
    from sklearn.ensemble import HistGradientBoostingRegressor
    return HistGradientBoostingRegressor(loss=loss, max_iter=300, learning_rate=0.05, random_state=0)


def classifier():
    if _lgb:
        return _lgb.LGBMClassifier(n_estimators=300, learning_rate=0.05, verbose=-1)
    from sklearn.ensemble import HistGradientBoostingClassifier
    return HistGradientBoostingClassifier(max_iter=300, learning_rate=0.05, random_state=0)


def solve_mckp(profit: np.ndarray, cost: np.ndarray, budget: float) -> list[int | None]:
    """Bài toán cái túi nhiều lựa chọn (NC1 PH1): mỗi nhóm i chọn tối đa một mức m.

    max Σ profit[i,m]·x[i,m]  s.t.  Σ cost[i,m]·x[i,m] ≤ budget,  Σ_m x[i,m] ≤ 1,  x ∈ {0,1}.
    Tổ hợp lợi nhuận âm bị loại trước. Trả về mức được chọn cho từng nhóm (None = không áp KM).
    """
    from scipy.optimize import Bounds, LinearConstraint, milp

    n, k = profit.shape
    usable = (profit > 0) & (cost <= budget)
    if not usable.any():
        return [None] * n
    c = -np.where(usable, profit, 0).ravel()
    ub = usable.astype(float).ravel()
    rows = [cost.ravel()]
    for i in range(n):
        r = np.zeros(n * k)
        r[i * k:(i + 1) * k] = 1
        rows.append(r)
    A = np.vstack(rows)
    upper = np.concatenate([[budget], np.ones(n)])
    res = milp(c, constraints=LinearConstraint(A, -np.inf, upper), integrality=np.ones(n * k),
               bounds=Bounds(0, ub))
    if res.x is None:
        return [None] * n
    x = np.round(res.x).reshape(n, k)
    return [int(np.argmax(x[i])) if x[i].max() > 0.5 else None for i in range(n)]


def solve_transport(supply: np.ndarray, demand: np.ndarray, gain: np.ndarray,
                    feasible: np.ndarray) -> np.ndarray:
    """Bài toán vận tải cho lô vàng (NC2 PH2): max Σ gain[i,j]·x[i,j], Σ_j x ≤ supply_i, Σ_i x ≤ demand_j."""
    from scipy.optimize import linprog

    n, m = gain.shape
    allowed = feasible & (gain > 0)
    if n == 0 or m == 0 or not allowed.any():
        return np.zeros((n, m))
    c = -np.where(allowed, gain, 0).ravel()
    A, b = [], []
    for i in range(n):
        r = np.zeros(n * m); r[i * m:(i + 1) * m] = 1; A.append(r); b.append(supply[i])
    for j in range(m):
        r = np.zeros(n * m); r[j::m] = 1; A.append(r); b.append(demand[j])
    bounds = [(0, None) if allowed.ravel()[t] else (0, 0) for t in range(n * m)]
    res = linprog(c, A_ub=np.array(A), b_ub=np.array(b), bounds=bounds, method="highs")
    return np.floor(res.x.reshape(n, m) + 1e-9) if res.success else np.zeros((n, m))
