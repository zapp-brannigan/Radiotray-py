import json
import subprocess
import sys
import platform
import threading
import time
import os
import requests
import re
from PIL import Image, ImageDraw
from PyQt5 import QtWidgets, QtGui, QtCore

# Paths to your bookmarks.json and config.json files
BOOKMARKS_FILE = "bookmarks.json"
CONFIG_FILE = "config.json"

# Global variables to keep track of the current process and station info
current_process = None
current_station_name = None
current_song_title = None
tray_icon = None
red_waveform_icon = None
green_waveform_icon = None
metadata_thread = None
stop_event = threading.Event()

# Global variable to hold the BookmarkEditor window instance
bookmark_editor_window = None

# Determine the appropriate command-line tool to use based on the operating system
if platform.system() == "Windows":
    player = "wmplayer.exe"
elif platform.system() == "Darwin":
    player = "afplay"
else:
    player = "mpv"

# Function to create waveform icons
def create_waveform_icon(color):
    """Generates a small waveform image and converts it to a QPixmap."""
    image = Image.new("RGBA", (32, 32), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)

    # Draw waveform
    points = [
        (4, 16), (8, 4), (12, 16), (16, 28), (20, 16),
        (24, 4), (28, 16), (32, 28)
    ]
    draw.line(points, fill=color, width=2)

    # Convert PIL image to QPixmap
    qimage = QtGui.QImage(
        image.tobytes(), image.width, image.height, QtGui.QImage.Format_RGBA8888
    )
    return QtGui.QPixmap.fromImage(qimage)

# Setup icons after the QApplication has been initialized
def setup_icons():
    """Initializes the red and green waveform icons."""
    global red_waveform_icon, green_waveform_icon
    red_waveform_icon = create_waveform_icon("red")
    green_waveform_icon = create_waveform_icon("green")

# Stop the currently playing station, if any
def stop_current_station():
    """Terminates the current subprocess and metadata thread."""
    global current_process, metadata_thread, stop_event
    if current_process:
        print("Stopping current process.")
        current_process.terminate()
        stop_event.set()
        if metadata_thread and metadata_thread.is_alive():
            metadata_thread.join(timeout=2)
        current_process = None
        metadata_thread = None
        stop_event.clear()

# Read bookmarks from JSON file
def read_bookmarks():
    """Loads bookmarks from the bookmarks.json file."""
    try:
        with open(BOOKMARKS_FILE, "r") as f:
            return json.load(f)
    except FileNotFoundError:
        print(f"Error: {BOOKMARKS_FILE} not found. Creating a new file.")
        default_bookmarks = [{"group": "Favourites", "stations": []}]
        with open(BOOKMARKS_FILE, "w") as f:
            json.dump(default_bookmarks, f, indent=4)
        return default_bookmarks

# Save bookmarks to JSON file
def save_bookmarks(bookmarks):
    """Saves the current bookmarks list to a JSON file."""
    with open(BOOKMARKS_FILE, "w") as f:
        json.dump(bookmarks, f, indent=4)

# Save the last played station URL and name to config.json
def save_last_station(url, name):
    """Saves the last played station to a config file."""
    config = {"last_station": url, "last_station_name": name}
    with open(CONFIG_FILE, "w") as f:
        json.dump(config, f)

# Load the last played station URL and name from config.json
def load_last_station():
    """Loads the last played station from a config file."""
    try:
        with open(CONFIG_FILE, "r") as f:
            config = json.load(f)
            return config.get("last_station"), config.get("last_station_name")
    except (FileNotFoundError, json.JSONDecodeError):
        return None, None

def fetch_metadata_from_api(url):
    """Fetches song title from a JSON API URL."""
    try:
        response = requests.get(url, timeout=5)
        response.raise_for_status() # Raise an error for bad status codes
        data = response.json()

        # This is a generic way to find the title, as API structures can vary.
        if 'current' in data and 'item' in data['current'] and 'title' in data['current']['item']:
            return data['current']['item']['title']

    except (requests.exceptions.RequestException, json.JSONDecodeError, KeyError) as e:
        print(f"Failed to fetch metadata from API: {e}")
        return None

