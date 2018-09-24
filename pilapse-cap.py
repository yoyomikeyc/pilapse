"""Time lapse photography server"""
import errno
import os
import subprocess
import sys
import threading
from datetime import datetime, timedelta
from time import sleep
import pickle
import glob
import re
from pathlib import Path
from paramiko import SSHClient
from scp import SCPClient
import paramiko

from picamera import PiCamera, PiCameraRuntimeError

from db_model import create_tables, Settings, States, Sessions
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
# [X] ssh keys for easy scp
# [ ] while balance
# [ ] enforce threads not stepping on eachother or make it ok to miss a deadline
# [ ] Proximity snsor
# [ ] Led light for recording
# [X] Package sensor
# [X] make service
# [X] back up or SCP timelapse.mp4 so it is never lost
# [ ] SMS notification

##############
# Constants
##############

SYSTEM_LOG = "pilapse-system.log"

# Number of seconds to sleep inbetween polling for changes from the controlling www API
POLL_PERIOD = 0.2
class AbortCapture(Exception):
    pass

##############
# State related
##############
STATE_DB_FN="pilapse.db"

statedb = {'to_delete':[],'to_backup':[]}

def load_statedb():
    global statedb

    if file_exists(STATE_DB_FN):
        # open the file for reading
        f = open(STATE_DB_FN,'rb')
        statedb = pickle.load(f)
        f.close()
    return statedb

def save_statedb():
    global statedb

    # open the file for writing
    f = open(STATE_DB_FN,'wb')
    pickle.dump(statedb, f)

##################################################################################
#
# Functions
#
##################################################################################


def create_dir(directory):
    try:
        os.makedirs(directory)
    except OSError as e:
        if e.errno != errno.EEXIST:
            raise

def file_exists(fn):
    f = Path(fn)
    return f.is_file()


def disable_power_options(camera):
    # disable hdmi
    if Settings.get_value_by_key('power_disable_hdmi'):
        cmd = "/usr/bin/tvservice -o"
        run_cmd(cmd)
        
    # Disabling LEDs can save about 5mA per LED
    # https://www.jeffgeerling.com/blogs/jeff-geerling/raspberry-pi-zero-conserve-energy
    if Settings.get_value_by_key('power_disable_pi_leds'):
        # PiZero Only
        # https://www.jeffgeerling.com/blogs/jeff-geerling/controlling-pwr-act-leds-raspberry-pi

        # Set the Pi Zero ACT LED trigger to 'none'.
        #cmd1 = "echo none | sudo tee /sys/class/leds/led0/trigger"
        #run_cmd(cmd1)
        
        # Turn off the Pi Zero ACT LED.   
        #cmd2 = "echo 1 | (sudo tee /sys/class/leds/led0/brightness)"
        #run_cmd(cmd2)
        #with open("/sys/class/leds/led0/brightness","w") as f:
        #    f.write('1\n')
        cmd="echo 'Pi Zero ACT LED turned off.'"
        run_cmd(cmd)

    if Settings.get_value_by_key('power_disable_camera_led'):
        # Turn the camera's LED off
        camera.led = False
        cmd = "echo 'Camera LED disabled.'"
        run_cmd(cmd)
        
def restore_power_options(camera):
    
    # enable hdmi
    if Settings.get_value_by_key('power_disable_hdmi'):
        cmd = "/usr/bin/tvservice -p"
        run_cmd(cmd)
        
    # Disabling LEDs can save about 5mA per LED
    # https://www.jeffgeerling.com/blogs/jeff-geerling/raspberry-pi-zero-conserve-energy
    if Settings.get_value_by_key('power_disable_pi_leds'):
        # PiZero Only
        # Set the Pi Zero ACT LED trigger to 'none'.
        #cmd1 = "echo none | sudo tee /sys/class/leds/led0/trigger"
        #run_cmd(cmd)

        # Turn on the Pi Zero ACT LED.   
        #cmd2 = "echo 0 | sudo tee /sys/class/leds/led0/brightness"
        #run_cmd(cmd2)
        #with open("/sys/class/leds/led0/brightness","w") as f:
        #f.write('0\n')
        cmd = "echo 'Pi Zero ACT LED turned on.'"
        run_cmd(cmd)

    if Settings.get_value_by_key('power_disable_camera_led'):
        # Turn the camera's LED on
        camera.led = True
        cmd = "echo 'Camera LED enabled.'"
        run_cmd(cmd)



