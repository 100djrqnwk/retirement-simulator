"""
노후설계 시뮬레이터 (Streamlit UI)
- 실행: streamlit run streamlit_app.py
- 모든 입력값 변경 시 전 결과 실시간 재계산
- 기반: 노후설계 작업지시서 v3.5

v3.5 변경사항
- 근로소득 UI 제거 (내부 고정: 남편 400 / 부인 600)
- 부인 국민연금 수령액: 임의가입 납입액 기반 자동 연동 (공단 4앵커 선형보간)
- IRP/ISA Phase 2구간 (Phase 전환 기준: 부인 나이, 기본 54세 = 2030)
- 월 총 적립 상한선 제거 (자유입력, 미래 증액 대비)
- 임의가입 9.623만은 급여에서 별도 처리 (시뮬레이터 외부)
- 반납 666만 별도 처리 (사용자 결정, 설계 미반영)
"""
import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from datetime import datetime
import math
import json
import os

# ============================================================
# 사용자 기본값 저장/로드 (파일 기반 영속성 · 카테고리별 구조화 + 한글 주석)
# ============================================================
DEFAULTS_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "streamlit_defaults.json")

# 파라미터 카테고리 정의 (순서·라벨 포함)
PARAM_CATEGORIES = {
    "1_프로필": {
        "husband_birth": "남편 출생연도",
        "self_birth": "부인 출생연도",
        "work_income_50_59": "근로소득 50~59세 (부부합산/월, 만원)",
        "work_income_60_61": "근로소득 60~61세 (부부합산/월, 만원)",
        "work_income_62_63": "근로소득 62~63세 (부부합산/월, 만원)",
        "work_income_64_64": "근로소득 64세 (부부합산/월, 만원)",
        "work_income_65_69": "근로소득 65~69세 (부부합산/월, 만원)",
        "work_income_70_79": "근로소득 70~79세 (부부합산/월, 만원)",
        "work_income_80_120": "근로소득 80세~ (부부합산/월, 만원)",
        "husband_income": "남편 대표 근로소득 (참고, 50~59세×0.4 자동)",
        "self_income": "부인 대표 근로소득 (참고, 50~59세×0.6 자동)",
        "husband_retire_age": "남편 퇴직 나이 (참고, 시기별 자동 파생)",
        "self_retire_age": "부인 퇴직 나이 (참고, 시기별 자동 파생)",
        "retire_reduce_ratio": "퇴직기 소득 비율 (%, 부부 공통)",
        "saving_end_age": "사적연금 적립종료 나이 (부인 기준, 세)",
        "saving_years": "적립기간 (년, 자동 계산)",
    },
    "2_월_적립_배분": {
        "pension_saving": "연금저축 (부부합산/월, 만원)",
        "irp_phase1": "IRP Phase1 월 납입 (50세~Phase전환 이전, 만원)",
        "irp_phase2": "IRP Phase2 월 납입 (Phase전환 이후~적립종료, 만원)",
        "isa_phase1": "ISA Phase1 월 납입 (50세~Phase전환 이전, 만원)",
        "isa_phase2": "ISA Phase2 월 납입 (Phase전환 이후~적립종료, 만원)",
        "phase_transition_age": "Phase 전환 기준 부인 나이 (기본 54세=2030)",
        "nps_voluntary": "국민연금 임의가입 월 납입 (부인, 만원) · 급여 별도 처리",
        "nps_continue_years": "60세 이후 임의계속가입 기간 (년, 0~5)",
        "husband_saving_ratio": "남편 납입 비중 (%, 연금저축+IRP)",
        "refund_reinvest_ratio": "세액공제 환급금 재투자 비율 (%, 0=생활비)",
    },
    "2_5_일반_금융소득": {
        "other_financial_income": "기타 이자·배당 연 수령 (만원, 1000 초과 시 건보 산정)",
    },
    "3_공적연금": {
        "husband_nps": "남편 국민연금 수령액 (월, 만원)",
        "husband_nps_start": "남편 국민연금 개시 — 남편 나이(세)",
        "self_gong": "부인 공무원연금 수령액 (월, 만원)",
        "self_gong_start_age": "부인 공무원연금 개시 — 부인 나이(세)",
        "self_nps_start": "부인 국민연금 개시 — 부인 나이(세)",
    },
    "4_수익률_물가": {
        "nominal_return": "적립기 명목수익률 (%/년)",
        "withdraw_nominal_return": "인출기 명목수익률 (%/년, 보수적)",
        "inflation": "물가상승률 (%/년)",
        "refund_delay_enabled": "환급금 5월 지연 재투자 반영 (True/False)",
    },
    "5_세율_건보료": {
        "tax_nps_rate": "국민연금 세율 (%)",
        "tax_gong_rate": "공무원연금 세율 (%)",
        "pension_deduction_enabled": "연금소득공제 적용 (공적연금, True/False)",
        "tax_priv_rate": "사적연금 세율 — 55~69세 (%)",
        "tax_priv_rate_70": "사적연금 세율 — 70~79세 (%)",
        "tax_priv_rate_80": "사적연금 세율 — 80세+ (%)",
        "isa_type": "ISA 유형 (일반형 / 서민형)",
        "tax_isa_rate": "ISA 초과분 분리과세율 (%)",
        "isa_nontax_annual": "ISA 비과세 한도 (연, 만원)",
        "property_value_billion": "아파트 공시가 (억원, 재산분 건보 자동 산정)",
        "health_ins_manual": "건보료 수동 입력 (연금기, 0=공시가 기반 자동)",
        "ltc_rate": "장기요양보험료율 (% of 건보료)",
        "tax_credit_husband": "남편 세액공제율 (%, 16.5 or 13.2)",
        "tax_credit_self": "부인 세액공제율 (%, 16.5 or 13.2)",
    },
    "6_5_노란우산공제": {
        "yumam_enabled": "노란우산공제 가입 여부 (남편, True/False)",
        "yumam_monthly": "노란우산 월 납입액 (만원)",
        "yumam_start_age": "노란우산 가입 시작 — 남편 나이(세)",
        "yumam_end_age": "노란우산 적립 종료 — 남편 나이(세, 보통 퇴직시점)",
        "yumam_rate": "노란우산 보장 이율 (%/년)",
        "yumam_tax_rate": "노란우산 인출 시 퇴직소득세 (%, 분리과세 추정)",
    },
    "6_목표_보완축": {
        "target": "목표 세후 월액 (만원, 실질 2026 기준)",
        "private_draw": "사적연금 인출 (월, 62세~, 만원)",
        "private_reduce_age": "사적연금 감액 시작 연령",
        "private_draw_after": "감액 후 사적연금 인출액 (월, 만원)",
        "isa_draw": "ISA 월 인출 (세전, 65세~, 만원)",
        "isa_health_included": "ISA 인출 건보료 소득 산입 (보수적 가정, True/False)",
        "house_enabled": "주택연금 사용 여부 (True/False)",
        "house_age": "주택연금 가동 연령 (65/70/75/80)",
        "house_monthly": "주택연금 월 수령액 (가동시점 기준, 만원)",
        "house_nominal_fixed": "주택연금 명목 고정 — 실질가치 체감 (True/False)",
    },
}

def load_user_defaults():
    """사용자 저장 기본값 로드 (구조화 + 플랫 형식 모두 지원)"""
    if not os.path.exists(DEFAULTS_PATH):
        return {}
    try:
        with open(DEFAULTS_PATH, "r", encoding="utf-8") as f:
            raw = json.load(f)
    except Exception:
        return {}

    flat = {}
    for key, val in raw.items():
        if key.startswith("_"):
            continue  # 메타데이터(_메타, _설명 등) 스킵
        if isinstance(val, dict):
            # 카테고리 섹션: {"husband_birth": {"설명": "...", "value": 1975}, ...}
            for subkey, subval in val.items():
                if isinstance(subval, dict) and "value" in subval:
                    flat[subkey] = subval["value"]
                elif not subkey.startswith("_"):
                    flat[subkey] = subval
        else:
            # 플랫 키 (구버전 호환)
            flat[key] = val
    return flat

def save_user_defaults(data):
    """카테고리별 구조화 + 한글 설명 추가 JSON 저장"""
    from datetime import datetime as _dt
    output = {
        "_메타": {
            "저장시간": _dt.now().strftime("%Y-%m-%d %H:%M:%S"),
            "설명": "노후설계 시뮬레이터 사용자 기본값 (작업지시서 v2.4)",
            "사용법": [
                "1. 각 항목의 'value'를 수정하면 다음 실행 시 자동 로드됩니다.",
                "2. 이 파일 삭제 시 코드 하드코딩 기본값으로 복원됩니다.",
                "3. Streamlit UI의 '🗑️ 저장된 기본값 초기화' 버튼으로도 삭제 가능합니다.",
                "4. 기준: 실질(2026년 구매력) · 세후 · 부부 합산 · 단위 만원",
            ],
        }
    }
    for section_name, items in PARAM_CATEGORIES.items():
        section_dict = {}
        for key, label in items.items():
            if key in data:
                section_dict[key] = {
                    "설명": label,
                    "value": data[key],
                }
        if section_dict:
            output[section_name] = section_dict

    with open(DEFAULTS_PATH, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2, default=str)

_DEF = load_user_defaults()
def D(key, fallback):
    """저장된 기본값 조회 (없으면 fallback)"""
    return _DEF.get(key, fallback)

# ============================================================
# [v3.5] 부인 국민연금 임의가입 납입 → 수령 변환 함수
# ============================================================
# 공단 안내 4개 앵커 (전제: 반납 666만 완료 · 60세까지 납입)
#   9.623만 → 22.9만 (옵션 A)
#  20.040만 → 28.9만 (옵션 B)
#  25.080만 → 31.8만 (옵션 C)
#  30.020만 → 34.7만 (옵션 D)
# 구간별 선형보간. 9.623 이하는 A 대비 비례 감산 (보수적 추정)
NPS_ANCHORS = [
    (0.0,    0.0),
    (9.623,  22.9),
    (20.040, 28.9),
    (25.080, 31.8),
    (30.020, 34.7),
]
def calc_self_nps_from_voluntary(monthly_input, continue_years=0):
    """임의가입 월 납입 → 월 예상 수령 (구간별 선형보간)
    - continue_years: 60세 이후 임의계속가입 기간 (년, 0~5)
      납입액은 동일 유지, 가입기간 연장에 따른 수령액 비례 증가 근사
      (공단 안내 앵커는 10년 기준 → factor = (10 + continue_years) / 10)
    """
    if monthly_input <= 0:
        return 0.0
    for i in range(len(NPS_ANCHORS) - 1):
        x0, y0 = NPS_ANCHORS[i]
        x1, y1 = NPS_ANCHORS[i + 1]
        if monthly_input <= x1:
            base = y0 + (monthly_input - x0) * (y1 - y0) / (x1 - x0)
            break
    else:
        # 30.02 초과: 마지막 기울기 연장
        x0, y0 = NPS_ANCHORS[-2]
        x1, y1 = NPS_ANCHORS[-1]
        slope = (y1 - y0) / (x1 - x0)
        base = y1 + (monthly_input - x1) * slope
    # 임의계속가입 기간 반영 (가입기간 비례 근사)
    factor = (10 + max(0, continue_years)) / 10
    return base * factor

# ============================================================
# [v3.5.9] 근로소득 시기 구분 (차트 표출 시기와 일치, 50~59세 UI 제외)
# [v3.5.10] 물결표 '~' → Markdown 취소선 파싱 방지를 위해 '\~' 이스케이프
# ============================================================
# (라벨, start_age, end_age, 부부합산 월 기본값)
WORK_PERIODS = [
    ("60\\~61세 (2036\\~2037)", 60, 61, 500),
    ("62\\~63세 (2038\\~2039)", 62, 63, 0),
    ("64세 (2040)",              64, 64, 0),
    ("65\\~69세 (2041\\~2045)", 65, 69, 0),
    ("70\\~79세 (2046\\~2055)", 70, 79, 0),
    ("80세\\~ (2056\\~)",        80, 120, 0),
]
WORK_PERIOD_KEY = lambda s, e: f'work_income_{s}_{e}'

