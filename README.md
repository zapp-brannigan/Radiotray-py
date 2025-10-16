# Radiotray-py
Lets you listen to your favorite radio stations, easily accessible from the tray.  
Heavily inspired by the Linux app [Radiotray-NG](https://github.com/ebruck/radiotray-ng), this Python based app works on Mac, Windows and Linux.  
I decided to write my own variant of the traditional Radiotray app when I started using Mac, where there were no app quite like it.  

# Features and functionality 
Radiotray-py features a robust bookmark editor where you can add/remove and edit your radio stations, and stores the stations in bookmarks.json.  
On Mac, Radiotray-py takes adventage of the built-in AFPlay as its backend audioi player. And on Linux, BSD and others, MPV is being used to play your radio stations.  

# Installation
Clone the repository: git clone https://github.com/CHJ85/Radiotray-py.git  
Install dependencies: python install_dependencies.py  
Navigate to Radiotray-py: cd Radiotray-py  
python ./radiotray.py  

# Usage
Right-click to access the radio channels and the bookmark editor where you edit your channels list.
Left-click toggles playback on/off.
