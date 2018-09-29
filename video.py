"""Time lapse  video encoding"""
import subprocess
import sys
import threading
from datetime import datetime, timedelta
import glob
from pathlib import Path


from db_model import  Settings, States, Sessions

from utils import create_dir, file_exists, run_cmd
from image_capture import form_image_abs_fn, form_segment_name, create_image_list
##################################################################################
#
# Video encoding related
#
##################################################################################


#######################
# H.264 Encoding
#######################

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
    success &= create_video(input_fns, output_fn, frame_rate=None, profile=hq_profile, preset=hq_preset)


def create_video(image_list_fn, output_fn, frame_rate=24, profile="baseline", preset="medium"):
    """Create video output_fn from list of images specified in image_list_fn"""
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
          (frame_rate_option, image_list_fn, profile, preset, output_fn)
    cmd = niceness+cmd
    success = run_cmd(cmd, verbose=True, msg="-->  encoding_frames() begun!")
    return success

#TODO move back to pilapse-cap
def video_cleanup(video_path, seg_num):
    """Remove artifacts of the encoding process"""
    extensions = ['mp4', 'txt']
    success = True
    for ext in extensions:
        abs_fn = "%s/%s.%s" % (video_path, form_segment_name(seg_num), ext)
        cmd = 'rm -f %s' % abs_fn
        success &= run_cmd(cmd)
    return success

    
# Append Images
# TODO: move back to pilapse-cap
def video_worker(image_path, video_path, image_num, seg_num, seg_size, frame_rate, profile, preset):
    """Encode images in image_path"""
    try:
        # Create video segment from images
        input_fn = create_image_list(image_path, video_path, image_num, seg_num, seg_size)
        output_fn = "%s/%s.mp4" % (video_path, form_segment_name(seg_num))
        if not create_video(input_fn, output_fn, frame_rate=frame_rate, profile=profile, preset=preset):
            return False
        # Append to prior video
        if not append_video_segment(seg_num):
            return False
        # Clean up artifacts
        if not video_cleanup(video_path, seg_num):
            return False
    except (KeyboardInterrupt, SystemExit):
        terminate(1)
    return True

# TODO: delete when no longer needed
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

    # Create new video as tmp.mp4
    if not file_exists(abs_ivideo_fn):
        cmd = 'cp %s %s' % (abs_new_seg_fn, abs_ovideo_fn)
        success = run_cmd(cmd)
    else:
        success = concat_videos(abs_ivideo_fn, abs_new_seg_fn, abs_ovideo_fn)

    # Rename tmp as new full timelapse mpeg
    # If tmp doesnt exist, its possible the encoding failed or the user aborted 
    if success:
        # file exists, so delete old copy and rename tmp to new copy
        cmd = 'mv %s %s' % (abs_ovideo_fn, abs_ivideo_fn)
        success = run_cmd(cmd)

    return success


def concat_videos(v1, v2, output_video):
    """concat v2 to the end of v1, saving the result as output_video"""

    if not file_exists(v1) or not file_exists(v2):
        return False
    
    # Create file with list of files to concat
    concat_fn = "/tmp/concat.txt"
    with open(concat_fn,"w") as f:
        f.write("file %s\n" % (v1))
        f.write("file %s\n" % (v2))
        f.close()
    cmd = 'avconv -f concat -safe 0  -i %s -c copy %s' % (concat_fn, output_video)
    success = run_cmd(cmd)
    if not success:
        print("Concat of %s to end of %s failed!" % (v2, v1))
    return success

def append_images_to_video(image_path, video_fn, starting_image, num, preset, profile, frame_rate):
    """Append images to video_fn, starting at starting_image into the video file video_fn,                                                                                            
    using the encoder preset/profile/frame_rate.  If num < 0, all images                                                                                                              
    until one is not found will be incorporated. if video_fn exists the images will                                                                                                   
    be appended to the end."""
    
    # images ==> snippet
    # video_fn + snippet ==> temp_video_fn
    # temp_video_fn ==> video_fn
    temp_path = "/tmp"
    temp_video_fn = "%s/%s" % (temp_path, "temp_video.mp4")

    # Create video snippet from a file specifying the list of images
    image_list_fn = "%s/snippet_images.txt" % temp_path
    create_image_list(image_path, image_list_fn, starting_image, num)
    snippet_fn = "%s/snippet.mp4" % temp_path
    if not create_video(image_list_fn, snippet_fn, frame_rate=frame_rate, profile=profile, preset=preset):
        return False
    # Create new video as tmp.mp4
    if not file_exists(video_fn):
        cmd = 'cp %s %s' % (snippet_fn, video_fn)
        success = run_cmd(cmd)
    else:
        success = concat_videos(video_fn, snippet_fn, temp_video_fn)
        # Rename tmp as new full timelapse mpeg
        # If tmp doesnt exist, its possible the encoding failed or the user aborted
        if success:
            # file exists, so delete old copy and rename tmp to new copy
            cmd = 'mv %s %s' % (temp_video_fn, video_fn)
            success = run_cmd(cmd)
    return success
        
        
#######################
# GIF Encoding
#######################

def gif_worker(image_path, gif_path, image_num, seg_num):
    try:
        success = True
        success &= create_gif_segment(seg_num, image_num)
        if success:
            return
    except (KeyboardInterrupt, SystemExit):
        terminate(1)
        
def create_gif_segment(seg_num, start_img):
    # Create an animated gif (Requires ImageMagick).
    #    print('\nCreating animated gif.\n')
    seg_str = form_segment_name(seg_num)
    fn = '%s.gif' % seg_str
    cmd = 'convert -delay 10 -loop 0 %s/%s/img*.jpg %s/%s' % (image_dir, seg_str,Settings.get_value_by_key('encoder_gif_path'), fn)                
    success = run_cmd(cmd, verbose=True, msg="-->  encoding_frames() begun!")             


    

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



def terminate(ret):
    print('\nTime-lapse capture process cancelled.\n')
    sys.exit(ret)
