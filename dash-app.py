import streamlit as st
import pandas as pd
from googleapiclient.discovery import build
from datetime import datetime, timezone, timedelta
from dateutil.parser import isoparse

# === KONFIG ===
API_KEY = "AIzaSyCEhqf92qs5ykEUNG15e_3h6bPO71m0TuU"  # Lägg in din API key här
MY_HANDLE = "@NextMomentumClips"     # Din kanal-handle
CUTOFF = isoparse("2025-05-01T00:00:00Z")  # Jämför mot nya kanaler från maj

yt = build("youtube", "v3", developerKey=API_KEY)

def get_channel_info(handle):
    res = yt.channels().list(
        part="snippet,statistics",
        forHandle=handle
    ).execute()
    info = res["items"][0]
    return {
        "id": info["id"],
        "title": info["snippet"]["title"],
        "subs": int(info["statistics"].get("subscriberCount",0)),
        "views": int(info["statistics"].get("viewCount",0)),
        "videos": int(info["statistics"].get("videoCount",0))
    }

def get_last_videos(channel_id, days=7):
    res = yt.search().list(
        part="id,snippet",
        channelId=channel_id,
        order="date",
        maxResults=50
    ).execute()
    vids = [v["id"]["videoId"] for v in res["items"] if v["id"]["kind"]=="youtube#video"]

    stats = []
    for i in range(0, len(vids), 50):
        r = yt.videos().list(
            part="statistics,snippet",
            id=",".join(vids[i:i+50])
        ).execute()
        for it in r["items"]:
            stats.append({
                "title": it["snippet"]["title"],
                "publishedAt": it["snippet"]["publishedAt"],
                "views": int(it["statistics"].get("viewCount",0)),
                "likes": int(it["statistics"].get("likeCount",0)),
                "comments": int(it["statistics"].get("commentCount",0))
            })
    df = pd.DataFrame(stats)
    df["publishedAt"] = pd.to_datetime(df["publishedAt"])
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    return df[df["publishedAt"] >= cutoff], df

def search_shorts(q, published_after, max_results=50):
    res = yt.search().list(
        part="id,snippet",
        q=q,
        type="video",
        maxResults=max_results,
        publishedAfter=published_after,
        videoDuration="short"
    ).execute()
    items = []
    for it in res.get("items", []):
        if it["id"]["kind"] == "youtube#video":
            items.append({
                "videoId": it["id"]["videoId"],
                "title": it["snippet"]["title"],
                "channelId": it["snippet"]["channelId"],
                "channelTitle": it["snippet"]["channelTitle"],
                "videoPublishedAt": it["snippet"]["publishedAt"]
            })
    return items

def chunk(lst, n=50):
    for i in range(0, len(lst), n):
        yield lst[i:i+n]

st.title("📊 YouTube Dashboard – NextMomentum")

info = get_channel_info(MY_HANDLE)
st.subheader("Din kanal")
c1, c2, c3 = st.columns(3)
c1.metric("Subscribers", f"{info['subs']:,}")
c2.metric("Totala visningar", f"{info['views']:,}")
c3.metric("Totala videos", f"{info['videos']:,}")

df7, df_all = get_last_videos(info["id"], days=7)
views7 = df7["views"].sum()
daily = round(views7/7,1) if views7 > 0 else 0

st.subheader("Senaste 7 dagar")
st.metric("Totala views (7d)", f"{views7:,}")
st.metric("Snitt views/dag", f"{daily:,}")
st.write("📈 Senaste videos")
st.dataframe(df_all.sort_values("publishedAt", ascending=False).head(10))

proj_30d = int(daily*30)
proj_90d = int(daily*90)
st.subheader("Prognos (om tempot håller)")
st.write(f"➡️ Om 30 dagar: ~{proj_30d:,} extra views")
st.write(f"➡️ Om 90 dagar: ~{proj_90d:,} extra views")

st.subheader("Peer-jämförelse")
KEYWORDS = [
    "Charlie Kirk", "Israel debate", "Turkey NATO", "immigration debate",
    "Candace Owens", "Patrick Bet-David", "Middle East politics", "campus protest",
    "Jordan Peterson debate", "Ben Shapiro", "Tucker Carlson", "Andrew Tate",
    "Donald Trump speech", "Biden gaffe", "Palestine protest", "college debate",
    "viral politics", "congress hearing", "freedom of speech debate", "US politics"
]

rows = []
for kw in KEYWORDS:
    rows += search_shorts(kw, CUTOFF.isoformat(), max_results=25)

df = pd.DataFrame(rows).drop_duplicates(subset=["videoId"]).reset_index(drop=True)

stats_rows = []
for group in chunk(df["videoId"].tolist(), 50):
    res = yt.videos().list(
        part="contentDetails,statistics",
        id=",".join(group)
    ).execute()
    for it in res.get("items", []):
        dur = it["contentDetails"]["duration"]
        is_short = dur.startswith("PT") and ("M" not in dur)
        if is_short:
            stats_rows.append({
                "videoId": it["id"],
                "views": int(it["statistics"].get("viewCount",0))
            })

stats = pd.DataFrame(stats_rows)
df = df.merge(stats, on="videoId", how="left")

CHANNELS = df["channelId"].drop_duplicates().tolist()
chan_rows = []
for group in chunk(CHANNELS, 50):
    res = yt.channels().list(
        part="snippet,statistics",
        id=",".join(group)
    ).execute()
    for it in res.get("items", []):
        chan_rows.append({
            "channelId": it["id"],
            "channelPublishedAt": it["snippet"]["publishedAt"],
            "subs": int(it["statistics"].get("subscriberCount",0)),
            "viewCount": int(it["statistics"].get("viewCount",0)),
            "handle": it["snippet"].get("customUrl") or it["snippet"]["title"]
        })

ch = pd.DataFrame(chan_rows)
df = df.merge(ch, on="channelId", how="left")
df["channelCreated"] = pd.to_datetime(df["channelPublishedAt"], errors="coerce")
peers = df[df["channelCreated"] >= CUTOFF].copy()

peer_summary = (
    peers.groupby(["channelId","handle"])
    .agg(channel_views=("viewCount","max"),
         channel_subs=("subs","max"),
         median_video_views=("views","median"),
         p75_video_views=("views", lambda x: int(pd.Series(x).quantile(0.75))),
         latest_video=("videoPublishedAt","max"))
    .reset_index()
    .sort_values("p75_video_views", ascending=False)
)

st.write("Top 20 peers (nya kanaler ≥ maj 2025)")
st.dataframe(peer_summary.head(20))

all_p75 = peer_summary["p75_video_views"].tolist()
if daily > 0 and len(all_p75) > 0:
    my_rank = sum(v <= daily for v in all_p75) / len(all_p75) * 100
    st.metric("Din percentilrank", f"Top {my_rank:.1f}%")
