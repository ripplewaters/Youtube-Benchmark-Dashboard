import streamlit as st
import pandas as pd
from googleapiclient.discovery import build
from datetime import datetime, timezone, timedelta
from dateutil.parser import isoparse

# === KONFIG ===
API_KEY = "DIN_YOUTUBE_API_KEY_HÄR"   # <-- Lägg in din YouTube API key här
MY_HANDLE = "@NextMomentumClips"
CUTOFF = isoparse("2025-05-01T00:00:00Z")

yt = build("youtube", "v3", developerKey=API_KEY)

def get_channel_info(handle):
    res = yt.channels().list(part="snippet,statistics", forHandle=handle).execute()
    info = res["items"][0]
    return {
        "id": info["id"],
        "title": info["snippet"]["title"],
        "subs": int(info["statistics"].get("subscriberCount",0)),
        "views": int(info["statistics"].get("viewCount",0)),
        "videos": int(info["statistics"].get("videoCount",0))
    }

def get_last_videos(channel_id, days=7):
    # Hämta uploads playlist
    res = yt.channels().list(part="contentDetails", id=channel_id).execute()
    uploads_id = res["items"][0]["contentDetails"]["relatedPlaylists"]["uploads"]

    # Hämta senaste videos
    videos = []
    next_page = None
    while True:
        r = yt.playlistItems().list(
            part="contentDetails",
            playlistId=uploads_id,
            maxResults=50,
            pageToken=next_page
        ).execute()
        videos += [it["contentDetails"]["videoId"] for it in r["items"]]
        next_page = r.get("nextPageToken")
        if not next_page or len(videos) >= 100:
            break

    # Hämta statistik
    stats = []
    for i in range(0, len(videos), 50):
        r = yt.videos().list(part="statistics,snippet", id=",".join(videos[i:i+50])).execute()
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

def search_shorts(q, published_after, max_results=20):
    res = yt.search().list(
        part="id,snippet", q=q, type="video",
        maxResults=max_results, publishedAfter=published_after,
        videoDuration="short"
    ).execute()
    return [
        {
            "videoId": it["id"]["videoId"],
            "title": it["snippet"]["title"],
            "channelId": it["snippet"]["channelId"],
            "channelTitle": it["snippet"]["channelTitle"],
            "videoPublishedAt": it["snippet"]["publishedAt"]
        }
        for it in res.get("items", []) if it["id"]["kind"]=="youtube#video"
    ]

def chunk(lst, n=50):
    for i in range(0, len(lst), n):
        yield lst[i:i+n]

st.title("📊 YouTube Benchmark Dashboard")

info = get_channel_info(MY_HANDLE)
c1, c2, c3 = st.columns(3)
c1.metric("Subscribers", f"{info['subs']:,}")
c2.metric("Totala visningar", f"{info['views']:,}")
c3.metric("Totala videos", f"{info['videos']:,}")

df7, df_all = get_last_videos(info["id"], days=7)
views7 = df7["views"].sum()
daily = round(views7/7,1) if views7>0 else 0

st.subheader("Senaste 7 dagar")
st.metric("Totala views (7d)", f"{views7:,}")
st.metric("Snitt views/dag", f"{daily:,}")
st.write("📈 Senaste videos")
st.dataframe(df_all.sort_values("publishedAt", ascending=False).head(10))

proj_30d = int(daily*30)
proj_90d = int(daily*90)
st.subheader("Prognos")
st.write(f"➡️ Om 30 dagar: ~{proj_30d:,} extra views")
st.write(f"➡️ Om 90 dagar: ~{proj_90d:,} extra views")

st.subheader("Peer-jämförelse")
KEYWORDS = [
    "Charlie Kirk","Israel debate","Turkey NATO","immigration debate",
    "Candace Owens","Patrick Bet-David","Jordan Peterson","Ben Shapiro",
    "Tucker Carlson","Andrew Tate","Donald Trump","Biden gaffe",
    "Palestine protest","college debate","viral politics","freedom of speech"
]

rows = []
for kw in KEYWORDS:
    rows += search_shorts(kw, CUTOFF.isoformat(), max_results=10)

df = pd.DataFrame(rows).drop_duplicates(subset=["videoId"]).reset_index(drop=True)

stats_rows = []
for group in chunk(df["videoId"].tolist(), 50):
    res = yt.videos().list(part="contentDetails,statistics", id=",".join(group)).execute()
    for it in res.get("items", []):
        stats_rows.append({"videoId": it["id"], "views": int(it["statistics"].get("viewCount",0))})
stats = pd.DataFrame(stats_rows)
df = df.merge(stats, on="videoId", how="left")

chan_rows = []
for group in chunk(df["channelId"].tolist(), 50):
    res = yt.channels().list(part="snippet,statistics", id=",".join(group)).execute()
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
if daily>0 and len(all_p75)>0:
    my_rank = sum(v <= daily for v in all_p75)/len(all_p75)*100
    st.metric("Din percentilrank", f"Top {my_rank:.1f}%")