# ============================================================
# [v3.6] 노란우산공제 FV 계산 (보장이율, 월복리, 실질 환산)
# [v3.6.1] 부부 확장 + 분할 수령 함수 추가
# ============================================================
def calc_yumam_fv(monthly, years, nominal_rate, inflation):
    """노란우산공제 적립 FV (실질, 월복리)
    - monthly: 월 납입액 (만원)
    - years: 적립 연수
    - nominal_rate: 명목 보장이율 (%/년)
    - inflation: 물가상승률 (%/년)
    """
    if monthly <= 0 or years <= 0:
        return 0.0
    real_rate = (1 + nominal_rate / 100) / (1 + inflation / 100) - 1
    monthly_rate = (1 + real_rate) ** (1 / 12) - 1 if real_rate > -1 else 0
    months = int(years * 12)
    if monthly_rate > 0:
        return monthly * ((1 + monthly_rate) ** months - 1) / monthly_rate
    return monthly * months

def calc_yumam_payout(fv_at_start, years, nominal_rate, inflation):
    """[v3.6.1] 노란우산공제 분할 수령 월액 (실질, 2026 구매력)
    - fv_at_start: 적립 종료 시점 실질 FV (만원)
    - years: 분할 기간 (년)
    - nominal_rate: 명목 보장이율 (%/년)
    - inflation: 물가상승률 (%/년)
    잔여 적립금이 실질이자율로 계속 굴어가며 등액 분할 지급.
    """
    if fv_at_start <= 0 or years <= 0:
        return 0.0
    real_rate = (1 + nominal_rate / 100) / (1 + inflation / 100) - 1
    monthly_rate = (1 + real_rate) ** (1 / 12) - 1 if real_rate > -1 else 0
    months = int(years * 12)
    if monthly_rate > 0:
        return fv_at_start * monthly_rate / (1 - (1 + monthly_rate) ** (-months))
    return fv_at_start / months

# [v3.6.1] 노란우산공제 소득공제 한도 (종합소득금액 구간별)
YUMAM_DEDUCTION_LIMIT = {
    "4천만_이하": 500,   # 만원/년
    "4천_1억":    300,
    "1억_초과":   200,
}

def yumam_annual_saving(monthly, bracket, marginal_rate):
    """[v3.6.1] 노란우산 연 절세액 (소득공제 × 한계세율 × 지방세 가산)"""
    annual = monthly * 12
    limit = YUMAM_DEDUCTION_LIMIT.get(bracket, 200)
    deductible = min(annual, limit)
    return deductible * (marginal_rate / 100) * 1.1

# ============================================================
# [v3.5] Phase 2구간 적립 FV 계산
# ============================================================
def calc_fv_phased(monthly_p1, monthly_p2, p1_years, p2_years, monthly_rate):
    """Phase1 → Phase2 월납 적립 FV (월복리)
    - monthly_p1: Phase1 월 납입 총액
    - monthly_p2: Phase2 월 납입 총액
    - p1_years, p2_years: 각 Phase 연수
    - monthly_rate: 실질 월이율
    """
    p1_m = int(round(p1_years * 12))
    p2_m = int(round(p2_years * 12))
    if monthly_rate > 0:
        # Phase1 적립분의 FV (Phase1 종료 시점) → Phase2 종료까지 이자만
        fv_p1_end = monthly_p1 * ((1 + monthly_rate) ** p1_m - 1) / monthly_rate
        fv_p1_final = fv_p1_end * (1 + monthly_rate) ** p2_m
        # Phase2 적립분 FV
        fv_p2 = monthly_p2 * ((1 + monthly_rate) ** p2_m - 1) / monthly_rate
        return fv_p1_final + fv_p2
    else:
        return monthly_p1 * p1_m + monthly_p2 * p2_m

# ============================================================
# 페이지 설정
# ============================================================
st.set_page_config(
    page_title="노후설계 시뮬레이터",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
)

# 한글 및 스타일 (다크/라이트 모드 무관 시인성 확보)
st.markdown("""
<style>
    /* v3.6.3: React DOM 재조정 충돌 방지 — 외관 스타일만 적용, 내부 구조 강제 금지 */
    .main > div { padding-top: 1rem; }
    .block-container { padding-top: 2rem; padding-bottom: 2rem; }

    /* KPI 카드 컨테이너 간격 */
    [data-testid="stHorizontalBlock"] {
        gap: 10px;
    }

    /* KPI 카드 외관 (배경·테두리·여백만) */
    [data-testid="stMetric"] {
        background: linear-gradient(135deg, #E3F2FD 0%, #BBDEFB 100%);
        padding: 14px 12px;
        border-radius: 10px;
        border-left: 4px solid #1F4E78;
        box-shadow: 0 1px 3px rgba(0,0,0,0.08);
        min-height: 110px;
    }

    /* 라벨 색상·굵기 */
    [data-testid="stMetricLabel"] {
        color: #1F4E78;
        font-weight: 600;
        font-size: 14px;
    }

    /* 값 색상·굵기·크기 */
    [data-testid="stMetricValue"] {
        color: #C00000;
        font-weight: 800;
        font-size: clamp(18px, 1.8vw, 26px);
    }

    /* delta 색상 */
    [data-testid="stMetricDelta"] {
        color: #1a1a1a;
        font-weight: 600;
    }

    /* 상단 캡션 시인성 */
    [data-testid="stCaptionContainer"] {
        color: #9AA5B1;
    }

    /* 탭 영역 구분선 */
    div[data-baseweb="tab-list"] {
        border-top: 2px solid #2E75B6;
        border-bottom: 2px solid #2E75B6;
        margin-top: 20px;
        margin-bottom: 12px;
        padding: 4px 0;
    }

    /* 탭 버튼 시인성 */
    button[data-baseweb="tab"] {
        font-size: 16px;
        font-weight: 700;
        padding: 10px 18px;
    }

    /* 활성 탭 인디케이터 */
    div[data-baseweb="tab-highlight"] {
        background-color: #FFC000;
        height: 3px;
    }

    /* 알림 박스 강조 */
    [data-testid="stAlert"] {
        font-size: 15px;
        font-weight: 500;
    }
</style>
""", unsafe_allow_html=True)

st.title("📊 노후설계 시뮬레이터")
st.caption("입력값을 변경하면 모든 결과가 실시간 재계산됩니다. · 기반: 작업지시서 v3.5 · Choby 부부")

