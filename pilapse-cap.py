"""Time lapse photography server"""
import errno
import os
import sys
import threading
from datetime import datetime, timedelta
from time import sleep
import pickle
import glob
import re
from pathlib import Path

import config
from picamera import PiCamera, PiCameraRuntimeError

from message import Message

#######
# (Life Rate)    x      (Reduction factor)      = (Slowed Rate)
# (24frames/1s)  x  (1s/10min)  x  (1min/60s)   = (0.04 frame/s)
#
#  Delay = 1 / (24 / (1 / 600)) = 25s
#

# TODO
#
# [.] trigger via app
# [.] interval divisor = only use (pictures mod divisor == 0)
# [x] remove old segments
# [x] http server
# [X] pylint
# [ ] ssh keys for easy scp
# [ ] while balance
# [ ] enforce threads not stepping on eachother or make it ok to miss a deadline
# [ ] Proximity snsor
# [ ] Led light for recording
# [X] Package sensor
# [X] make service
# [ ] back up or SCP timelapse.mp4 so it is never lost

##############
# Constants
##############

SYSTEM_LOG = "pilapse-system.log"

# How many old segments to keep around before deleting
SEGMENT_DELETION_DELAY = 10

# Number of seconds to sleep inbetween polling for changes from the controlling www API
POLL_PERIOD = 0.2
class AbortCapture(Exception):
    pass

##################################################################################
#
# Functions
#
##################################################################################


def create_dir(dir):
    try:
        os.makedirs(dir)
    except OSError as e:
        if e.errno != errno.EEXIST:
            raise

def disable_power_options():
    global camera
    # disable hdmi
    if config['disable_hdmi']:
        cmd = "/usr/bin/tvservice -o"
        run_cmd(cmd)
        
    # Disabling LEDs can save about 5mA per LED
    # https://www.jeffgeerling.com/blogs/jeff-geerling/raspberry-pi-zero-conserve-energy
    if config['disable_pi_leds']:
        # PiZero Only
        # https://www.jeffgeerling.com/blogs/jeff-geerling/controlling-pwr-act-leds-raspberry-pi

        # Turn off the Pi Zero ACT LED.
        cmd = "echo 1 | sudo tee /sys/class/leds/led0/brightness"
        run_cmd(cmd)
        
    if config['disable_camera_led']:
        # Turn the camera's LED off
        camera.led = False
        
def enable_power_options():
    global camera
    
    # enable hdmi
    if config['disable_hdmi']:
        cmd = "/usr/bin/tvservice -p"
        run_cmd(cmd)
        
    # Disabling LEDs can save about 5mA per LED
    # https://www.jeffgeerling.com/blogs/jeff-geerling/raspberry-pi-zero-conserve-energy
    if config['disable_pi_leds']:
        # PiZero Only
        # Set the Pi Zero ACT LED trigger to 'none'.
        cmd = "echo none | sudo tee /sys/class/leds/led0/trigger"
        run_cmd(cmd)

    if config['disable_camera_led']:
        # Turn the camera's LED on
        camera.led = True

        



def set_camera_options(camera):
    # Set camera resolution.
    if config['resolution']:
        camera.resolution = (
            config['resolution']['width'],
            config['resolution']['height']
        )

    # Set ISO.
    if config['iso']:
        camera.iso = config['iso']

    # Set shutter speed.
    if config['shutter_speed']:
        camera.shutter_speed = config['shutter_speed']
        # Sleep to allow the shutter speed to take effect correctly.
        sleep(1)
        camera.exposure_mode = 'off'

    # Set white balance.
    if config['white_balance']:
        camera.awb_mode = 'off'
        camera.awb_gains = (
            config['white_balance']['red_gain'],
            config['white_balance']['blue_gain']
        )

    # Set camera rotation
    if config['rotation']:
        camera.rotation = config['rotation']

    return camera


def batch_capture(path, image_num, batch_size, last_capture):
    """Capture up to batch_size images at interval seconds apart into path with filenames indexed starting at image_num"""
    cnt = image_num % config['segment_size']
    
    # Init time markers
    interval = timedelta(seconds=config['interval'])
    if last_capture is None:
        last_capture = datetime.now()
    next_capture = last_capture + interval

    # Capture images
    while cnt < batch_size:
        capture = mailman.get_capture_status()
        if not capture:
            raise AbortCapture
                
        now = datetime.now()
        #If not time yet, sleep and check again
        if now < next_capture:
            sleep(POLL_PERIOD)
            continue
        msg = "Capturing image #%d    Time: %s     Delta: %s" % \
              (image_num, str(now), str(now-last_capture))
        print(msg)
        sys.stdout.flush()
            
        # Capture a picture.
        image_str = 'img{0:07d}.jpg'.format(image_num)
        try: 
            camera.capture(path + '/' +image_str)
        except PiCameraRuntimeError:
            print("ERROR: Timed out waiting for capture to end!")
            continue
        # Book keeping
        last_capture = next_capture
        next_capture = last_capture + interval
        image_num += 1
        cnt+=1
    return (last_capture, image_num)

