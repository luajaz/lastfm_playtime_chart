import time
import requests
import json
import logging

import io
from PIL import Image

from ytmusicapi import YTMusic
yt = YTMusic()  # no auth needed for public search

API_KEY = "30416f85ed6f65c3cdef6654a202e75f"
BASE = "https://ws.audioscrobbler.com/2.0/"
USER = "rage_floyd"

logging.basicConfig(filename=f"playtime_chart_{time.strftime('%Y_%m_%d_%H_%M_%S', time.gmtime(time.time()))}.log",
                    format='%(asctime)s %(levelname)s: %(message)s',
                    filemode='w')
log = logging.getLogger()
log.setLevel(logging.INFO)

def ytmusic_duration(artist: str, album: str, track: str) -> int | None:
    query = f"{artist} {album} {track}"
    results = yt.search(query, filter="songs", limit=10)
    if not results:
        return None

    for r in results:
        title = r.get("title", "").lower()
        artists = " ".join(a["name"] for a in r.get("artists", [])).lower()
        alb = (r.get("album") or {}).get("name", "").lower()

        if track.lower() in title and artist.lower() in artists:
            # Prefer an exact-ish album match, but don't require it
            if album.lower() in alb or alb in album.lower():
                return r.get("duration_seconds")
            # keep a fallback if nothing better appears
            fallback = r.get("duration_seconds")

    # nothing matched album, return best artist+title match if we saw one
    return locals().get("fallback")

def lastfm(method, params, retries=3):
    params.update({"method": method, "api_key": API_KEY, "user": USER, "format": "json"})
    for attempt in range(retries):
        r = requests.get(BASE, params=params, timeout=10)
        log.info(f"requesting {r.url}...")
        if r.status_code == 500:
            wait = 2 ** attempt
            log.info(f"Got 500, retrying in {wait}s (attempt {attempt + 1}/{retries})")
            time.sleep(wait)
            continue
        r.raise_for_status()
        data = r.json()
        if "error" in data:
            raise RuntimeError(f"{data['error']}: {data['message']}")
        time.sleep(0.2)
        return data
    raise RuntimeError("Last.fm API kept returning 500 after retries")