# ============================================================
# 사이드바 — 입력
# ============================================================
with st.sidebar:
    st.header("⚙️ 입력 파라미터")

    # [v3.5.3] 프로필(출생연도·퇴직나이) UI 숨김 → 내부 고정
    husband_birth = D('husband_birth', 1975)
    self_birth = D('self_birth', 1976)
    retire_reduce_ratio = D('retire_reduce_ratio', 50)

    # [v3.5.9] 시기별 근로소득 입력 (차트 표출 시기와 일치, 60세~)
    with st.expander("💼 근로소득", expanded=True):
        st.caption("시기별 부부합산 월 근로소득 (만원, 세후) · 내부 40:60 분배")
        work_income_by_age = {}  # age -> 부부합산 월 소득
        _work_income_map = {}    # label -> value (save_payload용)
        # 50~59세 근로소득 (UI 비노출, JSON 고정값)
        _base_work_income = D('work_income_50_59', 1000)
        for age in range(50, 60):
            work_income_by_age[age] = _base_work_income
        st.caption(f"※ 50\\~59세 근로소득 고정: **{_base_work_income}만/월** (부부합산, JSON 수정으로 변경)")
        # 60세~ 시기별 입력
        for label, s_age, e_age, default in WORK_PERIODS:
            key = WORK_PERIOD_KEY(s_age, e_age)
            value = st.number_input(label,
                min_value=0, max_value=10000, value=D(key, default), step=100,
                key=f"widget_{key}")
            _work_income_map[key] = value
            for age in range(s_age, e_age + 1):
                work_income_by_age[age] = value

    # 대표 근로소득(50~59세) — v3.6.2: 남편 직접 입력 우선, 부인은 잔여 파생
    # 미지정 시 기존 40:60 자동 파생 유지 (하위 호환)
    _base_income = work_income_by_age.get(50, 1000)
    husband_income = D('husband_income_50_59', int(_base_income * 0.4))
    self_income = max(0, _base_income - husband_income)
    # 퇴직 나이(레거시) = 근로소득이 처음 0이 되는 시점 직전 나이
    _retire_age = 61
    for age in range(50, 120):
        if work_income_by_age.get(age, 0) == 0:
            _retire_age = age - 1
            break
    husband_retire_age = _retire_age
    self_retire_age = _retire_age
    husband_retire_start = husband_birth + husband_retire_age
    self_retire_start = self_birth + self_retire_age

    with st.expander("💰 사적연금", expanded=True):
        st.markdown("### 🎯 연금저축 (부부합산/월)")
        pension_saving = st.number_input("연금저축 (부부합산/월)",
            min_value=0, max_value=1000, value=D('pension_saving', 100), step=10,
            help="세액공제 최대 한도 (부부합산 연 1,800만 = 월 150만) 기본값 100만",
            label_visibility="collapsed")
        st.markdown("---")
        st.markdown("### 🔹 그 이외")
        phase_transition_age = st.number_input("단계전환 (부인나이 기준)",
            50, 61, D('phase_transition_age', 54),
            help="작은아이 고교 졸업·수입 증가 시점. 기본 54세 = 2030년")

        st.markdown(f"**1단계** (50~{phase_transition_age - 1}세)")
        col_p1_irp, col_p1_isa = st.columns(2)
        with col_p1_irp:
            irp_phase1 = st.number_input("IRP 1단계 (만원)",
                min_value=0, max_value=1000, value=D('irp_phase1', 50), step=10)
        with col_p1_isa:
            isa_phase1 = st.number_input("ISA 1단계 (만원)",
                min_value=0, max_value=1000, value=D('isa_phase1', 50), step=10)

        st.markdown(f"**2단계** ({phase_transition_age}세~적립종료)")
        col_p2_irp, col_p2_isa = st.columns(2)
        with col_p2_irp:
            irp_phase2 = st.number_input("IRP 2단계 (만원)",
                min_value=0, max_value=1000, value=D('irp_phase2', 50), step=10)
        with col_p2_isa:
            isa_phase2 = st.number_input("ISA 2단계 (만원)",
                min_value=0, max_value=1000, value=D('isa_phase2', 50), step=10)

        # 1단계·2단계 합계 표시 (상한선 없음)
        _sum_p1 = pension_saving + irp_phase1 + isa_phase1
        _sum_p2 = pension_saving + irp_phase2 + isa_phase2
        st.caption(f"📊 월 적립 합계 → 1단계: **{_sum_p1}만** / 2단계: **{_sum_p2}만**")

        st.divider()
        husband_saving_ratio = st.slider("남편 납입 비중 (%)", 0, 100, D('husband_saving_ratio', 50), 5,
            help="한도 900만/인 → 50:50 배분이 세액공제 총액 최대 (각자 900만 한도 풀 활용). 부부 합산 1,800만")
        refund_reinvest_ratio = st.slider("세액공제 환급금 재투자 비율(%)", 0, 100, D('refund_reinvest_ratio', 0), 10,
            help="연 환급금을 자산화할 비율. 0% = 전액 생활비 사용 / 100% = 전액 재투자")
        # [v3.5.3] 적립종료 시기 변수화 (부인 나이 기준)
        saving_end_age = st.number_input("사적연금 적립종료 나이 (부인 기준, 세)",
            min_value=51, max_value=80, value=D('saving_end_age', 61), step=1,
            help="부인 나이 기준 적립 마감 시점(포함). 기본 61세(2037) · 자유롭게 조정 가능")
        # 적립기간: 50세~적립종료나이 포함 연도 수 = (saving_end_age - 50 + 1)
        saving_years = max(1, saving_end_age - 50 + 1)
        st.caption(f"↳ 적립기간 자동 계산: **{saving_years}년** (50세\\~{saving_end_age}세, 2026\\~{2026 + saving_years - 1})")

        # ─────────────────────────────────────────────
        # [v3.6.1] 노란우산공제 (부부 각자) — 사적연금 섹션 내부 통합
        # ─────────────────────────────────────────────
        st.divider()
        st.markdown("### ☂️ 노란우산공제 (부부 각자)")
        st.caption("사업자 본인 명의만 가입. 소득공제 + 압류 보호 + 분리과세")

        _bracket_options = ["4천만_이하", "4천_1억", "1억_초과"]

        # 👨 남편
        st.markdown("**👨 남편** (개인사업자)")
        yumam_enabled = st.checkbox("남편 가입",
            value=D('yumam_enabled', True),
            help="남편 개인사업자 자격 · 1억 초과 → 한도 200만/년",
            key="yumam_enabled_h_chk")
        col_h1, col_h2 = st.columns(2)
        with col_h1:
            yumam_monthly = st.number_input("월 납입 (만원)",
                min_value=0.0, max_value=100.0, value=float(D('yumam_monthly', 16.7)), step=0.1,
                help="한도: 4천↓ 41.7 / 4천~1억 25.0 / 1억↑ 16.7만/월",
                disabled=not yumam_enabled, key="yumam_monthly_h")
        with col_h2:
            yumam_income_bracket_h = st.selectbox("종합소득 구간",
                _bracket_options,
                index=_bracket_options.index(D('yumam_income_bracket_h', '1억_초과')),
                disabled=not yumam_enabled, key="yumam_bracket_h")
        yumam_marginal_rate_h = st.slider("남편 한계세율 (%)",
            min_value=6.0, max_value=45.0, value=float(D('yumam_marginal_rate_h', 35)), step=1.0,
            help="종합소득세 한계세율 (절세 효과 계산용)",
            disabled=not yumam_enabled, key="yumam_mr_h")

        # 👩 부인 (v3.6.1 신규)
        st.markdown("**👩 부인** (법인대표)")
        yumam_enabled_s = st.checkbox("부인 가입",
            value=D('yumam_enabled_s', True),
            help="부인 법인대표 자격 · 4천~1억 → 한도 300만/년",
            key="yumam_enabled_s_chk")
        col_s1, col_s2 = st.columns(2)
        with col_s1:
            yumam_monthly_s = st.number_input("월 납입 (만원, 부인)",
                min_value=0.0, max_value=100.0, value=float(D('yumam_monthly_s', 25.0)), step=0.1,
                help="한도: 4천↓ 41.7 / 4천~1억 25.0 / 1억↑ 16.7만/월",
                disabled=not yumam_enabled_s, key="yumam_monthly_s_in")
        with col_s2:
            yumam_income_bracket_s = st.selectbox("종합소득 구간 (부인)",
                _bracket_options,
                index=_bracket_options.index(D('yumam_income_bracket_s', '4천_1억')),
                disabled=not yumam_enabled_s, key="yumam_bracket_s")
        yumam_marginal_rate_s = st.slider("부인 한계세율 (%)",
            min_value=6.0, max_value=45.0, value=float(D('yumam_marginal_rate_s', 24)), step=1.0,
            disabled=not yumam_enabled_s, key="yumam_mr_s")

        # ⚙️ 공통 파라미터
        st.markdown("**⚙️ 공통**")
        col_c1, col_c2 = st.columns(2)
        with col_c1:
            yumam_start_age = st.number_input("남편 가입시작(세)",
                min_value=30, max_value=70, value=D('yumam_start_age', 51), step=1,
                key="yumam_start_h")
            yumam_end_age = st.number_input("남편 적립종료(세)",
                min_value=30, max_value=80, value=D('yumam_end_age', 60), step=1,
                key="yumam_end_h")
        with col_c2:
            yumam_start_age_s = st.number_input("부인 가입시작(세)",
                min_value=30, max_value=70, value=D('yumam_start_age_s', 50), step=1,
                key="yumam_start_s")
            yumam_end_age_s = st.number_input("부인 적립종료(세)",
                min_value=30, max_value=80, value=D('yumam_end_age_s', 60), step=1,
                key="yumam_end_s")
        col_pay1, col_pay2 = st.columns(2)
        with col_pay1:
            yumam_payout_start_age = st.number_input("수령 시작 나이 (부부 공통)",
                min_value=55, max_value=80, value=D('yumam_payout_start_age', 60), step=1,
                help="노령 조건: 만 60세 이상 + 10년 이상 납입. 폐업 사유면 더 빨라질 수 있음")
        with col_pay2:
            yumam_payout_years = st.number_input("분할 수령 기간 (년)",
                min_value=1, max_value=30, value=D('yumam_payout_years', 10), step=1,
                help=f"기본 10년 ({yumam_payout_start_age}~{yumam_payout_start_age+9}세)")
        col_c3, col_c4 = st.columns(2)
        with col_c3:
            yumam_rate = st.slider("보장 이율 (%/년)",
                min_value=0.0, max_value=8.0, value=float(D('yumam_rate', 3.4)), step=0.1,
                help="명목 보장이율. 시뮬레이터 내부에서 실질로 환산")
        with col_c4:
            yumam_tax_rate = st.slider("퇴직소득세 실효율 (%)",
                min_value=0.0, max_value=20.0, value=float(D('yumam_tax_rate', 1.0)), step=0.1,
                help="분할 수령 시 실측 약 0.7~1.0%")

        # 한도 및 절세 안내 caption
        _h_limit = YUMAM_DEDUCTION_LIMIT.get(yumam_income_bracket_h, 200)
        _s_limit = YUMAM_DEDUCTION_LIMIT.get(yumam_income_bracket_s, 200)
        _h_save = yumam_annual_saving(yumam_monthly, yumam_income_bracket_h, yumam_marginal_rate_h) if yumam_enabled else 0
        _s_save = yumam_annual_saving(yumam_monthly_s, yumam_income_bracket_s, yumam_marginal_rate_s) if yumam_enabled_s else 0
        st.caption(f"💡 한도(연): 남편 **{_h_limit}만** / 부인 **{_s_limit}만**")
        st.caption(f"💰 연 절세: 남편 **{_h_save:.0f}만** + 부인 **{_s_save:.0f}만** = **{_h_save+_s_save:.0f}만/년**")

    with st.expander("🏛️ 공적연금", expanded=True):
        st.markdown("### 👨 남편 국민연금")
        husband_nps = st.number_input("남편 국민연금 수령액(월, 만원)", 0, 500, D('husband_nps', 165), 5)
        husband_nps_start = st.number_input("남편 국민연금 개시 — 남편 나이(세)", 55, 75, D('husband_nps_start', 65))
        st.markdown("---")
        st.markdown("### 👩 부인 공무원연금")
        self_gong = st.number_input("부인 공무원연금 수령액(월, 만원)", 0, 500, D('self_gong', 150), 5)
        self_gong_start_age = st.number_input("부인 공무원연금 개시 — 부인 나이(세)", 55, 75, D('self_gong_start_age', 62))
        st.markdown("---")
        st.markdown("### 🎯 부인 국민연금 임의가입")
        st.caption("급여에서 별도 처리 · 시뮬레이터 외부")
        nps_voluntary = st.number_input("부인 국민연금 월 납입액 (만원, 50~59세)",
            min_value=0.0, max_value=100.0, value=float(D('nps_voluntary', 9.623)), step=0.1,
            help="공단 안내 기준: 9.623 / 20.040 / 25.080 / 30.020 (옵션 A~D) · 범위 밖은 구간 선형보간")
        nps_continue_years = st.number_input("60세 이후 임의계속가입 기간(년)",
            min_value=0, max_value=5, value=D('nps_continue_years', 0), step=1,
            help="60~64세 기간 동안 동일 납입액으로 추가 가입 (최대 5년). 가입기간 연장에 따른 수령액 비례 증가")
        # [v3.5.6] 수령액 값만 크고 흰색 강조, 나머지는 기존 caption 톤 유지
        self_nps = calc_self_nps_from_voluntary(nps_voluntary, nps_continue_years)
        _cont_txt = f" + 60세 후 {nps_continue_years}년" if nps_continue_years > 0 else ""
        st.markdown(
            f"<div style='color:#9AA5B1; font-size:13px; margin-top:4px;'>"
            f"↳ 예상 월 수령액: "
            f"<span style='color:#FFFFFF; font-size:20px; font-weight:800;'>{self_nps:.2f}만</span>"
            f" (65세~, 10년 납입{_cont_txt} · 공단 4앵커 선형보간)"
            f"</div>",
            unsafe_allow_html=True,
        )
        self_nps_start = st.number_input("부인 국민연금 개시 — 부인 나이(세)", 55, 75, D('self_nps_start', 65))
        st.caption("※ 과세비율 고정: 남편 국민 2003 가입 **100%** · 부인 공무원 2004 임용 **100%** · "
                   "부인 국민 (2001 최초가입 + 임의가입) **95%** (2001년분 비과세 반영)")

    with st.expander("📊 수익률·물가", expanded=False):
        nominal_return = st.slider("적립기 명목수익률(%/년)", 0.0, 10.0, float(D('nominal_return', 5.0)), 0.1)
        withdraw_nominal_return = st.slider("인출기 명목수익률(%/년)", 0.0, 10.0, float(D('withdraw_nominal_return', 3.5)), 0.1,
            help="은퇴 후 보수적 자산배분 반영 (채권 비중 증가). 낙관이면 5%")
        inflation = st.slider("물가상승률(%/년)", 0.0, 6.0, float(D('inflation', 2.5)), 0.1)
        refund_delay_enabled = st.checkbox("환급금 5월 지연 재투자 반영", value=D('refund_delay_enabled', True),
            help="종소세 환급은 이듬해 5월 — 약 5/12년 지연 보정")

    with st.expander("💸 세율·건보료 (중립 시나리오)", expanded=False):
        tax_nps_rate = st.slider("국민연금 세율(%)", 0.0, 15.0, float(D('tax_nps_rate', 6.0)), 0.5)
        tax_gong_rate = st.slider("공무원연금 세율(%)", 0.0, 15.0, float(D('tax_gong_rate', 7.0)), 0.5)
        pension_deduction_enabled = st.checkbox("연금소득공제 적용(공적연금)", value=D('pension_deduction_enabled', True),
            help="소득세법 §47의2 최대 연 900만 공제. 공적연금 세금 과대계상 방지")
        st.markdown("**사적연금 분리과세 (연령별)**")
        tax_priv_rate = st.slider("55~69세 세율(%)", 0.0, 15.0, float(D('tax_priv_rate', 5.5)), 0.1)
        tax_priv_rate_70 = st.slider("70~79세 세율(%)", 0.0, 15.0, float(D('tax_priv_rate_70', 4.4)), 0.1)
        tax_priv_rate_80 = st.slider("80세+ 세율(%)", 0.0, 15.0, float(D('tax_priv_rate_80', 3.3)), 0.1)
        st.markdown("**ISA**")
        _isa_opts = ["일반형", "서민형"]
        isa_type = st.radio("ISA 유형", _isa_opts, horizontal=True,
            index=_isa_opts.index(D('isa_type', "일반형")) if D('isa_type', "일반형") in _isa_opts else 0,
            help="서민형: 총급여 5,000만↓ 또는 종합소득 3,800만↓ / 비과세 400만")
        isa_nontax_default = 400 if isa_type == "서민형" else 200
        tax_isa_rate = st.slider("ISA 초과분 분리과세율(%)", 0.0, 15.0, float(D('tax_isa_rate', 9.9)), 0.1)
        isa_nontax_annual = st.number_input("ISA 비과세 한도(연/만원)", 0, 500, D('isa_nontax_annual', isa_nontax_default), 10)
        st.markdown("**건보료**")
        property_value_billion = st.number_input("아파트 공시가(억원)", 0.0, 50.0, float(D('property_value_billion', 12.0)), 0.5,
            help="주택공시가격 기반 건보 재산과표 (재산세 과세표준 아님). 국토교통부 부동산공시가격 알리미 조회")
        health_ins_manual = st.number_input("건보료 수동 입력(연금기, 0=자동)", 0, 200, D('health_ins_manual', 0), 5,
            help="0: 공시가 기반 자동 계산 / 양수: 수동값 사용")
        ltc_rate = st.slider("장기요양보험료율(% of 건보료)", 0.0, 20.0, float(D('ltc_rate', 12.95)), 0.05)
        st.markdown("---")
        st.markdown("**💰 세액공제 (적립기 환급 재투자)**")
        tax_credit_husband = st.slider("남편 세액공제율(%)", 0.0, 20.0, float(D('tax_credit_husband', 16.5)), 0.1,
                                        help="총급여 5,500만↓ 또는 종합소득 4,500만↓: 16.5% / 초과: 13.2%")
        tax_credit_self = st.slider("부인 세액공제율(%)", 0.0, 20.0, float(D('tax_credit_self', 13.2)), 0.1)

    with st.expander("💹 일반 금융소득 (선택)", expanded=False):
        other_financial_income = st.number_input("기타 이자·배당 (연, 만원)",
            0, 5000, D('other_financial_income', 0), 100,
            help="ISA 외 일반 예금 이자, 배당 등. 연 2,000만 초과 시 금융소득종합과세. 연 1,000만 초과분은 건보료 산정")

    with st.expander("🎯 목표·보완축", expanded=False):
        target = st.number_input("목표 세후 월액(만원)", 100, 1000, D('target', 450), 10)
        private_draw = st.number_input("사적연금 인출(월, 62세~)", 0, 300, D('private_draw', 110), 5)
        private_reduce_age = st.number_input("사적연금 감액 시작 연령", 65, 100, D('private_reduce_age', 80))
        private_draw_after = st.number_input("감액 후 사적연금 인출액(월)", 0, 300, D('private_draw_after', 80), 5)
        isa_draw = st.number_input("ISA 월 인출(세전, 65세~)", 0, 300, D('isa_draw', 60), 5)
        isa_health_included = st.checkbox("ISA 인출 건보료 소득 산입(보수적 가정)",
            value=D('isa_health_included', False),
            help="공단 공식 답변 미확정. 체크 시 ISA 인출액의 약 7%를 추가 건보료로 차감")
        st.markdown("**🏠 주택연금**")
        house_enabled = st.checkbox("주택연금 사용", value=D('house_enabled', True),
            help="체크 해제 시 주택연금 현금흐름에 반영 안 됨")
        _house_opts = [65, 70, 75, 80]
        _saved_house_age = D('house_age', 70)
        house_age = st.selectbox("주택연금 가동 연령", _house_opts,
            index=_house_opts.index(_saved_house_age) if _saved_house_age in _house_opts else 1,
            disabled=not house_enabled)
        house_monthly = st.number_input("주택연금 월 수령액(가동시점 기준)", 0, 500, D('house_monthly', 250), 10,
            disabled=not house_enabled)
        house_nominal_fixed = st.checkbox("주택연금 명목 고정 (실질가치 체감)",
            value=D('house_nominal_fixed', True),
            help="실제 제도는 가입시점 금액이 명목 고정 → 시간 경과에 따라 실질가치 감소. 체크 해제 시 실질 고정(낙관)",
            disabled=not house_enabled)

    st.divider()
    if st.button("🔄 기본값 재설정", use_container_width=True,
                 help="저장된 사용자 기본값 유지하면서 앱 새로고침"):
        st.rerun()

    # 현재 값 → 저장 payload 구성 (다이얼로그에서 사용)
    save_payload = {
        'husband_birth': husband_birth, 'self_birth': self_birth,
        'husband_income': husband_income, 'self_income': self_income,
        'husband_retire_age': husband_retire_age,
        'self_retire_age': self_retire_age,
        'retire_reduce_ratio': retire_reduce_ratio,
        # [v3.5.8] 시기별 근로소득
        **_work_income_map,
        'saving_end_age': saving_end_age, 'saving_years': saving_years,
        'pension_saving': pension_saving,
        'irp_phase1': irp_phase1, 'irp_phase2': irp_phase2,
        'isa_phase1': isa_phase1, 'isa_phase2': isa_phase2,
        'phase_transition_age': phase_transition_age,
        'nps_voluntary': nps_voluntary, 'nps_continue_years': nps_continue_years,
        'husband_saving_ratio': husband_saving_ratio,
        'refund_reinvest_ratio': refund_reinvest_ratio,
        'other_financial_income': other_financial_income,
        'husband_nps': husband_nps, 'husband_nps_start': husband_nps_start,
        'self_gong': self_gong, 'self_gong_start_age': self_gong_start_age,
        'self_nps_start': self_nps_start,
        'nominal_return': nominal_return, 'withdraw_nominal_return': withdraw_nominal_return,
        'inflation': inflation, 'refund_delay_enabled': refund_delay_enabled,
        'tax_nps_rate': tax_nps_rate, 'tax_gong_rate': tax_gong_rate,
        'pension_deduction_enabled': pension_deduction_enabled,
        'tax_priv_rate': tax_priv_rate, 'tax_priv_rate_70': tax_priv_rate_70,
        'tax_priv_rate_80': tax_priv_rate_80,
        'isa_type': isa_type, 'tax_isa_rate': tax_isa_rate,
        'isa_nontax_annual': isa_nontax_annual,
        'property_value_billion': property_value_billion,
        'health_ins_manual': health_ins_manual,
        'ltc_rate': ltc_rate,
        'tax_credit_husband': tax_credit_husband, 'tax_credit_self': tax_credit_self,
        'target': target, 'private_draw': private_draw,
        'private_reduce_age': private_reduce_age, 'private_draw_after': private_draw_after,
        'isa_draw': isa_draw, 'isa_health_included': isa_health_included,
        'house_enabled': house_enabled, 'house_age': house_age,
        'house_monthly': house_monthly, 'house_nominal_fixed': house_nominal_fixed,
        # [v3.6] 노란우산공제
        'yumam_enabled': yumam_enabled, 'yumam_monthly': yumam_monthly,
        'yumam_start_age': yumam_start_age, 'yumam_end_age': yumam_end_age,
        'yumam_rate': yumam_rate, 'yumam_tax_rate': yumam_tax_rate,
    }

    if st.button("💾 현재 값을 기본값으로 설정", use_container_width=True,
                 help="확인 모달이 뜹니다 → 확인 버튼 클릭 시 파일 저장"):
        st.session_state['show_save_dialog'] = True

    # 저장된 기본값 존재 시 초기화 옵션
    if _DEF:
        if st.button("🗑️ 저장된 기본값 초기화", use_container_width=True,
                     help="저장된 기본값 파일 삭제 → 다음 실행 시 코드 기본값 사용"):
            st.session_state['show_reset_dialog'] = True