def parse_metadata(metadata_string):
    """Parses a raw metadata string to find a StreamTitle or StreamUrl."""
    stream_title = None
    stream_url = None

    # First, try to find StreamUrl
    url_match = re.search(r"StreamUrl='([^']*)'", metadata_string)
    if url_match:
        stream_url = url_match.group(1)
        print(f"Found StreamUrl in metadata: {stream_url}")

    # Then, try to find StreamTitle
    title_match = re.search(r"StreamTitle='([^']*)'", metadata_string)
    if title_match:
        stream_title = title_match.group(1)
        # Filter out empty or placeholder titles
        if stream_title.strip() in ['', '-', ';']:
            stream_title = None
        else:
            print(f"Found StreamTitle in metadata: {stream_title}")

    return stream_title, stream_url

def monitor_metadata(url):
    """Monitors the stream for metadata and updates the song title."""
    global current_song_title
    print(f"Metadata thread started for URL: {url}")

    stream_url = None

    # Try the Icy-MetaData protocol first
    try:
        headers = {'Icy-MetaData': '1'}
        response = requests.get(url, headers=headers, stream=True, timeout=10)

        metaint_str = response.headers.get('icy-metaint', '0')
        metaint = int(metaint_str)

        if metaint > 0:
            while not stop_event.is_set():
                try:
                    response.raw.read(metaint)
                    metadata_length_byte = response.raw.read(1)
                    if not metadata_length_byte:
                        break # End of stream
                    metadata_length = ord(metadata_length_byte) * 16

                    if metadata_length > 0:
                        metadata = response.raw.read(metadata_length).decode('utf-8', errors='ignore')
                        print(f"Raw metadata: {metadata}")

                        new_song_title, new_stream_url = parse_metadata(metadata)

                        if new_stream_url:
                            stream_url = new_stream_url

                        if new_song_title and new_song_title != current_song_title:
                            current_song_title = new_song_title
                            tray_icon.update_menu.emit()

                except (requests.exceptions.ReadTimeout, requests.exceptions.ChunkedEncodingError, requests.exceptions.ConnectionError, TypeError) as e:
                    print(f"Stream read error, retrying: {e}")
                    time.sleep(5)
                    try:
                        response = requests.get(url, headers=headers, stream=True, timeout=10)
                    except Exception as e:
                        print(f"Failed to reconnect: {e}")
                        break
        else:
            print("No metadata interval found, attempting to get metadata from a different source.")

    except Exception as e:
        print(f"Error in metadata thread: {e}")

    # --- Polling loop for API-based metadata ---
    if stream_url:
        print(f"Polling API for metadata from: {stream_url}")
        while not stop_event.is_set():
            new_song_title = fetch_metadata_from_api(stream_url)
            if new_song_title and new_song_title != current_song_title:
                print(f"New song title detected (via API): {new_song_title}")
                current_song_title = new_song_title
                tray_icon.update_menu.emit()
            # Poll every 10 seconds to avoid excessive requests
            time.sleep(10)

    print("Metadata thread stopped.")

# Launch the appropriate command-line tool to play the selected station URL
def play_station(url, name):
    """Plays the selected station using the configured player."""
    global current_process, current_station_name, current_song_title, metadata_thread, player
    stop_current_station()
    current_song_title = None

    try:
        print(f"Playing station: {name} ({url})")

        # Pre-flight check to see if the stream URL is accessible
        try:
            response = requests.get(url, stream=True, timeout=5)
            if response.status_code != 200:
                print(f"Error: Could not connect to stream for '{name}'. Status code: {response.status_code}")
                tray_icon.update_menu.emit()
                return
        except requests.exceptions.RequestException as e:
            print(f"Error: Could not connect to stream for '{name}'. {e}")
            tray_icon.update_menu.emit()
            return

        # Launch player
        cmd = [player, url]
        if platform.system() != "Windows":
             cmd.append("--no-terminal")

        current_process = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

        # Add a short delay to allow the process to start or fail
        time.sleep(2)

        # Check if the process has already terminated (i.e., failed to play)
        if current_process.poll() is not None:
            print(f"Error: Player process for '{name}' terminated unexpectedly. The stream might be down.")
            current_process = None  # Ensure it's None so the icon stays red
            tray_icon.update_menu.emit()
            return  # Stop further execution

        # If the process is still running, we can assume it's playing.
        print("Playback started successfully.")

        # Start the new, non-IPC metadata monitoring thread
        stop_event.clear()
        metadata_thread = threading.Thread(target=monitor_metadata, args=(url,), daemon=True)
        metadata_thread.start()

        save_last_station(url, name)
        current_station_name = name
        tray_icon.update_menu.emit()

    except FileNotFoundError:
        print(f"Error: {player} is not installed. Please install {player} for this feature.")
        current_process = None
        tray_icon.update_menu.emit()
    except Exception as e:
        print(f"An unexpected error occurred while trying to play: {e}")
        current_process = None
        tray_icon.update_menu.emit()