def set_camera_options(camera):
    # Set camera resolution.
    resolution = Settings.get_value_by_key('capture_resolution')
    if resolution:
        camera.resolution = (
            resolution['width'],
            resolution['height']
        )

    # Set ISO.
    iso =  Settings.get_value_by_key('capture_iso')
    if iso:
        camera.iso = iso

    # Set shutter speed.
    shutter_speed = Settings.get_value_by_key('capture_shutter_speed')
    if shutter_speed:
        camera.shutter_speed = shutter_speed
        # Sleep to allow the shutter speed to take effect correctly.
        sleep(1)
        camera.exposure_mode = 'off'

    # Set white balance.
    white_balance =  Settings.get_value_by_key('capture_white_balance')
    if white_balance:
        camera.awb_mode = 'off'
        camera.awb_gains = (
            white_balance['red_gain'],
            white_balance['blue_gain']
        )

    # Set camera rotation
    rotation = Settings.get_value_by_key('capture_rotation')
    if rotation:
        camera.rotation = rotation

    return camera


def batch_capture(camera, path, batch_size, last_capture_time, interval, backup, cleanup):
    """Capture up to batch_size images at interval seconds apart into path with filenames indexed starting at image_num"""
    image_num = States.get_image_num()
    cnt = image_num % batch_size
    #TODO: Shouldbt be loading settings in here
    
    # Init time markers
    if last_capture_time is None:
        last_capture_time = datetime.now()

    delta = timedelta(seconds=interval)
    next_capture_time = last_capture_time + delta

    # Capture images
    while cnt < batch_size:
        if not Settings.get_value_by_key('capture_enable'):
            raise AbortCapture
                
        now = datetime.now()
        #If not time yet, sleep and check again
        if now < next_capture_time:
            sleep(POLL_PERIOD)
            continue
        msg = "Capturing image #%d    Time: %s     Delta: %s" % \
              (image_num, str(now), str(now-last_capture_time))
        print(msg)
        sys.stdout.flush()
            
        # Capture a picture.
        image_abs_fn = form_image_abs_fn(path, image_num)
        
        try: 
            camera.capture(image_abs_fn)
        except PiCameraRuntimeError:
            print("ERROR: Timed out waiting for capture to end!")
            continue

        # backup image to server if specified
        if backup:
            backup_image(image_abs_fn)
                
        # delete any old image(s)
        if cleanup:
            delete_old_images(image_num)

        # Book keeping
        last_capture_time = now
        next_capture_time = last_capture_time + delta
        image_num += 1
        States.set_image_num(image_num)
        cnt+=1
    return last_capture_time
#

def gen_final_video():
    concat_fn= '%s/filelist-%s.txt' % (Settings.get_value_by_key('capture_video_path'), datetime.now().strftime('%Y-%m-%d_%H-%M-%S'))
    all_images =  get_all_images(Settings.get_value_by_key('capture_image_path'), descending=False)
    with open(concat_fn, 'w') as f:
        for i in all_images:
            f.write("file '%s'\n" % i)
    input_fns = "-f concat -safe 0 -i %s" % (concat_fn)
    output_fn = "%s/%s.mp4" % (Settings.get_value_by_key('capture_image_path'), "final")
    hq_profile = Settings.get_value_by_key('encoder_hq_video_profile')
    hq_preset = Settings.get_value_by_key('encoder_hq_video_preset')
    success = True
    success &= create_video(input_fns, output_fn, None, frame_rate=None, profile=hq_profile, preset=hq_preset)

def create_image_list(image_path, video_path, image_num, seg_num, seg_size):
    seg_fn = "%s/%s.txt" % (video_path, form_segment_name(seg_num))
    with open(seg_fn, 'w') as f:
        for i in range(image_num, image_num+seg_size):
            f.write("file '%s'\n" % form_image_abs_fn(image_path, i))
    return seg_fn

def video_cleanup(video_path, seg_num):
    """Remove old artifacts of the encoding / capture process"""
    extensions = ['mp4', 'txt']
    success = True
    for ext in extensions:
        abs_fn = "%s/%s.%s" % (video_path, form_segment_name(seg_num), ext)
        cmd = 'rm -f %s' % abs_fn
        success &= run_cmd(cmd)
    return success

