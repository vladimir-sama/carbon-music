import os, sys, threading, locale, configparser
from PySide6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QComboBox, QLineEdit, QListWidget, QPushButton, QSlider, QScrollBar, QListWidgetItem
)
from PySide6.QtCore import Qt, QTimer, Slot
from PySide6.QtGui import QFont, QKeyEvent

from ytmusicapi import YTMusic
from ytmusicapi.models import Lyrics, TimedLyrics, LyricLine
from ytmusicapi.exceptions import YTMusicUserError
import yt_dlp, json, shutil, subprocess
from typing import Optional, List, TypedDict, Dict, Union, Any

file_dir : str = os.path.dirname(os.path.realpath(__file__))
frozen_dir = os.path.dirname(sys.executable)
executable_dir : str = os.path.dirname(os.path.realpath(__file__))
if getattr(sys, 'frozen', False):
    executable_dir = os.path.dirname(sys.executable)


class Track(TypedDict):
    title:str
    url:str

class MusicPlayer(QWidget):
    def __init__(self) -> None:
        super().__init__()
        
        self.config: configparser.ConfigParser = configparser.ConfigParser()
        self.config.read(os.path.join(executable_dir, 'app.ini'))
        

        self.setWindowTitle('Carbon Music Player')
        self.setFixedSize(500, 600)
        theme_user : str = self.config.get('user', 'theme', fallback='default')
        theme_file : str = self.config.get('themes', theme_user, fallback='none.qss')
        with open(os.path.join(executable_dir, theme_file), 'r') as file:
            self.setStyleSheet(file.read())


        self.yt_music_api : YTMusic = YTMusic()
        self.player : Optional[subprocess.Popen] = None

        self.track_url : Optional[str] = None

        self.playlist : Dict[str, str] = {}
        self.playlist_titles : List[str] = []
        self.selected_playlist : str = ''
        self.tracks : List[Track] = []

        self.load_playlists()
        self.init_ui()

    def load_playlists(self) -> None:
        with open(os.path.join(executable_dir, 'playlists_yt.json'), 'r') as file:
            self.playlist.update({f'YT - {k}': v for k, v in json.load(file).items()})
        with open(os.path.join(executable_dir, 'playlists_local.json'), 'r') as file:
            self.playlist.update({f'LOCAL - {k}': v for k, v in json.load(file).items()})
        self.playlist['SEARCH YT'] = 'SEARCH'
        self.playlist_titles = list(self.playlist.keys())

    def init_ui(self) -> None:
        layout : QVBoxLayout = QVBoxLayout()

        self.combo_playlist : QComboBox = QComboBox()
        self.combo_playlist.addItems(self.playlist_titles)
        self.combo_playlist.currentIndexChanged.connect(self.load_selected_playlist)
        layout.addWidget(self.combo_playlist)

        self.entry_filter : QLineEdit = QLineEdit()
        self.entry_filter.setPlaceholderText('Search or filter tracks...')
        self.entry_filter.textChanged.connect(self.filter_tracks)
        self.entry_filter.returnPressed.connect(self.search_yt)
        layout.addWidget(self.entry_filter)

        self.list_tracks : QListWidget = QListWidget()
        self.list_tracks.itemDoubleClicked.connect(self.select_track)
        layout.addWidget(self.list_tracks)

        self.label_track : QLabel = QLabel('(NA)')
        self.label_track.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.label_track)

        self.setLayout(layout)
        self.combo_playlist.setCurrentIndex(-1)

    @Slot()
    def load_selected_playlist(self) -> None:
        index = self.combo_playlist.currentIndex()
        self.selected_playlist = self.playlist_titles[index]
        playlist_url = self.playlist[self.selected_playlist]
        self.load_playlist(playlist_url)

    def load_playlist(self, playlist_url:str) -> None:
        if not playlist_url:
            return
        if playlist_url == 'SEARCH':
            self.tracks = []
            self.update_track_list()
        elif os.path.isdir(playlist_url):
            self.tracks = [{'title': entry, 'url': os.path.join(playlist_url, entry)} for entry in sorted(os.listdir(playlist_url))]
            self.update_track_list()
        else:
            ydl_opts : dict = {'extract_flat': True, 'skip_download': True}
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info : dict = ydl.extract_info(playlist_url, download=False)
                self.tracks = [{'title': entry['title'], 'url': entry['url']} for entry in info['entries']]
                self.update_track_list()

    def update_track_list(self) -> None:
        self.list_tracks.clear()
        for idx, track in enumerate(self.tracks):
            self.list_tracks.addItem(f'{idx + 1}. {track['title']}')

    def filter_tracks(self) -> None:
        if self.selected_playlist == 'SEARCH YT':
            return
        keyword : str = self.entry_filter.text().lower()
        filtered_tracks : List[Track] = [{'title': str(idx + 1) + '. ' + track['title'], 'url': track['url']} for idx, track in enumerate(self.tracks) if keyword in track['title'].lower()]
        self.list_tracks.clear()
        for track in filtered_tracks:
            self.list_tracks.addItem(track['title'])

    def search_yt(self) -> None:
        if self.selected_playlist != 'SEARCH YT':
            return
        term : str = self.entry_filter.text().lower()
        results : List[dict] = self.yt_music_api.search(term, filter='songs')
        self.tracks = [{'title': item['title'], 'url': f'https://music.youtube.com/watch?v={item['videoId']}'} for item in results]
        self.update_track_list()

    def select_track(self) -> None:
        current_item : Optional[QListWidgetItem] = self.list_tracks.currentItem()
        if not current_item:
            return
        index : int = int(current_item.text().split('.')[0]) - 1
        self.track_url = self.tracks[index]['url']
        self.play_track()

    def play_track(self) -> None:
        if self.player:
            self.player.terminate()
        self.label_track.setText('(NA)')

        if self.track_url.startswith('https://music.youtube.com/watch?v='):
            video_id : str = self.track_url.split('=')[-1]
            try:
                details : dict = self.yt_music_api.get_song(video_id)
                if details:
                    self.label_track.setText(details['videoDetails']['title'])
            except (KeyError, YTMusicUserError):
                pass
        else:
            self.label_track.setText(os.path.basename(self.track_url))

        if self.track_url:
            self.player = subprocess.Popen(
                [
                    shutil.which('mpv'),
                    '--ytdl=yes',
                    # '--ytdl-raw-options=cookies-from-browser=firefox',
                    '--osc=yes',
                    '--force-window=yes',
                    '--loop=inf',
                    self.track_url
                ]
            )

    def closeEvent(self, event):
        if self.player:
            self.player.terminate()
        return super().closeEvent(event)

if __name__ == '__main__':
    os.chdir(executable_dir)
    app : QApplication = QApplication(sys.argv)
    player : MusicPlayer = MusicPlayer()
    player.show()
    sys.exit(app.exec())
