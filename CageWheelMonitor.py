#!/usr/bin/python
# coding: utf-8

import numpy as np
import sched, time
import signal, sys
import subprocess
import datetime
import os
import re


RUNNING_ON_PI = False
try:
    import pigpio as gpio
    RUNNING_ON_PI = True
except:
    print('** Not running on RaspberyPi — faking inputs. **')

######### USER MODIFIABLE PARAMETERS #########

# wheel & sensor
CLICKS_PER_REVOLUTION = 2
METERS_PER_REVOLUTION = 0.39 # measured diameter is ~0.124 m

# setup for timing & logging
loggingInterval_sec   = 10  # in seconds
logFileDuration_hours = 24  # in hours;  experiment logs will be broken up into
                            #            multiple files of this duration


######### DO NOT CHANGE VALUES BELOW THIS LINE #########

# setup for gpio
GLITCH_FILTER = 100 # in us
PINS = [4, 14, 15, 17, 18, 27, 22, 23, 24, 10, 9, 25, 11, 8, 7]
MAX_NUM_CAGES = len(PINS)

# setup for gpio
callbacks = []

# global to hold log files
logFiles = []

# create scheduler
scheduler = sched.scheduler(time.time, time.sleep)

def setupPins():
    # List of all usable GPIO pins aside from 2 or 3 as they are pulled up
    global PINS, RUNNING_ON_PI, pi, MAX_NUM_CAGES
    if (RUNNING_ON_PI and (pi.get_hardware_revision() >= 16)):
        # more pins on later version of RasPi
        PINS = PINS + [5, 6, 12, 13, 19, 16, 26, 20, 21]
    MAX_NUM_CAGES = len(PINS)

# cleanup
def cleanup():
    print("In Cleanup")
    global callbacks
    for cb in callbacks:
        cb.cancel()
    if RUNNING_ON_PI:
        global pi
        pi.stop()
    # close log file
    closeAllLogs()

# trigger cleanup() on ^C
def sigint_handler(signal, frame):
    cleanup()
    sys.exit()

signal.signal(signal.SIGINT, sigint_handler)


def startGPIODaemon():
    if not RUNNING_ON_PI:
        return
    # run 'sudo pigpiod' unless it is already running
    ps_list = subprocess.check_output(["ps", "-aux"])
    if not re.search('pigpiod', ps_list):
        subprocess.call(["sudo", "/usr/bin/pigpiod"])


# call this function to run the program!
def runCageWheelMonitor():
    # setup gpio pins
    if RUNNING_ON_PI:
        startGPIODaemon()
        global pi
        pi = gpio.pi()
        setupPins()

    # prompt user for mouse/cage info
    global samples
    global miceInfo, cages
    miceInfo, cages = getMiceInfo()

    # setup logging
    global startTime, logCount, logFileCount
    startTime = time.time()
    logCount = 0
    logFileCount = 0
    startLogging(miceInfo)

    global callbacks
    global active_pins, num_active_pins
    active_pins = [PINS[cage-1] for cage in cages]
    num_active_pins = len(active_pins)

    # clicks is the number of sensor clicks thusfar this sampling window
    global clicks
    clicks = np.zeros(num_active_pins)
    clicks[:] = 0

    if RUNNING_ON_PI:
        for pin in active_pins:
            pi.set_mode(pin, gpio.INPUT)
            pi.set_pull_up_down(pin, gpio.PUD_DOWN)
            pi.set_glitch_filter(pin, GLITCH_FILTER) # in us
            callbacks.append(pi.callback(pin, gpio.RISING_EDGE, edgeCallback))


    # start collecting data
    print('==========')
    print('')
    print('Running...')
    print('')
    print('Mouse speed in (rev/sec):')

    global scheduler
    scheduler.enterabs(startTime + loggingInterval_sec, 1, newLogEntry, ())

    # run until quit/^C
    scheduler.run()


def edgeCallback(channel, level, ticks):
    global clicks
    clicks[cages.index(PINS.index(channel)+1)] += 1 ## TODO this is too messy
    # print(PINS.index(channel), level) # for debugging

def newLogEntry():
    global samples
    global startTime
    global logCount
    global prevLogTime
    global clicks
    global scheduler

    logCount += 1
    scheduler.enterabs(startTime + (logCount+1)*loggingInterval_sec, 1, newLogEntry, ())

    # compute inter-log interval
    currLogTime = time.time()
    if not 'prevLogTime' in globals():
        prevLogTime = startTime
    interval = currLogTime - prevLogTime
    prevLogTime = currLogTime

    # compute wheel speeds for current interval
    currentClicks = np.array(clicks)
    # print(currentClicks)
    clicks[:] = 0 # reset to 0 for next interval
    # print(currentClicks)
    revsPerSec = currentClicks / float(CLICKS_PER_REVOLUTION) / interval
    metersPerSec = revsPerSec / METERS_PER_REVOLUTION

    # print(currentClicks)

    # write activityPercent to log
    logData(revsPerSec)

    # print debug info to screen:
    global miceInfo

    # print header every 10 iterations
    if ((logCount % 10) == 1):
        dt = datetime.datetime.now()
        # dateString = dt.strftime('%Y-%m-%d %H:%M:%S')
        dateString = dt.strftime('%Y-%m-%d %H:%M')
        print(dateString)
        outputString = ''
        for n in xrange(num_active_pins):
            mouse = miceInfo[n]
            outputString += '{:>8.8} |'.format(mouse['name'])
        print(outputString)

    outputString = ''
    for n in xrange(num_active_pins):
        outputString += '{:8.1f} |'.format(revsPerSec[n])
    print(outputString)