def get_recent_tracks(from_date, to_date):
    #from_date: Beginning timestamp of a range (UMA SEMANA ATRAS)
    #to_date: End timestamp of a range (AGORA)
    log.info(f"Getting recent tracks...")

    if from_date > to_date:
        raise Exception("from_date must be earlier than to_date")

    recent_tracks = []
    page = 1
    while True:
        data = lastfm("user.getRecentTracks", {"page":page, "limit":200, "from":int(from_date), "to":int(to_date)})
        for track in data["recenttracks"]["track"]:
            log.info(f"Appending {track["name"]} by {track["artist"]["#text"]} to recent_tracks")
            recent_tracks.append(track)
        page += 1
        if page > int(data["recenttracks"]["@attr"]["totalPages"]):
            break
    
    return recent_tracks

def add_album_to_cache(track_name, track_mbid, album_name, album_mbid, artist_name, cache):
    log.info(f"Adding {(track_name, album_name, artist_name)} to cache...")

    tmp_cache = {}

    try:
        # If a track's album in in the cache but the track cannot be found, there's a discrepancy
        # between the scrobble data and the album data (e.g. scrobbled as 'Baptise In Fire and Ice' but
        # album data has 'Baptised in Fire and Ice'). Throw exception so we get track data directly.

        for item in cache:
            # item[1] = album_name!
            if item[1] == album_name:
                raise Exception("Album already on cache. Trying track data...")

        log.info(f"Trying by album.getInfo...")
        if album_mbid != "":
            album_data = lastfm("album.getInfo", {"mbid":album_mbid})
            log.info(f"album_mbid found.")
        else:
            album_data = lastfm("album.getInfo", {"album":album_name, "artist":artist_name})
            log.info(f"album_mbid not found.")

        try:
            image_url = album_data["album"]["image"][-1]["#text"]
            log.info(f"Cover art URL found: {image_url}")
        except:
            log.info("Couldn't find cover art URL.")
            image_url = ""
        
        for track in album_data["album"]["tracks"]["track"]:
            try:
                duration = int(track["duration"]) * 1000 # gives in seconds, we use ms
            except:
                # if duration = None:
                duration = 0

            tmp_cache[(track["name"], album_name, artist_name)] = {"duration":duration, "image_url":image_url}
            log.info(f"Added {(track["name"], album_name, artist_name)} to tmp_cache with duration {duration} and cover art URL {image_url}.")
    
    except:
        log.info(f"album.getInfo failed! Trying track.getInfo...")
        try:
            if track_mbid != "":
                track_data = lastfm("track.getInfo", {"mbid":track_mbid})
                log.info(f"track_mbid found.")
            else:
                track_data = lastfm("track.getInfo", {"track":track_name, "artist":artist_name})
                log.info(f"track_mbid not found.")

            try:
                image_url = album_data["album"]["image"][-1]["#text"]
                log.info(f"Cover art URL found: {image_url}")
            except:
                log.info("Couldn't find cover art URL.")
                image_url = ""

            duration = int(track_data["track"]["duration"]) # gives in ms
            tmp_cache[(track_name, album_name, artist_name)] = {"duration":duration, "image_url":image_url}
            log.info(f"Added {(track_name, album_name, artist_name)} to tmp_cache with duration {duration} and cover art URL {image_url}.")

        except:
            duration = 0

    print(f"{tmp_cache = }")
    for item in tmp_cache.keys():
        track_name = item[0]
        album_name = item[1]
        artist_name = item[2]

        duration = tmp_cache[item]["duration"]
        image_url = tmp_cache[item]["image_url"]

        # if last fm doesnt provide duration, try ytmusic
        # maybe add spotify, bandcamp, deezer later
        if duration == 0:
            log.info(f"last fm data has no duration. Trying ytmusic...")
            duration = ytmusic_duration(artist_name, album_name, track_name)
            if duration == None:
                duration = 0
            else:
                duration *= 1000 # ytmusic gives in seconds, we use ms
            log.info(f"Duration from ytmusic: {duration}")

        cache[(track_name, album_name, artist_name)] = {"duration":duration, "image_url":image_url}
        log.info(f"Added {(track_name, album_name, artist_name)} to cache with duration {duration} and cover art URL {image_url}.")
    
    log.info("Cache updated successfully")
    return cache
    
def get_albums_by_playtime(from_date, to_date, cache={}):
    log.info(f"Getting albums by playtime list")

    recent_tracks = get_recent_tracks(from_date, to_date)
    albums = {}

    total_tracks = len(recent_tracks)
    track_counter = 0

    for track in recent_tracks:
        track_counter += 1

        track_name = track["name"]
        album_name = track["album"]["#text"]
        album_mbid = track["album"]["mbid"]
        artist_name = track["artist"]["#text"]
        track_mbid = track["mbid"]
        
        log.info(f"Current track: {track["name"]} (mbid={track_mbid}) from {album_name} (mbid={album_mbid}) by {artist_name}")
        log.info(f"Progress: {track_counter}/{total_tracks}")

        # IDEIA MELHOR: album.getInfo tem a track list com durações. Passar pela recent_tracks
        # fazendo um buffer antes com só um request por album.

        if (track_name, album_name, artist_name) not in cache:
            log.info(f"{(track_name, album_name, artist_name)} not in cache! Updating...")
            cache = add_album_to_cache(track_name, track_mbid, album_name, album_mbid, artist_name, cache)
        
        image_url = cache[(track_name, album_name, artist_name)]["image_url"]
        duration = cache[(track_name, album_name, artist_name)]["duration"]

        if (album_name, artist_name) not in albums.keys():
            albums[(album_name, artist_name)] ={
                "name":album_name,
                "artist":artist_name,
                "image_url":image_url,
                "playtime": duration,
                "playcount":1
                }
            log.info(f"{album_name},{artist_name} += {duration}. image_url={image_url}")

        else:
            albums[(album_name, artist_name)]["playtime"] += duration
            albums[(album_name, artist_name)]["playcount"] += 1
            log.info(f"{album_name},{artist_name} += {duration} ({duration // 60000}m {(duration // 1000) % 60}s)")
        
    # sorting by playtime...
    albums = dict(sorted(albums.items(), key=lambda kv: kv[1]["playtime"], reverse=True))
    return albums

def pretty_print_albums(albums):
    for album in albums.keys():
        print(f"Artist: {albums[album]["artist"]}")
        print(f"Album: {albums[album]["name"]}")
        print(f"Playtime: {albums[album]["playtime"] // 60000}m {(albums[album]["playtime"] // 1000) % 60}s")
        print(f"Playcount: {albums[album]["playcount"]}")
        print()
    
def create_chart(albums, n_columns, n_rows, size_x, output_path="chart.png"):
    cell = size_x // n_columns
    size_y = cell * n_rows

    canvas = Image.new("RGB", (size_x, size_y), (0, 0, 0))

    entries = list(albums.values()) if isinstance(albums, dict) else list(albums)

    for i in range(n_columns * n_rows):
        col = i % n_columns
        row = i // n_columns
        pos = (col * cell, row * cell)

        if i >= len(entries):
            break

        url = entries[i].get("image_url", "")
        img = fetch_cover(url, cell)
        canvas.paste(img, pos)

    canvas.save(output_path)
    return canvas


def fetch_cover(url, cell):
    log.info(f"Fetching image from {url}")
    if not url:
        return Image.new("RGB", (cell, cell), (0, 0, 0))

    try:
        r = requests.get(url, timeout=10)
        r.raise_for_status()
        img = Image.open(io.BytesIO(r.content)).convert("RGB")
    except Exception as e:
        log.info(f"failed {url}: {e}")
        return Image.new("RGB", (cell, cell), (0, 0, 0))

    w, h = img.size
    side = min(w, h)
    left = (w - side) // 2
    top = (h - side) // 2
    img = img.crop((left, top, left + side, top + side))
    return img.resize((cell, cell), Image.LANCZOS)

def main():
    to_date = time.time() #now
    from_date = to_date - 7*24*60*60 #last week
    
    albums = get_albums_by_playtime(from_date, to_date)
    # albums = dict([('The Key,Nocturnus', {'name': 'The Key', 'artist': 'Nocturnus', 'image_url': 'https://lastfm-img.freetls.fastly.net/i/u/300x300/478ca2c31d27190ec712c3286286e937.png', 'playtime': 5852000, 'playcount': 20}), ('Seven Chalices,Teitanblood', {'name': 'Seven Chalices', 'artist': 'Teitanblood', 'image_url': 'https://lastfm-img.freetls.fastly.net/i/u/300x300/7ac15f2e0fd2470fc782d978e0f4648e.png', 'playtime': 3531000, 'playcount': 11}), ('Hammerheart,Bathory', {'name': 'Hammerheart', 'artist': 'Bathory', 'image_url': 'https://lastfm-img.freetls.fastly.net/i/u/300x300/70d2b8b882a551ef3f3e0dad084155f7.png', 'playtime': 3294000, 'playcount': 7}), ('Anthems to the Welkin at Dusk,Emperor', {'name': 'Anthems to the Welkin at Dusk', 'artist': 'Emperor', 'image_url': 'https://lastfm-img.freetls.fastly.net/i/u/300x300/5b883b42dcc84150a7dd2d73ae72ffda.png', 'playtime': 3246000, 'playcount': 10}), ('Apocrypha,Fugitive Wizard', {'name': 'Apocrypha', 'artist': 'Fugitive Wizard', 'image_url': 'https://lastfm-img.freetls.fastly.net/i/u/300x300/9239d0433b6001600eb72cb84f7261e5.png', 'playtime': 2915000, 'playcount': 9}), ('Symphonies of Sickness,Carcass', {'name': 'Symphonies of Sickness', 'artist': 'Carcass', 'image_url': 'https://lastfm-img.freetls.fastly.net/i/u/300x300/dcd7322d48cf4ad1cae01e8361dbfe14.png', 'playtime': 2788000, 'playcount': 11}), ('Black Metal,Venom', {'name': 'Black Metal', 'artist': 'Venom', 'image_url': 'https://lastfm-img.freetls.fastly.net/i/u/300x300/7ef32299b27c7f599c9af706b16c155f.png', 'playtime': 2552000, 'playcount': 11}), ('Altars of Madness,Morbid Angel', {'name': 'Altars of Madness', 'artist': 'Morbid Angel', 'image_url': 'https://lastfm-img.freetls.fastly.net/i/u/300x300/6f8d367e2a9cfaf7dad8ff99a69e6a4f.png', 'playtime': 2525000, 'playcount': 10}), ('Covenant,Morbid Angel', {'name': 'Covenant', 'artist': 'Morbid Angel', 'image_url': 'https://lastfm-img.freetls.fastly.net/i/u/300x300/3c22f3390e1fa73ec9011bae785a82ff.png', 'playtime': 2425000, 'playcount': 10}), ('Phantasmagoria,The Mist', {'name': 'Phantasmagoria', 'artist': 'The Mist', 'image_url': 'https://lastfm-img.freetls.fastly.net/i/u/300x300/e5fca3fce7f1b95e210b34e2ad7f7930.png', 'playtime': 2377000, 'playcount': 10}), ('Blessed Are the Sick,Morbid Angel', {'name': 'Blessed Are the Sick', 'artist': 'Morbid Angel', 'image_url': 'https://lastfm-img.freetls.fastly.net/i/u/300x300/a2eb385662a7cd4279081d36548aec8a.png', 'playtime': 2281000, 'playcount': 14}), ('Hell Awaits,Slayer', {'name': 'Hell Awaits', 'artist': 'Slayer', 'image_url': 'https://lastfm-img.freetls.fastly.net/i/u/300x300/069f9356cea289ff77b302b83373056b.png', 'playtime': 2237000, 'playcount': 7}), ('Forgotten Legends,Drudkh', {'name': 'Forgotten Legends', 'artist': 'Drudkh', 'image_url': 'https://lastfm-img.freetls.fastly.net/i/u/300x300/d6947036fdae4e0ace69a47cd06582af.png', 'playtime': 2195000, 'playcount': 3}), ('Mortal Throne of Nazarene,Incantation', {'name': 'Mortal Throne of Nazarene', 'artist': 'Incantation', 'image_url': 'https://lastfm-img.freetls.fastly.net/i/u/300x300/9851eef2f1ad7add64a7c40e270b5423.png', 'playtime': 2156000, 'playcount': 8}), ('Ao Vivo em Rio Negrinho,Velho', {'name': 'Ao Vivo em Rio Negrinho', 'artist': 'Velho', 'image_url': '', 'playtime': 2132000, 'playcount': 11}), ('Tales From the Lost Pages,Sussurro', {'name': 'Tales From the Lost Pages', 'artist': 'Sussurro', 'image_url': 'https://lastfm-img.freetls.fastly.net/i/u/300x300/d2b955ebf44dba26e3e896cf9b444da2.png', 'playtime': 1984000, 'playcount': 8}), ('Ascensão do Anticristo,Amazarak', {'name': 'Ascensão do Anticristo', 'artist': 'Amazarak', 'image_url': 'https://lastfm-img.freetls.fastly.net/i/u/300x300/1c5c9813c11fe69be1b8456b7bff69de.png', 'playtime': 1853000, 'playcount': 8}), ('Back from Hell,Siegrid Ingrid', {'name': 'Back from Hell', 'artist': 'Siegrid Ingrid', 'image_url': '', 'playtime': 1794000, 'playcount': 10}), ('The Curse Of The Black Blood Moon,Feretral', {'name': 'The Curse Of The Black Blood Moon', 'artist': 'Feretral', 'image_url': '', 'playtime': 1726000, 'playcount': 10}), ('Hear Nothing See Nothing Say Nothing,Discharge', {'name': 'Hear Nothing See Nothing Say Nothing', 'artist': 'Discharge', 'image_url': 'https://lastfm-img.freetls.fastly.net/i/u/300x300/6bb18087b1e344c0b8c4457336c7b0e9.png', 'playtime': 1563000, 'playcount': 14}), ('Terminus Magus Chapter I,Fugitive Wizard', {'name': 'Terminus Magus Chapter I', 'artist': 'Fugitive Wizard', 'image_url': 'https://lastfm-img.freetls.fastly.net/i/u/300x300/5364d5d90417ba3acec4fff1b0bd7f36.png', 'playtime': 1308000, 'playcount': 3}), ('War, Pestilence and Sacrifice,Schizogoat', {'name': 'War, Pestilence and Sacrifice', 'artist': 'Schizogoat', 'image_url': 'https://lastfm-img.freetls.fastly.net/i/u/300x300/b93c3f323ae46f729c99a43c7a93f283.png', 'playtime': 1225000, 'playcount': 7}), ('Sangvis et Honor,The Black Spade', {'name': 'Sangvis et Honor', 'artist': 'The Black Spade', 'image_url': 'https://lastfm-img.freetls.fastly.net/i/u/300x300/9e1edea0d6055fe2b584e8f12fb3fadb.png', 'playtime': 1106000, 'playcount': 5}), ('Alice in Hell,Annihilator', {'name': 'Alice in Hell', 'artist': 'Annihilator', 'image_url': 'https://lastfm-img.freetls.fastly.net/i/u/300x300/c28ef13535cfc2a870486966586c20a2.png', 'playtime': 1071000, 'playcount': 5}), ('Focus,Cynic', {'name': 'Focus', 'artist': 'Cynic', 'image_url': 'https://lastfm-img.freetls.fastly.net/i/u/300x300/b1eb9296cb37489fb29dbcea677a5d7f.png', 'playtime': 1008000, 'playcount': 4}), ('Invincible War,Bywar', {'name': 'Invincible War', 'artist': 'Bywar', 'image_url': 'https://lastfm-img.freetls.fastly.net/i/u/300x300/df4ece5417e99e28cfaca1d37d07c85f.png', 'playtime': 990000, 'playcount': 5}), ('December Moon,Morbid', {'name': 'December Moon', 'artist': 'Morbid', 'image_url': '', 'playtime': 942000, 'playcount': 4}), ('...E do Fim Se Faz o Início...,The Black Spade', {'name': '...E do Fim Se Faz o Início...', 'artist': 'The Black Spade', 'image_url': 'https://lastfm-img.freetls.fastly.net/i/u/300x300/c15658cb9210696fb5fcc1816521e13c.png', 'playtime': 873000, 'playcount': 3}), ("Peace Sells...But Who's Buying (Deluxe Edition - Remastered),Megadeth", {'name': "Peace Sells...But Who's Buying (Deluxe Edition - Remastered)", 'artist': 'Megadeth', 'image_url': 'https://lastfm-img.freetls.fastly.net/i/u/300x300/c68c125f549369c0b2e829a84f41f208.png', 'playtime': 769000, 'playcount': 3}), ('From Enslavement To Obliteration (Full Dynamic Range Edition),Napalm Death', {'name': 'From Enslavement To Obliteration (Full Dynamic Range Edition)', 'artist': 'Napalm Death', 'image_url': 'https://lastfm-img.freetls.fastly.net/i/u/300x300/67ec2076d4860b84cf2f1def6bb0bcd5.png', 'playtime': 744000, 'playcount': 9}), ("Kill 'Em All,Metallica", {'name': "Kill 'Em All", 'artist': 'Metallica', 'image_url': 'https://lastfm-img.freetls.fastly.net/i/u/300x300/9849e2dc2f048cc92a87e29a3a3298db.png', 'playtime': 618000, 'playcount': 2}), ("Noise For Music's Sake,Napalm Death", {'name': "Noise For Music's Sake", 'artist': 'Napalm Death', 'image_url': 'https://lastfm-img.freetls.fastly.net/i/u/300x300/133a7437473245f58976ab8d70db01ff.png', 'playtime': 492000, 'playcount': 5}), ('Emperor / Wrath of the Tyrant,Emperor', {'name': 'Emperor / Wrath of the Tyrant', 'artist': 'Emperor', 'image_url': 'https://lastfm-img.freetls.fastly.net/i/u/300x300/24545512870b1b5c7f3bba403c9a93a0.png', 'playtime': 397000, 'playcount': 1}), ('From Enslavement to Obliteration,Napalm Death', {'name': 'From Enslavement to Obliteration', 'artist': 'Napalm Death', 'image_url': 'https://lastfm-img.freetls.fastly.net/i/u/300x300/273b8c98eadac5a6be9ab8ad40d08fed.png', 'playtime': 327000, 'playcount': 2}), ('Death,Teitanblood', {'name': 'Death', 'artist': 'Teitanblood', 'image_url': 'https://lastfm-img.freetls.fastly.net/i/u/300x300/c7b3bb00c5c44784c7de4d17d8001a39.png', 'playtime': 226000, 'playcount': 1}), ('Epitaph,Necrophagist', {'name': 'Epitaph', 'artist': 'Necrophagist', 'image_url': 'https://lastfm-img.freetls.fastly.net/i/u/300x300/2b34c41e536b99b013ba012ba3f81a03.png', 'playtime': 168000, 'playcount': 1}), ('Grind Madness At The BBC,Napalm Death', {'name': 'Grind Madness At The BBC', 'artist': 'Napalm Death', 'image_url': 'https://lastfm-img.freetls.fastly.net/i/u/300x300/847fcb12e0c4422cb5f9f8ef82860915.png', 'playtime': 166000, 'playcount': 3}), (',Bywar', {'name': '', 'artist': 'Bywar', 'image_url': '', 'playtime': 153000, 'playcount': 1}), ('The World Keeps Turning,Napalm Death', {'name': 'The World Keeps Turning', 'artist': 'Napalm Death', 'image_url': 'https://lastfm-img.freetls.fastly.net/i/u/300x300/98c34111d6126c2d8a3ca0bd1e4f0b9c.png', 'playtime': 147000, 'playcount': 1}), ('Black Metal (2009 Deluxe Expanded Edition),Venom', {'name': 'Black Metal (2009 Deluxe Expanded Edition)', 'artist': 'Venom', 'image_url': 'https://lastfm-img.freetls.fastly.net/i/u/300x300/82ed5fe12465f47fd0128fb635d931f6.png', 'playtime': 142000, 'playcount': 1}), ('Multinational HCorporations,Napalm Death', {'name': 'Multinational HCorporations', 'artist': 'Napalm Death', 'image_url': 'https://lastfm-img.freetls.fastly.net/i/u/300x300/166a5269a6991f1e072000fb7d43cea5.png', 'playtime': 83000, 'playcount': 1}), ('From Enslavement To Obliteration + Scum,Napalm Death', {'name': 'From Enslavement To Obliteration + Scum', 'artist': 'Napalm Death', 'image_url': 'https://lastfm-img.freetls.fastly.net/i/u/300x300/1448d56aeeb9bf7c756bff55a944c782.png', 'playtime': 66000, 'playcount': 1}), (',Napalm Death', {'name': '', 'artist': 'Napalm Death', 'image_url': '', 'playtime': 54000, 'playcount': 1}), (',cock', {'name': '', 'artist': 'cock', 'image_url': '', 'playtime': 0, 'playcount': 1})])
    print(albums)
    pretty_print_albums(albums)
    create_chart(albums, 6, 6, 1000)

if __name__=="__main__":
    main()