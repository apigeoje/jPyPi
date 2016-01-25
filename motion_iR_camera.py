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
OUTPUT_STORAGE_PATH = '/home/jeremy/Videos/'
# resolution
CAMERA_RESOLUTION = (640,480)
# bitrate
CAMERA_BITRATE = 700000
# length of circular buffer and time recorded before a triggered event
BUFFER_SECS = 5 
# the pin number
SENSOR_CHANNEL = 21
# camera splitters
MONITOR_SPLITTER = 1
STREAM_SPLITTER = 2
# ffmpeg
FFMPEG_BIN = "ffmpeg"


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

        elif isinstance(stream, io.BytesIO):
            stream.seek(0)
            buf = stream.getvalue()
            output.write(buf)

        else: 
            raise TypeError('Expecting a PiCameraCircularIO or an io.BytesIO')

        # clear the stream and prepare it for reuse
        stream.seek(0)
        stream.truncate()

def concat(clip, filename):

    concatString = 'concat:'+clip+'|after'+clip

    command = [ FFMPEG_BIN,
           '-y', # (optional) overwrite output file if it exists
           '-i', concatString,
           '-c', 'copy',
           OUTPUT_STORAGE_PATH+'o'+filename ]

    pipe = sp.Popen( command, stdin=sp.PIPE, stderr=sp.PIPE) 

    pipe.wait()

    os.remove(clip)
    os.remove('after'+clip)


'''------------------------------------------
  Classes
------------------------------------------'''

class jBabyMonitor(threading.Thread):
    def __init__(self, camera):
        threading.Thread.__init__(self)
        self.camera = camera

    def run(self):
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
                    # wait for edge
                    GPIO.wait_for_edge(SENSOR_CHANNEL, GPIO.RISING)
                
                # As soon as we detect motion, split the recording to
                # record the frames "after" motion
                # self.camera.split_recording(TEMP_STORAGE_PATH + PART_TWO)
                self.camera.split_recording(after,splitter_port=MONITOR_SPLITTER)

                # build the output filename
                outputFile = str(int(time.time())) + '.h264'

                # Write the "before" motion to disk as well
                write_video(stream, outputFile)

                # Wait until motion is no longer detected
                GPIO.wait_for_edge(SENSOR_CHANNEL, GPIO.FALLING)
                
                # then split recording back to the in-memory circular buffer
                self.camera.split_recording(stream,splitter_port=MONITOR_SPLITTER)

                # Write the "after" motion to disk
                write_video(after, 'after'+outputFile)

                ## concatenate two file
                concat(outputFile, outputFile)

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
