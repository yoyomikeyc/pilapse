"""Time lapse photography server"""
import sys
import threading
from datetime import datetime, timedelta
from time import sleep
import pickle
import os
from picamera import PiCamera, PiCameraRuntimeError

from db_model import create_tables, Settings, States, Sessions

from power import disable_power_options, restore_power_options
from utils import create_dir, file_exists, run_cmd
from video import gif_worker
from image_capture import set_camera_options, form_image_abs_fn, extract_from_abs_fn
import requests

# [ ] enforce threads not stepping on eachother or make it ok to miss a deadline
# [ ] Proximity snsor
# [ ] Led light for recording

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
STATE_DB_FN = "pilapse.db"

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







        
def delete_old_images(curr_image_num):
    for fileh in statedb['to_delete']:
        image_num = extract_from_abs_fn(fileh)
        if image_num is None:
            print("filename %s is invalid.  Could not delete" % fileh)
            continue
        # For an image to be "old" and no longer needed we need to possibly consider:
        # 1) its index is greater than a batch size away and thus it has already been added to a segment video.
        # 2) It is not contained in the list of files still to be backed up
        seg_size = Settings.get_value_by_key('encoder_video_frames_per_segment')
        old_enough = image_num < (curr_image_num - 2*seg_size)
        backed_up = fileh not in statedb['to_backup']
        ok_to_delete = True
        if Settings.get_value_by_key('backup_enable'):
            ok_to_delete = ok_to_delete and backed_up
        video_create = Settings.get_value_by_key('encoder_video_create')
        create_gif = Settings.get_value_by_key('encoder_gif_create')
        need_full_segment = video_create or create_gif
        if need_full_segment:
            ok_to_delete = ok_to_delete and old_enough
        if ok_to_delete:
            cmd = "rm -f %s" % fileh
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

    # backup all files 
    overall_success = True
    new_backup_list = []
    for filename in statedb['to_backup']:
        #cmd = "scp %s %s" % (file, dest)
        # make this run command silent so that in cases whhen the server is down we dont spam the log indefinitely
        #success = run_cmd(cmd, silent=(not overall_success))
        try:
            success=True
            try:
                files = {'file': (os.path.basename(filename), open(filename, 'rb'))}
                response = requests.post('http://%s:5001/upload' % server_details['hostname'], files=files)
                if response.status_code != 200:
                    success=False
                    print("Error POSTing file to %s.  Returned %d" % (server_details['hostname'],  response.status_code))
            except requests.exceptions.ConnectionError:
                print("Server down?")
        except FileNotFoundError:
            print("Error, file '%s' not found and thus unable to delete." % filename)
            # Set as successful so we dont keep trying to delete a file that isnt there.
            success= True
            
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
        
    if not overall_success:
        print("Failed copying one or more images to %s!" %server_details['hostname'])
    return overall_success




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
        cnt += 1
    return last_capture_time


def capture_loop():
    # Get all variables incase they change mid capture/encoding
    image_path = Settings.get_value_by_key('capture_image_path')
    video_path = Settings.get_value_by_key('encoder_video_path')        
    video_fn = Settings.get_value_by_key('encoder_video_output_filename')
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
                #args = (image_path, video_path, seg_start_image_num, seg_num, seg_size, frame_rate, profile, preset)
                #threading.Thread(target=video_worker, args=args).start()
            
                payload = {
                    'starting_image':seg_start_image_num,
                    'num':seg_size,
                    'video_fn':video_fn,
                    'preset':preset,
                    'profile':profile,
                    'frame_rate': frame_rate,
                }
                try:
                    r = requests.post('http://localhost:5001/encode', json=payload)
                    if r.status_code != 200:
                        print("HTTP request returned %d" % r.status_code)
                        print(r.json())
                except requests.exceptions.ConnectionError:
                    print("Connection error.  Server down?")
                    
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

    




def terminate(ret):
    print('\nTime-lapse capture process cancelled.\n')
    save_statedb()
    sys.exit(ret)




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
        run_cmd('echo Timelapse capture process started')


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

    
                                    
