import json
import subprocess
import sys
import platform
from PIL import Image, ImageDraw
from PyQt5 import QtWidgets, QtGui, QtCore

# Paths to your bookmarks.json and config.json files
BOOKMARKS_FILE = "bookmarks.json"
CONFIG_FILE = "config.json"

# Global variables to keep track of the current process and station info
current_process = None
current_station_name = None
tray_icon = None
red_waveform_icon = None
green_waveform_icon = None

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
    global red_waveform_icon, green_waveform_icon
    red_waveform_icon = create_waveform_icon("red")
    green_waveform_icon = create_waveform_icon("green")

# Stop the currently playing station, if any
def stop_current_station():
    global current_process
    if current_process:
        current_process.terminate()
        current_process = None

# Read bookmarks from JSON file
def read_bookmarks():
    try:
        with open(BOOKMARKS_FILE, "r") as f:
            return json.load(f)
    except FileNotFoundError:
        print(f"Error: {BOOKMARKS_FILE} not found.")
        return []

# Save bookmarks to JSON file
def save_bookmarks(bookmarks):
    with open(BOOKMARKS_FILE, "w") as f:
        json.dump(bookmarks, f, indent=4)

# Save the last played station URL and name to config.json
def save_last_station(url, name):
    config = {"last_station": url, "last_station_name": name}
    with open(CONFIG_FILE, "w") as f:
        json.dump(config, f)

# Load the last played station URL and name from config.json
def load_last_station():
    try:
        with open(CONFIG_FILE, "r") as f:
            config = json.load(f)
            return config.get("last_station"), config.get("last_station_name")
    except (FileNotFoundError, json.JSONDecodeError):
        return None, None

# Find URL by station name from bookmarks
def find_station_url(station_name):
    bookmarks = read_bookmarks()
    for group in bookmarks:
        for station in group["stations"]:
            if station["name"] == station_name:
                return station["url"]
    return None