#

def gen_final_video():
    concat_fn= '%s/filelist-%s.txt' % (config['video_path'], datetime.now().strftime('%Y-%m-%d_%H-%M-%S'))
    all_images =  get_all_images(config['image_path'], descending=False)
    with open(concat_fn, 'w') as f:
        for i in all_images:
            f.write("file '%s'\n" % i)
    input_fns = "-f concat -safe 0 -i %s" % (concat_fn)
    output_fn = "%s/%s.mp4" % (config['video_path'], "final")
    success = True
    success &= create_video(input_fns, output_fn, None, frame_rate=None, profile=config['hq_video_profile'], preset=config['hq_video_preset'])

# Declare worker
def video_worker(seg_num, image_num):
    input_fns = "-i %s/%s/img%%07d.jpg" % (image_dir, segment_name(seg_num))
    output_fn = "%s/%s.mp4" % (config['video_path'], segment_name(seg_num))
    
    success = True
    success &= create_video(input_fns, output_fn, image_num, frame_rate=config['frame_rate'], profile=config['video_profile'], preset=config['video_preset'])
    if success:
        success &= append_video_segment(seg_num)
        # If successful, delete old segment
        if success:
            video_cleanup(seg_num)
            return


def gif_worker(seg_num, image_num):
    success = True
    success &= create_gif_segment(seg_num, image_num)
    if success:
        return

def capture_loop(image_dir, seg_num, image_num):
    # Init
    mailman = Message()
    global camera

    # Init camera
    set_camera_options(camera)
   
    last_capture = None
    
    while True:
        try:
            print("============================================ Segment # %d ============================================" % (seg_num))
            seg_str = segment_name(seg_num)
            full_path = image_dir + '/' + seg_str
            create_dir(full_path)

            # Capture n images
            (last_capture, next_image_num) = batch_capture(full_path, image_num, config['segment_size'], last_capture) 

            if config['create_gif']:
                # Start thread to run concurrently
                t = threading.Thread(target=gif_worker, args=(seg_num, image_num)).start()

            # Create video segment and append to prior segments.
            if config['create_video']:
                # Start thread to run concurrently
                t = threading.Thread(target=video_worker, args=(seg_num, image_num)).start()
            # Increment segment number
            seg_num += 1
            image_num = next_image_num
            
        except (AbortCapture):
            camera.close()
            return
        except (KeyboardInterrupt, SystemExit) as e:
            camera.close()
            raise e


def terminate(ret):
    print('\nTime-lapse capture process cancelled.\n')
    enable_power_options()
    sys.exit(ret)

REDIRECT_ALL_OUTPUT = ">> %s 2>&1" % SYSTEM_LOG
NO_BUFFERING = "stdbuf -o0 "

def segment_name(seg_num):
    """Forms segment identiifer"""
    return 'seg{0:07d}'.format(seg_num)
        
def run_cmd(cmd, verbose=False, msg=None):
    """Run a command at shell prompt and optionally time/print messages"""
    # Put timestamp in log
    time_cmd = NO_BUFFERING
    time_cmd += ("echo -------------------- $(date) -------------------- %s" % REDIRECT_ALL_OUTPUT)
    os.system(time_cmd)
    # Put command in log
    echo_cmd = NO_BUFFERING
    echo_cmd += ("echo %s %s" % (cmd, REDIRECT_ALL_OUTPUT))
    os.system(echo_cmd)
    # Redirect output of command to log
    final_cmd = NO_BUFFERING
    final_cmd += ("%s %s" % (cmd, REDIRECT_ALL_OUTPUT))
    # Run command
    INDENT = "\t\t\t\t\t\t\t\t\t\t\t\t"
    start_time = datetime.now()
    if verbose:
        if msg:
            print(INDENT+msg)
        else:
            print(INDENT+cmd)
    ret_value = os.system(final_cmd)
    end_time = datetime.now()
    duration = end_time - start_time
    if verbose:
        mystr = "-->  Duration : %s seconds" % str(duration.seconds)
        print(INDENT+mystr)
    if ret_value != 0:
        print("Command Failed! : "+cmd)
    # Return True of success. (unlike unix)
    return not ret_value