# Toggle playback on/off
def toggle_playback():
    """Toggles playback of the last played station."""
    global current_process, current_station_name
    if current_process:
        print("Playback stopped via menu action.")
        stop_current_station()
        current_station_name = None
    else:
        print("Toggling playback on.")
        last_station, last_station_name = load_last_station()
        if last_station:
            play_station(last_station, last_station_name)
        else:
            print("No station was previously played.")
    tray_icon.update_menu.emit()

# Exit the program and clean up
def exit_program():
    """Stops the station and closes the application."""
    print("Exiting program.")
    stop_current_station()
    QtWidgets.QApplication.instance().quit()
    sys.exit()

# Main Tray Icon Class
class TrayIcon(QtWidgets.QSystemTrayIcon):
    update_menu = QtCore.pyqtSignal()

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Connect the signal to the menu update method
        self.update_menu.connect(self.build_and_set_menu)
        self.song_title_action = None
        self.scrolling_timer = QtCore.QTimer(self)
        self.scrolling_timer.timeout.connect(self.update_scrolling_text)
        self.scroll_offset = 0
        self.max_display_len = 40
        self.full_song_text = ""
        self.setToolTip("Radio Tray")
        self.build_and_set_menu()

    def update_scrolling_text(self):
        """Updates the song title action text to create a scrolling effect."""
        if not self.full_song_text:
            self.scrolling_timer.stop()
            return

        display_text = "Now Playing: " + self.full_song_text

        if len(display_text) > self.max_display_len:
            end_index = self.scroll_offset + self.max_display_len

            # Wrap around when we reach the end of the string
            if end_index > len(display_text):
                truncated_text = display_text[self.scroll_offset:] + "   " + display_text[:self.max_display_len - len(display_text[self.scroll_offset:]) - 3]
            else:
                truncated_text = display_text[self.scroll_offset:end_index]

            self.song_title_action.setText(truncated_text)
            self.scroll_offset = (self.scroll_offset + 1) % (len(display_text) + 3) # Add space for a small pause
        else:
            self.song_title_action.setText(display_text)
            self.scrolling_timer.stop()

    def start_scrolling(self):
        """Starts the scrolling timer if the song title is too long."""
        if len("Now Playing: " + self.full_song_text) > self.max_display_len:
            self.scrolling_timer.start(200) # milliseconds
        else:
            self.scrolling_timer.stop()
            if self.song_title_action:
                self.song_title_action.setText("Now Playing: " + self.full_song_text)

    def stop_scrolling(self):
        """Stops the scrolling timer."""
        self.scrolling_timer.stop()

    def build_and_set_menu(self):
        """Builds and sets the tray icon's context menu."""
        global current_station_name, current_song_title, current_process
        menu = QtWidgets.QMenu()
        menu.aboutToShow.connect(self.start_scrolling)
        menu.aboutToHide.connect(self.stop_scrolling)

        # Contextual Playback/Stop action
        if current_process:
            toggle_action = QtWidgets.QAction("Stop Playback", menu)
            self.setIcon(QtGui.QIcon(green_waveform_icon))
        else:
            # Display the last played station name if available
            last_url, last_name = load_last_station()
            last_station_display = last_name if last_name else "Last Station"
            toggle_action = QtWidgets.QAction(f"Play {last_station_display}", menu)
            self.setIcon(QtGui.QIcon(red_waveform_icon))

        toggle_action.triggered.connect(toggle_playback)
        menu.addAction(toggle_action)

        # Current station action (disabled)
        current_station_action = QtWidgets.QAction(
            " " * 4 + (current_station_name if current_station_name else "No Station Playing"), menu
        )
        current_station_action.setEnabled(False)
        menu.addAction(current_station_action)

        # Only add the song title action if there is a song title
        self.full_song_text = ""
        if current_song_title:
            self.full_song_text = current_song_title
            self.song_title_action = QtWidgets.QAction(
                " " * 4 + self.full_song_text, menu
            )
            self.song_title_action.setEnabled(False)
            menu.addAction(self.song_title_action)
        else:
            self.song_title_action = None


        # Station bookmarks
        bookmarks = read_bookmarks()
        for group in bookmarks:
            group_menu = menu.addMenu(group["group"])
            for station in group["stations"]:
                play_action = QtWidgets.QAction(station["name"], group_menu)
                play_action.triggered.connect(
                    lambda checked, url=station["url"], name=station["name"]: play_station(url, name)
                )
                group_menu.addAction(play_action)

        menu.addSeparator()

        # Bookmark Editor action
        editor_action = QtWidgets.QAction("Bookmark Editor", menu)
        editor_action.triggered.connect(open_bookmark_editor)
        menu.addAction(editor_action)

        menu.addSeparator()

        # Exit action
        exit_action = QtWidgets.QAction("Exit", menu)
        exit_action.triggered.connect(exit_program)
        menu.addAction(exit_action)

        self.setContextMenu(menu)