## functions for user input/setup

def getMiceInfo():
    print("Mouse Running Wheel Monitor v1.0")
    print("================================")
    print("")
    print("You can monitor up to {} cages.".format(MAX_NUM_CAGES))

    mice = []
    cages = []
    for mouseNum in xrange(MAX_NUM_CAGES):
        print("Mouse {}:".format(mouseNum+1))
        name = raw_input("- Name: ")
        sex = raw_input("- Sex: ")
        strain = raw_input("- Strain: ")
        while True:
            cage = raw_input("- Cage number: ")
            try:
                cage = int(cage)
            except:
                print("  ** You must enter a number from 1 to {}. **".format(MAX_NUM_CAGES))
                continue
            if not (0<cage<=MAX_NUM_CAGES):
                print("  ** You must enter a number from 1 to {}. **".format(MAX_NUM_CAGES))
                continue
            if cage in cages:
                print("  ** Cage {} already in use. **".format(cage))
                continue
            break

        mouse = dict()
        mouse['name'] = name
        mouse['sex'] = sex
        mouse['cage'] = cage
        mouse['strain'] = strain
        mice.append(mouse)
        cages.append(cage)
        if mouseNum < MAX_NUM_CAGES-1 :
            yn = '#'
            while not (len(yn) == 0 or
                        yn.startswith('Y') or
                        yn.startswith('y') or
                        yn.startswith('N') or
                        yn.startswith('n')):
                yn = raw_input("More mice? [Y/n] ")
            print("")
            if (yn.startswith('N') or yn.startswith('n')):
                break
    return mice, cages


## functions for data logging...

def startLogging(miceInfo):
    global startTime, scheduler, logFileCount
    createLogFiles(miceInfo)
    # schedule the next log file chunk to occur <logFileDuration_hours> from now
    logFileCount += 1
    scheduler.enterabs(startTime + (logFileCount * logFileDuration_hours * 3600), 1, startLogging, [miceInfo])

logFiles = []
def createLogFiles(miceInfo):
    closeAllLogs()
    dir = os.path.expanduser("~/logs/")
    if not os.path.exists(dir):
        os.mkdir(dir)
    # global logName
    # baseName = logName
    dt = datetime.datetime.now()
    dateString = dt.strftime('%Y-%m-%d_%H%M')
    global logFiles
    for mouse in miceInfo:
        logFile = newLogFile(mouse, dateString, dir)
        logFiles.append(logFile)
        addHeaders(logFile, mouse, dt)

def newLogFile(mouse, dateString, dir):
    name = mouse['name']
    logFile = open(os.path.join(dir, "{}_{}.log".format(name, dateString)), "w", 1) # open for writing w/line buffering
    return logFile

def addHeaders(logFile, mouse, dt):
    # 1 NAME
    logFile.write("# Name: {}\n".format(mouse['name']))
    # 2 START DATE (dd-mon-yyyy), where the month uses stardard 3-letter
    # abbreviations (lower case)
    logFile.write("# Start date: {}\n".format(dt.strftime('%d-%b-%Y').lower()))
    # 3 START TIME (24 hour) Always 2 digits for both hour and minute, as in 04:20
    logFile.write("# Start time: {}\n".format(dt.strftime('%H:%M')))
    # 4 INTERVAL (sample interval, or the time between data points, in sec)
    logFile.write("# Logging interval (sec): {}\n".format(int(loggingInterval_sec)))
    # 5 Any number (place holder) - cage number
    logFile.write("# Cage number: {}\n".format(mouse['cage']))
    # 6 Any number (place holder) - strain
    logFile.write("# Strain: {}\n".format(mouse['strain']))
    # 7 Sex (also a place holder and ignored)
    logFile.write("# Sex: {}\n".format(mouse['sex']))


def closeAllLogs():
    global logFiles
    for logFile in logFiles:
        logFile.close()
    logFiles = []

def logData(dataArray):
    global logFiles, num_active_pins
    for i in xrange(num_active_pins):
        logFile = logFiles[i]
        if np.isnan(dataArray[i]):
            dataArray[i] = -1
        logFile.write('{:.2f}\n'.format(dataArray[i]))




## run the program if this file is executed as a standalone script:

if __name__ == "__main__":
    runCageWheelMonitor()