def get_all_images(path, descending=True):
    """returns list of all images in path, in descending order"""
    # Get descending sorted list of all images in images folder
    all_images = glob.glob(path+"/*/seg*/img*.jpg", recursive=False)
    all_images.sort(reverse=descending)
    return all_images


#concat_fn= 'filelist-%s.txt' % datetime.now().strftime('%Y-%m-%d_%H-%M-%S')


#input_fns = "%s/%s/img%%07d.jpg" % (image_dir, segment_name(seg_num))
#output_fn = "%s/%s.mp4" % (config['video_path'], segment_name(seg_num))
#config['frame_rate'], profile=config['video_profile'], preset=config['video_preset']):
# Create segment video
def create_video(input_fns, output_fn, start_img=0, frame_rate=24, profile="baseline", preset="medium"):
    # Helpful Link:
    #
    # https://trac.ffmpeg.org/wiki/Encode/H.264#Listpresetsandtunes
    #
    # Use HW encoding with the h264_omx codec: -c:v h264_omx
    # Use Baseline profile to omit B frames and reduce cpu usage.   -profile:v baseline
    if start_img is None:
        start_number_option = ""
    else:
        start_number_option = "-start_number %s" % str(start_img)

    if frame_rate is None:
        frame_rate_option = ""
    else: 
        frame_rate_option = "-framerate %s" % str(frame_rate)

    # Slightly lower the priorty of the encoding process, in part to allow the API process
    # improved response time.  I would assume flask really just blocking on requests, so hopefully
    # the true effect of this is improving latency of the control commands and ensure the
    # system remains usable.
    niceness="nice -n 2 "
    cmd = 'avconv -y %s %s %s -profile:v %s -preset %s -vf format=yuv420p %s' % \
          (frame_rate_option, start_number_option, input_fns, profile, preset, output_fn)
    cmd = niceness+cmd
    #cmd = 'avconv -y -framerate %s -start_number %s -i %s/%s/img%%07d.jpg  -c:v h264_omx -vf format=yuv420p %s/%s' % \
    #      (str(frame_rate), str(start_img), image_dir, seg_str, config['video_path'], fn)
    success = run_cmd(cmd, verbose=True, msg="-->  encoding_frames() begun!")
    return success
                    
# Create segment video    
def create_video_segment(seg_num, start_img):
    #print("Creating video segment")
    seg_str = segment_name(seg_num)
    fn = '%s.mp4' % seg_str
    frame_rate = config['frame_rate']
    # Helpful Link:
    #
    # https://trac.ffmpeg.org/wiki/Encode/H.264#Listpresetsandtunes
    #
    # Use HW encoding with the h264_omx codec: -c:v h264_omx
    # Use Baseline profile to omit B frames and reduce cpu usage.   -profile:v baseline
    cmd = 'avconv -y -framerate %s -start_number %s -i %s/%s/img%%07d.jpg -profile:v %s  -preset %s -vf format=yuv420p %s/%s' % \
          (str(frame_rate), str(start_img), image_dir, seg_str, config['video_profile'], config['video_preset'], config['video_path'], fn)
    #cmd = 'avconv -y -framerate %s -start_number %s -i %s/%s/img%%07d.jpg  -c:v h264_omx -vf format=yuv420p %s/%s' % \
    #      (str(frame_rate), str(start_img), image_dir, seg_str, config['video_path'], fn)
    success = run_cmd(cmd, verbose=True, msg="-->  encoding_frames() begun!")
    return success

def create_gif_segment(seg_num, start_img):
    # Create an animated gif (Requires ImageMagick).
    #    print('\nCreating animated gif.\n')
    seg_str = segment_name(seg_num)
    fn = '%s.gif' % seg_str
    cmd = 'convert -delay 10 -loop 0 %s/%s/img*.jpg %s/%s' % (image_dir, seg_str, config['gif_path'], fn)                
    success = run_cmd(cmd, verbose=True, msg="-->  encoding_frames() begun!")             

    
