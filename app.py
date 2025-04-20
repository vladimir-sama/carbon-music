import os, sys, threading, locale
from PySide6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QComboBox, QLineEdit, QListWidget, QPushButton, QSlider, QScrollBar, QListWidgetItem
)
from PySide6.QtCore import Qt, QTimer, Slot
from PySide6.QtGui import QFont, QKeyEvent

from ytmusicapi import YTMusic
from ytmusicapi.models import Lyrics, TimedLyrics, LyricLine
from ytmusicapi.exceptions import YTMusicUserError
import mpv
import yt_dlp, json
from typing import Optional, List, TypedDict, Dict, Union, Any

class Track(TypedDict):
    title:str
    url:str

class MusicPlayer(QWidget):
    def __init__(self) -> None:
        super().__init__()

        self.setWindowTitle('Carbon Music Player')
        self.setFixedSize(500, 600)
        self.setStyleSheet("font-family: 'PT Sans Narrow';")
        locale.setlocale(locale.LC_NUMERIC, 'C')
        self.player : mpv.MPV = mpv.MPV(ytdl=True, input_default_bindings=True, input_vo_keyboard=True, video=False)
        self.player.loop_file = 'inf'
        locale.setlocale(locale.LC_NUMERIC, 'C')
        self.yt_music_api : YTMusic = YTMusic()

        self.track_url : Optional[str] = None
        self.is_paused : bool = False
        self.is_playing : bool = False
        self.track_length : float = 0.0
        self.is_user_dragging : bool = False

        self.playlist : Dict[str, str] = {}
        self.playlist_titles : List[str] = []
        self.selected_playlist : str = ''
        self.tracks : List[Track] = []
        self.lyrics : List[Union[Lyrics, TimedLyrics]] = []

        self.load_playlists()
        self.init_ui()

        self.seek_timer : QTimer = QTimer()
        self.seek_timer.timeout.connect(self.update_seek_slider)
        self.seek_timer.start(50)

    def load_playlists(self) -> None:
        with open('playlists_yt.json', 'r') as f:
            self.playlist.update({f'YT - {k}': v for k, v in json.load(f).items()})
        with open('playlists_local.json', 'r') as f:
            self.playlist.update({f'LOCAL - {k}': v for k, v in json.load(f).items()})
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

        control_layout : QHBoxLayout = QHBoxLayout()

        self.button_play : QPushButton = QPushButton('Play')
        self.button_play.clicked.connect(self.toggle_play)
        control_layout.addWidget(self.button_play)

        self.slider_volume : QSlider = QSlider(Qt.Horizontal)
        self.slider_volume.setRange(0, 100)
        self.slider_volume.setValue(100)
        self.slider_volume.valueChanged.connect(self.set_volume)
        control_layout.addWidget(self.slider_volume)

        self.slider_seek : QSlider = QSlider(Qt.Horizontal)
        self.slider_seek.setRange(0, 100)
        self.slider_seek.sliderPressed.connect(self.seek_start)
        self.slider_seek.sliderReleased.connect(self.seek_end)
        control_layout.addWidget(self.slider_seek)

        layout.addLayout(control_layout)

        self.label_track : QLabel = QLabel('(NA)')
        self.label_lyrics : QLabel = QLabel('(LYRICS)')
        self.label_track.setAlignment(Qt.AlignCenter)
        self.label_lyrics.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.label_track)
        layout.addWidget(self.label_lyrics)

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
        self.label_track.setText('(NA)')
        self.label_lyrics.setText('(LYRICS)')

        if self.track_url.startswith('https://music.youtube.com/watch?v='):
            video_id : str = self.track_url.split('=')[-1]
            try:
                details : dict = self.yt_music_api.get_song(video_id)
                if details:
                    self.label_track.setText(details['videoDetails']['title'])
                data : dict = self.yt_music_api.get_watch_playlist(video_id, limit=1)
                self.lyrics = self.yt_music_api.get_lyrics(data['lyrics'], True)
                if not self.lyrics.get('hasTimestamps'):
                    self.lyrics = []
                else:
                    self.label_lyrics.setText('...')
            except (KeyError, YTMusicUserError):
                self.lyrics = []
        else:
            self.label_track.setText(os.path.basename(self.track_url))

        if self.track_url:
            self.track_length = 0
            self.player.play(self.track_url)
            self.is_playing = True
            self.is_paused = False
            self.player.pause = False
            self.button_play.setText('Pause')

    def toggle_play(self) -> None:
        if self.is_playing:
            self.is_paused = not self.is_paused
            self.player.pause = self.is_paused
            self.button_play.setText('Play' if self.is_paused else 'Pause')
        elif self.track_url:
            self.play_track()

    def set_volume(self, value:int) -> None:
        self.player.volume = value

    def seek_start(self) -> None:
        self.is_user_dragging = True

    def seek_end(self) -> None:
        value : int = self.slider_seek.value()
        self.player.seek(value, reference='absolute')
        self.is_user_dragging = False

    def update_seek_slider(self) -> None:
        if not self.is_paused and not self.is_user_dragging:
            if self.track_length == 0 and self.player.duration:
                self.track_length = int(self.player.duration)
                self.slider_seek.setRange(0, self.track_length)
            if self.player.time_pos:
                current_time_ms : int = int(self.player.time_pos * 1000)
                current_time : int = int(self.player.time_pos)
                self.slider_seek.setValue(current_time)
                if self.lyrics:
                    for line in self.lyrics['lyrics']:
                        if line.start_time <= current_time_ms <= line.end_time:
                            self.label_lyrics.setText(line.text)
                            break
                    else:
                        self.label_lyrics.setText('...')


if __name__ == '__main__':
    file_dir : str = os.path.dirname(os.path.realpath(__file__))
    frozen_dir = os.path.dirname(sys.executable)
    executable_dir : str = os.path.dirname(os.path.realpath(__file__))
    if getattr(sys, 'frozen', False):
        executable_dir = os.path.dirname(sys.executable)
    os.chdir(executable_dir)
    app : QApplication = QApplication(sys.argv)
    player : MusicPlayer = MusicPlayer()
    player.show()
    sys.exit(app.exec())
