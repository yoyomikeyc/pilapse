"""Module to load configuration yaml"""
import sys
import os
import yaml

class SettingsBase():
    CSS_WIDTH_STR = 'style="width:250px"'
    def __init__(self, title="", help="", mutable=True, gui=True):
        self.mutable = mutable
        self.gui = gui
        self.title = title
        self.help = help
    
    def to_form_html(self, name, value):
        """name of the form field, and the current value"""
        if not self.gui:
            return ""
        if not self.mutable:
            return str(value)
        return None

class SettingsList(SettingsBase):
    def __init__(self, title="", help="", options=[], mutable=True, gui=True):
        super().__init__(title=title, help=help, mutable=mutable, gui=gui)
        self.options = options

    def _gen_option_list(self, name, value):
        options_str = ''
        for op in self.options:
            selected_str = ''
            # Stored as a string, so check as a string.
            if str(value) == str(op):
                selected_str="selected"
            options_str+='<option value="%s" %s>%s</option>\n' % (op, selected_str, op) 
        html='<select name="%s" %s>%s</select>' % (name, SettingsBase.CSS_WIDTH_STR, options_str)
        return html

    def to_form_html(self, name, value):
        html = super().to_form_html(name, value)
        if html is not None:
            return html
        return self._gen_option_list(name, value)

    
class SettingsStr(SettingsBase):
    def to_form_html(self, name, value):
        html = super().to_form_html(name, value)
        if html is not None:
            return html
        html = '<input name="%s" type="text" value="%s" %s>' % (name, value, SettingsBase.CSS_WIDTH_STR)
        return html

class SettingsInt(SettingsBase):
    def __init__(self, title="", help="", min=None, max=None, mutable=True, gui=True):
        super().__init__(title=title, help=help, mutable=mutable, gui=gui)
        self.min = min
        self.max = max
        
    def to_form_html(self, name, value):
        html = super().to_form_html(name, value)
        if html is not None:
            return html
        min_str=""
        if self.min is not None:
            min_str='min="%d"' % self.min
        max_str=""
        if self.max is not None:
            max_str='max="%d"' % self.max
        html = '<input name="%s" type="number" %s %s value="%s" %s>' % (name, min_str, max_str, value, SettingsBase.CSS_WIDTH_STR)
        return html


profiles=['baseline', 'main', 'high', 'high10', 'high422', 'high444']
presets=['ultrafast', 'superfast', 'veryfast', 'faster', 'fast', 'medium', 'slow', 'slower', 'veryslow']
rotations=[0, 90, 180, 270]
bools=[True, False]

# Mappings of Settings Keys to Settings Types
mapping = {
# Image Capture Options
    'capture_enable'        : SettingsList(title="Enable time-lapse image capture",
                                           options=bools),
    'capture_image_path'    : SettingsStr(title="Path to store raw images"),
    'capture_resolution'    : SettingsStr(title="Image capture resolution"),
    'capture_interval'      : SettingsInt(title="Time between image captures",
                                          min=0),
    'capture_iso'           : SettingsInt(title="Camera ISO setting",
                                          help="0 = auto, 60-800 for manual ISO.",
                                          min=0),
    'capture_shutter_speed' : SettingsInt(title="Camera shutter speed (ms)",
                                          help="0 = auto. Otherwise the value is in microseconds (ie, seconds * 1000000).",
                                          min=0),
    'capture_white_balance' : SettingsStr(title="Camera white balance",
                                          help="Set to empty braces, eg: { } to use auto white balance.  Otherwise, eg: {'red_gain': 1.3, 'blue_gain': 1.75}"),
    'capture_rotation'      : SettingsList(title="Image rotation",
                                           help="Rotate the images taken by the camera. Possible value are 0, 90, 180 or 270",
                                           options=rotations),
# GIF Encoding Options
    'encoder_gif_create' : SettingsList(title="Enable GIF creation",
                                        options=bools),
    'encoder_gif_path'   : SettingsStr(title="Path to store animated GIFs"),
# MPEG Video Encoding Options
    'encoder_video_create'                : SettingsList(title="Enable video generation",
                                                         options=bools),
    'encoder_video_path'                  : SettingsStr(title="Path to store videos"),
    'encoder_video_frames_per_segment'    : SettingsInt(title="Number of frames in encoding segment",
                                                        min=1),
    'encoder_video_frame_rate'      : SettingsInt(title="Frame rate of video<br>(real-time video)",
                                                  min=1),
    'encoder_video_profile'         : SettingsList(title="ffmpeg encoding profile<br>(real-time video)",
                                                   help='Used to specify the H.264 profile.  Options: baseline, main, high, high10, high422, high444.  See <a href="https://trac.ffmpeg.org/wiki/Encode/H.264">https://trac.ffmpeg.org/wiki/Encode/H.264</a> for more information',
                                                   options=profiles),
    'encoder_video_preset'          : SettingsList(title="ffmpeg encoding presets<br>(real-time video)",
                                                   help='A preset is a collection of options that will provide a certain encoding speed to compression ratio. A slower preset will provide better compression.  Options: ultrafast, superfast, veryfast, faster, fast, medium, slow, slower, veryslow. See <a href="https://trac.ffmpeg.org/wiki/Encode/H.264">https://trac.ffmpeg.org/wiki/Encode/H.264</a> for more information',
                                                   options=presets),
    'encoder_video_output_filename' : SettingsStr(title="Filename of generated video"),
    'encoder_hq_video_frame_rate'   : SettingsInt(title="Frame rate of video<br>(high quality)",
                                                  min=1),
    'encoder_hq_video_profile'      : SettingsList(title="ffmpeg encoding profile<br>(high quality)",
                                                   options=profiles),
    'encoder_hq_video_preset'       : SettingsList(title="ffmpeg encoding presets<br>(high quality)",
                                                   options=presets),
# Backup options
    'backup_enable'               : SettingsList(title="Backup raw images",
                                                 options=bools),
    'backup_size'                 : SettingsInt(min=1,
                                                title="Number of images to backup at once",
                                                help="Number of images to backup at once.  Larger numbers minimize the overhead of setting up an SSH connection but may delay image capture."),
    'backup_enable_image_cleanup' : SettingsList(title="Delete images after backup",
                                                 help="Used to free up disk space if backing up to external server.",
                                                 options=bools),
    'backup_server'               : SettingsStr(title="Server connection information"),
# Power/heat saving options #
    'power_disable_hdmi'       : SettingsList(title="Disable HDMI port",
                                              options=bools),
    'power_disable_pi_leds'    : SettingsList(title="Disable LEDs on Raspberry Pi",
                                              options=bools),
    'power_disable_camera_led' : SettingsList(title="Disable LED on camera module",
                                              options=bools),
}

def get_form_html(key, value):
    form_html=""
    if key in mapping:
        st = mapping[key]
        form_html = st.to_form_html(key, str(value))
    return form_html

def get_title(key):
    st = mapping[key]
    return st.title

def get_help(key):
    st = mapping[key]
    return st.help

def load_config():
    config = yaml.safe_load(open(os.path.join(sys.path[0], "defaults.yml")))
    return config
