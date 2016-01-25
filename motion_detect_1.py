import time
import requests
import io
import picamera
import fractions
from datetime import datetime

try:
    import RPi.GPIO as GPIO
except RuntimeError:
    print("Error importing RPi.GPIO!  This is probably because you need superuser privileges.  You can achieve this by using 'sudo' to run your script")

#define buffer types
BUF_CIRC = 1
BUF_IO = 2
#buffer length in seconds
BUF_LEN = 5

#define the switch pins
fastTwitch = 38
midTwitch = 37

#define date format for logging
STRFT = "%H:%M %a %d %b %Y"

#create a dictionary of the pins and labels
sensors = {fastTwitch:'Fast Twitch Sensor', midTwitch:'Mid Twitch Sensor'}

#create the event dict
jEvent = {}

#define the callback to log to node-red
def logItToNodeRed(jEvent):
    print("We got a log")

    r = requests.post('http://192.168.0.42:1880/event', json=jEvent)
    if r.status_code != 200:
        print("Problem POSTING to piLog\n")
    else:
        print "Just logged ", jEvent.items()


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

#set up the IO
GPIO.setmode(GPIO.BOARD);
for sensor in sensors:
    print "Setting up: ", sensors[sensor];
    GPIO.setup(sensor, GPIO.IN, pull_up_down=GPIO.PUD_DOWN);
    GPIO.add_event_detect(sensor, GPIO.RISING, bouncetime=500);


#wait for user to keyboard interrupt
try:
    with picamera.PiCamera() as camera:
        camera.resolution = (640, 480)
        camera.framerate = 25 
        stream = picamera.PiCameraCircularIO(camera, seconds=BUF_LEN)
        camera.start_recording(stream, format='h264', quality=20)
        try:
            while True:
                camera.wait_recording(1)
                if GPIO.event_detected(fastTwitch):
                    print "Initial Motion detected!"
                    jEvent['source'] = sensors[fastTwitch]
                    jEvent['time_stamp'] = int(time.time()) - BUF_LEN
                    jEvent['filename'] = str(jEvent['time_stamp']) + '.h264'
                    jEvent['logged at'] = datetime.fromtimestamp(jEvent['time_stamp']).strftime(STRFT)
                    jEvent['stage'] = "developmnent"

                    # As soon as we detect motion, split the recording to
                    # record the frames "after" motion
                    # afterStream = io.BytesIO()
                    camera.split_recording('after.h264')

                    # Write the BUF_LEN seconds "before" motion to disk as well
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
                            # split back to the circular stream
                            camera.split_recording(stream)
                            # write the afterStream
                            #write_video(afterStream, BUF_IO)
                            # calculate the length of the video
                            jEvent['length'] = int(time.time()) - jEvent['time_stamp']
                            # log it
                            logItToNodeRed(jEvent) 
                            print "run MP4Box to concat"
                            break

        finally:
            camera.stop_recording()


finally:
    print "Cleaning up...";
    GPIO.cleanup;
    exit();
