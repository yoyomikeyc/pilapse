"""Module to load configuration yaml"""
import sys
import os
import yaml
import pytz

class SettingsBase():
    """Base Type for configuration field"""
    CSS_WIDTH_STR = 'style="width:250px"'
    def __init__(self, title="", desc="", mutable=True, gui=True):
        self.mutable = mutable
        self.gui = gui
        self.title = title
        self.desc = desc

    def to_form_html(self, name, value):
        """name of the form field, and the current value"""
        if not self.gui:
            return ""
        if not self.mutable:
            return str(value)
        return None

class SettingsList(SettingsBase):
    """Configuration field class that is a list of strings."""
    def __init__(self, title="", desc="", options=[], mutable=True, gui=True):
        SettingsBase.__init__(self, title=title, desc=desc, mutable=mutable, gui=gui)
        self.options = options

    def _gen_option_list(self, name, value):
        options_str = ''
        for option in self.options:
            selected_str = ''
            # Stored as a string, so check as a string.
            if str(value) == str(option):
                selected_str = "selected"
            options_str += '<option value="%s" %s>%s</option>\n' % (option, selected_str, option)
        html = '<select name="%s" %s>%s</select>' % (name, SettingsBase.CSS_WIDTH_STR, options_str)
        return html

    def to_form_html(self, name, value):
        html = SettingsBase.to_form_html(self, name, value)
        if html is not None:
            return html
        return self._gen_option_list(name, value)

class SettingsStr(SettingsBase):
    """Configuration field class for a config option that is a string."""
    def __init__(self, title="", desc="", mutable=True, gui=True, masked=False):
        SettingsBase.__init__(self, title=title, desc=desc, mutable=mutable, gui=gui)
        self.masked = masked
        
    def to_form_html(self, name, value):
        html = SettingsBase.to_form_html(self, name, value)
        if html is not None:
            return html
        type_str="text"
        if self.masked:
            type_str="password"
        html = '<input name="%s" type="%s" value="%s" %s>' % (name, type_str, value, SettingsBase.CSS_WIDTH_STR)
        return html

class SettingsInt(SettingsBase):
    def __init__(self, title="", desc="", min_val=None, max_val=None, mutable=True, gui=True):
        SettingsBase.__init__(self, title=title, desc=desc, mutable=mutable, gui=gui)
        self.min_val = min_val
        self.max_val = max_val

    def to_form_html(self, name, value):
        html = SettingsBase.to_form_html(self, name, value)
        if html is not None:
            return html
        min_str = ""
        if self.min_val is not None:
            min_str = 'min="%d"' % self.min_val
        max_str = ""
        if self.max_val is not None:
            max_str = 'max="%d"' % self.max_val
        html = '<input name="%s" type="number" %s %s value="%s" %s>' % (name, min_str, max_str, value, SettingsBase.CSS_WIDTH_STR)
        return html


PROFILES = ['baseline', 'main', 'high', 'high10', 'high422', 'high444']
PRESETS = ['ultrafast', 'superfast', 'veryfast', 'faster', 'fast', 'medium', 'slow', 'slower', 'veryslow']
ROTATIONS = [0, 90, 180, 270]
BOOLS = [True, False]
SUPPORTED_TIMEZONES = [tz for tz in pytz.all_timezones if "US/" in  tz]

