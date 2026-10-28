
import re
import time
from collections import Counter
from urllib.parse import urlparse, parse_qs

import pandas as pd
import plotly.express as px
import requests
import streamlit as st

st.set_page_config(
    page_title="유튜브 댓글 분석기",
    page_icon="📊",
    layout="wide",
)

API_URL = "https://www.googleapis.com/youtube/v3/commentThreads"
VIDEO_API_URL = "https://www.googleapis.com/youtube/v3/videos"
MAX_COMMENTS = 500

STOPWORDS = set("""
그리고 하지만 그래서 정말 너무 진짜 그냥 약간 조금 많이
하는 있는 없는 이런 저런 그것 이거 저거 여기 저기
나는 제가 저는 우리가 너는 너무에서 으로에게 에서
입니다 있어요 했어요 해요 하는데 같은 대한 통해
오늘 지금 경우 부분 생각 영상 댓글 유튜브 사람
the and for that this with you are was have from
your just not but all can its they their what when
""".split())


def get_video_id(url):
    """유튜브 URL에서 영상 ID 추출"""
    url = url.strip()

    parsed = urlparse(
        url if "://" in url else "https://" + url
    )
    host = parsed.netloc.lower().split(":")[0]
    path_parts = [p for p in parsed.path.split("/") if p]

    if host in ("youtu.be", "www.youtu.be"):
        return path_parts[0] if path_parts else None

    if host.endswith("youtube.com") or host.endswith("youtube-nocookie.com"):
        if parsed.path == "/watch":
            return parse_qs(parsed.query).get("v", [None])[0]

        if len(path_parts) >= 2 and path_parts[0] in (
            "shorts", "embed", "live"
        ):
            return path_parts[1]

    return None


def get_video_title(video_id, api_key):
    """영상 제목 조회"""
    response = requests.get(
        VIDEO_API_URL,
        params={
            "part": "snippet",
            "id": video_id,
            "key": api_key,
        },
        timeout=20,
    )
    response.raise_for_status()
    items = response.json().get("items", [])

    if not items:
        return "유튜브 영상"

    return items[0]["snippet"]["title"]


def fetch_comments(video_id, api_key, limit=500):
    """최상위 댓글을 최대 limit개까지 수집"""
    comments = []
    page_token = None

    progress = st.progress(0, text="댓글을 수집하고 있어요...")

    while len(comments) < limit:
        batch_size = min(100, limit - len(comments))

        params = {
            "part": "snippet",
            "videoId": video_id,
            "maxResults": batch_size,
            "order": "relevance",
            "textFormat": "plainText",
            "key": api_key,
        }

        if page_token:
            params["pageToken"] = page_token

        response = requests.get(
            API_URL,
            params=params,
            timeout=30,
        )

        if not response.ok:
            try:
                error_data = response.json().get("error", {})
                error_message = error_data.get(
                    "message", response.text
                )
                error_reason = (
                    error_data.get("errors", [{}])[0].get("reason", "")
                )
            except (ValueError, IndexError, AttributeError):
                error_message = response.text
                error_reason = ""

            if error_reason == "commentsDisabled":
                raise ValueError(
                    "이 영상은 댓글이 사용 중지되어 있어요."
                )

            if response.status_code == 403:
                raise ValueError(
                    "API 권한 또는 할당량을 확인해 주세요. "
                    + error_message
                )

            raise ValueError(
                f"YouTube API 오류 ({response.status_code}): "
                + error_message
            )

        data = response.json()
        items = data.get("items", [])

        for item in items:
            snippet = item["snippet"]["topLevelComment"]["snippet"]

            comments.append({
                "작성자": snippet.get("authorDisplayName", "알 수 없음"),
                "댓글": snippet.get("textDisplay", ""),
                "좋아요": int(snippet.get("likeCount", 0)),
                "작성일": snippet.get("publishedAt", ""),
            })

        progress.progress(
            min(len(comments) / limit, 1.0),
            text=f"댓글 수집 중... {len(comments)}개"
        )

        page_token = data.get("nextPageToken")

        if not page_token or not items:
            break

    progress.empty()
    return comments


def extract_keywords(texts, top_n=20):
    """간단한 한국어·영어 키워드 빈도 분석"""
    counter = Counter()

    for text in texts:
        words = re.findall(
            r"[가-힣]{2,}|[A-Za-z][A-Za-z0-9']{2,}",
            str(text).lower(),
        )

        for word in words:
            if word not in STOPWORDS and not word.isdigit():
                counter[word] += 1

    return counter.most_common(top_n)


def show_error(error):
    st.error(str(error))


# 헤더
st.title("📊 유튜브 댓글 분석기")
st.write(
    "영상 링크를 입력하면 인기 댓글 TOP 10, "
    "키워드 순위와 통계를 확인할 수 있어요."
)

st.info(
    "분석 대상은 수집한 최대 500개의 최상위 댓글입니다. "
    "답글은 포함하지 않으며, 좋아요 순위는 수집된 댓글 안에서 계산합니다."
)

# API 키
try:
    api_key = st.secrets["YOUTUBE_API_KEY"]
except (KeyError, FileNotFoundError):
    api_key = None

if not api_key:
    st.warning(
        "YouTube API 키가 아직 설정되지 않았어요. "
        "아래의 배포 안내에서 Secrets 설정 방법을 확인해 주세요."
    )
    st.stop()