def append_video_segment(seg_num):
    #print("Appending segment")
    # Form absolute path for segment file
    seg_str = segment_name(seg_num)
    new_seg_fn = '%s.mp4' % seg_str
    abs_new_seg_fn = config['video_path']+'/'+new_seg_fn
    # Form absolute path for input video
    ivideo_fn = config['output_filename']
    abs_ivideo_fn = config['video_path']+'/'+ivideo_fn
    # Form absolute path for output video
    ovideo_fn = 'tmp.mp4'
    abs_ovideo_fn = config['video_path']+'/'+ovideo_fn

    # Append new video to old
    if seg_num == 0:
        cmd = 'cp %s %s' % (abs_new_seg_fn, abs_ovideo_fn)
    else:
        # Create file with list of files to concat
        concat_fn = config['video_path']+'/'+"concat.txt"
        with open(concat_fn,"w") as f:
            f.write("file %s\nfile %s\n" % (abs_ivideo_fn, abs_new_seg_fn))
            f.close()
        #cmd = 'avconv -i \"concat:%s|%s\" -c copy %s' % (abs_ivideo_fn, abs_new_seg_fn, abs_ovideo_fn)
        cmd = 'avconv -f concat -safe 0  -i %s -c copy %s' % (concat_fn, abs_ovideo_fn)
    success = run_cmd(cmd)
    if not success:
        print("Encoding of %s failed!" % abs_new_seg_fn)
        return success
    # If timelapse mpeg exists, rename as a backup
    timelapse_mpeg = Path(abs_ivideo_fn)
    if timelapse_mpeg.is_file():
         cmd = 'mv -f %s %s' % (abs_ivideo_fn, abs_ivideo_fn+".backup")
         success = run_cmd(cmd)
    # Rename tmp as new full timelapse mpeg
    # If tmp doesnt exist, its possible the encoding failed or the user aborted 
    tmp = Path(abs_ovideo_fn)
    if tmp.is_file():
        # file exists, so delete old copy and rename tmp to new copy
        cmd = 'mv %s %s' % (abs_ovideo_fn, abs_ivideo_fn)
        success = run_cmd(cmd)
    else:
        success = False
    return success

        
def video_cleanup(seg_num):
    """Remove old artifacts of the encoding / capture process"""
    # Remove old segments
    seg_to_delete = seg_num - SEGMENT_DELETION_DELAY
    seg_str = segment_name(seg_num)
    old_seg_fn = '%s.mp4' % seg_str
    abs_old_seg_fn = config['video_path']+'/' + old_seg_fn
    success = False
    if seg_to_delete > 0:
        cmd = 'rm -f %s' % (abs_old_seg_fn)
        success = run_cmd(cmd)
    else:
        success = True
    return success

###################
# Read config file
###################

# Log that process was started
cmd = 'echo Timelapse capture process started' 
run_cmd(cmd)

config = config.load_config()


###################
# init
###################

# Start up the camera.
camera = PiCamera()

disable_power_options()

            
# Create directory based on current timestamp.
create_dir(config['image_path'])

if config['create_video']:
    create_dir(config['video_path'])

if config['create_gif']:
    create_dir(config['gif_path'])

###############################
# Determine last image/segment
################################

seg_num  = 0
image_num = 0

# Get descending sorted list of all images in images folder
all_images =  get_all_images(config['image_path'])
                            
# Extract next image number and next segment number
if all_images:
    # Get all segments in most recent series
    last_image = all_images[0]
    m = re.match(".*/seg(\d{7})/img(\d{7})\.jpg$", last_image)
    seg_num = int(m.group(1))+1 
    image_num = int(m.group(2))+1
    # if next image is the first in the segment then increment the segment number because
    # the prior segment is complete.
    #if (image_num % config['segment_size']) == 0:
    #    seg_num += 1
else:
    print("No prior images found.")

##################################
# Create directory for new series
##################################

# Append subdir to image path and create
series_name = 'series-' + datetime.now().strftime('%Y-%m-%d_%H-%M-%S')
image_dir = os.path.join(
    config['image_path'],
    series_name
)
create_dir(image_dir)



######################
# Capture
######################

# Kick off the capture process.
mailman = Message()
capture = mailman.get_capture_status()

print("------------------------------------------------------------------------------------")
print("Start image     : #%d" % image_num)
print("Start segment   : #%d" % seg_num)
print("Image directory : %s" % image_dir)
print("Recording       : %s" % capture)
print("------------------------------------------------------------------------------------")
print("\n")


#gen_final_video()
#sys.exit(1)

try:
    while True:
        capture = mailman.get_capture_status()
        if capture:
            capture_loop(image_dir, seg_num, image_num)
        sleep(POLL_PERIOD)
except (KeyboardInterrupt, SystemExit):
    terminate(1)

                                    
