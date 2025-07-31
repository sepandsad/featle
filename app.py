from flask import Flask, render_template, request, redirect
import musicbrainzngs
import requests
import base64
import os

SPOTIFY_CLIENT_ID = "0495026a8ffe4e299f54ca5ae1e6fcba"
SPOTIFY_CLIENT_SECRET = "780f6fba13a24f928c8cb2ac3d7df4f7"

app = Flask(__name__)

musicbrainzngs.set_useragent("featle", "0.1", "sepand.sadeghi@gmail.com")

def get_spotify_token():
    auth = f"{SPOTIFY_CLIENT_ID}:{SPOTIFY_CLIENT_SECRET}"
    auth_bytes = auth.encode('utf-8')
    auth_b64 = base64.b64encode(auth_bytes).decode('utf-8')

    headers = {
        'Authorization': f'Basic {auth_b64}'
    }
    data = {
        'grant_type': 'client_credentials'
    }

    r = requests.post('https://accounts.spotify.com/api/token', headers=headers, data=data)
    return r.json().get('access_token')


def get_spotify_artist_id(name, token):
    url = f'https://api.spotify.com/v1/search?q={name}&type=artist&limit=1'
    headers = {'Authorization': f'Bearer {token}'}
    r = requests.get(url, headers=headers)
    items = r.json().get('artists', {}).get('items', [])
    return items[0]['id'] if items else None


def get_spotify_artist_albums(artist_id, token):
    url = f'https://api.spotify.com/v1/artists/{artist_id}/albums?include_groups=album,single&market=US&limit=50'
    headers = {'Authorization': f'Bearer {token}'}
    r = requests.get(url, headers=headers)

    seen = set()
    albums = []
    for item in r.json().get('items', []):
        name = item.get("name")
        if name not in seen:
            seen.add(name)
            albums.append({
                "id": item.get("id"),
                "name": name,
                "image": item.get("images", [{}])[0].get("url", "")
            })
    return albums



class FeatleGame:
    def __init__(self, start_artist, end_artist):
        self.start = start_artist
        self.end = end_artist
        self.current_artist = start_artist
        self.history = [start_artist]
        self.last_known_artists = [start_artist]
        self.pending_song = None

    def get_known_collab_songs(self):
        try:
            result = musicbrainzngs.browse_recordings(artist=self.current_artist, includes=["artist-credits"], limit=20)
            songs = []
            for rec in result.get("recording-list", []):
                if "artist-credit" in rec:
                    artists = [entry["artist"]["name"] for entry in rec["artist-credit"] if "artist" in entry]
                    if len(artists) > 1:
                        songs.append({
                            "title": rec["title"],
                            "artists": artists
                        })
            return songs
        except Exception as e:
            print(f"Error fetching collab songs: {e}")
            return []


    def get_song_artists(self, song_title):
        artist_hint = self.current_artist
        try:
            result = musicbrainzngs.search_recordings(recording=song_title, artist=artist_hint, limit=5)
            if not result["recording-list"]:
                return []

            for rec in result["recording-list"]:
                credits = rec.get("artist-credit", [])
                artists = [entry["artist"]["name"] for entry in credits if "artist" in entry]
                if len(artists) > 1:
                    return artists

# fallback to first result if no collaborators found
            if result["recording-list"]:
                credits = result["recording-list"][0].get("artist-credit", [])
                return [entry["artist"]["name"] for entry in credits if "artist" in entry]

            return []

        except Exception as e:
            print(f"Error fetching song: {e}")
            return []

    def play_turn(self, song_title, next_artist):
        collaborators = self.get_song_artists(song_title)
        if not collaborators or self.current_artist not in collaborators:
            return {"status": "error", "message": f"{self.current_artist} is not in '{song_title}'"}

        if next_artist not in collaborators or next_artist == self.current_artist:
            return {"status": "error", "message": f"{next_artist} is not a valid choice."}

        if self.end in collaborators:
            self.history.append(self.end)
            return {"status": "win", "history": self.history}

        self.current_artist = next_artist
        self.history.append(next_artist)
        self.last_known_artists = collaborators
        return {"status": "continue"}


# Global game instance (you could replace this with sessions per user in production)
game = None


@app.route('/')
def home():
    return render_template('index.html')


@app.route('/start', methods=['POST'])
def start():
    global game
    start = request.form['start']
    end = request.form['end']
    game = FeatleGame(start, end)
    return redirect('/play')


@app.route('/play')
def play():
    global game
    if game is None:
        return redirect('/')  # Redirect to home page or render a message

    token = get_spotify_token()
    artist_id = get_spotify_artist_id(game.current_artist, token)
    albums = get_spotify_artist_albums(artist_id, token) if artist_id else []

    return render_template('play.html',
                           current=game.current_artist,
                           history=game.history,
                           albums=albums)





@app.route('/album_tracks')
def album_tracks():
    album_id = request.args.get('album_id')
    token = get_spotify_token()
    headers = {"Authorization": f"Bearer {token}"}
    response = requests.get(f"https://api.spotify.com/v1/albums/{album_id}/tracks", headers=headers)

    if response.status_code != 200:
        return {"error": "Failed to fetch tracks"}

    data = response.json()
    tracks = []
    for t in data["items"]:
        track_name = t["name"]
        artists = ", ".join([a["name"] for a in t["artists"]])
        tracks.append(f"{track_name} – {artists}")

    return {"tracks": tracks}


@app.route('/submit_song', methods=['POST'])
def submit_song():
    global game
    song = request.form['song']
    collaborators = game.get_song_artists(song)

    token = get_spotify_token()
    artist_id = get_spotify_artist_id(game.current_artist, token)
    albums = get_spotify_artist_albums(artist_id, token) if artist_id else []

    if not collaborators:
        return render_template('play.html', current=game.current_artist, history=game.history,
                               error=f"No artists found for '{song}'", albums=albums)

    if game.current_artist not in collaborators:
        return render_template('play.html', current=game.current_artist, history=game.history,
                               error=f"{game.current_artist} is not part of this song.", albums=albums)

    options = [a for a in collaborators if a != game.current_artist]
    if not options:
        return render_template('play.html', current=game.current_artist, history=game.history,
                               error="No other collaborators found.", albums=albums)

    game.pending_song = song
    return render_template('choose_artist.html', current=game.current_artist, history=game.history,
                           song=song, options=options)



@app.route('/turn', methods=['POST'])
def turn():
    global game
    next_artist = request.form['next']
    result = game.play_turn(game.pending_song, next_artist)

    if result['status'] == 'win':
        return render_template('win.html', history=result['history'], end=game.end)
    elif result['status'] == 'continue':
        return redirect('/play')
    else:
        return render_template('play.html', current=game.current_artist, history=game.history,
                               error=result['message'])


if __name__ == '__main__':
    app.run(debug=True)