# Launch the appropriate command-line tool to play the selected station URL
def play_station(url, name):
    global current_process, current_station_name
    stop_current_station()
    try:
        current_process = subprocess.Popen([player, url], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        save_last_station(url, name)
        current_station_name = name
        update_tray_icon()  # Update the tray icon to show the current station
    except FileNotFoundError:
        print(f"Error: {player} is not installed. Please install {player}.")

# Toggle playback on/off
def toggle_playback():
    global current_process, current_station_name
    if current_process:
        stop_current_station()
        current_station_name = None  # Clear station name when stopped
    else:
        last_station, last_station_name = load_last_station()
        if last_station:
            play_station(last_station, last_station_name)
        else:
            print("No station was previously played.")
    update_tray_icon()  # Ensure the tray icon is updated correctly

# Exit the program and clean up
def exit_program():
    stop_current_station()
    QtWidgets.QApplication.instance().quit()
    sys.exit()

# Update the tray icon menu
def update_tray_icon():
    global tray_icon
    menu = QtWidgets.QMenu()

    # Toggle Playback action
    toggle_action = QtWidgets.QAction("Toggle Playback", menu)
    toggle_action.triggered.connect(toggle_playback)
    menu.addAction(toggle_action)

    # Current station action (disabled)
    current_station_action = QtWidgets.QAction(
        " " * 4 + (current_station_name if current_station_name else "No Station Playing"), menu
    )
    current_station_action.setEnabled(False)
    menu.addAction(current_station_action)

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

    tray_icon.setContextMenu(menu)

    # Update the tray icon image based on playback status
    if current_process:
        tray_icon.setIcon(QtGui.QIcon(green_waveform_icon))
    else:
        tray_icon.setIcon(QtGui.QIcon(red_waveform_icon))

# Open the bookmark editor GUI
def open_bookmark_editor():
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
        self.category_listbox.clear()
        for group in self.bookmarks:
            self.category_listbox.addItem(group["group"])
        self.update_stations()

    def update_stations(self):
        self.station_listbox.clear()
        if self.current_category:
            for station in self.current_category["stations"]:
                self.station_listbox.addItem(station["name"])

    def on_category_select(self, item):
        category_index = self.category_listbox.row(item)
        self.current_category = self.bookmarks[category_index]
        self.current_station = None
        self.update_stations()

    def on_station_select(self, item):
        station_index = self.station_listbox.row(item)
        self.current_station = self.current_category["stations"][station_index]

    def add_category(self):
        name, ok = QtWidgets.QInputDialog.getText(self, "Input", "Enter category name:")
        if ok and name:
            self.undo_stack.append((self.bookmarks, "add_category", name))
            self.redo_stack.clear()
            self.bookmarks.append({"group": name, "stations": []})
            self.update_categories()
            self.changes_made = True

    def add_station(self):
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
        if self.current_station:
            self.remove_station()
        elif self.current_category:
            self.remove_category()

    def remove_category(self):
        if self.current_category:
            name = self.current_category["group"]
            self.undo_stack.append((self.bookmarks, "remove_category", name))
            self.redo_stack.clear()
            self.bookmarks.remove(self.current_category)
            self.current_category = None
            self.update_categories()
            self.changes_made = True

    def remove_station(self):
        station_index = self.station_listbox.currentRow()
        if station_index != -1:
            station = self.current_category["stations"].pop(station_index)
            self.undo_stack.append((self.current_category["stations"], "remove_station", station))
            self.redo_stack.clear()
            self.update_stations()
            self.changes_made = True

    def move_up(self):
        if self.current_station:
            self.move_station(-1)
        elif self.current_category:
            self.move_category(-1)

    def move_down(self):
        if self.current_station:
            self.move_station(1)
        elif self.current_category:
            self.move_category(1)

    def move_category(self, direction):
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
        index = self.category_listbox.row(item)
        current_name = self.bookmarks[index]["group"]
        new_name, ok = QtWidgets.QInputDialog.getText(self, "Edit Category", "Edit category name:", text=current_name)
        if ok and new_name:
            self.bookmarks[index]["group"] = new_name
            self.update_categories()
            self.changes_made = True

    def edit_station(self, item):
        station_index = self.station_listbox.row(item)
        current_station = self.current_category["stations"][station_index]

        # Combine the current name and URL in one input screen
        current_name = current_station["name"]
        current_url = current_station["url"]

        # Use a dialog to prompt for both name and URL in a single input
        new_values = self.get_combined_input("Edit station details:", current_name, current_url)

        if new_values:
            new_name, new_url = new_values
            current_station["name"] = new_name
            current_station["url"] = new_url
            self.update_stations()
            self.changes_made = True

    def get_combined_input(self, prompt, name_default, url_default):
        # Create a new dialog for name and URL input
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
        save_bookmarks(self.bookmarks)
        update_tray_icon()
        self.changes_made = False

    def undo(self):
        if self.undo_stack:
            action = self.undo_stack.pop()
            data, action_type, details = action
            if action_type == "add_category":
                data.remove({"group": details, "stations": []})
                if self.current_category and self.current_category["group"] == details:
                    self.current_category = None
            elif action_type == "remove_category":
                data.append({"group": details, "stations": []})
                if not self.current_category:
                    self.current_category = {"group": details, "stations": []}
            elif action_type == "add_station":
                data.remove(details)
                if self.current_station == details:
                    self.current_station = None
            elif action_type == "remove_station":
                data.append(details)
                if not self.current_station:
                    self.current_station = details
            self.redo_stack.append(action)
            self.update_categories()
            self.changes_made = True

    def redo(self):
        if self.redo_stack:
            action = self.redo_stack.pop()
            data, action_type, details = action
            if action_type == "add_category":
                data.append({"group": details, "stations": []})
                if not self.current_category:
                    self.current_category = {"group": details, "stations": []}
            elif action_type == "remove_category":
                data.remove({"group": details, "stations": []})
                if self.current_category and self.current_category["group"] == details:
                    self.current_category = None
            elif action_type == "add_station":
                data.append(details)
                if not self.current_station:
                    self.current_station = details
            elif action_type == "remove_station":
                data.remove(details)
                if self.current_station == details:
                    self.current_station = None
            self.undo_stack.append(action)
            self.update_categories()
            self.changes_made = True

    def closeEvent(self, event):
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
        # Update the bookmarks data structure when a category is moved
        moved_category = self.bookmarks.pop(sourceStart)
        self.bookmarks.insert(destinationRow, moved_category)
        self.changes_made = True

    def on_station_moved(self, sourceParent, sourceStart, sourceEnd, destinationParent, destinationRow):
        # Update the bookmarks data structure when a station is moved
        moved_station = self.current_category["stations"].pop(sourceStart)
        self.current_category["stations"].insert(destinationRow, moved_station)
        self.changes_made = True

# Main application entry point
def main():
    global tray_icon
    app = QtWidgets.QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)

    setup_icons()

    tray_icon = QtWidgets.QSystemTrayIcon()
    tray_icon.setVisible(True)

    update_tray_icon()
    sys.exit(app.exec_())

if __name__ == "__main__":
    main()
