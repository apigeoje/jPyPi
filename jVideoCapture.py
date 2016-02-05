#!/usr/bin/python
'''-------------------------------------

  Dependencies:
  -------------
  io
  picamera
  RPi.GPIO
  threading
  # pyaudio


  This app will do the following

  1:  get the camera
      create a circular buffer
      start recording into the circular buffer

  2:  initiate the sensor
      check that the sensor is ready
      set the sensor

  3:  enter a loop
      wait for a Rising/Falling edge

  4:  when the sensor detects movement
      split recording to after file
      write the circular buffer to a file named <timestamp>
      clear the buffer
      wait for a the sensor to reset

  5:  when reset split back to circular
      write the after file

  6:  concat the two files into 1

  7:  http put the event to node-red

  8:  loop

----------------------------------------
  Dependencies
------------------------------------------'''
import io
import os
import picamera
import requests
import RPi.GPIO as GPIO
import socket
import threading
import time
import subprocess as sp

'''-----------------------------------------
  Global configuration variables
------------------------------------------'''
# for logging
APP_NAME = 'jBabyMonitor'
# where streams will be saved before concatenation
TEMP_STORAGE_PATH = ''
# where concatenated files will be stored
OUTPUT_STORAGE_PATH = 'final destination'
# resolution
CAMERA_RESOLUTION = (1296,730)
# bitrate
CAMERA_BITRATE = 1000000
# length of circular buffer and time recorded before a triggered event
BUFFER_SECS = 5
# the pin number
SENSOR_CHANNEL = 21
# camera splitters
MONITOR_SPLITTER = 1
STREAM_SPLITTER = 2
# ffmpeg
FFMPEG_BIN = "ffmpeg"
# youtubeupload script
YOUTUBE_UPLOADER = "./jYouTubeUploader.py"
# how big a movement stream is significant
SIGNIFICANT_STREAM_SIZE = 2500000

'''-----------------------------------------
  Helper functions
------------------------------------------'''

def write_video(stream, filename):
    # Write the entire content of the circular buffer to disk. No need to
    # lock the stream here as we're definitely not writing to it
    # simultaneously

    with io.open(TEMP_STORAGE_PATH + filename, 'wb') as output:
        if isinstance(stream, picamera.streams.PiCameraCircularIO):
            for frame in stream.frames:
                if frame.frame_type == picamera.PiVideoFrameType.sps_header:
                    stream.seek(frame.position)
                    break
            while True:
                buf = stream.read1()
                if not buf:
                    break
                output.write(buf)
            retFileSize = 0

        elif isinstance(stream, io.BytesIO):
            retFileSize = stream.tell()
            stream.seek(0)
            buf = stream.getvalue()
            output.write(buf)

        else:
            raise TypeError('Expecting a PiCameraCircularIO or an io.BytesIO')

        # clear the stream and prepare it for reuse
        stream.seek(0)
        stream.truncate()
        return retFileSize, filename

def concat(clip, filename):

    try:
        concatString = 'concat:'+clip[0]+'|'+clip[1]

        command = [ FFMPEG_BIN,
           '-y', # (optional) overwrite output file if it exists
           '-i', concatString,
           '-c', 'copy',
           TEMP_STORAGE_PATH+filename ]

        pipe = sp.Popen( command, stdin=sp.PIPE, stderr=sp.PIPE)

        pipe.wait()
        return filename 
    except:
        return False


def removeFiles(fileArray):
    for file in fileArray:
	os.remove(file)

def pushToYouTube(outputFile):

    try:
        command = [ YOUTUBE_UPLOADER,
            '--file', TEMP_STORAGE_PATH+outputFile,
            '--title', outputFile,
            '--noauth_local_webserver'
           ]

        youtubeId = sp.check_output( command ) 

	return youtubeId.strip()

    except:
        return False

def logToNodeRed(eventObj):
    # requests to node-red
    r = requests.post('http://localhost:1880/video', json=eventObj)
    if r.status_code != 200:
        print("Problem :/\n")

'''------------------------------------------
  Classes
------------------------------------------'''