# ============================================================
# 모달 다이얼로그 정의 (기본값 저장/초기화 확인)
# ============================================================
@st.dialog("기본값 변경 확인")
def confirm_save_dialog(payload):
    st.warning("⚠️ **기본값이 변경됩니다.**")
    st.write("현재 모든 입력값이 `streamlit_defaults.json` 파일에 저장되며, "
             "다음 실행 시 이 값이 **기본값으로 자동 로드**됩니다.")
    st.caption(f"변경될 항목 수: {len(payload)}개")

    col1, col2 = st.columns(2)
    with col1:
        if st.button("✅ 확인 (저장)", type="primary", use_container_width=True):
            try:
                save_user_defaults(payload)
                st.session_state['show_save_dialog'] = False
                st.rerun()
            except Exception as e:
                st.error(f"저장 실패: {e}")
    with col2:
        if st.button("❌ 취소", use_container_width=True):
            st.session_state['show_save_dialog'] = False
            st.rerun()

@st.dialog("저장된 기본값 초기화")
def confirm_reset_dialog():
    st.warning("⚠️ **저장된 기본값 파일이 삭제됩니다.**")
    st.write("`streamlit_defaults.json` 파일이 삭제되며, 다음 실행 시 "
             "**코드에 하드코딩된 기본값**으로 초기화됩니다.")

    col1, col2 = st.columns(2)
    with col1:
        if st.button("🗑️ 확인 (삭제)", type="primary", use_container_width=True):
            try:
                if os.path.exists(DEFAULTS_PATH):
                    os.remove(DEFAULTS_PATH)
                st.success("✅ 삭제됨. 페이지를 새로고침하세요.")
                st.session_state['show_reset_dialog'] = False
            except Exception as e:
                st.error(f"삭제 실패: {e}")
    with col2:
        if st.button("❌ 취소", use_container_width=True):
            st.session_state['show_reset_dialog'] = False
            st.rerun()

# 트리거된 경우 다이얼로그 표시
if st.session_state.get('show_save_dialog', False):
    confirm_save_dialog(save_payload)
if st.session_state.get('show_reset_dialog', False):
    confirm_reset_dialog()

# ============================================================
# 핵심 계산
# ============================================================
BIRTH_SELF = self_birth
BIRTH_HUSBAND = husband_birth

def self_age(year):
    return year - BIRTH_SELF

def husband_age(year):
    return year - BIRTH_HUSBAND

def get_pension_deduction(annual_income):
    """연금소득공제 (소득세법 §47의2 기준, 만원 단위)"""
    if annual_income <= 0:
        return 0
    if annual_income <= 350:
        return annual_income
    elif annual_income <= 700:
        return 350 + (annual_income - 350) * 0.4
    elif annual_income <= 1400:
        return 490 + (annual_income - 700) * 0.2
    else:
        return min(900, 630 + (annual_income - 1400) * 0.1)

def priv_tax_by_age(age):
    """연령별 사적연금 분리과세율"""
    if age < 70:
        return tax_priv_rate
    elif age < 80:
        return tax_priv_rate_70
    else:
        return tax_priv_rate_80

def property_health_portion(billion):
    """공시가(억) → 월 재산분 건보료 추정 (장기요양 포함 前)
    2026년 지역가입자 재산점수 기준 근사"""
    if billion <= 3:
        return 8
    elif billion <= 7:
        return 8 + (billion - 3) * 3
    elif billion <= 12:
        return 20 + (billion - 7) * 4
    elif billion <= 20:
        return 40 + (billion - 12) * 5
    else:
        return 80 + (billion - 20) * 3

# 실질 수익률 — 적립기(월복리 기하평균) / 인출기(별도)
real_return = (1 + nominal_return/100) / (1 + inflation/100) - 1
real_return_monthly = (1 + real_return) ** (1/12) - 1  # 기하평균 (정확)

# 인출기 실질수익률 (보수적 자산배분 반영)
withdraw_real_return = (1 + withdraw_nominal_return/100) / (1 + inflation/100) - 1
withdraw_real_return_monthly = (1 + withdraw_real_return) ** (1/12) - 1 if withdraw_real_return > -1 else 0

# [v3.5] Phase 2구간 기반 적립 FV 계산
# - Phase1: 50세 ~ (phase_transition_age - 1)
# - Phase2: phase_transition_age ~ (50 + saving_years - 1)
p1_years = max(0, min(saving_years, phase_transition_age - 50))
p2_years = max(0, saving_years - p1_years)
months = saving_years * 12

# 사적연금 (연금저축 + IRP) Phase별 월 적립액
private_monthly_p1 = pension_saving + irp_phase1
private_monthly_p2 = pension_saving + irp_phase2
fv_private_base = calc_fv_phased(private_monthly_p1, private_monthly_p2,
                                  p1_years, p2_years, real_return_monthly)

# ISA Phase별 월 적립액
isa_monthly_p1 = isa_phase1
isa_monthly_p2 = isa_phase2
fv_isa = calc_fv_phased(isa_monthly_p1, isa_monthly_p2,
                        p1_years, p2_years, real_return_monthly)

# [v3.6.1] 노란우산공제 FV (부부 각자, 실질 환산)
# 남편
yumam_years_h = max(0, yumam_end_age - yumam_start_age + 1) if yumam_enabled else 0
fv_yumam_h = calc_yumam_fv(yumam_monthly, yumam_years_h, yumam_rate, inflation) if yumam_enabled else 0
# 부인
yumam_years_s = max(0, yumam_end_age_s - yumam_start_age_s + 1) if yumam_enabled_s else 0
fv_yumam_s = calc_yumam_fv(yumam_monthly_s, yumam_years_s, yumam_rate, inflation) if yumam_enabled_s else 0
# 부부 합산 (KPI·xlsx 표시용)
fv_yumam = fv_yumam_h + fv_yumam_s
# 인출 시 세후 자산 (퇴직소득세 실효율 분리과세)
fv_yumam_net = fv_yumam * (1 - yumam_tax_rate / 100)

