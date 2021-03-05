# CageWheel

A RaspberryPi-based system for monitoring running wheels in up to 24 mouse cages.


## Instructions for setting up new Pi for Mouse Wheel Controller

### 1. Flash new SD card with Raspbian
- Get latest Raspbian from https://www.raspberrypi.org/downloads/raspbian/
	- Probably don't need full version with "recommended software"
- Use BalenaEtcher to flash it on to SD card

### 2. Boot up Pi
- Raspbian will ask for some setup information:
	- set language & time zone
	- set password: "mouse run fast"
- Create a new folder ~/bin
- Copy `CageWheelMonitor.py` to ~/bin
- Make `CageWheelMonitor.py` executable
	- open a terminal and type: `chmod +x ~/bin/CageWheelMonitor.py`
- You may need to log our and log back in before you can run it

You should be good to go!