# Open the bookmark editor GUI
def open_bookmark_editor():
    """Creates and displays the bookmark editor window."""
    global bookmark_editor_window
    if bookmark_editor_window is None:
        bookmark_editor_window = BookmarkEditor()
    bookmark_editor_window.show()

# GUI for editing bookmarks
class BookmarkEditor(QtWidgets.QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Bookmark Editor")
        self.bookmarks = read_bookmarks()
        self.current_category = None
        self.current_station = None
        self.undo_stack = []
        self.redo_stack = []
        self.changes_made = False

        # Categories Listbox
        self.category_listbox = QtWidgets.QListWidget()
        self.category_listbox.itemClicked.connect(self.on_category_select)
        self.category_listbox.itemDoubleClicked.connect(self.edit_category)  # Double-click to edit category
        self.category_listbox.setDragDropMode(QtWidgets.QAbstractItemView.InternalMove)
        self.category_listbox.model().rowsMoved.connect(self.on_category_moved)

        # Stations Listbox
        self.station_listbox = QtWidgets.QListWidget()
        self.station_listbox.itemClicked.connect(self.on_station_select)
        self.station_listbox.itemDoubleClicked.connect(self.edit_station)  # Double-click to edit station
        self.station_listbox.setDragDropMode(QtWidgets.QAbstractItemView.InternalMove)
        self.station_listbox.model().rowsMoved.connect(self.on_station_moved)

        # Buttons
        self.add_category_button = QtWidgets.QPushButton("Add Category")
        self.add_category_button.clicked.connect(self.add_category)
        self.add_station_button = QtWidgets.QPushButton("Add Station")
        self.add_station_button.clicked.connect(self.add_station)
        self.remove_button = QtWidgets.QPushButton("Remove")
        self.remove_button.clicked.connect(self.remove)
        self.move_up_button = QtWidgets.QPushButton("Move Up")
        self.move_up_button.clicked.connect(self.move_up)
        self.move_down_button = QtWidgets.QPushButton("Move Down")
        self.move_down_button.clicked.connect(self.move_down)
        self.save_button = QtWidgets.QPushButton("Save")
        self.save_button.clicked.connect(self.save_changes)
        self.undo_button = QtWidgets.QPushButton("Undo")
        self.undo_button.clicked.connect(self.undo)
        self.redo_button = QtWidgets.QPushButton("Redo")
        self.redo_button.clicked.connect(self.redo)

        # Layout
        main_layout = QtWidgets.QVBoxLayout()

        # Horizontal layout for categories and stations
        hbox_layout = QtWidgets.QHBoxLayout()
        hbox_layout.addWidget(self.category_listbox)
        hbox_layout.addWidget(self.station_listbox)

        # Horizontal layout for buttons
        button_layout = QtWidgets.QHBoxLayout()
        button_layout.addWidget(self.add_category_button)
        button_layout.addWidget(self.add_station_button)
        button_layout.addWidget(self.remove_button)
        button_layout.addWidget(self.move_up_button)
        button_layout.addWidget(self.move_down_button)
        button_layout.addWidget(self.save_button)
        button_layout.addWidget(self.undo_button)
        button_layout.addWidget(self.redo_button)

        main_layout.addLayout(hbox_layout)
        main_layout.addLayout(button_layout)
        self.setLayout(main_layout)

        self.update_categories()

    def update_categories(self):
        """Refreshes the category listbox."""
        self.category_listbox.clear()
        for group in self.bookmarks:
            self.category_listbox.addItem(group["group"])
        self.update_stations()

    def update_stations(self):
        """Refreshes the station listbox based on the selected category."""
        self.station_listbox.clear()
        if self.current_category:
            for station in self.current_category["stations"]:
                self.station_listbox.addItem(station["name"])

    def on_category_select(self, item):
        """Handles category selection."""
        category_index = self.category_listbox.row(item)
        self.current_category = self.bookmarks[category_index]
        self.current_station = None
        self.update_stations()

    def on_station_select(self, item):
        """Handles station selection."""
        station_index = self.station_listbox.row(item)
        self.current_station = self.current_category["stations"][station_index]

    def add_category(self):
        """Adds a new category."""
        name, ok = QtWidgets.QInputDialog.getText(self, "Input", "Enter category name:")
        if ok and name:
            self.undo_stack.append((self.bookmarks, "add_category", name))
            self.redo_stack.clear()
            self.bookmarks.append({"group": name, "stations": []})
            self.update_categories()
            self.changes_made = True

    def add_station(self):
        """Adds a new station to the current category."""
        if self.current_category:
            name, ok = QtWidgets.QInputDialog.getText(self, "Input", "Enter station name:")
            if ok and name:
                url, ok = QtWidgets.QInputDialog.getText(self, "Input", "Enter station URL:")
                if ok and url:
                    self.undo_stack.append((self.current_category["stations"], "add_station", {"name": name, "url": url}))
                    self.redo_stack.clear()
                    self.current_category["stations"].append({"name": name, "url": url})
                    self.update_stations()
                    self.changes_made = True

    def remove(self):
        """Removes the selected category or station."""
        if self.current_station:
            self.remove_station()
        elif self.current_category:
            self.remove_category()

    def remove_category(self):
        """Removes the selected category."""
        if self.current_category:
            name = self.current_category["group"]
            self.undo_stack.append((self.bookmarks, "remove_category", name))
            self.redo_stack.clear()
            self.bookmarks.remove(self.current_category)
            self.current_category = None
            self.update_categories()
            self.changes_made = True

    def remove_station(self):
        """Removes the selected station."""
        station_index = self.station_listbox.currentRow()
        if station_index != -1:
            station = self.current_category["stations"].pop(station_index)
            self.undo_stack.append((self.current_category["stations"], "remove_station", station))
            self.redo_stack.clear()
            self.update_stations()
            self.changes_made = True

    def move_up(self):
        """Moves the selected item up."""
        if self.current_station:
            self.move_station(-1)
        elif self.current_category:
            self.move_category(-1)

    def move_down(self):
        """Moves the selected item down."""
        if self.current_station:
            self.move_station(1)
        elif self.current_category:
            self.move_category(1)

    def move_category(self, direction):
        """Moves a category within the list."""
        if self.current_category:
            index = self.bookmarks.index(self.current_category)
            new_index = index + direction
            if 0 <= new_index < len(self.bookmarks):
                self.bookmarks.insert(new_index, self.bookmarks.pop(index))
                self.update_categories()
                self.category_listbox.setCurrentRow(new_index)
                self.on_category_select(self.category_listbox.currentItem())
                self.changes_made = True

    def move_station(self, direction):
        """Moves a station within the current category."""
        if self.current_station:
            stations = self.current_category["stations"]
            index = stations.index(self.current_station)
            new_index = index + direction
            if 0 <= new_index < len(stations):
                stations.insert(new_index, stations.pop(index))
                self.update_stations()
                self.station_listbox.setCurrentRow(new_index)
                self.on_station_select(self.station_listbox.currentItem())
                self.changes_made = True

    def edit_category(self, item):
        """Edits the name of a category."""
        index = self.category_listbox.row(item)
        current_name = self.bookmarks[index]["group"]
        new_name, ok = QtWidgets.QInputDialog.getText(self, "Edit Category", "Edit category name:", text=current_name)
        if ok and new_name:
            self.bookmarks[index]["group"] = new_name
            self.update_categories()
            self.changes_made = True

    def edit_station(self, item):
        """Edits the name and URL of a station."""
        station_index = self.station_listbox.currentRow()
        current_station = self.current_category["stations"][station_index]

        current_name = current_station["name"]
        current_url = current_station["url"]

        new_values = self.get_combined_input("Edit station details:", current_name, current_url)

        if new_values:
            new_name, new_url = new_values
            current_station["name"] = new_name
            current_station["url"] = new_url
            self.update_stations()
            self.changes_made = True

    def get_combined_input(self, prompt, name_default, url_default):
        """A helper method for getting both name and URL in one dialog."""
        dialog = QtWidgets.QDialog(self)
        dialog.setWindowTitle(prompt)
        layout = QtWidgets.QVBoxLayout()

        name_label = QtWidgets.QLabel("Station Name:")
        name_entry = QtWidgets.QLineEdit(name_default)
        url_label = QtWidgets.QLabel("Station URL:")
        url_entry = QtWidgets.QLineEdit(url_default)

        ok_button = QtWidgets.QPushButton("OK")
        cancel_button = QtWidgets.QPushButton("Cancel")

        layout.addWidget(name_label)
        layout.addWidget(name_entry)
        layout.addWidget(url_label)
        layout.addWidget(url_entry)
        layout.addWidget(ok_button)
        layout.addWidget(cancel_button)

        dialog.setLayout(layout)

        result = []

        def on_ok():
            result.append(name_entry.text())
            result.append(url_entry.text())
            dialog.accept()

        def on_cancel():
            dialog.reject()

        ok_button.clicked.connect(on_ok)
        cancel_button.clicked.connect(on_cancel)

        if dialog.exec_() == QtWidgets.QDialog.Accepted:
            return result
        else:
            return None

    def save_changes(self):
        """Saves all changes and updates the main tray menu."""
        print("Saving bookmarks.")
        save_bookmarks(self.bookmarks)
        tray_icon.build_and_set_menu()
        self.changes_made = False

    def undo(self):
        """Reverts the last change."""
        if self.undo_stack:
            print("Undoing last change.")
            action = self.undo_stack.pop()
            data, action_type, details = action
            if action_type == "add_category":
                data.remove({"group": details, "stations": []})
            elif action_type == "remove_category":
                data.append({"group": details, "stations": []})
            elif action_type == "add_station":
                data.remove(details)
            elif action_type == "remove_station":
                data.remove(details)
            self.redo_stack.append(action)
            self.update_categories()
            self.changes_made = True

    def redo(self):
        """Reapplies the last undone change."""
        if self.redo_stack:
            print("Redoing last undone change.")
            action = self.redo_stack.pop()
            data, action_type, details = action
            if action_type == "add_category":
                data.append({"group": details, "stations": []})
            elif action_type == "remove_category":
                data.remove({"group": details, "stations": []})
            elif action_type == "add_station":
                data.append(details)
            elif action_type == "remove_station":
                data.remove(details)
            self.undo_stack.append(action)
            self.update_categories()
            self.changes_made = True

    def closeEvent(self, event):
        """Asks the user to save changes before closing."""
        if self.changes_made:
            reply = QtWidgets.QMessageBox.question(self, "Save Changes", "Do you want to save the changes?",
                                                  QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No | QtWidgets.QMessageBox.Cancel)
            if reply == QtWidgets.QMessageBox.Yes:
                self.save_changes()
                event.accept()
            elif reply == QtWidgets.QMessageBox.No:
                event.accept()
            else:
                event.ignore()
        else:
            event.accept()

    def on_category_moved(self, sourceParent, sourceStart, sourceEnd, destinationParent, destinationRow):
        """Handles moving categories via drag and drop."""
        moved_category = self.bookmarks.pop(sourceStart)
        self.bookmarks.insert(destinationRow, moved_category)
        self.changes_made = True

    def on_station_moved(self, sourceParent, sourceStart, sourceEnd, destinationParent, destinationRow):
        """Handles moving stations via drag and drop."""
        moved_station = self.current_category["stations"].pop(sourceStart)
        self.current_category["stations"].insert(destinationRow, moved_station)
        self.changes_made = True

# Main application entry point
def main():
    """Initializes and runs the application."""
    global tray_icon
    app = QtWidgets.QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)

    setup_icons()

    tray_icon = TrayIcon(QtGui.QIcon(red_waveform_icon))
    tray_icon.setVisible(True)

    sys.exit(app.exec_())

if __name__ == "__main__":
    main()