def create_video(input_fn, output_fn, start_img=0, frame_rate=24, profile="baseline", preset="medium"):
    """Create segment video"""
    # Helpful Link:
    #
    # https://trac.ffmpeg.org/wiki/Encode/H.264#Listpresetsandtunes
    #
    # Use HW encoding with the h264_omx codec: -c:v h264_omx
    # Use Baseline profile to omit B frames and reduce cpu usage.   -profile:v baseline

    if frame_rate is None:
        frame_rate_option = ""
    else: 
        frame_rate_option = "-r %s" % str(frame_rate)

    # Slightly lower the priorty of the encoding process, in part to allow the API process
    # improved response time.  I would assume flask really just blocking on requests, so hopefully
    # the true effect of this is improving latency of the control commands and ensure the
    # system remains usable.
    niceness="nice -n 2 "
    # -y : overwrite output file
    cmd = 'avconv -y %s -f concat -safe 0  -i %s -profile:v %s -preset %s -vf format=yuv420p %s' % \
          (frame_rate_option, input_fn, profile, preset, output_fn)
    cmd = niceness+cmd
    success = run_cmd(cmd, verbose=True, msg="-->  encoding_frames() begun!")
    return success

# Declare worker
def video_worker(image_path, video_path, image_num, seg_num, seg_size, frame_rate, profile, preset):
    try:
        input_fn = create_image_list(image_path, video_path, image_num, seg_num, seg_size)
        output_fn = "%s/%s.mp4" % (video_path, form_segment_name(seg_num))
    
        success = True
        success &= create_video(input_fn, output_fn, image_num, frame_rate=frame_rate, profile=profile, preset=preset)
        if success:
            success &= append_video_segment(seg_num)
            # If successful, delete old segment
            if success:
                video_cleanup(video_path, seg_num)
                return
    except (KeyboardInterrupt, SystemExit):
        terminate(1)

def gif_worker(image_path, gif_path, image_num, seg_num):
    try:
        success = True
        success &= create_gif_segment(seg_num, image_num)
        if success:
            return
    except (KeyboardInterrupt, SystemExit):
        terminate(1)
        
def capture_loop():
    # Get all variables incase they change mid capture/encoding
    image_path = Settings.get_value_by_key('capture_image_path')
    video_path = Settings.get_value_by_key('encoder_video_path')        
    gif_path = Settings.get_value_by_key('encoder_gif_path')
    frame_rate = Settings.get_value_by_key('encoder_video_frame_rate')
    profile = Settings.get_value_by_key('encoder_video_profile')
    preset = Settings.get_value_by_key('encoder_video_preset')
    encode_gif = Settings.get_value_by_key('encoder_gif_create')
    encode_video = Settings.get_value_by_key('encoder_video_create')
    seg_size = Settings.get_value_by_key('encoder_video_frames_per_segment')
    interval = Settings.get_value_by_key('capture_interval')
    backup = Settings.get_value_by_key('backup_enable')
    cleanup = Settings.get_value_by_key('backup_enable_image_cleanup')

            
    # Start up the camera.
    camera = PiCamera()
    # Init camera
    set_camera_options(camera)
    # Lower power consumption
    disable_power_options(camera)
    
    last_capture_time = None

    # Create session in db
    Sessions.start_session()

    while True:
        try:
            seg_start_image_num = States.get_image_num()
            seg_num = int(seg_start_image_num / seg_size)
            print("========================================== Segment # %d ==========================================" % \
                  (seg_num))

            # Capture n images
            last_capture_time = batch_capture(camera, image_path, seg_size, last_capture_time, interval, backup, cleanup) 

            if encode_gif:
                # Start thread to run concurrently
                threading.Thread(target=gif_worker, args=(image_path, gif_path, seg_start_image_num, seg_num)).start()

            # Create video segment and append to prior segments.
            if encode_video:
                # Start thread to run concurrently
                args = (image_path, video_path, seg_start_image_num, seg_num, seg_size, frame_rate, profile, preset)
                threading.Thread(target=video_worker, args=args).start()
                
            # Check if reinit is necessary
            if States.get_value_by_key('reinit'):
                raise AbortCapture
        except (AbortCapture):
            restore_power_options(camera)
            camera.close()
            return
        except (KeyboardInterrupt, SystemExit) as e:
            restore_power_options(camera)
            camera.close()
            raise e

def delete_old_images(curr_image_num):
    for file in statedb['to_delete']:
        image_num = extract_from_abs_fn(file)
        if image_num is None:
            print("filename %s is invalid.  Could not delete" % file)
            continue
        # For an image to be "old" and no longer needed we need to possibly consider:
        # 1) its index is greater than a batch size away and thus it has already been added to a segment video.
        # 2) It is not contained in the list of files still to be backed up
        seg_size = Settings.get_value_by_key('encoder_video_frames_per_segment')
        old_enough = image_num < (curr_image_num - 2*seg_size)
        backed_up = file not in statedb['to_backup']
        ok_to_delete = True
        if Settings.get_value_by_key('backup_enable'):
            ok_to_delete = ok_to_delete and backed_up
        video_create = Settings.get_value_by_key('encoder_video_create')
        create_gif = Settings.get_value_by_key('encoder_gif_create')
        need_full_segment = video_create or create_gif
        if need_full_segment:
            ok_to_delete = ok_to_delete and old_enough
        if ok_to_delete:
            cmd = "rm -f %s" % file
            success = run_cmd(cmd)
            if success:
                statedb['to_delete'].pop(0)
        # Since the list is in ascending order, once we find a file that is too new, we are done.
        if need_full_segment:
            if not old_enough:
                break
        # If we arent required o have a full segment then we cant stop early