# 입력 화면
with st.form("youtube_form"):
    youtube_url = st.text_input(
        "유튜브 영상 링크",
        placeholder="https://www.youtube.com/watch?v=...",
    )

    submitted = st.form_submit_button(
        "🔍 댓글 분석하기",
        type="primary",
        use_container_width=True,
    )

if submitted:
    video_id = get_video_id(youtube_url)

    if not video_id:
        st.error("올바른 유튜브 영상 URL을 입력해 주세요.")
    else:
        try:
            with st.spinner("영상과 댓글을 분석하고 있어요..."):
                title = get_video_title(video_id, api_key)
                comments = fetch_comments(
                    video_id,
                    api_key,
                    MAX_COMMENTS,
                )

            if not comments:
                st.warning("가져올 수 있는 댓글이 없어요.")
                st.session_state.pop("analysis_data", None)
            else:
                df = pd.DataFrame(comments)
                df["작성일"] = pd.to_datetime(
                    df["작성일"], errors="coerce", utc=True
                )

                st.session_state["analysis_data"] = {
                    "title": title,
                    "video_id": video_id,
                    "df": df,
                }

        except (ValueError, requests.RequestException) as error:
            show_error(error)
        except Exception as error:
            st.error(f"예상하지 못한 오류가 발생했어요: {error}")

# 결과 표시
analysis = st.session_state.get("analysis_data")

if analysis:
    df = analysis["df"]
    title = analysis["title"]

    st.divider()
    st.subheader("🎬 " + title)

    # 핵심 통계
    total_comments = len(df)
    total_likes = int(df["좋아요"].sum())
    avg_likes = df["좋아요"].mean()
    max_likes = int(df["좋아요"].max())

    c1, c2, c3, c4 = st.columns(4)

    c1.metric("수집한 댓글", f"{total_comments:,}개")
    c2.metric("총 좋아요", f"{total_likes:,}개")
    c3.metric("댓글당 평균 좋아요", f"{avg_likes:.1f}개")
    c4.metric("최고 좋아요", f"{max_likes:,}개")

    st.divider()

    # 좋아요 TOP 10
    st.subheader("🏆 좋아요 TOP 10 댓글")

    top10 = (
        df.sort_values("좋아요", ascending=False)
        .head(10)
        .reset_index(drop=True)
    )

    for rank, row in top10.iterrows():
        with st.container(border=True):
            st.markdown(
                f"**{rank + 1}위 · ❤️ {int(row['좋아요']):,}개**"
            )
            st.write(row["댓글"])
            st.caption(f"작성자: {row['작성자']}")

    st.divider()

    # 좋아요 그래프
    st.subheader("📈 인기 댓글 비교")

    chart_df = top10.copy()
    chart_df["순위"] = [
        f"{i + 1}위" for i in range(len(chart_df))
    ]
    chart_df["댓글 미리보기"] = chart_df["댓글"].apply(
        lambda x: str(x).replace("\n", " ")[:35]
        + ("..." if len(str(x)) > 35 else "")
    )

    fig = px.bar(
        chart_df,
        x="좋아요",
        y="댓글 미리보기",
        orientation="h",
        hover_data=["작성자", "순위"],
        title="좋아요가 많은 댓글 TOP 10",
        labels={
            "좋아요": "좋아요 수",
            "댓글 미리보기": "댓글",
        },
    )
    fig.update_layout(
        yaxis={"categoryorder": "total ascending"},
        height=500,
    )
    st.plotly_chart(fig, use_container_width=True)

    # 좋아요 분포
    st.subheader("📊 전체 댓글 좋아요 분포")

    hist_fig = px.histogram(
        df,
        x="좋아요",
        nbins=20,
        title="댓글별 좋아요 수 분포",
        labels={"좋아요": "좋아요 수", "count": "댓글 수"},
    )
    st.plotly_chart(hist_fig, use_container_width=True)

    # 키워드
    st.divider()
    st.subheader("🔎 자주 등장하는 키워드 TOP 20")

    keywords = extract_keywords(df["댓글"].tolist())

    if keywords:
        keyword_df = pd.DataFrame(
            keywords, columns=["키워드", "등장 횟수"]
        )

        k1, k2 = st.columns([1, 2])

        with k1:
            st.dataframe(
                keyword_df,
                use_container_width=True,
                hide_index=True,
            )

        with k2:
            keyword_fig = px.bar(
                keyword_df.sort_values("등장 횟수"),
                x="등장 횟수",
                y="키워드",
                orientation="h",
                title="키워드 빈도",
            )
            st.plotly_chart(
                keyword_fig,
                use_container_width=True,
            )
    else:
        st.info("분석할 키워드가 충분하지 않아요.")

    # 댓글 전체 목록
    st.divider()
    st.subheader("💬 수집한 댓글 전체")

    sorted_df = df.sort_values(
        "좋아요", ascending=False
    ).copy()

    display_df = sorted_df.copy()
    display_df["작성일"] = display_df["작성일"].astype(str)

    st.dataframe(
        display_df,
        use_container_width=True,
        hide_index=True,
    )

    csv_data = sorted_df.to_csv(
        index=False
    ).encode("utf-8-sig")

    st.download_button(
        "📥 댓글 분석 결과 CSV 다운로드",
        data=csv_data,
        file_name="youtube_comments_analysis.csv",
        mime="text/csv",
        use_container_width=True,
    )

st.caption(
    "참고: 키워드는 단순 빈도 기준이며, "
    "한국어 조사 제거와 문맥 분석은 수행하지 않습니다."
)
