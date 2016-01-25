import logging
logging.basicConfig(filename='/var/log/jBabyMonitor.log', format='%(asctime)s %(filename)s %(message)s', datefmt='%y-%m-%d %H:%M', level=logging.DEBUG)
logging.info("jEventVideo.py initialising")

import time
import requests
import io
import picamera
import fractions
from datetime import datetime

try:
    import RPi.GPIO as GPIO
except RuntimeError:
    logging.critical("Error importing RPi.GPIO!  This is probably because you need superuser privileges. You can achieve this by using 'sudo' to run your script")

# set logging url
MONGO_LOG_URL = ''

# define buffer types
BUF_CIRC = 1
BUF_IO = 2
# buffer length in seconds
BUF_LEN = 5

# define the switch pins
FASTTWITCH = 38
MIDTWITCH = 37

# define date format for logging
STRFT = "%H:%M %a %d %b %Y"

# create a dictionary of the pins and labels
sensors = {FASTTWITCH: 'Fast Twitch Sensor', MIDTWITCH: 'Mid Twitch Sensor'}

# create the event dict
jEvent = {}

# define the callback to log to node-red

def logItToNodeRed(jEvent):

    # print("We got a log")

    r = requests.post(MONGO_LOG_URL, json=jEvent)
    if r.status_code != 200:
        logging.warning("Problem POSTING to piLog @ " + MONGO_LOG_URL)



def write_video(stream, bufType):
    # Write the entire content of the circular buffer to disk. No need to
    # lock the stream here as we're definitely not writing to it
    # simultaneously
    with io.open(jEvent['filename'], 'wb') as output:
        if bufType == BUF_CIRC:
            for frame in stream.frames:
                if frame.frame_type == picamera.PiVideoFrameType.sps_header:
                    stream.seek(frame.position)
                    break
            while True:
                buf = stream.read1()
                if not buf:
                    break
            output.write(buf)
            # Wipe the circular stream once we're done
            stream.seek(0)
            stream.truncate()
        elif bufType == BUF_IO:
            output.write(stream.getvalue())

logging.info("Initialsing sensors")
#set up the IO
GPIO.setmode(GPIO.BOARD);
for sensor in sensors:
    logging.info("Setting up: "+ sensors[sensor])
    GPIO.setup(sensor, GPIO.IN, pull_up_down=GPIO.PUD_DOWN);
    GPIO.add_event_detect(sensor, GPIO.RISING, bouncetime=2500);


#wait for user to keyboard interrupt
try:
    logging.info("Starting camera")
    with picamera.PiCamera() as camera:
        camera.resolution = (640, 480)
        camera.framerate = fractions.Fraction('25/1')
        stream = picamera.PiCameraCircularIO(camera, seconds=BUF_LEN)
        camera.start_recording(stream, format='h264')
        try:
            while True:
                camera.wait_recording(1)
                if GPIO.event_detected(fastTwitch):
                    print "Initial Motion detected!"
                    jEvent['source'] = sensors[fastTwitch]
                    jEvent['time_stamp'] = int(time.time()) - BUF_LEN
                    jEvent['filename'] = str(jEvent['time_stamp']) + '.h264'
                    jEvent['logged at'] = datetime.fromtimestamp(jEvent['time_stamp']).strftime(STRFT)
                    strFilename = str(int(time.time()))

                    # As soon as we detect motion, split the recording to
                    # record the frames "after" motion
                    afterStream = io.BytesIO()
                    camera.split_recording(afterStream)

                    # Write the 10 seconds "before" motion to disk as well
                    write_video(stream, BUF_CIRC)

                    # Wait until motion is no longer detected, then split
                    # recording back to the in-memory circular buffer

                    while True:
                        print "recording for 5 seconds"
                        camera.wait_recording(5)
                        if GPIO.event_detected(fastTwitch):
                            print "detected movement"
                        else:
                            print "no further movement detected"
                            break

                    # calculate the length of the 'event'
                    secdif = int(time.time()) - jEvent['time_stamp']
                    print "video should be", secdif, "seconds long"
                    jEvent['length'] = secdif
                    print "Motion stopped!"
                    camera.split_recording(stream)
                    write_video(afterStream, BUF_IO)
                    afterStream = None
                    logItToNodeRed(jEvent)
        finally:
            camera.stop_recording()


finally:
    logging.info("Cleaning up GPIOs and exiting")
    GPIO.cleanup;
    exit();