def backup_image(fn):
    # Generate file to backup and store to list of pending files to backup.
    statedb['to_backup'].append(fn)
    # Determine if we have enough files to make it worth backing up.
    if len(statedb['to_backup']) <  Settings.get_value_by_key('backup_size'):
        return True
    
    # hostname destination
    server_details = Settings.get_value_by_key('backup_server')

    ssh = SSHClient()
    ssh.load_system_host_keys()
    ssh.connect(server_details['hostname'])

    # SCPCLient takes a paramiko transport as an argument
    scp = SCPClient(ssh.get_transport())

    # backup all files 
    overall_success = True
    new_backup_list = []
    for filename in statedb['to_backup']:
        #cmd = "scp %s %s" % (file, dest)
        # make this run command silent so that in cases whhen the server is down we dont spam the log indefinitely
        #success = run_cmd(cmd, silent=(not overall_success))
        try:
            success=True
            scp.put(filename, remote_path=server_details['image_path'])
        except FileNotFoundError:
            print("Error, file '%s' not found and thus enable to delete." % file)
            # Set as successful so we dont keep trying to delete a file that isnt there.
            success= True
        except paramiko.ssh_exception.SSHException:
            print("paramiko.ssh_exception.SSHException: Channel closed?")
            success= False
            
        if success:
            # denote file as successfully backed up
            #statedb['to_backup'].remove(file)
            # Denote that image should be removed
            if Settings.get_value_by_key('backup_enable_image_cleanup'):
                statedb['to_delete'].append(filename)
        else:
            new_backup_list.append(filename)
        overall_success &= success
        statedb['to_backup']=new_backup_list
    scp.close()
        
    if not overall_success:
        print("Failed copying one or more images to %s!" %server_details['hostname'])
    return overall_success

def terminate(ret):
    print('\nTime-lapse capture process cancelled.\n')
    save_statedb()
    sys.exit(ret)

REDIRECT_TO_LOG = ">> %s 2>&1" % SYSTEM_LOG
REDIRECT_TO_NULL= ">> /dev/null 2>&1" 
NO_BUFFERING = "stdbuf -o0 "

        
def run_cmd(cmd, verbose=False, msg=None, silent=False):
    """Run a command at shell prompt and optionally time/print messages"""
    def myprint(s):
        if not silent:
            print(s)
    if silent:
        redirect = REDIRECT_TO_NULL
    else:
        redirect = REDIRECT_TO_LOG
        
    if not silent:
        # Put timestamp in log
        time_cmd = NO_BUFFERING
        time_cmd += ("echo -------------------- $(date) -------------------- %s" % redirect)
        subprocess.call(time_cmd, shell=True)
        # Put command in log
        echo_cmd = NO_BUFFERING
        echo_cmd += ("echo %s %s" % (cmd, redirect))
        subprocess.call(echo_cmd, shell=True)
    # Redirect output of command to log
    final_cmd = NO_BUFFERING
    final_cmd += ("%s %s" % (cmd, redirect))
    # Run command
    INDENT = "\t\t\t\t\t\t\t\t\t\t\t\t"
    start_time = datetime.now()
    if verbose:
        if msg:
            myprint(INDENT+msg)
        else:
            myprint(INDENT+cmd)
    ret_value = subprocess.call(final_cmd, shell=True)
    end_time = datetime.now()
    duration = end_time - start_time
    if verbose:
        mystr = "-->  Duration : %s seconds" % str(duration.seconds)
        myprint(INDENT+mystr)
    if ret_value != 0:
        myprint("Command Failed! : "+cmd)
    # Return True of success. (unlike unix)
    success = not ret_value
    return success


def get_all_images(path, descending=True):
    """returns list of all images in path, in descending order"""
    # Get descending sorted list of all images in images folder
    all_images = glob.glob(path+"/img*.jpg", recursive=False)
    all_images.sort(reverse=descending)
    return all_images




         

def form_segment_name(seg_num):
    """Forms segment identiifer"""
    return 'seg{0:07d}'.format(seg_num)

