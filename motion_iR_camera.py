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
import RPi.GPIO as GPIO
import socket
import threading
import time
import subprocess as sp
# from moviepy.editor import VideoFileClip, concatenate_videoclips

exitFlag = 0
'''-----------------------------------------
  Global configuration variables
------------------------------------------'''
# where streams will be saved before concatenation
TEMP_STORAGE_PATH = ''
# where concatenated files will be stored
OUTPUT_STORAGE_PATH = '/home/pi/Videos/'
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
# how big a movement stream is significant
SIGNIFICANT_STREAM_SIZE = 2500000

'''-----------------------------------------
  Helper functions
------------------------------------------'''

def write_video(stream, filename):
    # Write the entire content of the circular buffer to disk. No need to
    # lock the stream here as we're definitely not writing to it
    # simultaneously
    
    with io.open(TEMP_STORAGE_PATH + filename+'.h264', 'wb') as output:
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
        return retFileSize

def concat(clip, filename):

    try:
        concatString = 'concat:'+clip+'.h264|after'+clip+'.h264'

        command = [ FFMPEG_BIN,
           '-y', # (optional) overwrite output file if it exists
           '-i', concatString,
           '-c', 'copy',
           OUTPUT_STORAGE_PATH+filename ]

        pipe = sp.Popen( command, stdin=sp.PIPE, stderr=sp.PIPE) 

        pipe.wait()
        return True
    except:
        return False


def removeClipParts(clip):
    os.remove(clip+'.h264')
    os.remove('after'+clip+'.h264')


'''------------------------------------------
  Classes
------------------------------------------'''

class jBabyMonitor(threading.Thread):
    def __init__(self, camera):
        threading.Thread.__init__(self)
        self.camera = camera

    def run(self):
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
                    print '# wait for edge'
                    GPIO.wait_for_edge(SENSOR_CHANNEL, GPIO.RISING)
                
                # As soon as we detect motion, split the recording to
                # record the frames "after" motion
                # self.camera.split_recording(TEMP_STORAGE_PATH + PART_TWO)
                self.camera.split_recording(after,splitter_port=MONITOR_SPLITTER)

                # build the output filename
                outputFile = str(int(time.time()))

                # Write the "before" motion to disk as well
                beforeFileSize = write_video(stream, outputFile)

                print '# Wait until motion is no longer detected'
                GPIO.wait_for_edge(SENSOR_CHANNEL, GPIO.FALLING)
                
                # then split recording back to the in-memory circular buffer
                self.camera.split_recording(stream,splitter_port=MONITOR_SPLITTER)

                # Write the "after" motion to disk
                afterFileSize = write_video(after, 'after'+outputFile)
                print afterFileSize

                if afterFileSize > 2500000:
                    ## concatenate two file
                    concatSuccess = concat(outputFile, outputFile+'.mpg')
		    if concatSuccess:
                        removeClipParts(outputFile)
                    else:
                        print 'Problem writing the compiled file,' + outputFile + '... do it manually later'
                else:
		    removeClipParts(outputFile)

        finally:
            self.camera.stop_recording()
            GPIO.cleanup()


class jBabyWebstream(threading.Thread):
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

    raw_input('Hit enter to end motion_iR_camera.py')
    exitFlag = 1
    print 'Good-bye!'
