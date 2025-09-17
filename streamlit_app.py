import os
import re
from datetime import datetime, timezone
import requests
from typing import Dict, Any, List

import streamlit as st


# -----------------------------
# Environment & Config
# -----------------------------
# Prefer Streamlit secrets; fallback to OS env vars
API_KEY = (st.secrets.get("YOUTUBE_API_KEY", os.getenv("YOUTUBE_API_KEY", ""))).strip()

YOUTUBE_API_URL = "https://www.googleapis.com/youtube/v3/videos"
DEFAULT_REGION = (st.secrets.get("YOUTUBE_REGION", os.getenv("YOUTUBE_REGION", "KR"))).strip() or "KR"
MAX_RESULTS = 30


# -----------------------------
# Helpers
# -----------------------------
@st.cache_data(show_spinner=False, ttl=300)
def fetch_most_popular(api_key: str, region_code: str, max_results: int = 30) -> Dict[str, Any]:
    """Fetch most popular videos from YouTube Data API v3.

    Returns a dict with either {"items": [...]} or {"error": "message"}
    """
    if not api_key:
        return {"error": "API 키가 설정되지 않았습니다. .env에 YOUTUBE_API_KEY를 설정하세요."}

    params = {
        "part": "snippet,statistics,contentDetails",
        "chart": "mostPopular",
        "regionCode": region_code or "KR",
        "maxResults": max_results,
        "key": api_key,
    }

    try:
        resp = requests.get(YOUTUBE_API_URL, params=params, timeout=10)
        if resp.status_code != 200:
            # Try to parse YouTube error if available
            try:
                j = resp.json()
                msg = j.get("error", {}).get("message", resp.text)
            except Exception:
                msg = resp.text
            return {"error": f"YouTube API 오류 (status {resp.status_code}): {msg}"}
        data = resp.json()
        items = data.get("items", [])
        return {"items": items}
    except requests.Timeout:
        return {"error": "요청 시간이 초과되었습니다. 잠시 후 다시 시도하세요."}
    except requests.RequestException as e:
        return {"error": f"네트워크 오류가 발생했습니다: {e}"}
    except Exception as e:
        return {"error": f"알 수 없는 오류가 발생했습니다: {e}"}


@st.cache_data(show_spinner=False, ttl=3600)
def fetch_categories(api_key: str, region_code: str) -> Dict[str, str]:
    """카테고리 ID -> 이름 매핑을 반환합니다. (예: {"10": "음악"})"""
    if not api_key:
        return {}
    url = "https://www.googleapis.com/youtube/v3/videoCategories"
    params = {
        "part": "snippet",
        "regionCode": region_code or "KR",
        "key": api_key,
        "hl": "ko",
    }
    try:
        resp = requests.get(url, params=params, timeout=10)
        if resp.status_code != 200:
            return {}
        data = resp.json()
        items = data.get("items", [])
        mapping = {}
        for it in items:
            cid = it.get("id")
            name = (it.get("snippet") or {}).get("title")
            if cid and name:
                mapping[cid] = name
        return mapping
    except Exception:
        return {}


def format_views(views: str | int | None) -> str:
    try:
        n = int(views or 0)
        return f"{n:,}회"
    except Exception:
        return "조회수 정보 없음"


def format_compact_korean(num: str | int | None) -> str:
    """숫자를 한국어 축약(천/만/억)으로 표기. 예) 12543 -> 1.3만"""
    try:
        n = int(num or 0)
    except Exception:
        return "-"
    def strip_trailing_zero(s: str) -> str:
        return s[:-2] if s.endswith(".0") else s
    if n >= 100_000_000:
        return strip_trailing_zero(f"{n/100_000_000:.1f}") + "억"
    if n >= 10_000:
        return strip_trailing_zero(f"{n/10_000:.1f}") + "만"
    if n >= 1_000:
        return strip_trailing_zero(f"{n/1_000:.1f}") + "천"
    return f"{n}"