def extract_from_abs_fn(abs_fn):
    """Returns tuple containing seg_num and image_num extracted from image filename"""
    m = re.match(r'.*/img(\d{7}).jpg$', abs_fn)
    #datetime.now().strftime('%Y-%m-%d_%H-%M-%S')
 
    if m:
        image_num = int(m.group(1))
        return image_num
    return None

def form_image_fn_pattern():
    #return r"img%07d_%04d-%02d-%02d_%02d-%02d-%02d.jpg"
    return r"img%07d.jpg"

def form_image_fn(image_num):
    #timestamp = now.strftime('%Y-%m-%d_%H-%M-%S')   
    return 'img{0:07d}.jpg'.format(image_num)
    #timestamp = now.strftime('%Y%m%d%H%M%S')   
    #return 'img{0:07d}{1}.jpg'.format(image_num, timestamp)
    
def form_image_abs_fn(path, image_num):
    image_fn = form_image_fn(image_num)
    image_abs_fn = "%s/%s" % (path, image_fn)
    return image_abs_fn


def create_gif_segment(seg_num, start_img):
    # Create an animated gif (Requires ImageMagick).
    #    print('\nCreating animated gif.\n')
    seg_str = form_segment_name(seg_num)
    fn = '%s.gif' % seg_str
    cmd = 'convert -delay 10 -loop 0 %s/%s/img*.jpg %s/%s' % (image_dir, seg_str,Settings.get_value_by_key('encoder_gif_path'), fn)                
    success = run_cmd(cmd, verbose=True, msg="-->  encoding_frames() begun!")             

    
def append_video_segment(seg_num):
    video_path = Settings.get_value_by_key('encoder_video_path')
    #print("Appending segment")
    # Form absolute path for segment file
    seg_str = form_segment_name(seg_num)
    new_seg_fn = '%s.mp4' % seg_str
    abs_new_seg_fn = video_path+'/'+new_seg_fn
    # Form absolute path for input video  
    ivideo_fn = Settings.get_value_by_key('encoder_video_output_filename')
    abs_ivideo_fn = video_path+'/'+ivideo_fn
    # Form absolute path for output video
    ovideo_fn = 'tmp.mp4'
    abs_ovideo_fn = video_path+'/'+ovideo_fn

    # Append new video to old
    if not file_exists(abs_ivideo_fn):
        cmd = 'cp %s %s' % (abs_new_seg_fn, abs_ovideo_fn)
    else:
        # Create file with list of files to concat
        concat_fn = video_path+'/'+"concat.txt"
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
    if file_exists(abs_ovideo_fn):
        # file exists, so delete old copy and rename tmp to new copy
        cmd = 'mv %s %s' % (abs_ovideo_fn, abs_ivideo_fn)
        success = run_cmd(cmd)
    else:
        success = False
    return success



#seg_num  = 0
#image_num = 0

# Get descending sorted list of all images in images folder
#all_images =  get_all_images(Settings.get_value_by_key('capture_image_path'))
                            
# Extract next image number and next segment number
#if all_images:
#    # Get all segments in most recent series
#    last_image = all_images[0]
#    m = re.match(".*/seg(\d{7})/img(\d{7})\.jpg$", last_image)
#    seg_num = int(m.group(1))+1 
#    image_num = int(m.group(2))+1
#else:
#    print("No prior images found.")





########
# Main
########

#gen_final_video()
#sys.exit(1)

if __name__ == '__main__':
    try:

        load_statedb()
        create_tables()

        print("------------------------------------------------------------------------------------")
        print("Start image     : #%d" % States.get_image_num())
        print("Recording       : %s" %  Settings.get_value_by_key('capture_enable'))
        print("------------------------------------------------------------------------------------")
        print("\n")

        ######################
        # Read config & state
        ######################

        # Log that process was started
        run_cmd('echo Timelapse capture process started' )


        while True:
            # Capture if enabled
            if Settings.get_value_by_key('capture_enable'):
        
                # Re init if necessary
                if States.get_value_by_key('reinit'):
                    # Create directories
                    image_path = Settings.get_value_by_key('capture_image_path')
                    create_dir(image_path)
                    if Settings.get_value_by_key('encoder_video_create'):
                        video_path = Settings.get_value_by_key('encoder_video_path')        
                        create_dir(video_path)
                    if Settings.get_value_by_key('encoder_gif_create'):
                        gif_path = Settings.get_value_by_key('encoder_gif_path')
                        create_dir(gif_path)
                    # Denote done reinit
                    States.upsert_kvp('reinit', False, as_type=bool)        
                # Capture
                capture_loop()
            sleep(POLL_PERIOD)
    except (KeyboardInterrupt, SystemExit):
        terminate(1)

    
                                    