# [v3.6.1] 분할 수령 월액 (실질, 세후, 부부 각자)
# 60세 ~ 60+payout_years-1세 동안 매월 등액 수령
yumam_payout_h_gross = calc_yumam_payout(fv_yumam_h, yumam_payout_years, yumam_rate, inflation) if yumam_enabled else 0
yumam_payout_s_gross = calc_yumam_payout(fv_yumam_s, yumam_payout_years, yumam_rate, inflation) if yumam_enabled_s else 0
yumam_payout_h_net = yumam_payout_h_gross * (1 - yumam_tax_rate / 100)
yumam_payout_s_net = yumam_payout_s_gross * (1 - yumam_tax_rate / 100)

# 절세 누적 (10년 적립, 표시용)
_yumam_annual_save_h = yumam_annual_saving(yumam_monthly, yumam_income_bracket_h, yumam_marginal_rate_h) if yumam_enabled else 0
_yumam_annual_save_s = yumam_annual_saving(yumam_monthly_s, yumam_income_bracket_s, yumam_marginal_rate_s) if yumam_enabled_s else 0
yumam_total_save = _yumam_annual_save_h * yumam_years_h + _yumam_annual_save_s * yumam_years_s

# 표시/호환용 평균 월 적립 (KPI·환급금 가중평균용)
private_monthly = (private_monthly_p1 * p1_years + private_monthly_p2 * p2_years) / saving_years if saving_years > 0 else 0
isa = (isa_monthly_p1 * p1_years + isa_monthly_p2 * p2_years) / saving_years if saving_years > 0 else 0
irp = (irp_phase1 * p1_years + irp_phase2 * p2_years) / saving_years if saving_years > 0 else 0

# 세액공제 환급금 재투자 FV (적립기, 연 단위)
# Phase별 연 납입 합산 → 각 Phase의 세액공제 환급 연금 FV 합산
def _calc_phase_refund_fv(annual_contrib, years_in_phase, defer_factor=1.0):
    """해당 Phase 연간 환급금의 FV (Phase 종료 시점 기준)"""
    hus_ann = annual_contrib * husband_saving_ratio / 100
    self_ann = annual_contrib * (100 - husband_saving_ratio) / 100
    hus_credit = min(hus_ann, 900) * tax_credit_husband / 100
    self_credit = min(self_ann, 900) * tax_credit_self / 100
    annual_refund = hus_credit + self_credit
    if real_return > 0 and years_in_phase > 0:
        fv = annual_refund * ((1 + real_return) ** years_in_phase - 1) / real_return
        fv *= defer_factor  # 5월 지연 반영
    else:
        fv = annual_refund * years_in_phase
    return fv, annual_refund

annual_contrib_p1 = (pension_saving + irp_phase1) * 12
annual_contrib_p2 = (pension_saving + irp_phase2) * 12
defer_factor_p1 = (1 + real_return) ** (-5/12) if (refund_delay_enabled and real_return > 0) else 1.0

# Phase1 환급 FV (Phase1 종료 시점) → Phase2 종료까지 이자
fv_refund_p1_end, annual_refund_p1 = _calc_phase_refund_fv(annual_contrib_p1, p1_years, defer_factor_p1)
if real_return > 0:
    fv_refund_p1_final = fv_refund_p1_end * (1 + real_return) ** p2_years
else:
    fv_refund_p1_final = fv_refund_p1_end
# Phase2 환급 FV
fv_refund_p2, annual_refund_p2 = _calc_phase_refund_fv(annual_contrib_p2, p2_years, defer_factor_p1)
fv_tax_refund_full = fv_refund_p1_final + fv_refund_p2
# 대표 연 환급금 (표시용, 가중평균)
annual_tax_refund = (annual_refund_p1 * p1_years + annual_refund_p2 * p2_years) / saving_years if saving_years > 0 else 0
fv_tax_refund = fv_tax_refund_full * refund_reinvest_ratio / 100

# 자산 분리 (세제 체계 다름)
# - fv_private: 연금계좌(연금저축+IRP) 월납 FV → 인출 시 분리과세(5.5~3.3%) or 종합과세
# - fv_tax_refund: 세액공제 환급 재투자 자산 → 일반 금융소득(15.4%) or ISA 추가 납입
fv_private = fv_private_base  # 순수 연금계좌만
# fv_tax_refund는 별도 자산으로 유지 (합산하지 않음)

# 건보료 총액 (장기요양 포함) — 연금수령기 vs 사업소득기 분리
# 연금기 건보료: 공시가 기반 자동 산정 또는 수동 입력
property_hc_portion = property_health_portion(property_value_billion)
health_ins_income_portion = 32  # 연금기 소득분 근사 (공적+사적 343+110만 기준)
health_ins_auto = health_ins_income_portion + property_hc_portion
health_ins = health_ins_manual if health_ins_manual > 0 else health_ins_auto

health_total = health_ins * (1 + ltc_rate/100)

# ISA 인출 가능 기간 — 인출기 수익률 사용
if isa_draw > 0 and withdraw_real_return_monthly > 0:
    ratio = fv_isa * withdraw_real_return_monthly / isa_draw
    if ratio < 1:
        isa_draw_months = math.ceil(
            -math.log(1 - ratio) / math.log(1 + withdraw_real_return_monthly)
        )
    else:
        isa_draw_months = 999 * 12
elif isa_draw > 0:
    isa_draw_months = int(fv_isa / isa_draw)
else:
    isa_draw_months = 0
isa_draw_years = isa_draw_months / 12
isa_end_age = 65 + isa_draw_years

# ISA 세후 환산 — 수익분만 과세 (원금 비과세)
# [v3.5] Phase 2구간 적용: 명목 기준 FV와 원금 각각 계산
# gain_ratio는 명목 기준으로 계산 (원금/FV 단위 통일)
# [v2.7 6-A] 기하평균 월이율로 통일 (실질 월이율과 일관성)
nominal_return_monthly = (1 + nominal_return/100)**(1/12) - 1 if nominal_return > 0 else 0
fv_isa_nominal = calc_fv_phased(isa_monthly_p1, isa_monthly_p2,
                                p1_years, p2_years, nominal_return_monthly)
isa_principal_nominal = (isa_monthly_p1 * 12 * p1_years) + (isa_monthly_p2 * 12 * p2_years)  # 명목 원금
isa_gain_ratio = max(0.0, 1 - isa_principal_nominal / fv_isa_nominal) if fv_isa_nominal > 0 else 0.0

def isa_monthly_net(gross_monthly):
    """ISA 인출액 중 수익분만 분리과세. 원금은 비과세."""
    annual = gross_monthly * 12
    annual_gain = annual * isa_gain_ratio
    if annual_gain <= isa_nontax_annual:
        tax_annual = 0
    else:
        tax_annual = (annual_gain - isa_nontax_annual) * tax_isa_rate / 100
    return gross_monthly - tax_annual / 12

isa_net = isa_monthly_net(isa_draw)

# 사적연금 고갈 시뮬레이션 — 인출기 수익률 적용
def simulate_private_depletion():
    """사적연금 인출 시 잔액 월복리 운용(인출기 수익률) 고갈 시점 계산"""
    balance = fv_private
    age = 62
    month = 0
    while age < 120 and balance > 0:
        draw = private_draw if age < private_reduce_age else private_draw_after
        balance = balance * (1 + withdraw_real_return_monthly) - draw
        month += 1
        if month >= 12:
            age += 1
            month = 0
    if balance > 0:
        return None, balance
    return age + month/12, 0

private_depletion_age, private_final_balance = simulate_private_depletion()

# ============================================================
# 시기별 현금흐름 계산
# ============================================================
def calc_period_row(label, year_start, year_end, age):
    """한 구간의 수입 구성 계산 — 모든 분기는 year_start 기준으로 통일"""
    # 연령 미리 계산 (각자 부인/남편 기준)
    self_age_start = self_age(year_start)
    husband_age_start = husband_age(year_start)

    # [v3.5.8] 시기별 근로소득 (부부합산) → 40:60 분배
    _combined = work_income_by_age.get(self_age_start, 0)
    h_inc = _combined * 0.4
    s_inc = _combined * 0.6

    # 공무원연금 (부인 나이 기준)
    if self_age_start >= self_gong_start_age:
        gong = self_gong
    else:
        gong = 0

    # 남편 국민연금 (남편 나이 기준)
    h_nps = husband_nps if husband_age_start >= husband_nps_start else 0

    # 부인 국민연금 (부인 나이 기준)
    s_nps = self_nps if self_age_start >= self_nps_start else 0

    # 사적연금 (62세~)
    if self_age_start >= 62:
        priv = private_draw if self_age_start < private_reduce_age else private_draw_after
    else:
        priv = 0

    # 세전 합계
    gross = h_inc + s_inc + h_nps + gong + s_nps + priv

    # [v3.3] 과세비율 고정
    #   - 남편 국민(2003~): 100%
    #   - 부인 공무원(2004~): 100%
    #   - 부인 국민(2001 최초 + 임의가입): 95% (2001년분 비과세)
    h_nps_taxable_gross = h_nps
    gong_taxable_gross = gong
    s_nps_taxable_gross = s_nps * 0.95

    # 연금소득공제 (인별, 과세대상 금액에만 공제 적용)
    if pension_deduction_enabled:
        h_nps_annual_taxable = h_nps_taxable_gross * 12
        h_nps_taxable = max(0, h_nps_annual_taxable - get_pension_deduction(h_nps_annual_taxable)) / 12
        self_public_annual_taxable = (gong_taxable_gross + s_nps_taxable_gross) * 12
        self_public_deduction = get_pension_deduction(self_public_annual_taxable)
        if self_public_annual_taxable > 0:
            deduction_ratio = 1 - self_public_deduction / self_public_annual_taxable
        else:
            deduction_ratio = 1
        gong_taxable = gong_taxable_gross * deduction_ratio
        s_nps_taxable = s_nps_taxable_gross * deduction_ratio
    else:
        h_nps_taxable = h_nps_taxable_gross
        gong_taxable = gong_taxable_gross
        s_nps_taxable = s_nps_taxable_gross

    # 연령별 사적연금 세율 (기본 분리과세)
    priv_rate = priv_tax_by_age(self_age_start)
    # [v2.7 6-C] 1,500만 초과 시 자동 선택 (분리 16.5% vs 종합 근사 15% vs 현 세율)
    priv_annual_sim = priv * 12
    if priv_annual_sim > 1500:
        # 16.5% 분리과세 선택 vs 종합과세 근사 (누진 15% 가정)
        # 실무: 납세자가 유리한 쪽 선택. 여기선 보수적으로 16.5% 적용
        priv_rate = max(priv_rate, 16.5)

    # 차감 (사업소득은 실수령 전제, 건보료는 별도 가산)
    tax = (h_nps_taxable * tax_nps_rate/100
         + s_nps_taxable * tax_nps_rate/100
         + gong_taxable * tax_gong_rate/100
         + priv * priv_rate/100)
    # 건보료: 연금수령기만 별도 차감 (사업소득은 세후 실수령 전제)
    # - 사업기: 실수령에 건보·세금 이미 반영 → 추가 차감 0
    # - 연금기: 지역가입자 전환 → 건보료 추가 부과
    if (h_nps + gong + s_nps + priv) > 0:
        hc = health_total
        # 사적연금 연 1,200만 초과분 추가 건보 부과
        priv_annual = priv * 12
        if priv_annual > 1200:
            hc += (priv_annual - 1200) * 0.09 / 12
        # 일반 금융소득 연 1,000만 초과분 추가 건보 부과 (연금기만)
        if other_financial_income > 1000:
            hc += (other_financial_income - 1000) * 0.09 / 12
    else:
        hc = 0  # 근로소득 실수령 전제 (이중 차감 방지)

    deduction = tax + hc
    net = gross - deduction

    # 공적/사적 연금 분리 세후 계산 (비례 분할 + 개별 세금 반영)
    gross_public = h_nps + gong + s_nps  # 공적연금 합계
    gross_private = priv
    total_pension = gross_public + gross_private
    tax_public = (h_nps_taxable * tax_nps_rate/100
                + s_nps_taxable * tax_nps_rate/100
                + gong_taxable * tax_gong_rate/100)
    tax_private = priv * priv_rate / 100
    if total_pension > 0:
        hc_public = hc * gross_public / total_pension
        hc_private = hc * gross_private / total_pension
    else:
        hc_public = 0
        hc_private = 0
    net_public = gross_public - tax_public - hc_public
    net_private = gross_private - tax_private - hc_private
    net_work = (h_inc + s_inc)  # 근로소득 세후 실수령

    # ISA 추가 (65~isa_end_age)
    isa_add = isa_net if (self_age_start >= 65 and self_age_start < isa_end_age) else 0
    # ISA 건보료 산입 (2022 개정: 분리과세 금융소득 연 1,000만 초과 시)
    # - 원금분 제외, 수익분만 소득 산정 대상
    # - 장기요양 포함 실효율 ~9.0%
    if isa_health_included and isa_add > 0:
        annual_isa_gain = isa_draw * 12 * isa_gain_ratio
        if annual_isa_gain > 1000:
            excess = annual_isa_gain - 1000
            isa_health_burden = excess * 0.09 / 12  # 월 환산
            isa_add = max(0, isa_add - isa_health_burden)
        # else: 1,000만 이하 → 건보 산정 제외 (산입 토글과 무관)

    # 주택연금 — 사용 여부 체크 우선 (미사용 시 0)
    if not house_enabled:
        house_add = 0
    elif self_age_start >= house_age:
        if house_nominal_fixed:
            house_start_year = BIRTH_SELF + house_age
            years_post = max(0, year_start - house_start_year)
            house_add = house_monthly / ((1 + inflation/100) ** years_post)
        else:
            house_add = house_monthly
    else:
        house_add = 0

    # [v3.6.1] 노란우산 분할 수령 (실질 세후)
    # [v3.6.3] 수령 시작 나이 변수화 (부부 공통)
    # 시기 구간이 여러 연도를 포함할 수 있어 연도별 활성 비율 계산
    yumam_add = 0
    _y_end_year_h = year_end if year_end < 9999 else year_start + 50
    _pay_start = yumam_payout_start_age
    _pay_end = _pay_start + yumam_payout_years
    for _yr in range(year_start, _y_end_year_h + 1):
        _hage = husband_age(_yr)
        _sage = self_age(_yr)
        _h_active = (yumam_enabled and _pay_start <= _hage < _pay_end)
        _s_active = (yumam_enabled_s and _pay_start <= _sage < _pay_end)
        yumam_add += (yumam_payout_h_net if _h_active else 0)
        yumam_add += (yumam_payout_s_net if _s_active else 0)
    _years_in_period = max(1, _y_end_year_h - year_start + 1)
    yumam_add = yumam_add / _years_in_period  # 시기 평균

    adjusted = net + isa_add + house_add + yumam_add

    return {
        "시기": label, "연령(부인)": age,
        "남편근로": h_inc, "부인근로": s_inc,
        "남편국민": h_nps, "부인공무원": gong, "부인국민": s_nps, "사적연금": priv,
        "세전합계": gross, "세금": tax, "건보료": hc, "차감합계": deduction,
        "세후_근로": net_work, "세후_공적연금": net_public, "세후_사적연금": net_private,
        "세후": net, "ISA추가": isa_add, "노란우산": yumam_add, "주택연금": house_add,
        "조정세후": adjusted, "목표": target, "과부족": adjusted - target
    }

