#!/usr/bin/python

import numpy as np
import sched, time
import signal, sys
import subprocess
import datetime
import os
import re

try:
    import pigpio as gpio
    RUNNING_ON_PI = True
except:
    RUNNING_ON_PI = False

######### USER MODIFIABLE PARAMETERS #########

# setup for gpio
NUM_CAGES = 8
PINS = [4, 17, 27, 22, 14, 15, 18, 23] # don't use pins 2 or 3 as they are pulled up
GLITCH_FILTER = 100 # in us

# wheel & sensor
CLICKS_PER_REVOLUTION = 2
METERS_PER_REVOLUTION = 0.39 # measured diameter is ~0.124 m

# setup for timing
loggingInterval_sec = 10 # in seconds

# data collection
logTenthsOfPercent = True   # if True: 100% is represented as 1000 in log files
                            #       otherwise save percentages (e.g. 100% = 100)

######### DO NOT CHANGE VALUES BELOW THIS LINE #########

# setup for gpio
callbacks = []

# global to hold log files
logFiles = []

# create scheduler
s = sched.scheduler(time.time, time.sleep)


# cleanup
def cleanup():
    print("In Cleanup")
    global callbacks
    for cb in callbacks:
        cb.cancel()

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
    global samples
    global miceInfo, cages
    miceInfo, cages = getMiceInfo()

    createLogFiles(miceInfo)

    # setup gpio pins
    if RUNNING_ON_PI:
        startGPIODaemon()
        global pi
        pi = gpio.pi()
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
            callbacks.append(pi.callback(pin, gpio.EITHER_EDGE, edgeCallback))


    # start collecting data
    global startTime, logCount
    startTime = time.time()
    logCount = 0

    print('==========')
    print('')
    print('Running...')
    print('')

    #s.enter(1./samplingRate, 2, newSample, ()) # can be replaced by calling 'newSample()'
    s.enterabs(startTime + loggingInterval_sec, 1, newLogEntry, ()) 

    # run until quit/^C
    s.run()


def edgeCallback(channel, level, ticks):
    if level > 0:
        global clicks
        clicks[cages.index(PINS.index(channel)+1)] += 1 ## TODO this is too messy
    # print(PINS.index(channel), level) # for debugging


# def newSample():
#     global samples
#     global cages
#     global num_active_pins
#     s.enter(1./samplingRate, 1, newSample, ()) # setup next sample
#     samples += 1
#     for i in xrange(num_active_pins):
#         if not RUNNING_ON_PI:
#             clicks[i] += np.round(np.random.rand())
#         else:    
#             clicks[i] += pi.read(active_pins[i])


def newLogEntry():
    global samples
    global startTime 
    global logCount
    global prevLogTime
    global clicks

    logCount += 1
    s.enterabs(startTime + (logCount+1)*loggingInterval_sec, 1, newLogEntry, ()) 

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
    dt = datetime.datetime.now()
    dateString = dt.strftime('%Y-%m-%d %H:%M:%S')
    outputString = dateString
    for n in xrange(num_active_pins):
        mouse = miceInfo[n]
        outputString += '  |  {} {:4.1f} rev/sec'.format(mouse['name'], revsPerSec[n])

    print(outputString)
    # print(logCount, map(str, activityPercent))
    # print(prevSamples)
    # print(time.time() - startTime)
    # print(" ")


## functions for user input/setup        

def getMiceInfo():
    print("Mouse Activity Logger v1.0")
    print("==========================")
    print("")
    print("You can monitor up to {} cages.".format(NUM_CAGES))

    mice = []
    cages = []
    for mouseNum in xrange(NUM_CAGES):
        print("Mouse {}:".format(mouseNum+1))
        name = raw_input("- Name: ")
        sex = raw_input("- Sex: ")
        strain = raw_input("- Strain: ")
        while True:
            cage = raw_input("- Cage number: ")
            try:
                cage = int(cage)
            except:
                print("  ** You must enter a number from 1 to {}. **".format(NUM_CAGES))
                continue
            if not (0<cage<=NUM_CAGES):
                print("  ** You must enter a number from 1 to {}. **".format(NUM_CAGES))
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
        if mouseNum < NUM_CAGES-1 :
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
logFile = None
def createLogFiles(miceInfo):
    global logFiles
    if logFiles:
        for file in logFiles:
            file.close()
    logFiles = [];
    dir = os.path.expanduser("~/logs/")
    if not os.path.exists(dir):
        os.mkdir(dir)
    # global logName
    # baseName = logName
    dt = datetime.datetime.now()
    dateString = dt.strftime('%Y-%m-%d_%H%M')
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
    logFile.write("{}\n".format(mouse['name']))
    # 2 START DATE (dd-mon-yyyy), where the month uses stardard 3-letter
    # abbreviations (lower case)
    logFile.write("{}\n".format(dt.strftime('%d-%b-%Y').lower()))
    # 3 START TIME (24 hour) Always 2 digits for both hour and minute, as in 04:20
    logFile.write("{}\n".format(dt.strftime('%H:%M')))
    # 4 INTERVAL (sample interval, or the time between data points, in sec)
    logFile.write("{}\n".format(int(loggingInterval_sec)))
    # 5 Any number (place holder) - cage number
    logFile.write("cage-{}\n".format(mouse['cage']))
    # 6 Any number (place holder) - strain
    logFile.write("{}\n".format(mouse['strain']))
    # 7 Sex (also a place holder and ignored)
    logFile.write("{}\n".format(mouse['sex']))


def closeAllLogs():
    global logFiles
    for logFile in logFiles:
        logFile.close()

def logData(dataArray):
    global logFiles, num_active_pins
    for i in xrange(num_active_pins):
        logFile = logFiles[i]
        if np.isnan(dataArray[i]):
            dataArray[i] = -1 
        if logTenthsOfPercent:
            logFile.write('{}\n'.format(int(dataArray[i]*10)))
        else:
            logFile.write('{}\n'.format(int(np.round(dataArray[i]))))




## run the program if this file is executed as a standalone script:

if __name__ == "__main__":
    runCageWheelMonitor()