def parse_iso8601_duration(pt: str | None) -> str:
    """ISO8601 기간(예: PT5M32S, PT1H2M)를 h:mm:ss 또는 m:ss 로 변환"""
    if not pt:
        return "-"
    # 정규식으로 H, M, S 추출
    m = re.fullmatch(r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", pt)
    if not m:
        return "-"
    h = int(m.group(1) or 0)
    mi = int(m.group(2) or 0)
    s = int(m.group(3) or 0)
    total_seconds = h * 3600 + mi * 60 + s
    if total_seconds <= 0:
        return "-"
    if h > 0:
        return f"{h}:{mi:02d}:{s:02d}"
    else:
        return f"{mi}:{s:02d}"


def format_relative_time_korean(iso_time: str | None) -> str:
    """ISO8601 UTC 시간(예: 2024-09-01T12:34:56Z)을 'n일 전' 등으로 표시"""
    if not iso_time:
        return "-"
    try:
        # Z -> +00:00 로 바꾸어 fromisoformat 사용
        t = iso_time.replace("Z", "+00:00")
        dt = datetime.fromisoformat(t)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        now = datetime.now(timezone.utc)
        diff = now - dt
        seconds = int(diff.total_seconds())

        if seconds < 60:
            return "방금 전"
        minutes = seconds // 60
        if minutes < 60:
            return f"{minutes}분 전"
        hours = minutes // 60
        if hours < 24:
            return f"{hours}시간 전"
        days = hours // 24
        if days < 7:
            return f"{days}일 전"
        weeks = days // 7
        if weeks < 5:
            return f"{weeks}주 전"
        months = days // 30
        if months < 12:
            return f"{months}개월 전"
        years = days // 365
        return f"{years}년 전"
    except Exception:
        return "-"


# -----------------------------
# UI
# -----------------------------
st.set_page_config(page_title="인기 YouTube 동영상", page_icon="📺", layout="wide")

st.title("📺 YouTube 인기 동영상")
st.caption("간단한 YouTube API로 인기 동영상을 보여주는 데모 앱")

"""
간단 로그인 구현: st.secrets["auth"]["users"] 에 정의된 사용자/비밀번호로 인증
구조 예시 (secrets.toml):
[auth]
enabled = true

[auth.users]
demo = "demo123"
"""

def is_authenticated() -> bool:
    auth_conf = st.secrets.get("auth", {})
    enabled = bool(auth_conf.get("enabled", False))
    if not enabled:
        return True
    if st.session_state.get("auth_user"):
        return True
    return False

def login_ui():
    with st.sidebar:
        st.header("로그인")
        st.write("개별 사용을 위해 로그인하세요.")
        uname = st.text_input("아이디", key="login_username")
        upwd = st.text_input("비밀번호", type="password", key="login_password")
        do_login = st.button("로그인")
    if do_login:
        users = (st.secrets.get("auth", {}).get("users", {}))
        expected = users.get(uname)
        if expected and str(expected) == str(upwd):
            st.session_state["auth_user"] = uname
            st.success("로그인 성공")
            st.rerun()
        else:
            st.error("아이디 또는 비밀번호가 올바르지 않습니다.")

def logout_ui():
    with st.sidebar:
        if st.button("로그아웃"):
            st.session_state.pop("auth_user", None)
            st.experimental_set_query_params()  # 상태 초기화 보조
            st.rerun()

if not is_authenticated():
    login_ui()
    st.stop()

logout_ui()

with st.sidebar:
    st.header("설정")
    region = st.text_input("Region Code (예: KR, US, JP)", value=DEFAULT_REGION, max_chars=2)

    cols = st.columns([1, 1])
    do_refresh = cols[0].button("🔄 새로고침")
    if do_refresh:
        st.cache_data.clear()
        st.rerun()

# Fetch data (region 입력값을 사용)
result = fetch_most_popular(API_KEY, region, MAX_RESULTS)

if "error" in result:
    st.error(result["error"])
    st.info(
        "• .env 파일에 YOUTUBE_API_KEY를 설정했는지 확인하세요.\n"
        "• API 쿼터 초과 또는 키 권한 문제일 수 있습니다."
    )
    st.stop()

items: List[Dict[str, Any]] = result.get("items", [])
if not items:
    st.warning("표시할 동영상이 없습니다.")
    st.stop()

"""
필터 UI: 검색, 카테고리, 조회수 범위
"""
with st.sidebar:
    st.divider()
    st.header("필터")
    query = st.text_input("검색 (제목/채널)", value="", placeholder="예: 음악, BTS, 게임…")

    # 카테고리 목록 불러오기 (한국어 제목 요청)
    cat_map = fetch_categories(API_KEY, region)
    present_ids = sorted({(v.get("snippet") or {}).get("categoryId") for v in items if (v.get("snippet") or {}).get("categoryId")})
    options = [cat_map.get(cid, f"ID {cid}") for cid in present_ids]
    selected_names = st.multiselect("카테고리", options)
    # 이름 -> ID 역매핑
    name_to_id = {cat_map.get(cid, f"ID {cid}"): cid for cid in present_ids}
    selected_ids = {name_to_id[name] for name in selected_names if name in name_to_id}

    # 조회수 범위 슬라이더
    view_values = []
    for v in items:
        try:
            view_values.append(int((v.get("statistics") or {}).get("viewCount", 0)))
        except Exception:
            view_values.append(0)
    vmax = max(view_values) if view_values else 0
    slider_max = max(1000, vmax)
    view_min, view_max = st.slider("조회수 범위", min_value=0, max_value=slider_max, value=(0, slider_max), step=1000, format="%d")

# 필터 적용
def item_matches(v: Dict[str, Any]) -> bool:
    sn = v.get("snippet") or {}
    stt = v.get("statistics") or {}
    title = (sn.get("title") or "").lower()
    channel = (sn.get("channelTitle") or "").lower()
    if query:
        q = query.lower().strip()
        if q and (q not in title and q not in channel):
            return False
    if selected_ids:
        cid = sn.get("categoryId")
        if cid not in selected_ids:
            return False
    try:
        vc = int(stt.get("viewCount", 0))
    except Exception:
        vc = 0
    if vc < view_min or vc > view_max:
        return False
    return True

filtered_items = [v for v in items if item_matches(v)]

st.subheader(f"총 {len(filtered_items)}개 동영상")

# Display list of videos
for idx, v in enumerate(filtered_items, start=1):
    vid = v.get("id", "")
    snip = v.get("snippet", {})
    stats = v.get("statistics", {})
    details = v.get("contentDetails", {})

    title = snip.get("title", "제목 없음")
    channel = snip.get("channelTitle", "채널 정보 없음")
    thumbs = snip.get("thumbnails", {})
    thumb = (
        thumbs.get("medium")
        or thumbs.get("high")
        or thumbs.get("standard")
        or thumbs.get("default")
        or {}
    ).get("url")

    view_count = stats.get("viewCount")
    view_text = format_views(view_count)
    like_count = stats.get("likeCount")
    comment_count = stats.get("commentCount")
    duration_iso = details.get("duration")
    duration_text = parse_iso8601_duration(duration_iso)
    published_at = snip.get("publishedAt")
    rel_time = format_relative_time_korean(published_at)
    like_text = format_compact_korean(like_count)
    comment_text = format_compact_korean(comment_count)

    url = f"https://www.youtube.com/watch?v={vid}"

    # Layout per row
    c1, c2 = st.columns([1, 3])
    with c1:
        if thumb:
            st.image(thumb, use_container_width=True)
        else:
            st.write("썸네일 없음")
    with c2:
        st.markdown(f"**{idx}. [{title}]({url})**")
        st.write(f"채널: {channel}")
        st.write(f"조회수: {view_text}")
        # 이모지로 각종 통계 표시
        st.write(f"👍 {like_text} | 💬 {comment_text} | ⏱️ {duration_text} | 📅 {rel_time}")

st.success("완료")