# 시기 정의 — 부인 나이 기준 라벨 (self_birth 자동 반영)
def _age_label(ys, ye):
    """부인 나이 기준 + 연도 병기 라벨"""
    age_s = ys - BIRTH_SELF
    if ye >= 9999:
        return f"{age_s}세~\n({ys}~)"
    age_e = ye - BIRTH_SELF
    if age_s == age_e:
        return f"{age_s}세\n({ys})"
    return f"{age_s}~{age_e}세\n({ys}~{ye})"

_year_ranges = [
    # [v3.5.1] 50~59세 구간 표출 제거 (적립기 · 근로소득 단순 표시로 노후설계 정보 부재)
    (2036, 2037, 61),
    (2038, 2039, 62),
    (2040, 2040, 64),
    (2041, 2045, 65),
    (2046, 2055, 70),
    (2056, 9999, 80),
]
periods_def = [(_age_label(ys, ye), ys, ye, age) for ys, ye, age in _year_ranges]
rows = [calc_period_row(*p) for p in periods_def]
df = pd.DataFrame(rows)

# ============================================================
# KPI 영역 (상단)
# ============================================================
def fmt_money(v):
    """금액 통일: 항상 만원 단위"""
    return f"{v:,.0f}만"

# KPI 카드 — 1행 x 5열 (핵심 지표 + 노란우산 v3.6)
_total_p1 = pension_saving + irp_phase1 + isa_phase1
_total_p2 = pension_saving + irp_phase2 + isa_phase2
row1 = st.columns(5)
row1[0].metric("목표 세후", fmt_money(target), help=f"실질수익률 {real_return*100:.2f}%")
row1[1].metric("월 총 적립 (1단계/2단계)", f"{_total_p1}/{_total_p2}만",
               delta=f"전환 {phase_transition_age}세 · {p1_years}+{p2_years}년",
               delta_color="off",
               help=f"1단계: {_total_p1}만 × {p1_years}년 · 2단계: {_total_p2}만 × {p2_years}년")
# 사적연금 적립/고갈 (적립액 + 고갈 연령 병기)
if private_depletion_age is None:
    _depl_txt = "100세+ 지속"
else:
    _depl_txt = f"고갈 {private_depletion_age:.1f}세"
row1[2].metric("사적연금 적립 / 고갈", fmt_money(fv_private),
               delta=_depl_txt, delta_color="off",
               help="연금계좌(저축+IRP) 실질 FV · 인출 시 고갈 시점")
# ISA 적립/인출기간 (적립액 + 인출기간 병기)
row1[3].metric("ISA 적립 / 고갈", fmt_money(fv_isa),
               delta=f"인출 {isa_draw_years:.1f}년 (종료 {isa_end_age:.1f}세)",
               delta_color="off",
               help="ISA 실질 적립 · 월 인출 가능 기간")
# [v3.6.1] 노란우산공제 FV (부부 합산)
if (yumam_enabled or yumam_enabled_s) and fv_yumam > 0:
    _yumam_payout_avg = yumam_payout_h_net + yumam_payout_s_net
    _yumam_delta = f"월 추가 {_yumam_payout_avg:.1f}만 · 절세 {yumam_total_save:.0f}만"
else:
    _yumam_delta = "미가입"
row1[4].metric("노란우산 (부부)", fmt_money(fv_yumam),
               delta=_yumam_delta, delta_color="off",
               help=f"보장이율 {yumam_rate}% · 분할 {yumam_payout_years}년 · 실효세율 {yumam_tax_rate}%")

# ============================================================
# 탭 구성
# ============================================================
tabs = st.tabs(["① 요약 대시보드", "② 현금흐름 상세", "③ 시나리오 비교", "④ 보완축 분석", "⑤ 리스크", "⑥ 내보내기", "⑦ 검토제안"])

# ---------------- 탭 1 ----------------
with tabs[0]:
    st.subheader("📈 시기별 세후 흐름 요약")

    # [v3.6.1] 근로 / 연금 / ISA / 노란우산 / 주택연금 5구성 스택 차트
    fig = go.Figure()
    fig.add_trace(go.Bar(name="근로", x=df["시기"], y=df["세후_근로"],
                         marker_color="#4472C4"))
    fig.add_trace(go.Bar(name="연금(공적+사적)",
                         x=df["시기"],
                         y=df["세후_공적연금"] + df["세후_사적연금"],
                         marker_color="#70AD47"))
    fig.add_trace(go.Bar(name="ISA", x=df["시기"], y=df["ISA추가"],
                         marker_color="#ED7D31"))
    # [v3.6.1] 노란우산공제 (60~69세 활성, 규칙 14 조건부 렌더)
    if (yumam_enabled or yumam_enabled_s) and df["노란우산"].sum() > 0:
        fig.add_trace(go.Bar(name="노란우산", x=df["시기"], y=df["노란우산"],
                             marker_color="#FFC000"))
    if house_enabled:
        fig.add_trace(go.Bar(name="주택연금", x=df["시기"], y=df["주택연금"],
                             marker_color="#C00000"))
    fig.add_hline(y=target, line_dash="dash", line_color="red",
                  annotation_text=f"목표 {target}만", annotation_position="top right")
    fig.update_layout(
        barmode="stack",
        height=480,
        font=dict(size=13),
        xaxis=dict(title="시기", tickangle=-10),
        yaxis_title="월 세후 (만원, 실질)",
        legend=dict(orientation="h", yanchor="top", y=-0.18, xanchor="center", x=0.5, font=dict(size=12)),
        margin=dict(t=30, b=100, l=60, r=20),
    )
    st.plotly_chart(fig, use_container_width=True)

    # 핵심 결론 박스
    critical = df[df["조정세후"] < target]
    if len(critical) == 0:
        st.success(f"✅ 모든 구간에서 목표 {target}만 달성")
    else:
        # Markdown 취소선(~~) 방지 위해 물결표 이스케이프
        fail_periods = ", ".join(critical["시기"].tolist()).replace("~", "\\~")
        min_deficit = critical["과부족"].min()
        st.warning(f"⚠️ **목표 미달 구간**: {fail_periods} · 최대 부족: {min_deficit:,.0f}만/월")

    # Phase 4-B 추가 경고들
    warnings_box = []

    # 1. 사적연금 연 1,500만 초과 → 분리과세 배제
    annual_private = private_draw * 12
    if annual_private > 1500:
        warnings_box.append(
            f"🔴 **사적연금 연 {annual_private:,}만** — 1,500만 초과로 **분리과세 불가**, "
            f"종합과세 전환 (실효세율 15~24% 예상). 현재 모델은 분리과세 가정으로 낙관일 수 있음"
        )

    # 2. 사적연금 연 1,200만 초과 → 건보 산정 대상 (현재 이미 포함되어 있으나 명시)
    if annual_private > 1200:
        warnings_box.append(
            f"🟡 **사적연금 연 {annual_private:,}만** — 1,200만 초과로 건보료 소득 산정 대상 "
            f"(현재 연금기 건보료에 반영됨)"
        )

    # 3. 사적연금 고갈 경고
    if private_depletion_age is not None and private_depletion_age < 85:
        warnings_box.append(
            f"🔴 **사적연금 {private_depletion_age:.1f}세 고갈** — 기대여명(약 85~90세) 전 소진. "
            f"인출액 축소 또는 적립 증액 검토 필요 (잔액 {private_final_balance:,.0f}만)"
        )
    elif private_depletion_age is not None and private_depletion_age < 95:
        warnings_box.append(
            f"🟡 사적연금 {private_depletion_age:.1f}세 고갈 — 기대여명 내 소진 가능성"
        )

    # 4. ISA 건보 산입 가정 경고
    if isa_health_included:
        annual_isa_gain = isa_draw * 12 * isa_gain_ratio
        if annual_isa_gain > 1000:
            warnings_box.append(
                f"🟡 **ISA 건보 산입 가정 ON** — 연 수익 {annual_isa_gain:,.0f}만 중 "
                f"1,000만 초과분에 대해 건보료 9.0% 부과"
            )
        else:
            warnings_box.append(
                f"ℹ️ ISA 건보 산입 토글 ON 이지만 연 수익 {annual_isa_gain:,.0f}만 ≤ 1,000만 → "
                f"실제로는 건보 산입 제외"
            )

    for w in warnings_box:
        if "ℹ️" in w:
            st.info(w)
        else:
            st.warning(w)

    # 간단 요약 표 (세후를 근로·공적·사적 3분할 표시)
    summary_df = df[["시기", "세후_근로", "세후_공적연금", "세후_사적연금",
                     "세후", "ISA추가", "주택연금", "조정세후", "과부족"]].copy()
    st.dataframe(
        summary_df.style.format({
            "세후_근로": "{:,.0f}", "세후_공적연금": "{:,.0f}", "세후_사적연금": "{:,.0f}",
            "세후": "{:,.0f}", "ISA추가": "{:+,.1f}", "주택연금": "{:+,.0f}",
            "조정세후": "{:,.0f}", "과부족": "{:+,.0f}"
        }).background_gradient(subset=["과부족"], cmap="RdYlGn", vmin=-300, vmax=300),
        use_container_width=True, hide_index=True
    )

