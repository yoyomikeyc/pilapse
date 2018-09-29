"""Power saving functions"""
from db_model import Settings
from utils import run_cmd


##################################################################################
#
# Functions
#
##################################################################################

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




                                    