# Mappings of Settings Keys to Settings Types
mapping = {
    # webserver options
    'webserver_debug'    : SettingsList(title="Webserver debug mode",
                                        options=BOOLS,
                                        desc="In debug mode, an interactive debugger will be shown for unhandled exceptions, and the server will be reloaded when code changes. Debug mode consumes a reasonable fraction of CPU.  For security reasons, do not enable debug mode when deploying in production."),
    'webserver_secret'    : SettingsStr(title="Webserver secret key",
                                        masked=True,
                                        desc="A secret key that will be used for securely signing the session cookie and any other security related needs. It should be a long random string of bytes/unicode."),
    # general options
    'general_timezone'    : SettingsList(title="System timezone",
                                         options=SUPPORTED_TIMEZONES),
    'general_sitename'    : SettingsStr(title="Site name",
                                        desc="Name of site to be displayed within webpage"),
    # Image Capture Options
    'capture_enable'        : SettingsList(title="Enable time-lapse image capture",
                                           options=BOOLS),
    'capture_image_path'    : SettingsStr(title="Path to store raw images"),
    'capture_resolution'    : SettingsStr(title="Image capture resolution"),
    #TODO: Shouldnt be an int, but a float
    'capture_interval'      : SettingsInt(title="Time between image captures",
                                          min_val=0),
    'capture_iso'           : SettingsInt(title="Camera ISO setting",
                                          desc="0 = auto, 60-800 for manual ISO.",
                                          min_val=0),
    'capture_shutter_speed' : SettingsInt(title="Camera shutter speed (ms)",
                                          desc="0 = auto. Otherwise the value is in microseconds (ie, seconds * 1000000).",
                                          min_val=0),
    'capture_white_balance' : SettingsStr(title="Camera white balance",
                                          desc="Set to empty braces, eg: { } to use auto white balance.  Otherwise, eg: {'red_gain': 1.3, 'blue_gain': 1.75}"),
    'capture_rotation'      : SettingsList(title="Image rotation",
                                           desc="Rotate the images taken by the camera. Possible value are 0, 90, 180 or 270",
                                           options=ROTATIONS),
    # GIF Encoding Options
    'encoder_gif_create' : SettingsList(title="Enable GIF creation",
                                        options=BOOLS),
    'encoder_gif_path'   : SettingsStr(title="Path to store animated GIFs"),
    # MPEG Video Encoding Options
    'encoder_video_create'                : SettingsList(title="Enable video generation",
                                                         options=BOOLS),
    'encoder_video_path'                  : SettingsStr(title="Path to store videos"),
    'encoder_video_frames_per_segment'    : SettingsInt(title="Number of frames in encoding segment",
                                                        min_val=1),
    'encoder_video_frame_rate'      : SettingsInt(title="Frame rate of video<br>(real-time video)",
                                                  min_val=1,
                                                  desc="frames per second of final video.  If changed after some video has been created, the session offsets will be inaccurate until the entire video is regenerated."),
    'encoder_video_profile'         : SettingsList(title="ffmpeg encoding profile<br>(real-time video)",
                                                   desc='Used to specify the H.264 profile.  Options: baseline, main, high, high10, high422, high444.  See <a href="https://trac.ffmpeg.org/wiki/Encode/H.264">https://trac.ffmpeg.org/wiki/Encode/H.264</a> for more information',
                                                   options=PROFILES),
    'encoder_video_preset'          : SettingsList(title="ffmpeg encoding presets<br>(real-time video)",
                                                   desc='A preset is a collection of options that will provide a certain encoding speed to compression ratio. A slower preset will provide better compression.  Options: ultrafast, superfast, veryfast, faster, fast, medium, slow, slower, veryslow. See <a href="https://trac.ffmpeg.org/wiki/Encode/H.264">https://trac.ffmpeg.org/wiki/Encode/H.264</a> for more information',
                                                   options=PRESETS),
    'encoder_video_output_filename' : SettingsStr(title="Filename of generated video"),
    'encoder_hq_video_frame_rate'   : SettingsInt(title="Frame rate of video<br>(high quality)",
                                                  min_val=1),
    'encoder_hq_video_profile'      : SettingsList(title="ffmpeg encoding profile<br>(high quality)",
                                                   options=PROFILES),
    'encoder_hq_video_preset'       : SettingsList(title="ffmpeg encoding presets<br>(high quality)",
                                                   options=PRESETS),
    # Backup options
    'backup_enable'               : SettingsList(title="Backup raw images",
                                                 options=BOOLS),
    'backup_size'                 : SettingsInt(min_val=1,
                                                title="Number of images to backup at once",
                                                desc="Number of images to backup at once.  Larger numbers minimize the overhead of setting up an SSH connection but may delay image capture."),
    'backup_enable_image_cleanup' : SettingsList(title="Delete images after backup",
                                                 desc="Used to free up disk space if backing up to external server.",
                                                 options=BOOLS),
    'backup_server'               : SettingsStr(title="Server connection information"),
    # Power/heat saving options #
    'power_disable_hdmi'       : SettingsList(title="Disable HDMI port",
                                              options=BOOLS),
    'power_disable_pi_leds'    : SettingsList(title="Disable LEDs on Raspberry Pi",
                                              options=BOOLS),
    'power_disable_camera_led' : SettingsList(title="Disable LED on camera module",
                                              options=BOOLS),
}

def get_form_html(key, value):
    form_html = ""
    if key in mapping:
        st = mapping[key]
        form_html = st.to_form_html(key, str(value))
    return form_html

def get_title(key):
    st = mapping[key]
    return st.title

def get_desc(key):
    st = mapping[key]
    return st.desc

def load_config():
    """Load config file into dict"""
    config = yaml.safe_load(open(os.path.join(sys.path[0], "defaults.yml")))
    return config