# ---------------- 탭 2 ----------------
with tabs[1]:
    st.subheader("📋 시기별 현금흐름 상세")
    col_l, col_r = st.columns([1, 1])

    with col_l:
        st.markdown("**세전 구성 + 차감**")
        detail1 = df[["시기", "연령(부인)", "남편근로", "부인근로", "남편국민", "부인공무원", "부인국민", "사적연금", "세전합계"]]
        st.dataframe(detail1.style.format({col: "{:,.1f}" for col in detail1.columns[2:]}),
                     use_container_width=True, hide_index=True, height=280)

        st.markdown("**세금·건보료 차감**")
        detail2 = df[["시기", "세금", "건보료", "차감합계", "세후"]]
        st.dataframe(detail2.style.format({col: "{:,.1f}" for col in detail2.columns[1:]}),
                     use_container_width=True, hide_index=True, height=280)

    with col_r:
        st.markdown("**구간별 수입 구성**")
        fig2 = go.Figure()
        fig2.add_trace(go.Bar(name="남편근로", x=df["시기"], y=df["남편근로"], marker_color="#8FAADC"))
        fig2.add_trace(go.Bar(name="부인근로", x=df["시기"], y=df["부인근로"], marker_color="#4472C4"))
        fig2.add_trace(go.Bar(name="남편국민", x=df["시기"], y=df["남편국민"], marker_color="#A9D18E"))
        fig2.add_trace(go.Bar(name="부인공무원", x=df["시기"], y=df["부인공무원"], marker_color="#70AD47"))
        fig2.add_trace(go.Bar(name="부인국민", x=df["시기"], y=df["부인국민"], marker_color="#FFD966"))
        fig2.add_trace(go.Bar(name="사적연금", x=df["시기"], y=df["사적연금"], marker_color="#ED7D31"))
        # [v3.5.11] 가독성 개선: 높이 확대 · 범례 하단 가로 배치 · 여백 확보
        fig2.update_layout(
            barmode="stack",
            height=460,
            title=dict(text="소득원별 스택 차트", font=dict(size=15)),
            xaxis=dict(title="시기", tickangle=-15, tickfont=dict(size=11)),
            yaxis=dict(title="월 세전(만원)", tickfont=dict(size=11)),
            legend=dict(
                orientation="h",
                yanchor="top",
                y=-0.22,
                xanchor="center",
                x=0.5,
                font=dict(size=12),
                itemwidth=70,
            ),
            margin=dict(t=50, b=110, l=60, r=20),
        )
        st.plotly_chart(fig2, use_container_width=True)

        # 차감 파이
        fig3 = go.Figure()
        total_tax_gong = df["부인공무원"].sum() * tax_gong_rate/100
        total_tax_nps = (df["남편국민"].sum() + df["부인국민"].sum()) * tax_nps_rate/100
        total_tax_priv = df["사적연금"].sum() * tax_priv_rate/100
        total_health = df[df["건보료"] > 0]["건보료"].sum()
        fig3.add_trace(go.Pie(
            labels=["국민연금 세금", "공무원연금 세금", "사적연금 세금", "건보료"],
            values=[total_tax_nps, total_tax_gong, total_tax_priv, total_health],
            hole=0.4,
            marker_colors=["#4472C4", "#70AD47", "#ED7D31", "#C00000"]
        ))
        # [v3.5.11] 가독성 개선: 높이 확대 · 범례 하단
        fig3.update_layout(
            height=420,
            title=dict(text="전체 차감 구성(누적)", font=dict(size=15)),
            legend=dict(
                orientation="h",
                yanchor="top",
                y=-0.05,
                xanchor="center",
                x=0.5,
                font=dict(size=12),
            ),
            margin=dict(t=50, b=80, l=20, r=20),
        )
        st.plotly_chart(fig3, use_container_width=True)

# ---------------- 탭 3 ----------------
with tabs[2]:
    st.subheader("🎭 시나리오 비교")
    st.caption("세율·건보료 가정을 각 시나리오별로 가정하여 비교")

    def calc_scenario(tax_nps_r, tax_gong_r, tax_priv_r, hc_val, ltc_r, hc_work_val=None):
        """calc_period_row와 동일한 구간 분기·연금소득공제·연령별 세율 적용."""
        hc_total = hc_val * (1 + ltc_r/100)
        result = []
        for p in periods_def:
            label, ys, ye, _ = p
            self_age_start = self_age(ys)
            # [v3.5.8] 시기별 근로소득 (부부합산) → 40:60 분배
            _combined = work_income_by_age.get(self_age_start, 0)
            h_inc = _combined * 0.4
            s_inc = _combined * 0.6
            # 공적연금
            gong = self_gong if self_age_start >= self_gong_start_age else 0
            h_nps = husband_nps if husband_age(ys) >= husband_nps_start else 0
            s_nps = self_nps if self_age_start >= self_nps_start else 0
            # 사적연금 + 연령별 세율
            if self_age_start >= 62:
                priv = private_draw if self_age_start < private_reduce_age else private_draw_after
            else:
                priv = 0
            if self_age_start < 70:
                priv_rate_scenario = tax_priv_r
            elif self_age_start < 80:
                priv_rate_scenario = tax_priv_rate_70
            else:
                priv_rate_scenario = tax_priv_rate_80
            # [v3.3] 과세비율 고정 (부인 국민 95%, 나머지 100%)
            h_nps_tg = h_nps
            gong_tg = gong
            s_nps_tg = s_nps * 0.95
            if pension_deduction_enabled:
                h_nps_tx = max(0, h_nps_tg*12 - get_pension_deduction(h_nps_tg*12)) / 12
                self_pub_ann = (gong_tg + s_nps_tg) * 12
                self_pub_ded = get_pension_deduction(self_pub_ann)
                ratio = (1 - self_pub_ded / self_pub_ann) if self_pub_ann > 0 else 1
                gong_tx = gong_tg * ratio
                s_nps_tx = s_nps_tg * ratio
            else:
                h_nps_tx, gong_tx, s_nps_tx = h_nps_tg, gong_tg, s_nps_tg
            # [v2.7 6-C] 사적연금 1,500만 초과 시 16.5% 분리 선택
            if priv * 12 > 1500:
                priv_rate_scenario = max(priv_rate_scenario, 16.5)
            gross = h_inc + s_inc + h_nps + gong + s_nps + priv
            tax = h_nps_tx*tax_nps_r/100 + s_nps_tx*tax_nps_r/100 + gong_tx*tax_gong_r/100 + priv*priv_rate_scenario/100
            # 건보료 (연금기만 차감, 근로소득 실수령 전제)
            if (h_nps + gong + s_nps + priv) > 0:
                h = hc_total
                priv_annual = priv * 12
                if priv_annual > 1200:
                    h += (priv_annual - 1200) * 0.09 / 12
            else:
                h = 0
            result.append(gross - tax - h)
        return result

    # 낙관(원문서): 국민 5, 공무 3, 사적 5.5, 건보 35, 장기요양 0, 사업건보 60
    opt = calc_scenario(5, 3, 5.5, 35, 0)
    # 중립: 현재 사용자 입력값
    neu = df["세후"].tolist()
    # 비관: 국민 7, 공무 8, 사적 5.5, 건보 82, 장기 15, 사업건보 110
    pes = calc_scenario(7, 8, 5.5, 82, 15)

    scenario_df = pd.DataFrame({
        "시기": df["시기"], "낙관(원문서)": opt, "중립(현재)": neu, "비관": pes,
        "목표": [target]*len(opt),
    })
    scenario_df["중립-목표"] = scenario_df["중립(현재)"] - target

    col1, col2 = st.columns([1, 1])
    with col1:
        st.dataframe(
            scenario_df.style.format({"낙관(원문서)": "{:,.0f}", "중립(현재)": "{:,.0f}", "비관": "{:,.0f}",
                                      "목표": "{:,.0f}", "중립-목표": "{:+,.0f}"}),
            use_container_width=True, hide_index=True
        )

    with col2:
        fig_sc = go.Figure()
        fig_sc.add_trace(go.Bar(name="낙관(원문서)", x=scenario_df["시기"], y=scenario_df["낙관(원문서)"], marker_color="#70AD47"))
        fig_sc.add_trace(go.Bar(name="중립(현재)", x=scenario_df["시기"], y=scenario_df["중립(현재)"], marker_color="#4472C4"))
        fig_sc.add_trace(go.Bar(name="비관", x=scenario_df["시기"], y=scenario_df["비관"], marker_color="#C00000"))
        fig_sc.add_hline(y=target, line_dash="dash", line_color="red")
        fig_sc.update_layout(barmode="group", height=400, xaxis_title="시기", yaxis_title="월 세후")
        st.plotly_chart(fig_sc, use_container_width=True)

# ---------------- 탭 4 ----------------
with tabs[3]:
    st.subheader("🛡️ 보완축 분석")

    col1, col2 = st.columns([1, 1])
    with col1:
        st.markdown("**ISA 인출 파라미터**")
        isa_info = pd.DataFrame([
            ("ISA 실질 적립총액", f"{fv_isa:,.0f}만"),
            ("월 인출(세전)", f"{isa_draw:,}만"),
            ("월 인출(세후)", f"{isa_net:,.2f}만"),
            ("인출 가능기간", f"{isa_draw_years:.1f}년"),
            ("인출 종료 연령", f"{isa_end_age:.1f}세"),
        ], columns=["항목", "값"])
        st.dataframe(isa_info, use_container_width=True, hide_index=True)

        st.markdown("**주택연금 파라미터**")
        house_info = pd.DataFrame([
            ("사용 여부", "사용" if house_enabled else "미사용"),
            ("가동 연령", f"{house_age}세" if house_enabled else "-"),
            ("월 수령(가동시점)", f"{house_monthly:,}만" if house_enabled else "-"),
            ("명목 고정", "O (실질 감쇠)" if (house_enabled and house_nominal_fixed) else "X"),
            ("건보료 산입", "제외 (공식 비과세)"),
        ], columns=["항목", "값"])
        st.dataframe(house_info, use_container_width=True, hide_index=True)

    with col2:
        # 연도별 누적 효과 (표출 구간 시작~부인 99세까지)
        # [v3.5.1] periods_def 첫 구간 시작 연도를 동적 사용 (50~59세 제거 반영)
        _start_year = periods_def[0][1] if periods_def else 2026
        years = list(range(_start_year, 2076))
        base_series, isa_series, all_series = [], [], []
        for y in years:
            age = self_age(y)
            # base: 현재 세후
            base_val = 0  # 기본값 (매칭 실패 시 안전장치)
            for p in periods_def:
                _, ys, ye, _ = p
                if ys <= y <= (ye if ye < 9999 else 2100):
                    base_val = df.loc[df["시기"] == p[0], "세후"].values[0]
                    break
            base_series.append(base_val)
            isa_add = isa_net if 65 <= age < isa_end_age else 0
            isa_series.append(base_val + isa_add)
            # 주택연금 (사용여부 + 명목 고정 반영)
            if not house_enabled:
                house_add = 0
            elif age >= house_age:
                if house_nominal_fixed:
                    house_start_year = BIRTH_SELF + house_age
                    years_post = max(0, y - house_start_year)
                    house_add = house_monthly / ((1 + inflation/100) ** years_post)
                else:
                    house_add = house_monthly
            else:
                house_add = 0
            all_series.append(base_val + isa_add + house_add)

        # [v3.5.2] X축을 부인 나이로 변경 (다른 차트와 일관성)
        ages_x = [y - BIRTH_SELF for y in years]

        fig_p = go.Figure()
        fig_p.add_trace(go.Scatter(x=ages_x, y=base_series, name="기본 세후(중립)",
                                    line=dict(color="#4472C4", width=2.5), mode="lines+markers",
                                    hovertemplate="부인 %{x}세<br>세후 %{y:,.0f}만<extra></extra>"))
        fig_p.add_trace(go.Scatter(x=ages_x, y=isa_series, name="+ ISA 인출",
                                    line=dict(color="#70AD47", width=2.5), mode="lines+markers",
                                    hovertemplate="부인 %{x}세<br>세후 %{y:,.0f}만<extra></extra>"))
        if house_enabled:
            fig_p.add_trace(go.Scatter(x=ages_x, y=all_series, name="+ 주택연금",
                                        line=dict(color="#C00000", width=3), mode="lines+markers",
                                        hovertemplate="부인 %{x}세<br>세후 %{y:,.0f}만<extra></extra>"))
        fig_p.add_hline(y=target, line_dash="dash", line_color="red", annotation_text=f"목표 {target}만")
        fig_p.update_layout(height=450, xaxis_title="부인 나이(세)", yaxis_title="월 세후(만원, 실질)",
                           title="보완축 누적 효과")
        st.plotly_chart(fig_p, use_container_width=True)

