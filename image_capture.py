"""Time lapse photography server"""
from time import sleep
import glob
import re

from db_model import Settings
from utils import file_exists

NUM_IMAGE_DIGITS = 7
##################################################################################
#
# Image Capture related
#
##################################################################################

def form_segment_name(seg_num):
    """Forms segment identiifer"""
    return 'seg{0:07d}'.format(seg_num)

def create_image_list(image_path, image_list_fn, starting_image, num):
    """Return file containing list of images in filestructure"""
    
    if num < 0:
        num = 10**NUM_IMAGE_DIGITS
    with open(image_list_fn, 'w') as fileh:
        for i in range(starting_image, starting_image+num):
            image_fn = form_image_abs_fn(image_path, i)
            # If file doesnt exist, abort.
            if not file_exists(image_fn):
                break
            fileh.write("file '%s'\n" % image_fn)
    

def get_all_images(path, descending=True):
    """returns list of all images in path, in descending order"""
    # Get descending sorted list of all images in images folder
    all_images = glob.glob(path+"/img*.jpg", recursive=False)
    all_images.sort(reverse=descending)
    return all_images


def extract_from_abs_fn(abs_fn):
    """Returns tuple containing seg_num and image_num extracted from image filename"""
    match = re.match(r'.*/img(\d{7}).jpg$', abs_fn)
    #datetime.now().strftime('%Y-%m-%d_%H-%M-%S')

    if match:
        image_num = int(match.group(1))
        return image_num
    return None

def form_image_fn_pattern():
    """return string with ffmpeg image pattern"""
    #return r"img%07d_%04d-%02d-%02d_%02d-%02d-%02d.jpg"
    return r"img%07d.jpg"

def form_image_fn(image_num):
    """Form the name of an image filename"""
    #timestamp = now.strftime('%Y-%m-%d_%H-%M-%S')
    return 'img{0:07d}.jpg'.format(image_num)
    #timestamp = now.strftime('%Y%m%d%H%M%S')
    #return 'img{0:07d}{1}.jpg'.format(image_num, timestamp)

def form_image_abs_fn(path, image_num):
    """Form absolute filename for image given path"""
    image_fn = form_image_fn(image_num)
    image_abs_fn = "%s/%s" % (path, image_fn)
    return image_abs_fn


def set_camera_options(camera):
    """Set camera options as loaded from database"""
    # Set camera resolution.
    resolution = Settings.get_value_by_key('capture_resolution')
    if resolution:
        camera.resolution = (
            resolution['width'],
            resolution['height']
        )

    # Set ISO.
    iso = Settings.get_value_by_key('capture_iso')
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
    white_balance = Settings.get_value_by_key('capture_white_balance')
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