class jBabyMonitor(threading.Thread):

    def __init__(self, camera):
        threading.Thread.__init__(self)
        self.camera = camera

    def run(self):
        jEvent = {}
        time.sleep(1800)
        # create the circular buffer
        stream = picamera.PiCameraCircularIO(camera,
                                             seconds=BUFFER_SECS,
                                             bitrate=CAMERA_BITRATE,
                                             splitter_port=MONITOR_SPLITTER)

        # write a linear stream to store the after
        after = io.BytesIO()
        # start recording to the circular buffer
        self.camera.start_recording(stream,
                                    format='h264',
                                    bitrate=CAMERA_BITRATE,
                                    splitter_port=MONITOR_SPLITTER)


        # set up the IR sensor
        GPIO.setup(SENSOR_CHANNEL, GPIO.IN)
        self.camera.wait_recording(BUFFER_SECS, splitter_port=MONITOR_SPLITTER)
        try:
            # enter the loop
            while camera:
                if not GPIO.input(SENSOR_CHANNEL):
                    GPIO.wait_for_edge(SENSOR_CHANNEL, GPIO.RISING)

                # set the timestamp
                jEvent['timestamp'] = int(time.time()*1000)
                jEvent['datetime'] = time.strftime('%Y-%m-%d %H:%M') 
                # As soon as we detect motion, split the recording to
                # record the frames "after" motion
                self.camera.split_recording(after,splitter_port=MONITOR_SPLITTER)

                # build the output filename
                outputFile = str(int(time.time()))

                # Write the "before" motion to disk as well
                beforeFileSize, beforeFileName = write_video(stream, outputFile+'.h264')

                # print '# Wait until motion is no longer detected'
                GPIO.wait_for_edge(SENSOR_CHANNEL, GPIO.FALLING)

                # calculate the activity duration
                jEvent['duration'] = int((int(time.time()*1000) - jEvent['timestamp'])/1000)

                # then split recording back to the in-memory circular buffer
                self.camera.split_recording(stream,splitter_port=MONITOR_SPLITTER)

                # Write the "after" motion to disk
                afterFileSize, afterFileName = write_video(after, 'after'+outputFile+'.h264')

                if afterFileSize > 2500000:
                    jEvent['filename'] = outputFile + '.mpg'
                    ## concatenate two file
                    concatSuccess = concat([beforeFileName, afterFileName], jEvent['filename'])
        	    if concatSuccess:
                        jEvent['YTid'] = pushToYouTube(jEvent['filename'])
                        if jEvent['YTid']:
                            removeFiles([beforeFileName, afterFileName, jEvent['filename']])
                    else:
                        print 'Problem writing the compiled file,' + outputFile + '... do it manually later'
                else:
	            removeFiles([beforeFileName, afterFileName]) 

                jEvent['source'] = APP_NAME 
                jEvent['activity'] = 'Movement'
                jEvent['mood'] = 'Active Baby!'
                jEvent['location'] = 'Cot'
                # the sensor takes about 10 seconds to turn off so 
                # if the duration is less than 10 it is a hangover 
                # from the last event or too short to bother
                if jEvent['duration'] > 10:
		    logToNodeRed(jEvent)
                jEvent = {}

        finally:
            self.camera.stop_recording()
            GPIO.cleanup()


class jBabyWebstream(threading.Thread):
    '''
    TODO
    '''
    def __init__(self, camera):
        print 'jBabyWebstream has initiated'
        threading.Thread.__init__(self)
        self.camera = camera

    def run(self):
        print 'Started the Webstream... :p yeah right!!!!!'


GPIO.setmode(GPIO.BCM)

'''-----------------------------------------
  Setup the camera
------------------------------------------'''
with picamera.PiCamera() as camera:
    camera.resolution = CAMERA_RESOLUTION
    camera.hflip = True
    camera.vflip = True

    myBabyMon = jBabyMonitor(camera)
    myBabyMon.start()
    raw_input("Hit enter to close the Babymonitor")
    print 'Good-bye!'