# ---------------- 탭 5 ----------------
with tabs[4]:
    st.subheader("⚠️ 리스크 우선순위 Top 10")

    risks = pd.DataFrame([
        ("ISA 건보료 산입 여부", 50, "건보공단 서면질의", "高"),
        ("주택공시가격", 40, "공시가 알리미", "高"),
        ("재건축 완공·신축 공시가", 35, "조합 발표", "高"),
        ("재건축 분담금", 30, "정비계획 인가", "中"),
        ("회사 정리 시점", 25, "부인 결정", "中"),
        ("종합소득 구간 확정", 20, "종소세 신고", "中"),
        ("임의가입 증액 가능성", 15, "국민연금공단", "低"),
        ("아들 교육비 피크", 15, "부인 결정", "低"),
        ("주담대 승계조건", 10, "은행 상담", "低"),
        ("장기요양보험료 반영", 7, "문서 수정", "低"),
    ], columns=["항목", "월 영향(만)", "확정 경로", "등급"])

    col1, col2 = st.columns([1, 1])
    with col1:
        def color_grade(val):
            if val == "高": return "background-color: #ffcccc; color: #c00;"
            elif val == "中": return "background-color: #ffe4b3; color: #c70;"
            else: return "background-color: #fff4cc; color: #770;"
        st.dataframe(
            risks.style.applymap(color_grade, subset=["등급"]),
            use_container_width=True, hide_index=True, height=400
        )

    with col2:
        fig_r = go.Figure()
        colors = ["#C00000" if g == "高" else "#ED7D31" if g == "中" else "#FFC000" for g in risks["등급"]]
        fig_r.add_trace(go.Bar(
            x=risks["월 영향(만)"], y=risks["항목"],
            orientation="h", marker_color=colors,
            text=risks["확정 경로"], textposition="outside"
        ))
        fig_r.update_layout(height=430, yaxis=dict(autorange="reversed"),
                           xaxis_title="월 영향(만원)", showlegend=False)
        st.plotly_chart(fig_r, use_container_width=True)

# ---------------- 탭 6 ----------------
with tabs[5]:
    st.subheader("💾 내보내기")
    st.caption("현재 입력값과 결과를 표준 5종 산출물로 저장")

    ts = datetime.now().strftime("%Y%m%d_%H%M")
    st.code(f"파일명 타임스탬프: {ts}")

    col1, col2, col3 = st.columns(3)
    with col1:
        csv = df.to_csv(index=False).encode("utf-8-sig")
        st.download_button("📄 CSV 다운로드", csv, f"노후설계_현금흐름_{ts}.csv", "text/csv", use_container_width=True)

    with col2:
        # Excel 내보내기
        import io
        buf = io.BytesIO()
        with pd.ExcelWriter(buf, engine="openpyxl") as writer:
            df.to_excel(writer, sheet_name="현금흐름", index=False)
            pd.DataFrame({
                "항목": ["목표", "남편근로", "부인근로", "연금저축(고정)",
                        "IRP 1단계", "IRP 2단계", "ISA 1단계", "ISA 2단계",
                        "단계 전환 나이", "임의가입(부인)",
                        "남편국민연금", "부인공무원연금", "부인국민연금(자동)", "수익률", "물가",
                        "건보료", "장기요양율", "사적연금인출", "ISA인출", "주택연금연령", "주택연금월액"],
                "값": [target, husband_income, self_income, pension_saving,
                      irp_phase1, irp_phase2, isa_phase1, isa_phase2,
                      phase_transition_age, nps_voluntary,
                      husband_nps, self_gong, self_nps, nominal_return, inflation,
                      health_ins, ltc_rate, private_draw, isa_draw, house_age, house_monthly]
            }).to_excel(writer, sheet_name="입력파라미터", index=False)
        st.download_button("📊 Excel 다운로드", buf.getvalue(),
                          f"노후설계_시뮬결과_{ts}.xlsx",
                          "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                          use_container_width=True)

    with col3:
        # 입력값을 JSON으로
        import json
        params = {
            "husband_income": husband_income, "self_income": self_income,
            "pension_saving": pension_saving,
            "irp_phase1": irp_phase1, "irp_phase2": irp_phase2,
            "isa_phase1": isa_phase1, "isa_phase2": isa_phase2,
            "phase_transition_age": phase_transition_age,
            "nps_voluntary": nps_voluntary,
            "husband_nps": husband_nps, "self_gong": self_gong,
            "self_nps_calc": self_nps,
            "nominal_return": nominal_return, "inflation": inflation,
            "health_ins": health_ins, "ltc_rate": ltc_rate,
            "target": target, "private_draw": private_draw,
            "isa_draw": isa_draw, "house_age": house_age, "house_monthly": house_monthly,
            "timestamp": ts,
        }
        st.download_button("⚙️ 입력파라미터 JSON", json.dumps(params, ensure_ascii=False, indent=2),
                          f"노후설계_파라미터_{ts}.json", "application/json", use_container_width=True)

    st.divider()
    st.markdown("**현재 파라미터 요약**")
    st.json({
        "목표": f"{target}만",
        "월 적립 1단계": f"{_total_p1}만 × {p1_years}년",
        "월 적립 2단계": f"{_total_p2}만 × {p2_years}년",
        "부인 국민연금 자동수령": f"{self_nps:.2f}만",
        "사적연금 적립(실질)": f"{fv_private:,.0f}만",
        "ISA 적립(실질)": f"{fv_isa:,.0f}만",
        "ISA 인출기간": f"{isa_draw_years:.1f}년",
        "목표 미달 구간": df[df["조정세후"] < target]["시기"].tolist() or ["없음"],
    })

# ---------------- 탭 7 — 검토제안 (미반영 항목 설명) ----------------
with tabs[6]:
    st.subheader("⑦ 검토제안 — 추가 반영 가능 항목")
    st.caption("A/B/C/D 멀티에이전트 검토 중 현재 시뮬레이터에 **부분 반영 또는 미반영**된 항목. 각 항목 세부내용을 확인 후 필요 시 사용자 결정에 따라 추가 반영.")

    suggestions = [
        {
            "항목": "✅ 남편/부인 납입 분배",
            "상태": "반영 (Phase 5-B)",
            "설명": "연금저축+IRP 총액을 남편·부인에게 비율로 분배. 세액공제율(16.5% vs 13.2%)이 다를 경우 높은 쪽에 집중 배분하면 환급액 극대화 가능.",
            "현재": f"남편 {husband_saving_ratio}% / 부인 {100-husband_saving_ratio}%",
            "영향": "연 환급 최대 ±30만 차이",
        },
        {
            "항목": "✅ 재산과표 용어 정정",
            "상태": "반영 (Phase 5-C)",
            "설명": "'재산세 과세표준'이 아닌 '주택공시가격 기반 건보 재산과표'. 소득세법(지방세법)과 건보공단 산정기준은 별개 체계.",
            "현재": "공시가 입력 → 재산분 자동 산정",
            "영향": "용어 혼선 제거, 계산 구조 명확화",
        },
        {
            "항목": "✅ 일반 금융소득 건보료",
            "상태": "반영 (Phase 5-D)",
            "설명": "ISA 외 일반 예금이자·배당 등 금융소득이 연 1,000만 초과 시 건보료 소득 산정. 사이드바 '일반 금융소득' 섹션에서 입력.",
            "현재": f"입력: {other_financial_income}만/년",
            "영향": "1,000만 초과분 × 9% 추가 건보",
        },
        {
            "항목": "✅ 근로소득 세후 실수령 전제",
            "상태": "반영",
            "설명": "부부 모두 일반 근로자. 세후 실수령에 건보·세금·연금 이미 차감됨 → 근로기 건보료 추가 차감 없음.",
            "현재": "근로기 hc = 0 (연금기만 차감)",
            "영향": "실수령 그대로 적립 가능",
        },
        {
            "항목": "🔲 근로기 공적연금 종합과세 누진 모사",
            "상태": "미반영 (향후 반영 대상)",
            "설명": "2026~2035 적립기에 사업소득+공적연금 병행 시 종합과세 누진 15~24% 구간 진입. 현재 코드는 연금 단일세율만 적용. 사업기에는 아직 연금 수령이 없어서 현재 모델엔 영향 없음 (2038~ 이후 구간은 사업소득 0이므로 이 문제 발생 안 함).",
            "현재": "현재 기본값에서는 영향 없음",
            "영향": "입력값 변경 시에만 발생",
        },
        {
            "항목": "🔲 ISA 종합과세 비교 옵션",
            "상태": "미반영 (향후 반영 대상)",
            "설명": "ISA 초과분 9.9% 분리과세 vs 종합과세(6~45%) 선택 가능. 부인 소득수준 낮으면 종합과세가 유리할 수 있음. 현재는 분리과세 고정.",
            "현재": "분리과세 9.9% 고정",
            "영향": "과세표준 낮으면 월 1~3만 절세 가능",
        },
        {
            "항목": "🔲 ISA 재가입 시나리오",
            "상태": "**제외 확정** (사용자 결정)",
            "설명": "12년 적립 후 비과세 한도 초과 시 재가입으로 한도 복원. 현재 설계(7,200만 납입)는 1억 한도 내 → 재가입 불필요로 판단.",
            "현재": "재가입 없음 전제 유지",
            "영향": "영향 없음",
        },
        {
            "항목": "🔲 피부양자 전환 시나리오 탭",
            "상태": "부분 반영 (향후 상세 반영 대상)",
            "설명": "남편·부인 모두 직장가입자(2026~2037) → 공무원연금 개시(2038) 후 지역가입자 전환 자동 발생. 자녀 피부양자 등재 시나리오는 추가 탭으로 분리 가능.",
            "현재": "단순 직장/지역 전환만 반영",
            "영향": "자녀 피부양 등재 시 월 -80만",
        },
    ]

    for s in suggestions:
        with st.container(border=True):
            c1, c2 = st.columns([3, 1])
            c1.markdown(f"### {s['항목']}")
            c2.markdown(f"**{s['상태']}**")
            st.write(s['설명'])
            c3, c4 = st.columns(2)
            c3.markdown(f"**현재 설정**: {s['현재']}")
            c4.markdown(f"**월 영향**: {s['영향']}")

    st.markdown("---")
    st.info("📝 **외부 정보 수집 필요 항목** (현재 향후 반영 대상):\n"
            "- ISA 건보 산입 여부 공단 서면질의 (1577-1000)\n"
            "- 아파트 주택공시가격 조회 (부동산공시가격 알리미)\n"
            "- 종합소득세 신고서 기반 세액공제율 확정\n"
            "- 국민연금공단 임의가입 증액 상담\n"
            "- 재건축 특별정비계획 인가·분담금 확정")

# 푸터
st.divider()
st.caption("📌 본 시뮬레이터는 작업지시서 v2.6 기반이며, 단일 도구의 판단이 아닌 A/B/C/D/E 멀티에이전트 검증 권고 참고용입니다.")
